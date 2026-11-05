"""Catalog CRUD, validation, import/export."""

from __future__ import annotations

from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ValidationError

from cheshire.api.deps import Conn, require
from cheshire.auth import service
from cheshire.auth.service import User
from cheshire.catalog.loader import CatalogLoadError
from cheshire.catalog.models import Status
from cheshire.catalog.transfer import Format, dump_document, item_to_raw, parse_document
from cheshire.catalog.validator import validate_catalog
from cheshire.db import catalog_import
from cheshire.db.catalog_repo import (
    MODEL_FOR_KIND,
    CatalogRefError,
    CatalogRepo,
    CatalogStateError,
    Kind,
)
from cheshire.maintenance import overview
from cheshire.maintenance.diff import diff_items

router = APIRouter(prefix="/api/catalog")

Reader = Annotated[User, Depends(require("catalog.read"))]
Writer = Annotated[User, Depends(require("catalog.write"))]
Validator = Annotated[User, Depends(require("catalog.validate"))]
Importer = Annotated[User, Depends(require("catalog.import"))]
Exporter = Annotated[User, Depends(require("catalog.export"))]


def _storage_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CatalogRefError):
        return HTTPException(422, {"code": "unknown_reference", "message": str(exc)})
    if isinstance(exc, CatalogStateError):
        return HTTPException(409, {"code": "conflict", "message": str(exc)})
    if isinstance(exc, psycopg.errors.CheckViolation | psycopg.errors.ForeignKeyViolation):
        return HTTPException(422, {"code": "constraint", "message": str(exc).splitlines()[0]})
    return HTTPException(500, "unexpected error")


def _issues(repo: CatalogRepo, include_drafts: bool = False) -> list[str]:
    return [str(i) for i in validate_catalog(repo.load_catalog(include_drafts))]


# --- fixed paths first: they must not be read as {kind} -------------------------------


@router.get("/validation")
def validation(_: Reader, conn: Conn, include_drafts: bool = False) -> dict[str, Any]:
    issues = validate_catalog(CatalogRepo(conn).load_catalog(include_drafts))
    return {
        "errors": [str(i) for i in issues if i.severity == "error"],
        "warnings": [str(i) for i in issues if i.severity == "warning"],
    }


@router.get("/export", response_class=PlainTextResponse)
def export(
    _: Exporter, conn: Conn, format: Format = "yaml", include_drafts: bool = False
) -> PlainTextResponse:
    text = dump_document(CatalogRepo(conn).load_catalog(include_drafts), format)
    media = "application/json" if format == "json" else "application/yaml"
    return PlainTextResponse(text, media_type=media)


class ImportIn(BaseModel):
    format: Format = "yaml"
    content: str
    filename: str = ""
    dry_run: bool = True


@router.post("/import")
def import_catalog(body: ImportIn, user: Importer, conn: Conn) -> catalog_import.ImportReport:
    """Dry-run by default (a diff); `dry_run: false` applies it, landing items as `proposed`."""
    try:
        incoming = parse_document(body.content, body.format)
    except CatalogLoadError as exc:
        raise HTTPException(422, {"code": "invalid_document", "problems": exc.problems}) from exc
    try:
        if body.dry_run:
            report = catalog_import.diff(CatalogRepo(conn), incoming)
            catalog_import.record_dry_run(
                conn, report, user_id=user.id, filename=body.filename, content=body.content
            )
            return report
        report = catalog_import.apply(
            conn, incoming, user_id=user.id, filename=body.filename, content=body.content
        )
    except (CatalogRefError, CatalogStateError, psycopg.errors.IntegrityError) as exc:
        raise _storage_error(exc) from exc
    if report.blocking:
        raise HTTPException(409, {"code": "validation_errors", "report": report.model_dump()})
    service.audit(
        conn,
        user.id,
        "catalog.import",
        "import_batch",
        report.batch_id,
        {"filename": body.filename},
    )
    return report


# --- items ------------------------------------------------------------------------------


@router.get("/{kind}")
def list_items(kind: Kind, _: Reader, conn: Conn, detail: bool = False) -> list[dict[str, Any]]:
    """`detail=true` adds key facts, coverage and usage for the catalog tables."""
    repo = CatalogRepo(conn)
    return overview.table(conn, repo, kind) if detail else repo.summaries(kind)


