"""Catalog maintenance (M5): health, work queue, Try-it, impact preview, history, starter packs.

Mounted before `catalog_routes`, because its fixed paths (`/health`, `/work`, ...) must not
be read as `{kind}`.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, TypeAdapter, ValidationError

from cheshire.api.consult_routes import _EXPECTED, Ctx
from cheshire.api.consult_routes import _http as _llm_http
from cheshire.api.deps import Config, Conn, require
from cheshire.auth import service
from cheshire.auth.service import User
from cheshire.catalog.models import Cond, Status
from cheshire.catalog.transfer import item_to_raw
from cheshire.db import catalog_import
from cheshire.db.catalog_repo import (
    MODEL_FOR_KIND,
    CatalogRefError,
    CatalogRepo,
    CatalogStateError,
    Kind,
)
from cheshire.maintenance import impact, interviews, overview, queue, starter
from cheshire.maintenance.diff import Change, diff_items
from cheshire.maintenance.tryit import TryInputError, TryResult, try_condition

router = APIRouter(prefix="/api/catalog")

Reader = Annotated[User, Depends(require("catalog.read"))]
Writer = Annotated[User, Depends(require("catalog.write"))]
Importer = Annotated[User, Depends(require("catalog.import"))]
Admin = Annotated[User, Depends(require("users.manage"))]

_STATUS = {"not_found": 404, "conflict": 409, "invalid": 422}


def _queue_error(exc: queue.QueueError) -> HTTPException:
    return HTTPException(_STATUS.get(exc.code, 422), {"code": exc.code, "message": str(exc)})


# --- overview -----------------------------------------------------------------------


@router.get("/health")
def health(_: Reader, conn: Conn) -> dict[str, Any]:
    return overview.health(conn)


# --- work queue ---------------------------------------------------------------------


@router.get("/work")
def work(
    user: Writer,
    conn: Conn,
    config: Config,
    status: str = "active",
    kind: str | None = None,
) -> list[dict[str, Any]]:
    if status not in ("active", "open", "claimed", "done", "dismissed"):
        raise HTTPException(422, "status must be active, open, claimed, done or dismissed")
    if kind is not None and kind not in queue.KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(queue.KINDS)}")
    return queue.list_work(
        conn, user, warning_hours=config.claim_warning_hours, status=status, kind=kind
    )


def _after(conn: Conn, user: User, config: Config, work_id: int) -> dict[str, Any]:
    return queue.get_work(conn, user, work_id, config.claim_warning_hours)


@router.post("/work/{work_id}/claim")
def claim(work_id: int, user: Writer, conn: Conn, config: Config) -> dict[str, Any]:
    try:
        queue.claim(conn, user, work_id, config.claim_ttl_days)
        return _after(conn, user, config, work_id)
    except queue.QueueError as exc:
        raise _queue_error(exc) from exc


@router.post("/work/{work_id}/renew")
def renew(work_id: int, user: Writer, conn: Conn, config: Config) -> dict[str, Any]:
    try:
        queue.renew(conn, user, work_id, config.claim_ttl_days)
        return _after(conn, user, config, work_id)
    except queue.QueueError as exc:
        raise _queue_error(exc) from exc


@router.post("/work/{work_id}/release")
def release(work_id: int, user: Writer, conn: Conn, config: Config) -> dict[str, Any]:
    try:
        queue.release(conn, user, work_id)
        return _after(conn, user, config, work_id)
    except queue.QueueError as exc:
        raise _queue_error(exc) from exc


class ReasonIn(BaseModel):
    reason: str = ""


@router.post("/work/{work_id}/dismiss")
def dismiss(
    work_id: int, body: ReasonIn, user: Writer, conn: Conn, config: Config
) -> dict[str, Any]:
    try:
        queue.dismiss(conn, user, work_id, body.reason)
        service.audit(conn, user.id, "work.dismiss", "work_item", work_id, {"reason": body.reason})
        return _after(conn, user, config, work_id)
    except queue.QueueError as exc:
        raise _queue_error(exc) from exc


@router.post("/work/{work_id}/resolve")
def resolve(
    work_id: int, body: ReasonIn, user: Writer, conn: Conn, config: Config
) -> dict[str, Any]:
    try:
        queue.resolve(conn, user, work_id, body.reason)
        return _after(conn, user, config, work_id)
    except queue.QueueError as exc:
        raise _queue_error(exc) from exc


class AssignIn(BaseModel):
    user_id: int


@router.post("/work/{work_id}/assign")
def assign(
    work_id: int, body: AssignIn, admin: Admin, conn: Conn, config: Config
) -> dict[str, Any]:
    try:
        queue.reassign(conn, admin, work_id, body.user_id, config.claim_ttl_days)
        service.audit(conn, admin.id, "work.assign", "work_item", work_id, {"to": body.user_id})
        return _after(conn, admin, config, work_id)
    except queue.QueueError as exc:
        raise _queue_error(exc) from exc


# --- Try it and impact ----------------------------------------------------------------


class TryIn(BaseModel):
    condition: dict[str, Any]
    attributes: dict[str, str | list[str]] = {}
    abbs: list[str] = []


@router.post("/try", response_model=TryResult)
def try_it(body: TryIn, _: Writer, conn: Conn) -> TryResult:
    """Evaluate a condition (not saved) against hand-set facts, with the users' trace text."""
    try:
        condition = TypeAdapter(Cond).validate_python(body.condition)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
    catalog = CatalogRepo(conn).load_catalog(include_drafts=True)
    try:
        return try_condition(catalog, condition, body.attributes, body.abbs)
    except TryInputError as exc:
        raise HTTPException(422, {"code": "invalid_input", "message": str(exc)}) from exc


