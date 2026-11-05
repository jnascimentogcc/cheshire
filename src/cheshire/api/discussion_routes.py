"""Discussions (M6): inbox, the discussion page, comments and positions, the mediator,
transfer / reassign, the decision, and in-app notifications (docs/features/discussions.md).

Only architects (and admins) take part. Everybody else sees a decision summary on the item
(`GET /api/catalog/{kind}/{slug}/decisions`) and nothing of the thread.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cheshire.agents.mediator import Mode
from cheshire.api.consult_routes import _EXPECTED, Ctx
from cheshire.api.consult_routes import _http as _llm_http
from cheshire.api.deps import Config, Conn, require
from cheshire.auth import service as auth
from cheshire.auth.service import User
from cheshire.db.catalog_repo import CatalogRepo, Kind
from cheshire.discussions import mediation, notifications, service

router = APIRouter(prefix="/api")

Member = Annotated[User, Depends(require("catalog.write"))]
Reader = Annotated[User, Depends(require("catalog.read"))]
Admin = Annotated[User, Depends(require("users.manage"))]

_STATUS = {
    "not_found": 404,
    "forbidden": 403,
    "conflict": 409,
    "already_open": 409,
    "stale": 409,
    "missing_responses": 422,
    "invalid": 422,
}
_ERRORS = (service.DiscussionError, *_EXPECTED)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, service.DiscussionError):
        detail = {"code": exc.code, "message": str(exc), **exc.extra}
        return HTTPException(_STATUS.get(exc.code, 422), detail)
    return _llm_http(exc)


# --- inbox ---------------------------------------------------------------------------


@router.get("/discussions")
def inbox(
    user: Member,
    conn: Conn,
    tab: str = "open",
    kind: str | None = None,
    domain: str | None = None,
    older_than_days: int | None = None,
    inactive_days: int | None = None,
) -> list[dict[str, Any]]:
    if tab == "orphaned" and user.role != "admin":
        raise HTTPException(403, "only an admin sees the reassign queue")
    try:
        return service.list_discussions(
            conn,
            user,
            tab,
            kind=kind,
            domain=domain,
            older_than_days=older_than_days,
            inactive_days=inactive_days,
        )
    except service.DiscussionError as exc:
        raise _http(exc) from exc


class RelatedIn(BaseModel):
    kind: Kind
    slug: str


class OpenIn(BaseModel):
    kind: Kind
    slug: str = Field(min_length=1)
    proposal: dict[str, Any] | None = None  # required for an item that does not exist yet
    related: list[RelatedIn] = []
    title: str = Field(default="", max_length=200)
    work_item_id: int | None = None


@router.post("/discussions", status_code=201)
def open_discussion(
    body: OpenIn, user: Member, conn: Conn, config: Config, ctx: Ctx
) -> dict[str, Any]:
    """Open a discussion (the opener decides). The mediator's brief is requested right after;
    when the provider fails the discussion exists anyway and `mediator_error` says why."""
    try:
        did = service.open_discussion(
            conn,
            user,
            config,
            kind=body.kind,
            slug=body.slug,
            proposal=body.proposal,
            related=[(r.kind, r.slug) for r in body.related],
            title=body.title,
            work_item_id=body.work_item_id,
        )
        auth.audit(conn, user.id, "discussion.open", "discussion", did, {})
        conn.commit()
    except service.DiscussionError as exc:
        raise _http(exc) from exc
    out = service.view(conn, user, did)
    try:
        mediation.speak(conn, ctx, user, did, "brief")
        conn.commit()
        out = service.view(conn, user, did)
    except _ERRORS as exc:
        conn.rollback()
        out["mediator_error"] = _http(exc).detail
    return out


@router.get("/discussions/members")
def members(_: Member, conn: Conn) -> list[dict[str, Any]]:
    """Who can be mentioned or made decider: active architects and admins."""
    rows = conn.execute(
        "select id, display_name, role from users where active"
        " and role in ('architect', 'admin') order by display_name, id"
    ).fetchall()
    return [{"id": r[0], "name": r[1], "role": r[2]} for r in rows]


@router.get("/discussions/{discussion_id}")
def get_discussion(discussion_id: int, user: Member, conn: Conn) -> dict[str, Any]:
    try:
        return service.view(conn, user, discussion_id)
    except service.DiscussionError as exc:
        raise _http(exc) from exc


@router.post("/discussions/{discussion_id}/seen", status_code=204)
def seen(discussion_id: int, user: Member, conn: Conn) -> None:
    service.mark_seen(conn, user, discussion_id)


def _again(conn: Conn, user: User, did: int) -> dict[str, Any]:
    return service.view(conn, user, did)


@router.post("/discussions/{discussion_id}/join")
def join(discussion_id: int, user: Member, conn: Conn) -> dict[str, Any]:
    try:
        service.join(conn, user, discussion_id)
        return _again(conn, user, discussion_id)
    except service.DiscussionError as exc:
        raise _http(exc) from exc


# --- comments and positions ----------------------------------------------------------


class CommentIn(BaseModel):
    body: str
    mentions: list[int] = []


@router.post("/discussions/{discussion_id}/comments", status_code=201)
def add_comment(discussion_id: int, body: CommentIn, user: Member, conn: Conn) -> dict[str, Any]:
    try:
        service.comment(conn, user, discussion_id, body.body, body.mentions)
        return _again(conn, user, discussion_id)
    except service.DiscussionError as exc:
        raise _http(exc) from exc


class EditIn(BaseModel):
    body: str


@router.patch("/discussions/{discussion_id}/comments/{comment_id}")
def edit_comment(
    discussion_id: int, comment_id: int, body: EditIn, user: Member, conn: Conn
) -> dict[str, Any]:
    try:
        service.edit_comment(conn, user, discussion_id, comment_id, body.body)
        return _again(conn, user, discussion_id)
    except service.DiscussionError as exc:
        raise _http(exc) from exc


@router.post("/discussions/{discussion_id}/comments/{comment_id}/retract")
def retract_comment(
    discussion_id: int, comment_id: int, user: Member, conn: Conn
) -> dict[str, Any]:
    try:
        service.retract_comment(conn, user, discussion_id, comment_id)
        return _again(conn, user, discussion_id)
    except service.DiscussionError as exc:
        raise _http(exc) from exc


class PositionIn(BaseModel):
    stance: str
    reason: str = ""


@router.put("/discussions/{discussion_id}/position")
def set_position(discussion_id: int, body: PositionIn, user: Member, conn: Conn) -> dict[str, Any]:
    try:
        service.set_position(conn, user, discussion_id, body.stance, body.reason)
        return _again(conn, user, discussion_id)
    except service.DiscussionError as exc:
        raise _http(exc) from exc


# --- proposal and impact -------------------------------------------------------------


class ProposalIn(BaseModel):
    item: dict[str, Any]


@router.put("/discussions/{discussion_id}/proposal")
def propose(discussion_id: int, body: ProposalIn, user: Member, conn: Conn) -> dict[str, Any]:
    """The decider saves the pending change (a draft version: consultations ignore it)."""
    try:
        issues = service.propose(conn, user, discussion_id, body.item)
        return {**_again(conn, user, discussion_id), "issues": issues}
    except service.DiscussionError as exc:
        raise _http(exc) from exc


@router.post("/discussions/{discussion_id}/impact/refresh")
def refresh_impact(discussion_id: int, user: Member, conn: Conn, config: Config) -> dict[str, Any]:
    try:
        service.refresh_impact(conn, user, discussion_id, config)
        return _again(conn, user, discussion_id)
    except service.DiscussionError as exc:
        raise _http(exc) from exc


# --- mediator ------------------------------------------------------------------------


class MediatorIn(BaseModel):
    mode: Mode
    question: str = Field(default="", max_length=2000)


@router.post("/discussions/{discussion_id}/mediator", status_code=201)
def ask_mediator(
    discussion_id: int, body: MediatorIn, user: Member, conn: Conn, ctx: Ctx
) -> dict[str, Any]:
    """The mediator speaks on request. If it cannot (provider error, or its answer fails the
    grounding check twice) nothing is posted and the error is explained to the requester."""
    try:
        mediation.speak(conn, ctx, user, discussion_id, body.mode, body.question)
        return _again(conn, user, discussion_id)
    except _ERRORS as exc:
        raise _http(exc) from exc


# --- decider -------------------------------------------------------------------------


class TransferIn(BaseModel):
    to_user_id: int
    reason: str = Field(default="", max_length=500)


@router.post("/discussions/{discussion_id}/transfer")
def transfer(discussion_id: int, body: TransferIn, user: Member, conn: Conn) -> dict[str, Any]:
    try:
        service.transfer(conn, user, discussion_id, body.to_user_id, body.reason)
        auth.audit(
            conn, user.id, "discussion.transfer", "discussion", discussion_id,
            {"to": body.to_user_id},
        )  # fmt: skip
        return _again(conn, user, discussion_id)
    except service.DiscussionError as exc:
        raise _http(exc) from exc


@router.post("/discussions/{discussion_id}/reassign")
def reassign(discussion_id: int, body: TransferIn, admin: Admin, conn: Conn) -> dict[str, Any]:
    try:
        service.reassign(conn, admin, discussion_id, body.to_user_id, body.reason)
        auth.audit(
            conn, admin.id, "discussion.reassign", "discussion", discussion_id,
            {"to": body.to_user_id},
        )  # fmt: skip
        return _again(conn, admin, discussion_id)
    except service.DiscussionError as exc:
        raise _http(exc) from exc


class ResponseIn(BaseModel):
    position_id: int
    accepted: bool
    response: str


class DecisionIn(BaseModel):
    outcome: str
    status: str = "validated"
    rationale: str = Field(default="", max_length=5000)
    responses: list[ResponseIn] = []
    acknowledge_stale: bool = False


@router.post("/discussions/{discussion_id}/decision")
def decide(
    discussion_id: int, body: DecisionIn, user: Member, conn: Conn, config: Config
) -> dict[str, Any]:
    """Close the discussion. Only the decider; every opposing position needs a response."""
    try:
        service.decide(
            conn,
            user,
            config,
            discussion_id,
            outcome=body.outcome,
            status=body.status,
            rationale=body.rationale,
            responses=[r.model_dump() for r in body.responses],
            acknowledge_stale=body.acknowledge_stale,
        )
        auth.audit(
            conn, user.id, "discussion.decide", "discussion", discussion_id,
            {"outcome": body.outcome},
        )  # fmt: skip
        return _again(conn, user, discussion_id)
    except service.DiscussionError as exc:
        raise _http(exc) from exc


# --- what everybody sees about an item -----------------------------------------------


@router.get("/catalog/{kind}/{slug}/decisions")
def item_decisions(kind: Kind, slug: str, user: Reader, conn: Conn) -> dict[str, Any]:
    """Decision summaries (decider, outcome, rationale, date). Architects also get the link
    to the discussion and the open one, if any; users get neither."""
    if CatalogRepo(conn).find_item_id(kind, slug) is None:
        raise HTTPException(404, f"{kind} {slug!r} not found")
    rows = service.decision_summaries(conn, kind, slug)
    member = user.role in ("architect", "admin")
    if not member:
        for r in rows:
            r.pop("discussion_id", None)
    return {
        "decisions": rows,
        "open_discussion": service.open_for_item(conn, kind, slug) if member else None,
    }


# --- notifications -------------------------------------------------------------------


@router.get("/notifications")
def list_notifications(
    user: Member, conn: Conn, config: Config, unread: bool = False
) -> dict[str, Any]:
    notifications.refresh(conn, user, config.discussion_nudge_days, config.claim_warning_hours)
    return notifications.list_for(conn, user, unread_only=unread)


@router.post("/notifications/read-all")
def read_all(user: Member, conn: Conn) -> dict[str, int]:
    return {"marked": notifications.mark_all_read(conn, user)}


@router.post("/notifications/{notification_id}/read", status_code=204)
def read_one(notification_id: int, user: Member, conn: Conn) -> None:
    if not notifications.mark_read(conn, user, notification_id):
        raise HTTPException(404, "notification not found")