@router.get("/{kind}/{slug}")
def get_item(
    kind: Kind, slug: str, _: Reader, conn: Conn, version: int | None = None
) -> dict[str, Any]:
    repo = CatalogRepo(conn)
    item = repo.load_item(kind, slug, version)
    if item is None:
        raise HTTPException(404, f"{kind} {slug!r} (version {version or 'effective'}) not found")
    return {
        "item": item_to_raw(item),
        "versions": [
            {k: v for k, v in row.items() if k != "version_id"} for row in repo.versions(kind, slug)
        ],
    }


@router.get("/{kind}/{slug}/dependents")
def dependents(kind: Kind, slug: str, _: Reader, conn: Conn) -> list[dict[str, Any]]:
    try:
        return CatalogRepo(conn).dependents(kind, slug)
    except CatalogRefError as exc:
        raise HTTPException(404, str(exc)) from exc


class SaveOut(BaseModel):
    version: int
    status: Status
    issues: list[str]  # validation of the resulting catalog; saving is never blocked by it


@router.put("/{kind}/{slug}", response_model=SaveOut)
def save_item(
    kind: Kind,
    slug: str,
    body: dict[str, Any],
    user: Writer,
    conn: Conn,
    status: Literal["draft", "proposed", "validated"] = "proposed",
    change_note: Annotated[str, Query(max_length=500)] = "",
    base_version: Annotated[int | None, Query(ge=1)] = None,
) -> SaveOut:
    """Create the item or add a new immutable version of it.

    With `base_version` (the version the editor started from) the save is refused with
    `409 stale` when someone saved in between; the answer carries their version and the
    diff, and nothing is lost (catalog-maintenance.md section 5).
    """
    try:
        model = MODEL_FOR_KIND[kind].model_validate({**body, "status": status})
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
    if model.id != slug:
        raise HTTPException(
            422, "the id in the body must equal the slug in the path (slugs are immutable)"
        )
    repo = CatalogRepo(conn)
    if base_version is not None:
        _check_not_stale(conn, repo, kind, slug, base_version)
    try:
        with conn.transaction():
            version_id = repo.save_version(
                kind, model, status=status, author_id=user.id, change_note=change_note
            )
    except (CatalogRefError, CatalogStateError, psycopg.errors.IntegrityError) as exc:
        raise _storage_error(exc) from exc
    number = conn.execute(
        "select number from item_versions where id = %s", (version_id,)
    ).fetchone()
    assert number is not None
    return SaveOut(version=number[0], status=status, issues=_issues(repo, include_drafts=True))


def _check_not_stale(
    conn: psycopg.Connection[Any], repo: CatalogRepo, kind: Kind, slug: str, base_version: int
) -> None:
    if repo.find_item_id(kind, slug) is None:
        return
    row = conn.execute(
        "select max(number) from item_versions v join catalog_items i on i.id = v.item_id"
        " where i.kind = %s and i.slug = %s",
        (kind, slug),
    ).fetchone()
    latest = row[0] if row else None
    if latest is None or latest == base_version:
        return
    theirs = repo.load_item(kind, slug, latest)
    mine = repo.load_item(kind, slug, base_version)
    assert theirs is not None
    raise HTTPException(
        409,
        {
            "code": "stale",
            "message": f"{kind} {slug!r} was saved as version {latest} while you were editing",
            "latest_version": latest,
            "latest_item": item_to_raw(theirs),
            "changes": [
                c.model_dump()
                for c in diff_items(item_to_raw(mine) if mine else {}, item_to_raw(theirs))
            ],
        },
    )


class StatusIn(BaseModel):
    status: Status


@router.post("/{kind}/{slug}/versions/{number}/status")
def set_status(
    kind: Kind, slug: str, number: int, body: StatusIn, user: Validator, conn: Conn
) -> dict[str, Any]:
    repo = CatalogRepo(conn)
    try:
        repo.set_status(repo.version_id(kind, slug, number), body.status, user.id)
    except CatalogRefError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"version": number, "status": body.status}


@router.post("/{kind}/{slug}/archive", status_code=204)
def archive(kind: Kind, slug: str, user: Writer, conn: Conn) -> None:
    try:
        CatalogRepo(conn).archive_item(kind, slug, user.id)
    except CatalogRefError as exc:
        raise HTTPException(404, str(exc)) from exc
    except CatalogStateError as exc:
        raise _storage_error(exc) from exc
