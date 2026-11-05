"""Impact preview: what a catalog change would do, before it is saved
(catalog-maintenance.md section 7).

The engine is deterministic and cheap, so the answer is computed, not guessed: reference
cases and recent consultations are replayed against the catalog as it would be with the
change, and every difference is described in words.
"""

from __future__ import annotations

from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from cheshire.catalog.effective import effective_catalog
from cheshire.catalog.models import Catalog, Status
from cheshire.catalog.validator import validate_catalog
from cheshire.consult.service import fold_state
from cheshire.db.catalog_repo import CatalogRepo, ItemModel
from cheshire.engine.model import EngineInputError, EngineResult, InterpreterOutput
from cheshire.engine.run import run as run_engine
from cheshire.maintenance.overview import catalog_field

Conn = psycopg.Connection[Any]
Label = Literal["added", "removed", "changed", "question"]

# {abb: {"coverage": ..., "sbbs": {sbb: result}}} plus the questions still open
Shape = dict[str, Any]


def shape(result: EngineResult) -> Shape:
    return {
        "abbs": {
            a.id: {"coverage": a.coverage, "sbbs": {s.id: s.result for s in a.sbbs}}
            for a in result.abbs
        },
        "questions": sorted(q.attribute for q in result.pending_questions),
    }


def with_item(catalog: Catalog, kind: str, item: ItemModel) -> Catalog:
    """The catalog with `item` added or replacing the one with the same id."""
    name = catalog_field(kind)
    kept = [i for i in getattr(catalog, name) if getattr(i, "id") != item.id]  # noqa: B009
    return catalog.model_copy(update={name: [*kept, item]})


def describe(before: Shape, after: Shape) -> list[dict[str, str]]:
    """Differences in words; each carries a label so colour is never the only signal."""
    out: list[dict[str, str]] = []

    def add(label: Label, text: str) -> None:
        out.append({"label": label, "text": text})

    b_abbs, a_abbs = before["abbs"], after["abbs"]
    for abb in sorted(set(a_abbs) - set(b_abbs)):
        add("added", f"ABB {abb} would now appear in the result ({a_abbs[abb]['coverage']}).")
    for abb in sorted(set(b_abbs) - set(a_abbs)):
        add("removed", f"ABB {abb} would no longer appear in the result.")
    for abb in sorted(set(b_abbs) & set(a_abbs)):
        b, a = b_abbs[abb], a_abbs[abb]
        if b["coverage"] != a["coverage"]:
            add(
                "changed",
                f"Coverage of {abb} would change from {b['coverage']} to {a['coverage']}.",
            )
        for sbb in sorted(set(a["sbbs"]) - set(b["sbbs"])):
            add("added", f"Solution {sbb} would become a candidate for {abb} ({a['sbbs'][sbb]}).")
        for sbb in sorted(set(b["sbbs"]) - set(a["sbbs"])):
            add("removed", f"Solution {sbb} would no longer be a candidate for {abb}.")
        for sbb in sorted(set(b["sbbs"]) & set(a["sbbs"])):
            if b["sbbs"][sbb] != a["sbbs"][sbb]:
                add(
                    "changed",
                    f"Solution {sbb} for {abb} would change from {b['sbbs'][sbb]}"
                    f" to {a['sbbs'][sbb]}.",
                )
    if "questions" in before and "questions" in after:
        for q in sorted(set(after["questions"]) - set(before["questions"])):
            add("question", f"A new question would be asked: {q}.")
        for q in sorted(set(before["questions"]) - set(after["questions"])):
            add("question", f"The question {q} would no longer be asked.")
    return out


def _replay(catalog: Catalog, engine_input: InterpreterOutput) -> tuple[Shape | None, str]:
    try:
        return shape(run_engine(catalog, engine_input)), ""
    except EngineInputError as exc:
        return None, str(exc)


def preview(
    conn: Conn,
    kind: str,
    item: ItemModel,
    status: Status,
    recent: int,
) -> dict[str, Any]:
    repo = CatalogRepo(conn)
    current = effective_catalog(repo.load_catalog())
    candidate = item.model_copy(update={"status": status})
    after_catalog = effective_catalog(with_item(repo.load_catalog(), kind, candidate))

    existing = repo.find_item_id(kind, item.id)
    dependents = repo.dependents(kind, item.id) if existing is not None else []
    current_status = None
    if existing is not None:
        row = conn.execute(
            "select status from effective_versions where item_id = %s", (existing,)
        ).fetchone()
        current_status = row[0] if row else None
    # a pending change to a validated item never replaces it (invariant 8)
    effective_now = status == "validated" or (
        status == "proposed" and current_status != "validated"
    )

    before_issues = {str(i) for i in validate_catalog(current)}
    new_issues = [str(i) for i in validate_catalog(after_catalog) if str(i) not in before_issues]

    reference_cases = []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select r.id, r.title, r.revision_id, rev.consultation_id, r.expected"
            " from reference_cases r join consultation_revisions rev on rev.id = r.revision_id"
            " where r.archived_at is null order by r.id"
        )
        cases = cur.fetchall()
        cur.execute(
            "select rev.id as revision_id, rev.consultation_id, c.title"
            " from consultation_revisions rev join consultations c on c.id = rev.consultation_id"
            " where rev.id = (select max(id) from consultation_revisions"
            "   where consultation_id = rev.consultation_id)"
            " and exists (select 1 from evaluations e where e.revision_id = rev.id)"
            " and not exists (select 1 from reference_cases r where r.revision_id = rev.id"
            "   and r.archived_at is null)"
            " order by rev.consultation_id desc limit %s",
            (recent,),
        )
        recents = cur.fetchall()

    for case in cases:
        engine_input, _ = fold_state(conn, case["revision_id"])
        now, now_error = _replay(current, engine_input)
        after, error = _replay(after_catalog, engine_input)
        expected = {"abbs": case["expected"]["abbs"]}
        entry: dict[str, Any] = {
            "id": case["id"],
            "title": case["title"],
            "consultation_id": case["consultation_id"],
            "error": error,
            "differences": [] if after is None else describe(expected, {"abbs": after["abbs"]}),
            # the case may already disagree with its pinned expectation, whatever this change does
            "already_differs": now is not None and bool(describe(expected, {"abbs": now["abbs"]})),
        }
        del now_error
        reference_cases.append(entry)

    recent_out = []
    for r in recents:
        engine_input, _ = fold_state(conn, r["revision_id"])
        now, _ = _replay(current, engine_input)
        after, error = _replay(after_catalog, engine_input)
        recent_out.append(
            {
                "consultation_id": r["consultation_id"],
                "title": r["title"],
                "error": error,
                "differences": [] if now is None or after is None else describe(now, after),
            }
        )

    return {
        "effective_now": effective_now,
        "dependents": dependents,
        "new_issues": new_issues,
        "reference_cases": reference_cases,
        "recent_consultations": recent_out,
    }
