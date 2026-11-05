"""Guided capture (catalog-maintenance.md section 9): lens-by-lens interviews.

The questions are deterministic: one per lens, then a pre-mortem. The Interviewer agent only
turns an answer into *suggestions*, which stay `pending` until a human accepts, rejects or
qualifies them. Accepting saves a `proposed` version with `origin = interview` and the
suggestion as its origin, so the conversation stays attached to what came out of it.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from cheshire.agents.interviewer import Draft, Turn, attribute_with_value, interview_turn
from cheshire.auth.service import User
from cheshire.catalog.models import Attribute
from cheshire.consult.service import Context, _model, record_run
from cheshire.db.catalog_repo import (
    MODEL_FOR_KIND,
    CatalogRefError,
    CatalogRepo,
    CatalogStateError,
    ItemModel,
)

Conn = psycopg.Connection[Any]
Decision = Literal["accept", "reject", "depends"]

PRE_MORTEM = (
    "Think of a project where something went wrong, or was found late. "
    "What should this catalog have warned about?"
)
NOT_APPLICABLE = "Not applicable."


class InterviewError(Exception):
    code = "invalid"


class InterviewNotFound(InterviewError):
    code = "not_found"


class InterviewConflict(InterviewError):
    code = "conflict"


# ------------------------------------------------------------------ questions


def _questions(repo: CatalogRepo) -> list[tuple[str | None, str]]:
    """(lens slug, question) in catalog order, then the pre-mortem."""
    lenses = [(lens.id, lens.question) for lens in repo.load_catalog().lenses]
    return [*lenses, (None, PRE_MORTEM)]


def _add_message(
    conn: Conn,
    interview_id: int,
    role: str,
    text: str,
    lens_slug: str | None = None,
    llm_run_id: int | None = None,
) -> int:
    lens_id = None
    if lens_slug is not None:
        row = conn.execute(
            "select id from catalog_items where kind = 'lens' and slug = %s", (lens_slug,)
        ).fetchone()
        lens_id = row[0] if row else None
    row = conn.execute(
        "insert into interview_messages (interview_id, seq, role, lens_item_id, text, llm_run_id)"
        " values (%s, (select coalesce(max(seq), 0) + 1 from interview_messages"
        " where interview_id = %s), %s, %s, %s, %s) returning id",
        (interview_id, interview_id, role, lens_id, text, llm_run_id),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _interview(conn: Conn, interview_id: int) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select i.id, i.status, i.started_at, u.display_name as started_by,"
            " s.slug as subject from interviews i join users u on u.id = i.started_by"
            " left join catalog_items s on s.id = i.subject_item_id where i.id = %s",
            (interview_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise InterviewNotFound(f"interview {interview_id} not found")
    return row


def _messages(conn: Conn, interview_id: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select m.id, m.seq, m.role, m.text, m.at, l.slug as lens from interview_messages m"
            " left join catalog_items l on l.id = m.lens_item_id"
            " where m.interview_id = %s order by m.seq",
            (interview_id,),
        )
        return cur.fetchall()


# ----------------------------------------------------------------------- start


def start(conn: Conn, user: User, subject: str | None = None) -> int:
    repo = CatalogRepo(conn)
    subject_id = None
    if subject:
        found = repo.find_item_id("abb", subject)
        if found is None:
            raise InterviewError(f"unknown ABB {subject!r}")
        subject_id = found
    row = conn.execute(
        "insert into interviews (subject_item_id, started_by) values (%s, %s) returning id",
        (subject_id, user.id),
    ).fetchone()
    assert row is not None
    interview_id = int(row[0])
    lens, question = _questions(repo)[0]
    _add_message(conn, interview_id, "assistant", question, lens)
    return interview_id


# ---------------------------------------------------------------------- answer


def _current_question(conn: Conn, repo: CatalogRepo, interview_id: int) -> tuple[int, str | None]:
    """Index of the question waiting for an answer, and its lens (None for the pre-mortem)."""
    answered = conn.execute(
        "select count(*) from interview_messages where interview_id = %s and role = 'user'",
        (interview_id,),
    ).fetchone()
    assert answered is not None
    questions = _questions(repo)
    index = min(int(answered[0]), len(questions) - 1)
    return index, questions[index][0]


def answer(
    conn: Conn,
    ctx: Context,
    user: User,
    interview_id: int,
    text: str,
    not_applicable: bool = False,
) -> None:
    """Store the answer, then (unless "not applicable") ask the Interviewer about it.

    The answer is committed before the LLM is called, so a provider failure loses nothing:
    `retry` processes it later."""
    interview = _interview(conn, interview_id)
    if interview["status"] != "open":
        raise InterviewConflict("this interview is closed")
    messages = _messages(conn, interview_id)
    if messages and messages[-1]["role"] == "user":
        raise InterviewConflict("the previous answer has not been processed yet; retry it")
    text = NOT_APPLICABLE if not_applicable else text.strip()
    if not text:
        raise InterviewError("an answer cannot be empty (use 'not applicable' to skip)")
    if messages and messages[-1]["text"] == _DONE:
        raise InterviewConflict("the interview has no more questions")
    repo = CatalogRepo(conn)
    index, lens = _current_question(conn, repo, interview_id)
    _add_message(conn, interview_id, "user", text, lens)
    conn.commit()
    if not_applicable:
        _advance(conn, repo, interview_id, index)
        return
    _process(conn, ctx, user, interview_id)


_DONE = "That was the last question. Review the suggestions, then close the interview."


def _advance(conn: Conn, repo: CatalogRepo, interview_id: int, index: int) -> None:
    questions = _questions(repo)
    if index + 1 < len(questions):
        lens, question = questions[index + 1]
        _add_message(conn, interview_id, "assistant", question, lens)
    else:
        _add_message(conn, interview_id, "assistant", _DONE)


def retry(conn: Conn, ctx: Context, user: User, interview_id: int) -> None:
    """Process the last answer again after a provider error."""
    _interview(conn, interview_id)
    messages = _messages(conn, interview_id)
    if not messages or messages[-1]["role"] != "user":
        raise InterviewConflict("nothing to retry")
    _process(conn, ctx, user, interview_id)


def _process(conn: Conn, ctx: Context, user: User, interview_id: int) -> None:
    interview = _interview(conn, interview_id)
    repo = CatalogRepo(conn)
    messages = _messages(conn, interview_id)
    last = messages[-1]
    question = next(
        (m["text"] for m in reversed(messages[:-1]) if m["role"] == "assistant"), PRE_MORTEM
    )
    index = sum(1 for m in messages if m["role"] == "user") - 1
    model = _model(ctx.settings, "interviewer")
    catalog = repo.load_catalog(include_drafts=True)
    try:
        turn = interview_turn(
            ctx.llm_factory(),
            model,
            catalog,
            subject=interview["subject"],
            question=question,
            answer=last["text"],
            language=ctx.settings.language,
        )
    except Exception as exc:
        run = getattr(exc, "run", None)
        if run is not None:  # failed runs are stored too
            record_run(conn, run, user.id)
            conn.commit()
        raise
    run_id = record_run(conn, turn.run, user.id)
    _store(conn, interview_id, last["id"], turn)
    if turn.follow_up:  # shown before the next question; the architect may answer it there
        _add_message(conn, interview_id, "assistant", turn.follow_up, last["lens"], run_id)
    _advance(conn, repo, interview_id, index)


def _store(conn: Conn, interview_id: int, message_id: int, turn: Turn) -> None:
    for d in turn.suggestions:
        _insert_suggestion(conn, interview_id, message_id, d)


def _insert_suggestion(conn: Conn, interview_id: int, message_id: int, d: Draft) -> None:
    conn.execute(
        "insert into suggestions (interview_id, kind, payload, source_message_id)"
        " values (%s, %s, %s::jsonb, %s)",
        (
            interview_id,
            d.kind,
            json.dumps({**d.payload, "quote": d.quote, "why": d.why}),
            message_id,
        ),
    )


# -------------------------------------------------------------------- decisions


def _suggestion(conn: Conn, suggestion_id: int) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select * from suggestions where id = %s for update", (suggestion_id,))
        row = cur.fetchone()
    if row is None:
        raise InterviewNotFound(f"suggestion {suggestion_id} not found")
    return row


def _model_of(kind: str, raw: dict[str, Any]) -> ItemModel:
    return MODEL_FOR_KIND[kind].model_validate({**raw, "status": "proposed"})


def _accept(conn: Conn, user: User, row: dict[str, Any]) -> int:
    repo = CatalogRepo(conn)
    payload = row["payload"]
    kind = row["kind"]
    note = f"Accepted from interview {row['interview_id']} (suggestion {row['id']})"
    try:
        if kind == "attribute_value":
            slug = payload["attribute"]
            numbers = repo.versions("attribute", slug)
            current = repo.load_item("attribute", slug, numbers[0]["number"]) if numbers else None
            if not isinstance(current, Attribute):
                raise InterviewConflict(f"attribute {slug!r} no longer exists")
            if payload["value"] in current.values:
                raise InterviewConflict(f"attribute {slug!r} already has {payload['value']!r}")
            model: ItemModel = attribute_with_value(current, payload["value"]).model_copy(
                update={"status": "proposed"}
            )
            return repo.save_version(
                "attribute",
                model,
                status="proposed",
                author_id=user.id,
                origin="interview",
                origin_ref=row["id"],
                change_note=note,
            )
        model = _model_of(kind, payload["item"])
        if repo.find_item_id(kind, model.id) is not None:
            raise InterviewConflict(f"{kind} {model.id!r} already exists in the catalog")
        return repo.save_version(
            kind,
            model,
            status="proposed",
            author_id=user.id,
            origin="interview",
            origin_ref=row["id"],
            change_note=note,
        )
    except (CatalogRefError, CatalogStateError, psycopg.errors.IntegrityError) as exc:
        raise InterviewConflict(f"cannot accept: {exc}") from exc


def decide(
    conn: Conn,
    ctx: Context,
    user: User,
    suggestion_id: int,
    decision: Decision,
    note: str = "",
) -> None:
    row = _suggestion(conn, suggestion_id)
    if row["status"] != "pending":
        raise InterviewConflict(f"this suggestion is already {row['status']}")
    version_id: int | None = None
    if decision == "accept":
        version_id = _accept(conn, user, row)
    note = note.strip()
    if decision == "depends" and not note:
        raise InterviewError("say what it depends on")
    status = {"accept": "accepted", "reject": "rejected", "depends": "depends"}[decision]
    conn.execute(
        "update suggestions set status = %s, follow_up = %s, decided_by = %s,"
        " decided_at = now(), resulting_version_id = %s where id = %s",
        (status, note if decision == "depends" else "", user.id, version_id, suggestion_id),
    )
    if decision != "depends":
        return
    conn.commit()
    _refine(conn, ctx, user, row, note)


def _refine(conn: Conn, ctx: Context, user: User, row: dict[str, Any], note: str) -> None:
    """ "It depends": ask the Interviewer for a better suggestion given the qualification."""
    repo = CatalogRepo(conn)
    interview = _interview(conn, row["interview_id"])
    payload = row["payload"]
    earlier = json.dumps({k: v for k, v in payload.items() if k not in ("quote", "why")})
    try:
        turn = interview_turn(
            ctx.llm_factory(),
            _model(ctx.settings, "interviewer"),
            repo.load_catalog(include_drafts=True),
            subject=interview["subject"],
            question="Refine an earlier suggestion that depends on a condition.",
            answer=note,
            context=f"Earlier suggestion (kind {row['kind']}): {earlier}",
            language=ctx.settings.language,
        )
    except Exception as exc:
        run = getattr(exc, "run", None)
        if run is not None:
            record_run(conn, run, user.id)
            conn.commit()
        raise
    record_run(conn, turn.run, user.id)
    _store(conn, row["interview_id"], row["source_message_id"], turn)


def close(conn: Conn, interview_id: int) -> None:
    _interview(conn, interview_id)
    conn.execute("update interviews set status = 'closed' where id = %s", (interview_id,))


# ------------------------------------------------------------------------ views


def view(conn: Conn, interview_id: int) -> dict[str, Any]:
    interview = _interview(conn, interview_id)
    messages = _messages(conn, interview_id)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select s.id, s.kind, s.payload, s.status, s.follow_up, s.source_message_id,"
            " s.decided_at, d.display_name as decided_by, v.number as resulting_version,"
            " ri.kind as resulting_kind, ri.slug as resulting_item"
            " from suggestions s left join users d on d.id = s.decided_by"
            " left join item_versions v on v.id = s.resulting_version_id"
            " left join catalog_items ri on ri.id = v.item_id"
            " where s.interview_id = %s order by s.id",
            (interview_id,),
        )
        suggestions = cur.fetchall()
    repo = CatalogRepo(conn)
    total = len(_questions(repo))
    answered = sum(1 for m in messages if m["role"] == "user")
    return {
        **interview,
        "messages": messages,
        "suggestions": suggestions,
        "needs_retry": bool(messages) and messages[-1]["role"] == "user",
        "progress": {"answered": min(answered, total), "total": total},
        "finished": bool(messages) and messages[-1]["text"] == _DONE,
    }


def list_interviews(conn: Conn) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select i.id, i.status, i.started_at, u.display_name as started_by,"
            " s.slug as subject,"
            " (select count(*) from suggestions x where x.interview_id = i.id"
            "   and x.status = 'pending') as pending from interviews i"
            " join users u on u.id = i.started_by"
            " left join catalog_items s on s.id = i.subject_item_id order by i.id desc"
        )
        return cur.fetchall()
