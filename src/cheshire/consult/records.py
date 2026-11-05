"""Choice records, feedback, reference cases and user preferences (consult.md 3, regions 8-9).

Choices and feedback are append-only; the latest choice per ABB is the current one.
Everything the user sends is checked against the stored evaluation, never trusted.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from psycopg.rows import dict_row

from cheshire.auth.permissions import allowed
from cheshire.auth.service import User
from cheshire.consult.service import (
    Conn,
    ConsultError,
    InvalidInput,
    _current,
)
from cheshire.db.catalog_repo import CatalogRepo
from cheshire.engine.model import EngineResult

ChoiceKind = Literal["chosen", "decide_later", "outside_catalog"]
FeedbackKind = Literal["missing", "wrong"]


class Forbidden(ConsultError):
    code = "forbidden"


def _latest_evaluation(conn: Conn, revision_id: int) -> tuple[int, EngineResult]:
    row = conn.execute(
        "select id, result from evaluations where revision_id = %s order by id desc limit 1",
        (revision_id,),
    ).fetchone()
    if row is None:
        raise InvalidInput("there is no result to record a decision on yet")
    stored = dict(row[1])
    stored.pop("schema_version", None)
    return int(row[0]), EngineResult.model_validate(stored)


# ----------------------------------------------------------------------- choices


def record_choice(
    conn: Conn,
    user: User,
    consultation_id: int,
    abb: str,
    kind: ChoiceKind,
    sbb: str | None = None,
    reason: str = "",
) -> None:
    """Append a choice for one ABB. The SBB's result and state are read from the stored
    evaluation. A reason is required when the SBB is conditional or deprecating; a
    conditional choice keeps the questions that were still unresolved."""
    revision = _current(conn, user, consultation_id)
    evaluation_id, result = _latest_evaluation(conn, revision["id"])
    abb_result = result.abb(abb)
    if abb_result is None:
        raise InvalidInput(f"{abb!r} is not part of the current result")
    reason = reason.strip()

    sbb_row: tuple[Any, ...] | None = None
    unresolved: list[str] = []
    if kind == "chosen":
        if not sbb:
            raise InvalidInput("choose a solution, or decide later")
        outcome = next((s for s in abb_result.sbbs if s.id == sbb), None)
        if outcome is None:
            raise InvalidInput(f"{sbb!r} is not a solution of {abb!r}")
        if outcome.result == "excluded":
            raise InvalidInput(f"{sbb!r} is excluded for this requirement and cannot be chosen")
        if (outcome.result == "conditional" or outcome.state == "deprecating") and not reason:
            raise InvalidInput(
                "a reason is required when the chosen solution is conditional or deprecating"
            )
        if outcome.result == "conditional":
            unresolved = [q.attribute for q in result.pending_questions if abb in q.impact]
        sbb_row = (outcome.result, outcome.state)
    else:
        if sbb:
            raise InvalidInput("a solution can only be given with kind 'chosen'")
        if kind == "outside_catalog" and abb_result.coverage != "gap":
            raise InvalidInput("'outside the catalog' is only for building blocks with a gap")

    repo = CatalogRepo(conn)
    conn.execute(
        "insert into choice_records (consultation_id, revision_id, evaluation_id, abb_item_id,"
        " kind, sbb_item_id, sbb_kind, sbb_result, sbb_state, reason, unresolved_questions,"
        " actor_id) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
        (
            consultation_id,
            revision["id"],
            evaluation_id,
            repo.item_id("abb", abb),
            kind,
            repo.item_id("sbb", sbb) if sbb else None,
            "sbb" if sbb else None,
            sbb_row[0] if sbb_row else None,
            sbb_row[1] if sbb_row else None,
            reason,
            json.dumps(unresolved),
            user.id,
        ),
    )


def current_choices(conn: Conn, revision_id: int) -> list[dict[str, Any]]:
    """Latest choice per ABB of a revision."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select distinct on (c.abb_item_id) c.id, a.slug as abb, c.kind, s.slug as sbb,"
            " c.sbb_result, c.sbb_state, c.reason, c.unresolved_questions, c.evaluation_id,"
            " u.display_name as actor, c.at"
            " from choice_records c join catalog_items a on a.id = c.abb_item_id"
            " left join catalog_items s on s.id = c.sbb_item_id"
            " join users u on u.id = c.actor_id where c.revision_id = %s"
            " order by c.abb_item_id, c.id desc",
            (revision_id,),
        )
        rows = cur.fetchall()
    return sorted(rows, key=lambda r: r["abb"])


def choice_history(conn: Conn, revision_id: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select c.id, a.slug as abb, c.kind, s.slug as sbb, c.sbb_result, c.sbb_state,"
            " c.reason, u.display_name as actor, c.at"
            " from choice_records c join catalog_items a on a.id = c.abb_item_id"
            " left join catalog_items s on s.id = c.sbb_item_id"
            " join users u on u.id = c.actor_id where c.revision_id = %s order by c.id",
            (revision_id,),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------- feedback


def add_feedback(
    conn: Conn,
    user: User,
    consultation_id: int,
    kind: FeedbackKind,
    text: str,
    abb: str | None = None,
) -> None:
    """ "Something is missing / wrong", on one ABB or on the whole result. The architects'
    queue (M5) is built from these rows."""
    revision = _current(conn, user, consultation_id)
    text = text.strip()
    if not text:
        raise InvalidInput("describe what is missing or wrong")
    repo = CatalogRepo(conn)
    abb_id: int | None = None
    if abb is not None:
        if repo.load_catalog().abb(abb) is None:
            raise InvalidInput(f"unknown ABB {abb!r}")
        abb_id = repo.item_id("abb", abb)
    last = conn.execute(
        "select id from evaluations where revision_id = %s order by id desc limit 1",
        (revision["id"],),
    ).fetchone()
    conn.execute(
        "insert into feedback (consultation_id, revision_id, evaluation_id, abb_item_id, abb_kind,"
        " kind, text, author_id) values (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            consultation_id,
            revision["id"],
            last[0] if last else None,
            abb_id,
            "abb" if abb_id else None,
            kind,
            text,
            user.id,
        ),
    )


