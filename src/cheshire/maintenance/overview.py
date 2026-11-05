"""Read models for the catalog screens: health strip, tables, item usage and connections."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from cheshire.catalog.models import Abb, Attribute, Catalog, Characteristic, Lens, Rule, Sbb
from cheshire.catalog.validator import validate_catalog
from cheshire.db.catalog_repo import KINDS, CatalogRepo, ItemModel
from cheshire.maintenance import queue

Conn = psycopg.Connection[Any]


def health(conn: Conn) -> dict[str, Any]:
    """Counts for the health strip. Each one links to the matching filtered list."""
    repo = CatalogRepo(conn)
    catalog = repo.load_catalog()
    issues = validate_catalog(catalog)
    by_status = {"draft": 0, "proposed": 0, "validated": 0}
    for status, n in conn.execute(
        "select v.status, count(*) from catalog_items i join lateral ("
        " select status from item_versions where item_id = i.id order by number desc limit 1"
        ") v on true where i.archived_at is null group by v.status"
    ):
        by_status[status] = int(n)
    covered = {s.realises for s in catalog.sbbs}
    gap_abbs = sorted(a.id for a in catalog.abbs if a.id not in covered)
    return {
        "items_by_status": by_status,
        "abbs_without_sbb": gap_abbs,
        "validator_errors": sum(1 for i in issues if i.severity == "error"),
        "validator_warnings": sum(1 for i in issues if i.severity == "warning"),
        "queue": queue.counts(conn),
        "empty": not any(by_status.values()),
    }


def usage(conn: Conn, repo: CatalogRepo, kind: str, slug: str) -> dict[str, Any]:
    """Evidence for prioritising work: how often an item was used, flagged or corrected."""
    item_id = repo.item_id(kind, slug)
    used = conn.execute(
        "select count(distinct rev.consultation_id), max(e.created_at)"
        " from evaluation_item_uses u join evaluations e on e.id = u.evaluation_id"
        " join consultation_revisions rev on rev.id = e.revision_id where u.item_id = %s",
        (item_id,),
    ).fetchone()
    flagged = conn.execute("select count(*) from feedback where abb_item_id = %s", (item_id,))
    corrected = conn.execute(
        "select count(*) from consultation_abb_events"
        " where abb_item_id = %s and origin = 'user_removed'",
        (item_id,),
    )
    chosen = conn.execute(
        "select count(*) from choice_records where sbb_item_id = %s and kind = 'chosen'",
        (item_id,),
    )
    assert used is not None
    f, c, ch = flagged.fetchone(), corrected.fetchone(), chosen.fetchone()
    assert f is not None and c is not None and ch is not None
    return {
        "consultations": int(used[0]),
        "last_used": used[1],
        "flagged": int(f[0]),
        "corrected": int(c[0]),
        "chosen": int(ch[0]),
    }


def connections(conn: Conn, repo: CatalogRepo, kind: str, slug: str) -> dict[str, Any]:
    """Everything an item reads and everything that reads it, on effective versions."""
    item_id = repo.item_id(kind, slug)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select distinct t.kind, t.slug, r.ref_kind from item_refs_v r"
            " join catalog_items t on t.id = r.to_item_id"
            " where r.from_item_id = %s order by t.kind, t.slug, r.ref_kind",
            (item_id,),
        )
        uses = cur.fetchall()
    return {"uses": uses, "used_by": repo.dependents(kind, slug)}


_FIELD = {
    "attribute": "attributes",
    "characteristic": "characteristics",
    "lens": "lenses",
    "abb": "abbs",
    "sbb": "sbbs",
    "rule": "rules",
}


def catalog_field(kind: str) -> str:
    return _FIELD[kind]


def _facts(item: ItemModel) -> dict[str, Any]:
    """The few fields a list needs to filter and show, per kind."""
    if isinstance(item, Abb):
        return {"name": item.name, "domain": item.domain, "cross_cutting": item.cross_cutting}
    if isinstance(item, Sbb):
        return {"name": item.name, "realises": item.realises, "state": item.state}
    if isinstance(item, Rule):
        return {"name": item.id, "activates": item.activates, "strength": item.strength}
    if isinstance(item, Attribute):
        return {"name": item.id, "values": len(item.values), "multi": item.multi}
    if isinstance(item, Characteristic):
        return {"name": item.id, "values": len(item.values)}
    if isinstance(item, Lens):
        return {"name": item.name}
    return {"name": item.id}


def table(conn: Conn, repo: CatalogRepo, kind: str) -> list[dict[str, Any]]:
    """Rows of a catalog list: status, key facts, coverage for ABBs, and recent use.

    Sorted by id: lists never carry a quality order (invariant 2)."""
    latest: Catalog = repo.load_catalog(include_drafts=True)
    models: dict[str, ItemModel] = {
        getattr(i, "id"): i  # noqa: B009
        for i in getattr(latest, _FIELD[kind])
    }
    sbb_count: dict[str, int] = {}
    if kind == "abb":
        for sbb in latest.sbbs:
            sbb_count[sbb.realises] = sbb_count.get(sbb.realises, 0) + 1
    uses = {
        slug: (n, corrected)
        for slug, n, corrected in conn.execute(
            "select i.slug, count(distinct rev.consultation_id),"
            " (select count(*) from feedback f where f.abb_item_id = i.id)"
            " + (select count(*) from consultation_abb_events x where x.abb_item_id = i.id"
            "    and x.origin = 'user_removed') from catalog_items i"
            " join evaluation_item_uses u on u.item_id = i.id"
            " join evaluations e on e.id = u.evaluation_id"
            " join consultation_revisions rev on rev.id = e.revision_id"
            " where i.kind = %s group by i.id, i.slug",
            (kind,),
        )
    }
    rows = []
    for summary in repo.summaries(kind):
        slug = summary["slug"]
        model = models.get(slug)
        row: dict[str, Any] = {
            **summary,
            "facts": _facts(model) if model is not None else {"name": slug},
            "consultations": int(uses.get(slug, (0, 0))[0]),
            "corrections": int(uses.get(slug, (0, 0))[1]),
        }
        if kind == "abb":
            row["sbbs"] = sbb_count.get(slug, 0)
        rows.append(row)
    return sorted(rows, key=lambda r: r["slug"])


KIND_ORDER = KINDS
