"""Consultation workflow. The engine decides; the agents translate and explain; every
step is stored so a result can be shown again, debugged and reproduced (D30)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from cheshire.agents.base import AgentError, RunRecord
from cheshire.agents.interpreter import interpret
from cheshire.agents.writer import DetailLevel, write_rationale
from cheshire.auth.permissions import allowed
from cheshire.auth.service import User
from cheshire.catalog.models import Catalog
from cheshire.catalog.validator import validate_catalog
from cheshire.db.catalog_repo import CatalogRepo
from cheshire.engine.model import (
    AbbMention,
    AttributeValue,
    EngineInputError,
    EngineResult,
    InterpreterOutput,
)
from cheshire.engine.run import run as run_engine
from cheshire.engine.trace import build_trace
from cheshire.providers.base import LLMClient, LLMNotConfigured
from cheshire.settings import Settings

Conn = psycopg.Connection[Any]
Trigger = Literal["analyze", "answer", "edit", "catalog_change"]
RESULT_SCHEMA_VERSION = 1


class ConsultError(Exception):
    code = "consult_error"


class NotFound(ConsultError):
    code = "not_found"


class EmptyCatalog(ConsultError):
    code = "empty_catalog"


class CatalogInvalid(ConsultError):
    code = "catalog_invalid"

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class InvalidInput(ConsultError):
    code = "invalid_input"


class NothingToExplain(ConsultError):
    code = "nothing_to_explain"


@dataclass
class Context:
    settings: Settings
    llm_factory: Callable[[], LLMClient]
    # progress by stage ("interpreting", "checking", "evaluating"), for the SSE stream
    on_stage: Callable[[str], None] | None = None

    def stage(self, name: str) -> None:
        if self.on_stage is not None:
            self.on_stage(name)


# ----------------------------------------------------------------------- helpers


def record_run(conn: Conn, run: RunRecord, user_id: int | None) -> int:
    row = conn.execute(
        "insert into llm_runs (purpose, provider, model, prompt_version, input, output, status,"
        " attempts, tokens_in, tokens_out, latency_ms, error, problems, requested_by)"
        " values (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)"
        " returning id",
        (
            run.purpose,
            run.provider,
            run.model,
            run.prompt_version,
            json.dumps(run.input),
            json.dumps(run.output) if run.output is not None else None,
            run.status,
            max(run.attempts, 1),
            run.tokens_in,
            run.tokens_out,
            run.latency_ms,
            run.error,
            json.dumps(run.problems),
            user_id,
        ),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _model(
    settings: Settings, role: Literal["interpreter", "writer", "interviewer", "mediator"]
) -> str:
    model = {
        "interpreter": settings.llm_interpreter_model,
        "writer": settings.llm_writer_model,
        "interviewer": settings.llm_interviewer_model,
        "mediator": settings.llm_mediator_model,
    }[role]
    if not model:
        raise LLMNotConfigured(f"CHESHIRE_LLM_{role.upper()}_MODEL is not set")
    return model


def _can_see(user: User, owner_id: int) -> bool:
    return user.id == owner_id or allowed(user.role, "catalog.write")  # architects see all


def _consultation(conn: Conn, user: User, consultation_id: int) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select c.id, c.owner_id, c.title, c.created_at, u.display_name as owner"
            " from consultations c join users u on u.id = c.owner_id where c.id = %s",
            (consultation_id,),
        )
        row = cur.fetchone()
    if row is None or not _can_see(user, row["owner_id"]):
        raise NotFound("consultation not found")  # no hint whether it exists
    return row


def latest_revision(conn: Conn, consultation_id: int) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select id, number, requirement_text, unrecognised, created_at"
            " from consultation_revisions where consultation_id = %s order by number desc limit 1",
            (consultation_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise NotFound("consultation has no revision")
    return row


# ------------------------------------------------------------------- consultations


def create(conn: Conn, user: User, requirement: str, title: str = "") -> int:
    text = requirement.strip()
    if not text:
        raise InvalidInput("the requirement is empty")
    row = conn.execute(
        "insert into consultations (owner_id, title) values (%s, %s) returning id",
        (user.id, title.strip() or text[:80]),
    ).fetchone()
    assert row is not None
    conn.execute(
        "insert into consultation_revisions (consultation_id, number, requirement_text, created_by)"
        " values (%s, 1, %s, %s)",
        (row[0], text, user.id),
    )
    return int(row[0])


def new_revision(conn: Conn, user: User, consultation_id: int, requirement: str) -> int:
    """Rewriting the text creates a new revision; earlier ones stay readable."""
    _consultation(conn, user, consultation_id)
    text = requirement.strip()
    if not text:
        raise InvalidInput("the requirement is empty")
    last = latest_revision(conn, consultation_id)
    row = conn.execute(
        "insert into consultation_revisions (consultation_id, number, requirement_text, created_by)"
        " values (%s, %s, %s, %s) returning id",
        (consultation_id, last["number"] + 1, text, user.id),
    ).fetchone()
    assert row is not None
    return int(row[0])


def list_consultations(conn: Conn, user: User) -> list[dict[str, Any]]:
    see_all = allowed(user.role, "catalog.write")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select c.id, c.title, c.created_at, u.display_name as owner,"
            " (select max(number) from consultation_revisions r where r.consultation_id = c.id)"
            " as revisions from consultations c join users u on u.id = c.owner_id"
            " where c.archived_at is null and (%s or c.owner_id = %s) order by c.id desc",
            (see_all, user.id),
        )
        return cur.fetchall()


# ----------------------------------------------------------------------- analysis


def analyze(conn: Conn, ctx: Context, user: User, consultation_id: int) -> dict[str, Any]:
    """Interpret the latest revision, store what was understood, evaluate."""
    _consultation(conn, user, consultation_id)
    revision = latest_revision(conn, consultation_id)
    repo = CatalogRepo(conn)
    catalog = repo.load_catalog()
    if not catalog.abbs:
        raise EmptyCatalog("the catalog has no building blocks yet")
    model = _model(ctx.settings, "interpreter")
    client = ctx.llm_factory()
    ctx.stage("interpreting")
    try:
        interpretation = interpret(
            client, model, catalog, revision["requirement_text"], ctx.settings.language
        )
    except AgentError as exc:
        record_run(conn, exc.run, user.id)
        conn.commit()  # keep the failed run for debugging although the request fails
        raise
    ctx.stage("checking")
    run_id = record_run(conn, interpretation.run, user.id)

    out = interpretation.output
    for abb in out.abbs:
        conn.execute(
            "insert into consultation_abb_events (revision_id, abb_item_id, origin, span,"
            " llm_run_id, actor_id) values (%s, %s, 'interpreter', %s::jsonb, %s, %s)",
            (
                revision["id"],
                repo.item_id("abb", abb.id),
                json.dumps({"text": abb.span}),
                run_id,
                user.id,
            ),
        )
    for attr_id, value in out.attributes.items():
        _insert_fact(
            conn,
            repo,
            revision["id"],
            attr_id,
            value.value,
            value.source,
            {"text": value.span},
            run_id,
            user.id,
        )
    conn.execute(
        "update consultation_revisions set unrecognised = %s where id = %s",
        (interpretation.recognised_nothing, revision["id"]),
    )
    if not interpretation.recognised_nothing:
        ctx.stage("evaluating")
        evaluate(conn, ctx, user, revision["id"], "analyze")
    return view(conn, user, consultation_id)


def _insert_fact(
    conn: Conn,
    repo: CatalogRepo,
    revision_id: int,
    attr_slug: str,
    value: str | list[str] | None,
    source: str,
    span: dict[str, Any] | None,
    run_id: int | None,
    user_id: int,
) -> None:
    attr_id = repo.item_id("attribute", attr_slug)
    row = conn.execute(
        "insert into consultation_facts (revision_id, attribute_item_id, source, span,"
        " llm_run_id, actor_id) values (%s, %s, %s, %s::jsonb, %s, %s) returning id",
        (revision_id, attr_id, source, json.dumps(span) if span else None, run_id, user_id),
    ).fetchone()
    assert row is not None
    values = [] if value is None else [value] if isinstance(value, str) else value
    for key in values:
        vrow = conn.execute(
            "select id from attribute_values where attribute_item_id = %s and key = %s",
            (attr_id, key),
        ).fetchone()
        if vrow is None:
            raise InvalidInput(f"attribute {attr_slug!r} has no value {key!r}")
        conn.execute(
            "insert into fact_values (fact_id, attribute_item_id, value_id) values (%s, %s, %s)",
            (row[0], attr_id, vrow[0]),
        )


# ------------------------------------------------------------------------ state


def fold_state(conn: Conn, revision_id: int) -> tuple[InterpreterOutput, list[str]]:
    """Current facts and identified ABBs of a revision, folded from the append-only logs.

    Returns the engine input and the attributes the user explicitly answered "unknown".
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select distinct on (f.attribute_item_id) f.id, i.slug, f.source, f.span"
            " from consultation_facts f join catalog_items i on i.id = f.attribute_item_id"
            " where f.revision_id = %s order by f.attribute_item_id, f.id desc",
            (revision_id,),
        )
        facts = cur.fetchall()
        cur.execute(
            "select fv.fact_id, av.key from fact_values fv join attribute_values av"
            " on av.id = fv.value_id join consultation_facts f on f.id = fv.fact_id"
            " where f.revision_id = %s order by fv.fact_id, fv.value_id",
            (revision_id,),
        )
        values: dict[int, list[str]] = {}
        for r in cur.fetchall():
            values.setdefault(r["fact_id"], []).append(r["key"])
        cur.execute(
            "select e.origin, i.slug, e.span from consultation_abb_events e"
            " join catalog_items i on i.id = e.abb_item_id where e.revision_id = %s order by e.id",
            (revision_id,),
        )
        events = cur.fetchall()

    attributes: dict[str, AttributeValue] = {}
    unknown: list[str] = []
    for f in facts:
        if f["source"] == "unknown" or not values.get(f["id"]):
            unknown.append(f["slug"])
            continue
        vals = values[f["id"]]
        attributes[f["slug"]] = AttributeValue(
            value=vals[0] if len(vals) == 1 else vals,
            source=f["source"],
            span=(f["span"] or {}).get("text", ""),
        )
    identified: dict[str, str] = {}
    for e in events:
        if e["origin"] == "user_removed":
            identified.pop(e["slug"], None)
        else:
            identified[e["slug"]] = (e["span"] or {}).get("text", "")
    return (
        InterpreterOutput(
            abbs=[AbbMention(id=k, span=v) for k, v in identified.items()], attributes=attributes
        ),
        sorted(unknown),
    )


