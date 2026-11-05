"""Consultation endpoints (requirement -> interpretation -> engine -> rationale)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from cheshire.agents.base import AgentError, OutputRejected, ProviderFailure
from cheshire.agents.writer import DetailLevel
from cheshire.api.deps import Config, Conn, require
from cheshire.auth.service import User
from cheshire.consult import export, records, service
from cheshire.consult.service import ConsultError, Context
from cheshire.providers.base import LLMError, LLMNotConfigured

router = APIRouter(prefix="/api/consultations")

Consultant = Annotated[User, Depends(require("consult"))]

_STATUS = {
    "not_found": 404,
    "empty_catalog": 409,
    "catalog_invalid": 409,
    "invalid_input": 422,
    "nothing_to_explain": 409,
    "forbidden": 403,
}


def get_context(request: Request, settings: Config) -> Context:
    factory = getattr(request.app.state, "llm_factory", None)
    if factory is None:
        raise HTTPException(503, {"code": "llm_not_configured", "message": "no LLM configured"})
    return Context(settings, factory)


Ctx = Annotated[Context, Depends(get_context)]


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, ConsultError):
        detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
        if isinstance(exc, service.CatalogInvalid):
            detail["errors"] = exc.errors
        return HTTPException(_STATUS.get(exc.code, 400), detail)
    if isinstance(exc, LLMNotConfigured):
        return HTTPException(503, {"code": "llm_not_configured", "message": str(exc)})
    if isinstance(exc, ProviderFailure):
        return HTTPException(502, {"code": "llm_unavailable", "message": str(exc)})
    if isinstance(exc, OutputRejected):
        return HTTPException(
            502, {"code": "llm_output_rejected", "message": str(exc), "problems": exc.problems}
        )
    if isinstance(exc, AgentError | LLMError):
        return HTTPException(502, {"code": "llm_error", "message": str(exc)})
    return HTTPException(500, "unexpected error")


_EXPECTED = (ConsultError, LLMNotConfigured, AgentError, LLMError)


class CreateIn(BaseModel):
    requirement: str = Field(min_length=1, max_length=20000)
    title: str = ""


@router.post("", status_code=201)
def create(body: CreateIn, user: Consultant, conn: Conn, ctx: Ctx) -> dict[str, Any]:
    """Create a consultation and analyze the requirement. The text is kept even if the
    provider fails: the response is an error but the consultation exists (`Try again`)."""
    try:
        consultation_id = service.create(conn, user, body.requirement, body.title)
        conn.commit()
        return service.analyze(conn, ctx, user, consultation_id)
    except _EXPECTED as exc:
        raise _http(exc) from exc


@router.get("")
def list_all(user: Consultant, conn: Conn) -> list[dict[str, Any]]:
    return service.list_consultations(conn, user)


@router.get("/{consultation_id}")
def get(
    consultation_id: int, user: Consultant, conn: Conn, revision: int | None = None
) -> dict[str, Any]:
    try:
        return service.view(conn, user, consultation_id, revision)
    except _EXPECTED as exc:
        raise _http(exc) from exc


class RevisionIn(BaseModel):
    requirement: str = Field(min_length=1, max_length=20000)


@router.post("/{consultation_id}/revisions", status_code=201)
def revise(
    consultation_id: int, body: RevisionIn, user: Consultant, conn: Conn, ctx: Ctx
) -> dict[str, Any]:
    try:
        service.new_revision(conn, user, consultation_id, body.requirement)
        conn.commit()
        return service.analyze(conn, ctx, user, consultation_id)
    except _EXPECTED as exc:
        raise _http(exc) from exc


@router.post("/{consultation_id}/analyze")
def reanalyze(consultation_id: int, user: Consultant, conn: Conn, ctx: Ctx) -> dict[str, Any]:
    """Try again after a provider error, on the latest revision."""
    try:
        return service.analyze(conn, ctx, user, consultation_id)
    except _EXPECTED as exc:
        raise _http(exc) from exc


class ValueIn(BaseModel):
    value: str | list[str]


class AnswerIn(ValueIn):
    attribute: str


@router.post("/{consultation_id}/answers")
def answer(
    consultation_id: int, body: AnswerIn, user: Consultant, conn: Conn, ctx: Ctx
) -> dict[str, Any]:
    try:
        return service.answer(conn, ctx, user, consultation_id, body.attribute, body.value)
    except _EXPECTED as exc:
        raise _http(exc) from exc


@router.put("/{consultation_id}/facts/{attribute}")
def edit_fact(
    consultation_id: int, attribute: str, body: ValueIn, user: Consultant, conn: Conn, ctx: Ctx
) -> dict[str, Any]:
    try:
        return service.edit_fact(conn, ctx, user, consultation_id, attribute, body.value)
    except _EXPECTED as exc:
        raise _http(exc) from exc


class AbbIn(BaseModel):
    abb: str


@router.post("/{consultation_id}/abbs")
def add_abb(
    consultation_id: int, body: AbbIn, user: Consultant, conn: Conn, ctx: Ctx
) -> dict[str, Any]:
    try:
        return service.add_abb(conn, ctx, user, consultation_id, body.abb)
    except _EXPECTED as exc:
        raise _http(exc) from exc


@router.delete("/{consultation_id}/abbs/{abb}")
def remove_abb(
    consultation_id: int, abb: str, user: Consultant, conn: Conn, ctx: Ctx
) -> dict[str, Any]:
    try:
        return service.remove_abb(conn, ctx, user, consultation_id, abb)
    except _EXPECTED as exc:
        raise _http(exc) from exc


class RationaleIn(BaseModel):
    detail: DetailLevel = "summary"


@router.post("/{consultation_id}/rationale")
def rationale(
    consultation_id: int, body: RationaleIn, user: Consultant, conn: Conn, ctx: Ctx
) -> dict[str, Any]:
    """Generate (or regenerate) the explanation of the latest evaluation."""
    try:
        return service.generate_rationale(conn, ctx, user, consultation_id, body.detail)
    except _EXPECTED as exc:
        raise _http(exc) from exc


# --------------------------------------------------------------- choices, feedback, pins


class ChoiceIn(BaseModel):
    abb: str
    kind: records.ChoiceKind
    sbb: str | None = None
    reason: str = Field(default="", max_length=4000)


@router.post("/{consultation_id}/choices", status_code=201)
def choose(consultation_id: int, body: ChoiceIn, user: Consultant, conn: Conn) -> dict[str, Any]:
    """Append a choice record for one ABB (the latest per ABB is the current one)."""
    try:
        records.record_choice(
            conn, user, consultation_id, body.abb, body.kind, body.sbb, body.reason
        )
        return service.view(conn, user, consultation_id)
    except _EXPECTED as exc:
        raise _http(exc) from exc


class FeedbackIn(BaseModel):
    kind: records.FeedbackKind
    text: str = Field(min_length=1, max_length=4000)
    abb: str | None = None


@router.post("/{consultation_id}/feedback", status_code=201)
def send_feedback(
    consultation_id: int, body: FeedbackIn, user: Consultant, conn: Conn
) -> dict[str, Any]:
    try:
        records.add_feedback(conn, user, consultation_id, body.kind, body.text, body.abb)
        return service.view(conn, user, consultation_id)
    except _EXPECTED as exc:
        raise _http(exc) from exc


class PinIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.put("/{consultation_id}/pin")
def pin(consultation_id: int, body: PinIn, user: Consultant, conn: Conn) -> dict[str, Any]:
    """Pin the latest result as a reference case (architects)."""
    try:
        records.pin(conn, user, consultation_id, body.title)
        return service.view(conn, user, consultation_id)
    except _EXPECTED as exc:
        raise _http(exc) from exc


@router.delete("/{consultation_id}/pin")
def unpin(consultation_id: int, user: Consultant, conn: Conn) -> dict[str, Any]:
    try:
        records.unpin(conn, user, consultation_id)
        return service.view(conn, user, consultation_id)
    except _EXPECTED as exc:
        raise _http(exc) from exc


@router.get("/{consultation_id}/export")
def export_consultation(
    consultation_id: int,
    user: Consultant,
    conn: Conn,
    format: Literal["markdown", "json"] = "markdown",
) -> Response:
    try:
        shown = service.view(conn, user, consultation_id)
    except _EXPECTED as exc:
        raise _http(exc) from exc
    revision = service.latest_revision(conn, consultation_id)
    conn.execute(
        "insert into exports (consultation_id, revision_id, format, requested_by)"
        " values (%s, %s, %s, %s)",
        (consultation_id, revision["id"], format, user.id),
    )
    if format == "json":
        body, media, ext = export.to_json(shown), "application/json", "json"
    else:
        body, media, ext = export.to_markdown(shown), "text/markdown; charset=utf-8", "md"
    return Response(
        body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="consultation-{consultation_id}.{ext}"'
        },
    )


# ----------------------------------------------------------------- preferences, cases

prefs_router = APIRouter(prefix="/api")


class PreferencesIn(BaseModel):
    detail_level: Literal["summary", "detailed"] | None = None
    locale: str | None = None
    theme: Literal["system", "light", "dark"] | None = None


@prefs_router.get("/preferences")
def get_preferences(user: Consultant, conn: Conn) -> dict[str, str]:
    return records.get_preferences(conn, user)


@prefs_router.put("/preferences")
def put_preferences(body: PreferencesIn, user: Consultant, conn: Conn) -> dict[str, str]:
    try:
        return records.set_preferences(conn, user, body.detail_level, body.locale, body.theme)
    except _EXPECTED as exc:
        raise _http(exc) from exc


ArchitectUser = Annotated[User, Depends(require("catalog.write"))]


@prefs_router.get("/reference-cases")
def reference_cases(user: ArchitectUser, conn: Conn) -> list[dict[str, Any]]:
    return records.list_reference_cases(conn)
