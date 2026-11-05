"""Server-sent events for the analysis pipeline (consult.md 5, step 2).

The client posts the requirement and reads a stream of events:

  created      {id}                       the consultation exists (text is kept)
  stage        {stage}                    interpreting | checking | evaluating | writing
  result       {consultation}             the session view as soon as the engine finished
  rationale    {consultation}             the first explanation, after the result
  rationale_error {code, message}         the explanation failed; the page stays usable
  error        {code, message, problems?} the analysis failed
  done         {}

The rationale is sent whole once it has passed the checker: sentences are verified
against the trace before anyone sees them (invariant 6), so tokens are not streamed.
The pipeline runs in its own thread and connection, so the page never waits for the
explanation.
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Callable, Iterator
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from cheshire.api.consult_routes import Consultant, _http
from cheshire.auth.service import User
from cheshire.consult import records, service
from cheshire.consult.service import Context

router = APIRouter(prefix="/api/consultations")

Emit = Callable[[str, Any], None]
_END = object()


def _sse(event: str, data: Any) -> bytes:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data))}\n\n".encode()


def _error_payload(exc: Exception) -> dict[str, Any]:
    http = _http(exc)
    detail = http.detail
    return detail if isinstance(detail, dict) else {"code": "internal", "message": str(detail)}


def _run(
    pool: ConnectionPool[psycopg.Connection[Any]],
    request: Request,
    user: User,
    work: Callable[[psycopg.Connection[Any], Context, Emit], int],
) -> Iterator[bytes]:
    """Run `work` in a thread and relay its events; it returns the consultation id."""
    events: queue.Queue[Any] = queue.Queue()
    factory = getattr(request.app.state, "llm_factory", None)
    if factory is None:
        raise HTTPException(503, {"code": "llm_not_configured", "message": "no LLM configured"})

    def emit(event: str, data: Any) -> None:
        events.put((event, data))

    ctx = Context(
        request.app.state.settings, factory, on_stage=lambda s: emit("stage", {"stage": s})
    )

    def target() -> None:
        try:
            with pool.connection() as conn:
                consultation_id = 0
                try:
                    consultation_id = work(conn, ctx, emit)
                except Exception as exc:
                    conn.rollback()
                    emit("error", _error_payload(exc))
                    return
                # the first explanation never blocks the page: the result was already sent
                try:
                    _first_rationale(conn, ctx, user, consultation_id, emit)
                except Exception as exc:
                    conn.rollback()
                    emit("rationale_error", _error_payload(exc))
                emit("done", {})
        except Exception as exc:
            emit("error", _error_payload(exc))
        finally:
            events.put(_END)

    threading.Thread(target=target, daemon=True).start()
    while True:
        item = events.get()
        if item is _END:
            return
        yield _sse(*item)


def _first_rationale(
    conn: psycopg.Connection[Any], ctx: Context, user: User, consultation_id: int, emit: Emit
) -> None:
    """Automatic first explanation for a revision that has none (consult.md 9.1)."""
    revision = service.latest_revision(conn, consultation_id)
    has_evaluation = conn.execute(
        "select 1 from evaluations where revision_id = %s limit 1", (revision["id"],)
    ).fetchone()
    has_rationale = conn.execute(
        "select 1 from rationales r join evaluations e on e.id = r.evaluation_id"
        " where e.revision_id = %s limit 1",
        (revision["id"],),
    ).fetchone()
    if not has_evaluation or has_rationale:
        return
    emit("stage", {"stage": "writing"})
    detail = records.get_preferences(conn, user)["detail_level"]
    shown = service.generate_rationale(
        conn, ctx, user, consultation_id, "detailed" if detail == "detailed" else "summary"
    )
    conn.commit()
    emit("rationale", shown)


def _stream(request: Request, user: User, work: Callable[..., int]) -> StreamingResponse:
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(503, "database not available")
    return StreamingResponse(
        _run(pool, request, user, work),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _analysis(conn: psycopg.Connection[Any], ctx: Context, user: User, cid: int, emit: Emit) -> int:
    try:
        shown = service.analyze(conn, ctx, user, cid)
    finally:
        conn.commit()  # keeps the failed run and the stored text even when analysis fails
    emit("result", shown)
    return cid


class CreateIn(BaseModel):
    requirement: str = Field(min_length=1, max_length=20000)
    title: str = ""


class RevisionIn(BaseModel):
    requirement: str = Field(min_length=1, max_length=20000)


@router.post("/stream")
def create_stream(body: CreateIn, request: Request, user: Consultant) -> StreamingResponse:
    def work(conn: psycopg.Connection[Any], ctx: Context, emit: Emit) -> int:
        cid = service.create(conn, user, body.requirement, body.title)
        conn.commit()
        emit("created", {"id": cid})
        return _analysis(conn, ctx, user, cid, emit)

    return _stream(request, user, work)


@router.post("/{consultation_id}/revisions/stream")
def revise_stream(
    consultation_id: int, body: RevisionIn, request: Request, user: Consultant
) -> StreamingResponse:
    def work(conn: psycopg.Connection[Any], ctx: Context, emit: Emit) -> int:
        service.new_revision(conn, user, consultation_id, body.requirement)
        conn.commit()
        return _analysis(conn, ctx, user, consultation_id, emit)

    return _stream(request, user, work)


@router.post("/{consultation_id}/analyze/stream")
def analyze_stream(consultation_id: int, request: Request, user: Consultant) -> StreamingResponse:
    def work(conn: psycopg.Connection[Any], ctx: Context, emit: Emit) -> int:
        return _analysis(conn, ctx, user, consultation_id, emit)

    return _stream(request, user, work)