def feedback_of(conn: Conn, revision_id: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select f.id, f.kind, a.slug as abb, f.text, u.display_name as author, f.at"
            " from feedback f left join catalog_items a on a.id = f.abb_item_id"
            " join users u on u.id = f.author_id where f.revision_id = %s order by f.id",
            (revision_id,),
        )
        return cur.fetchall()


# ------------------------------------------------------------------ reference cases


def _expected(result: EngineResult) -> dict[str, Any]:
    """What a reference case promises: per ABB its coverage and the SBB results."""
    return {
        "abbs": {
            a.id: {
                "coverage": a.coverage,
                "sbbs": {s.id: s.result for s in a.sbbs},
            }
            for a in result.abbs
        }
    }


def pin(conn: Conn, user: User, consultation_id: int, title: str) -> dict[str, Any]:
    """Pin the latest evaluation as a reference case (architects: the impact preview of a
    catalog change replays these)."""
    if not allowed(user.role, "catalog.write"):
        raise Forbidden("only architects can pin reference cases")
    revision = _current(conn, user, consultation_id)
    evaluation_id, result = _latest_evaluation(conn, revision["id"])
    title = title.strip()
    if not title:
        raise InvalidInput("a reference case needs a title")
    if pinned(conn, revision["id"]) is not None:
        raise InvalidInput("this consultation is already pinned")
    conn.execute(
        "insert into reference_cases (revision_id, evaluation_id, title, pinned_by, expected)"
        " values (%s, %s, %s, %s, %s::jsonb)",
        (revision["id"], evaluation_id, title, user.id, json.dumps(_expected(result))),
    )
    found = pinned(conn, revision["id"])
    assert found is not None
    return found


def unpin(conn: Conn, user: User, consultation_id: int) -> None:
    if not allowed(user.role, "catalog.write"):
        raise Forbidden("only architects can unpin reference cases")
    revision = _current(conn, user, consultation_id)
    updated = conn.execute(
        "update reference_cases set archived_at = now() where revision_id = %s"
        " and archived_at is null",
        (revision["id"],),
    ).rowcount
    if not updated:
        raise InvalidInput("this consultation is not pinned")


def pinned(conn: Conn, revision_id: int) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select r.id, r.title, r.evaluation_id, r.pinned_at, u.display_name as pinned_by"
            " from reference_cases r join users u on u.id = r.pinned_by"
            " where r.revision_id = %s and r.archived_at is null",
            (revision_id,),
        )
        return cur.fetchone()


def list_reference_cases(conn: Conn) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select r.id, r.title, rev.consultation_id, r.evaluation_id, r.pinned_at,"
            " u.display_name as pinned_by, r.expected from reference_cases r"
            " join consultation_revisions rev on rev.id = r.revision_id"
            " join users u on u.id = r.pinned_by where r.archived_at is null order by r.id"
        )
        return cur.fetchall()


# ------------------------------------------------------------------ preferences


def get_preferences(conn: Conn, user: User) -> dict[str, str]:
    row = conn.execute(
        "select detail_level, locale, theme from user_preferences where user_id = %s", (user.id,)
    ).fetchone()
    if row is None:
        return {"detail_level": "summary", "locale": "en", "theme": "system"}
    return {"detail_level": row[0], "locale": row[1], "theme": row[2]}


def set_preferences(
    conn: Conn,
    user: User,
    detail_level: str | None = None,
    locale: str | None = None,
    theme: str | None = None,
) -> dict[str, str]:
    if detail_level not in (None, "summary", "detailed"):
        raise InvalidInput("detail_level must be 'summary' or 'detailed'")
    if theme not in (None, "system", "light", "dark"):
        raise InvalidInput("theme must be 'system', 'light' or 'dark'")
    if locale is not None and not (1 <= len(locale) <= 16 and locale.replace("-", "").isalnum()):
        raise InvalidInput("locale is not valid")
    current = get_preferences(conn, user)
    merged = {
        "detail_level": detail_level or current["detail_level"],
        "locale": locale or current["locale"],
        "theme": theme or current["theme"],
    }
    # select-then-write: the app role has no ON CONFLICT ... DO UPDATE path it cannot use
    exists = conn.execute(
        "select 1 from user_preferences where user_id = %s", (user.id,)
    ).fetchone()
    if exists:
        conn.execute(
            "update user_preferences set detail_level = %s, locale = %s, theme = %s"
            " where user_id = %s",
            (merged["detail_level"], merged["locale"], merged["theme"], user.id),
        )
    else:
        conn.execute(
            "insert into user_preferences (user_id, detail_level, locale, theme)"
            " values (%s, %s, %s, %s)",
            (user.id, merged["detail_level"], merged["locale"], merged["theme"]),
        )
    return merged