def _inputs_hash(output: InterpreterOutput, snapshot_id: int) -> str:
    canonical = json.dumps(
        {
            "input": output.model_dump(mode="json", exclude={"abbs": {"__all__": {"span"}}}),
            "snapshot": snapshot_id,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def evaluate(
    conn: Conn, ctx: Context, user: User, revision_id: int, trigger: Trigger
) -> dict[str, Any]:
    """Run the engine on the current facts and store the evaluation (reused if nothing changed)."""
    repo = CatalogRepo(conn)
    catalog = repo.load_catalog()
    errors = [str(i) for i in validate_catalog(catalog) if i.severity == "error"]
    if errors:
        raise CatalogInvalid(errors)
    engine_input, _ = fold_state(conn, revision_id)
    try:
        result = run_engine(catalog, engine_input)
    except EngineInputError as exc:
        raise InvalidInput(str(exc)) from exc
    snapshot_id = repo.snapshot()
    digest = _inputs_hash(engine_input, snapshot_id)

    last = conn.execute(
        "select id, inputs_hash from evaluations where revision_id = %s order by id desc limit 1",
        (revision_id,),
    ).fetchone()
    if last is not None and last[1] == digest:
        return {"id": last[0], "reused": True}

    trace = [e.model_dump(mode="json") for e in build_trace(result, catalog)]
    row = conn.execute(
        "insert into evaluations (revision_id, snapshot_id, inputs_hash, input, result, trace,"
        " trigger, created_by) values (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)"
        " returning id",
        (
            revision_id,
            snapshot_id,
            digest,
            engine_input.model_dump_json(),
            json.dumps({"schema_version": RESULT_SCHEMA_VERSION, **result.model_dump(mode="json")}),
            json.dumps({"schema_version": RESULT_SCHEMA_VERSION, "entries": trace}),
            trigger,
            user.id,
        ),
    ).fetchone()
    assert row is not None
    evaluation_id = int(row[0])
    _store_item_uses(conn, repo, evaluation_id, result)
    return {"id": evaluation_id, "reused": False}


def _store_item_uses(
    conn: Conn, repo: CatalogRepo, evaluation_id: int, result: EngineResult
) -> None:
    """Feeds item usage statistics and the gap queue (outcome `gap`) cheaply."""
    uses: dict[tuple[int, str], str] = {}
    for abb in result.abbs:
        uses[(repo.item_id("abb", abb.id), "abb")] = abb.coverage
        for ev in abb.origin:
            uses[(repo.item_id("rule", ev.rule), "rule")] = "applied" if ev.result else "undecided"
        for sbb in abb.sbbs:
            uses[(repo.item_id("sbb", sbb.id), "sbb")] = sbb.result
    for (item_id, role), outcome in uses.items():
        conn.execute(
            "insert into evaluation_item_uses (evaluation_id, item_id, role, outcome)"
            " values (%s, %s, %s, %s)",
            (evaluation_id, item_id, role, outcome),
        )


# ------------------------------------------------------------- user changes


def _current(conn: Conn, user: User, consultation_id: int) -> dict[str, Any]:
    _consultation(conn, user, consultation_id)
    return latest_revision(conn, consultation_id)


def answer(
    conn: Conn,
    ctx: Context,
    user: User,
    consultation_id: int,
    attribute: str,
    value: str | list[str],
) -> dict[str, Any]:
    """Answer an open question. "unknown" is a valid answer and stays unknown."""
    return _set_fact(conn, ctx, user, consultation_id, attribute, value, "answered", "answer")


def edit_fact(
    conn: Conn,
    ctx: Context,
    user: User,
    consultation_id: int,
    attribute: str,
    value: str | list[str],
) -> dict[str, Any]:
    """Change a value the Interpreter filled in; it becomes `edited` (by you)."""
    return _set_fact(conn, ctx, user, consultation_id, attribute, value, "edited", "edit")


def _set_fact(
    conn: Conn,
    ctx: Context,
    user: User,
    consultation_id: int,
    attribute: str,
    value: str | list[str],
    source: str,
    trigger: Trigger,
) -> dict[str, Any]:
    revision = _current(conn, user, consultation_id)
    repo = CatalogRepo(conn)
    catalog = repo.load_catalog()
    attr = catalog.attribute(attribute)
    if attr is None:
        raise InvalidInput(f"unknown attribute {attribute!r}")
    values = [value] if isinstance(value, str) else list(value)
    if values == ["unknown"]:
        stored: list[str] | None = None
        source = "unknown"
    else:
        if not values or any(v not in attr.values for v in values):
            raise InvalidInput(f"attribute {attribute!r}: invalid value {values}")
        if len(values) > 1 and not attr.multi:
            raise InvalidInput(f"attribute {attribute!r} is single-valued")
        stored = values
    _insert_fact(conn, repo, revision["id"], attribute, stored, source, None, None, user.id)
    evaluate(conn, ctx, user, revision["id"], trigger)
    return view(conn, user, consultation_id)


def add_abb(conn: Conn, ctx: Context, user: User, consultation_id: int, abb: str) -> dict[str, Any]:
    revision = _current(conn, user, consultation_id)
    repo = CatalogRepo(conn)
    if repo.load_catalog().abb(abb) is None:
        raise InvalidInput(f"unknown ABB {abb!r}")
    conn.execute(
        "insert into consultation_abb_events (revision_id, abb_item_id, origin, actor_id)"
        " values (%s, %s, 'user_added', %s)",
        (revision["id"], repo.item_id("abb", abb), user.id),
    )
    conn.execute(
        "update consultation_revisions set unrecognised = false where id = %s", (revision["id"],)
    )
    evaluate(conn, ctx, user, revision["id"], "edit")
    return view(conn, user, consultation_id)


def remove_abb(
    conn: Conn, ctx: Context, user: User, consultation_id: int, abb: str
) -> dict[str, Any]:
    """Only ABBs identified from the text (or added by the user) can be removed here;
    ABBs activated by rules cannot (use feedback)."""
    revision = _current(conn, user, consultation_id)
    state, _ = fold_state(conn, revision["id"])
    if abb not in {m.id for m in state.abbs}:
        raise InvalidInput(f"{abb!r} is not an identified ABB of this consultation")
    repo = CatalogRepo(conn)
    conn.execute(
        "insert into consultation_abb_events (revision_id, abb_item_id, origin, actor_id)"
        " values (%s, %s, 'user_removed', %s)",
        (revision["id"], repo.item_id("abb", abb), user.id),
    )
    evaluate(conn, ctx, user, revision["id"], "edit")
    return view(conn, user, consultation_id)


# ------------------------------------------------------------------- rationale


def generate_rationale(
    conn: Conn, ctx: Context, user: User, consultation_id: int, detail: DetailLevel = "summary"
) -> dict[str, Any]:
    """Write the explanation of the latest evaluation. The checker result is stored with it."""
    revision = _current(conn, user, consultation_id)
    row = conn.execute(
        "select id, snapshot_id, result from evaluations where revision_id = %s"
        " order by id desc limit 1",
        (revision["id"],),
    ).fetchone()
    if row is None:
        raise NothingToExplain("there is no evaluation to explain yet")
    stored = dict(row[2])
    stored.pop("schema_version", None)
    result = EngineResult.model_validate(stored)
    # the catalog exactly as it was when the evaluation ran
    catalog = CatalogRepo(conn).load_snapshot(row[1])

    model = _model(ctx.settings, "writer")
    try:
        outcome = write_rationale(
            ctx.llm_factory(), model, result, catalog, ctx.settings.language, detail
        )
    except AgentError as exc:
        record_run(conn, exc.run, user.id)
        conn.commit()
        raise
    run_id = record_run(conn, outcome.run, user.id)
    conn.execute(
        "insert into rationales (evaluation_id, llm_run_id, content, checker, status, created_by)"
        " values (%s, %s, %s::jsonb, %s::jsonb, %s, %s)",
        (
            row[0],
            run_id,
            outcome.rationale.model_dump_json(),
            json.dumps(outcome.checker),
            outcome.status,
            user.id,
        ),
    )
    return view(conn, user, consultation_id)


# ------------------------------------------------------------------------ view


def _display_catalog(
    catalog: Catalog, state: InterpreterOutput, result: dict[str, Any] | None
) -> dict[str, Any]:
    """Names and texts the page needs to show the result, from the catalog the evaluation
    used. All ABBs are listed (alphabetical) so the user can add one."""
    abb_ids = {a["id"] for a in (result or {}).get("abbs", [])}
    questions = {q["attribute"] for q in (result or {}).get("pending_questions", [])}
    attribute_ids = questions | set(state.attributes)
    return {
        "abbs": [
            {
                "id": a.id,
                "name": a.name,
                "domain": a.domain,
                "cross_cutting": a.cross_cutting,
                "description": a.description,
                "does_not_apply_when": a.does_not_apply_when,
                "status": a.status,
            }
            for a in sorted(catalog.abbs, key=lambda x: x.id)
        ],
        "sbbs": [
            {
                "id": s.id,
                "realises": s.realises,
                "name": s.name,
                "when_to_choose": s.when_to_choose,
                "limitations": s.limitations,
                "characteristics": s.characteristics,
                "owner": s.owner,
            }
            for s in sorted(catalog.sbbs, key=lambda x: x.id)
            if s.realises in abb_ids
        ],
        "attributes": [
            {"id": a.id, "question": a.question, "values": a.values, "multi": a.multi}
            for a in sorted(catalog.attributes, key=lambda x: x.id)
            if a.id in attribute_ids
        ],
    }


def view(
    conn: Conn, user: User, consultation_id: int, revision_number: int | None = None
) -> dict[str, Any]:
    """Everything the session page shows, from stored data (no recomputation).

    An earlier revision stays readable: pass its number (consult.md 5).
    """
    cons = _consultation(conn, user, consultation_id)
    revision = latest_revision(conn, consultation_id)
    latest_number = revision["number"]
    if revision_number is not None and revision_number != latest_number:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select id, number, requirement_text, unrecognised, created_at"
                " from consultation_revisions where consultation_id = %s and number = %s",
                (consultation_id, revision_number),
            )
            found = cur.fetchone()
        if found is None:
            raise NotFound("revision not found")
        revision = found
    state, unknown = fold_state(conn, revision["id"])
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select id, snapshot_id, trigger, created_at, result, trace from evaluations"
            " where revision_id = %s order by id desc limit 1",
            (revision["id"],),
        )
        evaluation = cur.fetchone()
        cur.execute(
            "select r.id, r.evaluation_id, r.status, r.content, r.checker, r.created_at"
            " from rationales r join evaluations e on e.id = r.evaluation_id"
            " where e.revision_id = %s order by r.id desc limit 1",
            (revision["id"],),
        )
        rationale = cur.fetchone()
        cur.execute(
            "select number, created_at from consultation_revisions where consultation_id = %s"
            " order by number",
            (consultation_id,),
        )
        revisions = cur.fetchall()

    result: dict[str, Any] | None = None
    if evaluation is not None:
        result = {k: v for k, v in evaluation["result"].items() if k != "schema_version"}
    if rationale is not None:
        rationale["outdated"] = evaluation is None or rationale["evaluation_id"] != evaluation["id"]

    from cheshire.consult import records  # late: records builds on this module

    repo = CatalogRepo(conn)
    shown = repo.load_snapshot(evaluation["snapshot_id"]) if evaluation else repo.load_catalog()
    return {
        "catalog": _display_catalog(shown, state, result),
        "choices": records.current_choices(conn, revision["id"]),
        "feedback": records.feedback_of(conn, revision["id"]),
        "pinned": records.pinned(conn, revision["id"]),
        "id": cons["id"],
        "title": cons["title"],
        "owner": cons["owner"],
        "revision": {k: revision[k] for k in ("number", "requirement_text", "unrecognised")},
        "latest_revision": latest_number,
        "revisions": revisions,
        "identified_abbs": [m.model_dump() for m in state.abbs],
        "facts": {k: v.model_dump() for k, v in state.attributes.items()},
        "answered_unknown": unknown,
        "evaluation": (
            {
                "id": evaluation["id"],
                "snapshot_id": evaluation["snapshot_id"],
                "trigger": evaluation["trigger"],
                "at": evaluation["created_at"],
                "result": result,
                "trace": evaluation["trace"]["entries"],
            }
            if evaluation is not None
            else None
        ),
        "rationale": rationale,
    }