class ImpactIn(BaseModel):
    kind: Kind
    item: dict[str, Any]
    status: Status = "proposed"


@router.post("/impact")
def impact_preview(body: ImpactIn, _: Writer, conn: Conn, config: Config) -> dict[str, Any]:
    """What saving this item would change, replayed over reference cases and recent ones."""
    try:
        model = MODEL_FOR_KIND[body.kind].model_validate({**body.item, "status": body.status})
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
    return impact.preview(conn, body.kind, model, body.status, config.impact_recent_consultations)


# --- starter packs ---------------------------------------------------------------------


@router.get("/starter-packs")
def starter_packs(_: Writer, config: Config) -> list[dict[str, object]]:
    return starter.available(config)


class StarterIn(BaseModel):
    dry_run: bool = True


@router.post("/starter-packs/{name}/import")
def import_starter_pack(
    name: str, body: StarterIn, user: Importer, conn: Conn, config: Config
) -> catalog_import.ImportReport:
    from cheshire.catalog.transfer import dump_document

    pack = starter.load(config, name)
    if pack is None:
        raise HTTPException(404, f"no starter pack {name!r}")
    content = dump_document(pack, "yaml")
    repo = CatalogRepo(conn)
    try:
        if body.dry_run:
            report = catalog_import.diff(repo, pack)
            catalog_import.record_dry_run(
                conn, report, user_id=user.id, filename=f"starter:{name}", content=content
            )
            return report
        report = catalog_import.apply(
            conn, pack, user_id=user.id, filename=f"starter:{name}", content=content
        )
    except (CatalogRefError, CatalogStateError, psycopg.errors.IntegrityError) as exc:
        raise HTTPException(409, {"code": "conflict", "message": str(exc)}) from exc
    if report.blocking:
        raise HTTPException(409, {"code": "validation_errors", "report": report.model_dump()})
    service.audit(conn, user.id, "catalog.import", "import_batch", report.batch_id, {"pack": name})
    return report


# --- item pages -------------------------------------------------------------------------


@router.get("/{kind}/{slug}/usage")
def usage(kind: Kind, slug: str, _: Reader, conn: Conn) -> dict[str, Any]:
    try:
        return overview.usage(conn, CatalogRepo(conn), kind, slug)
    except CatalogRefError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{kind}/{slug}/connections")
def connections(kind: Kind, slug: str, _: Reader, conn: Conn) -> dict[str, Any]:
    try:
        return overview.connections(conn, CatalogRepo(conn), kind, slug)
    except CatalogRefError as exc:
        raise HTTPException(404, str(exc)) from exc


class DiffOut(BaseModel):
    from_version: int
    to_version: int
    changes: list[Change]


@router.get("/{kind}/{slug}/diff", response_model=DiffOut)
def version_diff(
    kind: Kind, slug: str, _: Reader, conn: Conn, from_version: int, to_version: int
) -> DiffOut:
    repo = CatalogRepo(conn)
    before = repo.load_item(kind, slug, from_version)
    after = repo.load_item(kind, slug, to_version)
    if before is None or after is None:
        raise HTTPException(404, f"{kind} {slug!r} has no such version")
    return DiffOut(
        from_version=from_version,
        to_version=to_version,
        changes=diff_items(item_to_raw(before), item_to_raw(after)),
    )


