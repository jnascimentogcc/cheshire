"""Import into the database: dry-run diff, then apply. Imports always land as `proposed`
(docs/data-model.md section 9), in dependency order and in two passes so references
inside one batch resolve."""

from __future__ import annotations

import hashlib
from typing import Any

import psycopg
from pydantic import BaseModel

from cheshire.catalog.models import Catalog, Status
from cheshire.catalog.validator import Issue, has_errors, validate_catalog
from cheshire.db.catalog_repo import KINDS, CatalogRepo, ItemModel, Kind

_SECTION: dict[Kind, str] = {
    "attribute": "attributes",
    "characteristic": "characteristics",
    "lens": "lenses",
    "abb": "abbs",
    "sbb": "sbbs",
    "rule": "rules",
}


class ImportReport(BaseModel):
    created: dict[str, list[str]]
    changed: dict[str, list[str]]
    unchanged: dict[str, list[str]]
    absent: dict[str, list[str]]  # in the database but not in the file; never deleted
    issues: list[str]
    blocking: bool
    batch_id: int | None = None


def _content(item: ItemModel) -> dict[str, Any]:
    """Item content without its review status (a re-import of the same text is unchanged)."""
    return item.model_dump(exclude={"status"})


def _items(catalog: Catalog, kind: Kind) -> list[ItemModel]:
    return list(getattr(catalog, _SECTION[kind]))


def diff(repo: CatalogRepo, incoming: Catalog) -> ImportReport:
    current = repo.load_catalog(include_drafts=True)  # latest version of every item
    created: dict[str, list[str]] = {}
    changed: dict[str, list[str]] = {}
    unchanged: dict[str, list[str]] = {}
    absent: dict[str, list[str]] = {}
    for kind in KINDS:
        have = {i.id: i for i in _items(current, kind)}
        want = _items(incoming, kind)
        created[kind] = [i.id for i in want if i.id not in have]
        changed[kind] = [i.id for i in want if i.id in have and _content(i) != _content(have[i.id])]
        unchanged[kind] = [
            i.id for i in want if i.id in have and _content(i) == _content(have[i.id])
        ]
        absent[kind] = sorted(set(have) - {i.id for i in want})

    merged = _merge(current, incoming)
    issues: list[Issue] = validate_catalog(merged)
    return ImportReport(
        created=created,
        changed=changed,
        unchanged=unchanged,
        absent=absent,
        issues=[str(i) for i in issues],
        blocking=has_errors(issues),
    )


def _merge(current: Catalog, incoming: Catalog) -> Catalog:
    """What the catalog would look like after the import (incoming wins per item)."""
    data: dict[str, list[ItemModel]] = {}
    for kind in KINDS:
        by_id: dict[str, ItemModel] = {i.id: i for i in _items(current, kind)}
        for item in _items(incoming, kind):
            by_id[item.id] = item.model_copy(update={"status": "proposed"})
        data[_SECTION[kind]] = list(by_id.values())
    return Catalog.model_validate(data)


def apply(
    conn: psycopg.Connection[Any],
    incoming: Catalog,
    *,
    user_id: int,
    filename: str,
    content: str,
    status: Status = "proposed",
) -> ImportReport:
    """Apply an import in the caller's transaction. Blocking validation errors abort it."""
    repo = CatalogRepo(conn)
    report = diff(repo, incoming)
    if report.blocking:
        return report
    row = conn.execute(
        "insert into import_batches (user_id, filename, content_hash, mode, report, applied_at)"
        " values (%s, %s, %s, 'applied', %s::jsonb, now()) returning id",
        (user_id, filename, hashlib.sha256(content.encode()).hexdigest(), report.model_dump_json()),
    ).fetchone()
    assert row is not None
    batch_id = int(row[0])

    todo: dict[Kind, list[ItemModel]] = {}
    for kind in KINDS:
        wanted = set(report.created[kind]) | set(report.changed[kind])
        todo[kind] = [i for i in _items(incoming, kind) if i.id in wanted]

    # pass 1: every new item exists, so references inside the batch resolve
    for kind in KINDS:
        for item in todo[kind]:
            repo.ensure_item(kind, item.id, user_id)

    def core(kind: Kind, item: ItemModel) -> int:
        return repo.insert_version_core(
            kind,
            repo.item_id(kind, item.id),
            item,
            status=status,
            author_id=user_id,
            origin="import",
            origin_ref=batch_id,
            change_note=f"import {filename}".strip(),
        )

    # pass 2: vocabulary first (conditions need attribute values), then the rest
    versions: list[tuple[Kind, int, ItemModel]] = []
    for kind in ("characteristic", "attribute"):
        for item in todo[kind]:
            versions.append((kind, core(kind, item), item))
    for kind in ("abb", "lens", "sbb", "rule"):
        for item in todo[kind]:
            versions.append((kind, core(kind, item), item))
    for kind, version_id, item in versions:
        repo.insert_conditions(kind, version_id, item)

    report.batch_id = batch_id
    return report


def record_dry_run(
    conn: psycopg.Connection[Any],
    report: ImportReport,
    *,
    user_id: int,
    filename: str,
    content: str,
) -> None:
    conn.execute(
        "insert into import_batches (user_id, filename, content_hash, mode, report)"
        " values (%s, %s, %s, 'dry_run', %s::jsonb)",
        (user_id, filename, hashlib.sha256(content.encode()).hexdigest(), report.model_dump_json()),
    )