@router.post("/{kind}/{slug}/versions/{number}/restore")
def restore(kind: Kind, slug: str, number: int, user: Writer, conn: Conn) -> dict[str, Any]:
    """Restoring never rewrites history: it saves a copy of an old version as a new one."""
    repo = CatalogRepo(conn)
    old = repo.load_item(kind, slug, number)
    if old is None:
        raise HTTPException(404, f"{kind} {slug!r} has no version {number}")
    try:
        with conn.transaction():
            version_id = repo.save_version(
                kind,
                old,
                status="proposed",
                author_id=user.id,
                origin="restore",
                origin_ref=number,
                change_note=f"Restored from version {number}",
            )
    except (CatalogRefError, CatalogStateError, psycopg.errors.IntegrityError) as exc:
        raise HTTPException(409, {"code": "conflict", "message": f"cannot restore: {exc}"}) from exc
    new = conn.execute("select number from item_versions where id = %s", (version_id,)).fetchone()
    assert new is not None
    return {"version": new[0], "status": "proposed", "restored_from": number}


# --- guided capture (Interviewer) ---------------------------------------------------------

interview_router = APIRouter(prefix="/api")


def _interview_http(exc: Exception) -> HTTPException:
    if isinstance(exc, interviews.InterviewError):
        return HTTPException(_STATUS.get(exc.code, 422), {"code": exc.code, "message": str(exc)})
    return _llm_http(exc)


_INTERVIEW_ERRORS = (interviews.InterviewError, *_EXPECTED)


class StartIn(BaseModel):
    subject: str | None = None  # an ABB id; omit to start from scratch


@interview_router.post("/interviews", status_code=201)
def start_interview(body: StartIn, user: Writer, conn: Conn) -> dict[str, Any]:
    try:
        interview_id = interviews.start(conn, user, body.subject)
    except interviews.InterviewError as exc:
        raise _interview_http(exc) from exc
    return interviews.view(conn, interview_id)


@interview_router.get("/interviews")
def list_interviews(_: Writer, conn: Conn) -> list[dict[str, Any]]:
    return interviews.list_interviews(conn)


@interview_router.get("/interviews/{interview_id}")
def get_interview(interview_id: int, _: Writer, conn: Conn) -> dict[str, Any]:
    try:
        return interviews.view(conn, interview_id)
    except interviews.InterviewError as exc:
        raise _interview_http(exc) from exc


class AnswerIn(BaseModel):
    text: str = ""
    not_applicable: bool = False


@interview_router.post("/interviews/{interview_id}/answers")
def answer_interview(
    interview_id: int, body: AnswerIn, user: Writer, conn: Conn, ctx: Ctx
) -> dict[str, Any]:
    """Store the answer (kept even if the provider fails), then collect suggestions."""
    try:
        interviews.answer(conn, ctx, user, interview_id, body.text, body.not_applicable)
    except _INTERVIEW_ERRORS as exc:
        raise _interview_http(exc) from exc
    return interviews.view(conn, interview_id)


@interview_router.post("/interviews/{interview_id}/retry")
def retry_interview(interview_id: int, user: Writer, conn: Conn, ctx: Ctx) -> dict[str, Any]:
    try:
        interviews.retry(conn, ctx, user, interview_id)
    except _INTERVIEW_ERRORS as exc:
        raise _interview_http(exc) from exc
    return interviews.view(conn, interview_id)


@interview_router.post("/interviews/{interview_id}/close")
def close_interview(interview_id: int, _: Writer, conn: Conn) -> dict[str, Any]:
    try:
        interviews.close(conn, interview_id)
        return interviews.view(conn, interview_id)
    except interviews.InterviewError as exc:
        raise _interview_http(exc) from exc


class DecisionIn(BaseModel):
    decision: interviews.Decision
    note: str = ""


@interview_router.post("/suggestions/{suggestion_id}/decision")
def decide_suggestion(
    suggestion_id: int, body: DecisionIn, user: Writer, conn: Conn, ctx: Ctx
) -> dict[str, Any]:
    """accept (saves a `proposed` version), reject, or "it depends" (asks for a refined one)."""
    try:
        interviews.decide(conn, ctx, user, suggestion_id, body.decision, body.note)
        row = conn.execute(
            "select interview_id from suggestions where id = %s", (suggestion_id,)
        ).fetchone()
    except _INTERVIEW_ERRORS as exc:
        raise _interview_http(exc) from exc
    assert row is not None
    return interviews.view(conn, row[0])
