"""Round trip: catalog/*.yaml -> database -> Catalog -> YAML, and engine parity."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from cheshire.catalog.effective import effective_catalog
from cheshire.catalog.loader import load_catalog
from cheshire.catalog.models import Abb, Catalog
from cheshire.catalog.transfer import dump_document, dump_files, parse_document
from cheshire.catalog.validator import has_errors, validate_catalog
from cheshire.db import catalog_import
from cheshire.db.catalog_repo import CatalogRefError, CatalogRepo, CatalogStateError
from cheshire.scenarios import run_all
from tests.conftest import ROOT, TestDb

Conn = psycopg.Connection[Any]


def make_user(conn: Conn, role: str = "architect") -> int:
    row = conn.execute(
        "insert into users (email, display_name, role, password_hash) values "
        "(%s, 'Test', %s, 'x') returning id",
        (f"{role}@example.org", role),
    ).fetchone()
    assert row is not None
    return int(row[0])


def seed(conn: Conn, catalog: Catalog, user: int) -> CatalogRepo:
    """Store a catalog keeping the statuses written in it (the file-loader semantics)."""
    repo = CatalogRepo(conn)
    kinds: list[tuple[Any, list[Any]]] = [
        ("characteristic", catalog.characteristics),
        ("attribute", catalog.attributes),
        ("abb", catalog.abbs),
        ("lens", catalog.lenses),
        ("sbb", catalog.sbbs),
        ("rule", catalog.rules),
    ]
    for kind, items in kinds:
        for item in items:
            repo.ensure_item(kind, item.id, user)
    versions = []
    for kind, items in kinds:
        for item in items:
            vid = repo.insert_version_core(
                kind,
                repo.item_id(kind, item.id),
                item,
                status=item.status,
                author_id=user,
                origin="import",
                origin_ref=None,
                change_note="",
            )
            versions.append((kind, vid, item))
    for kind, vid, item in versions:
        repo.insert_conditions(kind, vid, item)
    return repo


@pytest.fixture
def conn(clean_db: TestDb) -> Iterator[Conn]:
    with psycopg.connect(clean_db.app_url) as connection:
        yield connection


def test_round_trip_yaml_database_catalog_yaml(
    conn: Conn, example_catalog: Catalog, tmp_path: Path
) -> None:
    repo = seed(conn, example_catalog, make_user(conn))
    from_db = repo.load_catalog()
    assert from_db == example_catalog

    dump_files(from_db, tmp_path / "out")
    assert load_catalog(tmp_path / "out") == example_catalog
    for fmt in ("yaml", "json"):
        assert parse_document(dump_document(from_db, fmt), fmt) == example_catalog


def test_engine_gives_the_same_results_from_the_database(
    conn: Conn, example_catalog: Catalog
) -> None:
    repo = seed(conn, example_catalog, make_user(conn))
    from_db = repo.load_catalog()
    assert not has_errors(validate_catalog(from_db))
    reports = run_all(from_db, ROOT / "scenarios")
    assert len(reports) == 4
    assert all(r.passed for r in reports), [r.failures for r in reports]


def test_effective_version_rules(conn: Conn, example_catalog: Catalog) -> None:
    user = make_user(conn)
    repo = seed(conn, example_catalog, user)
    original = repo.load_item("abb", "audit-log")
    assert isinstance(original, Abb)

    # a newer proposed version does not replace the validated one
    changed = original.model_copy(update={"name": "Audit log v2"})
    pending = repo.save_version("abb", changed, status="proposed", author_id=user)
    assert repo.load_item("abb", "audit-log") == original
    assert repo.load_item("abb", "audit-log", 2) == changed.model_copy(
        update={"status": "proposed"}
    )

    # once validated, it becomes effective
    repo.set_status(pending, "validated", user)
    now = repo.load_item("abb", "audit-log")
    assert isinstance(now, Abb) and now.name == "Audit log v2" and now.status == "validated"
    assert [v["number"] for v in repo.versions("abb", "audit-log")] == [2, 1]

    # a draft is never effective, but test runs can include it
    repo.save_version(
        "abb", changed.model_copy(update={"name": "v3"}), status="draft", author_id=user
    )
    effective = repo.load_catalog().abb("audit-log")
    assert effective is not None and effective.name == "Audit log v2"
    with_drafts = repo.load_catalog(include_drafts=True).abb("audit-log")
    assert with_drafts is not None and with_drafts.name == "v3"


def test_proposed_only_item_is_effective_but_draft_only_is_not(conn: Conn) -> None:
    user = make_user(conn)
    repo = CatalogRepo(conn)
    repo.save_version("abb", Abb(id="p", name="P", domain="d"), status="proposed", author_id=user)
    repo.save_version("abb", Abb(id="d", name="D", domain="d"), status="draft", author_id=user)
    assert [a.id for a in repo.load_catalog().abbs] == ["p"]
    assert [a.id for a in repo.load_catalog(include_drafts=True).abbs] == ["p", "d"]


def test_rejects_unknown_reference(conn: Conn, example_catalog: Catalog) -> None:
    user = make_user(conn)
    repo = seed(conn, example_catalog, user)
    sbb = example_catalog.sbbs[0].model_copy(update={"id": "x", "realises": "nope"})
    with pytest.raises(CatalogRefError):
        repo.save_version("sbb", sbb, status="proposed", author_id=user)


def test_database_rejects_wrong_kind_reference(conn: Conn, example_catalog: Catalog) -> None:
    """An SBB cannot 'realise' a rule: the composite foreign key enforces the kind."""
    seed(conn, example_catalog, make_user(conn))
    rule = conn.execute("select id from catalog_items where kind='rule' limit 1").fetchone()
    version = conn.execute(
        "insert into item_versions (item_id, kind, number, status) "
        "select id, kind, 99, 'draft' from catalog_items where kind='sbb' limit 1 returning id"
    ).fetchone()
    assert rule is not None and version is not None
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "insert into sbb_data (version_id, realises_item_id, name, state) "
            "values (%s, %s, 'bad', 'accepted')",
            (version[0], rule[0]),
        )


def test_prohibited_sbb_requires_a_reason(conn: Conn, example_catalog: Catalog) -> None:
    user = make_user(conn)
    repo = seed(conn, example_catalog, user)
    bad = example_catalog.sbbs[0].model_copy(update={"id": "bad", "state": "prohibited"})
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.save_version("sbb", bad, status="draft", author_id=user)


def test_snapshots_are_shared_and_reproducible(conn: Conn, example_catalog: Catalog) -> None:
    user = make_user(conn)
    repo = seed(conn, example_catalog, user)
    first = repo.snapshot()
    assert repo.snapshot() == first
    before = repo.load_catalog()
    assert repo.load_snapshot(first) == before

    changed = before.abbs[0].model_copy(update={"name": "Renamed"})
    repo.save_version("abb", changed, status="validated", author_id=user)
    second = repo.snapshot()
    assert second != first
    assert repo.load_snapshot(first) == before  # the past is still rebuildable
    assert repo.load_snapshot(second).abbs[0].name == "Renamed"


def test_archive_is_blocked_while_referenced(conn: Conn, example_catalog: Catalog) -> None:
    user = make_user(conn)
    repo = seed(conn, example_catalog, user)
    with pytest.raises(CatalogStateError):
        repo.archive_item("abb", "channel-sms", user)
    deps = repo.dependents("abb", "channel-sms")
    assert {"kind": "sbb", "slug": "sms-provider-a", "ref_kind": "realises"} in deps
    assert any(d["kind"] == "rule" and d["ref_kind"] == "abb_present" for d in deps)


def test_effective_catalog_helper_matches_database_view(
    conn: Conn, example_catalog: Catalog
) -> None:
    repo = seed(conn, example_catalog, make_user(conn))
    assert repo.load_catalog() == effective_catalog(example_catalog)


# --- import ------------------------------------------------------------------------


def test_import_lands_as_proposed_and_is_idempotent(conn: Conn, example_catalog: Catalog) -> None:
    user = make_user(conn)
    text = dump_document(example_catalog, "yaml")
    incoming = parse_document(text, "yaml")

    dry = catalog_import.diff(CatalogRepo(conn), incoming)
    assert not dry.blocking
    assert len(dry.created["abb"]) == len(example_catalog.abbs) and not dry.changed["abb"]

    report = catalog_import.apply(conn, incoming, user_id=user, filename="c.yaml", content=text)
    assert report.batch_id is not None
    assert {r[0] for r in conn.execute("select status from item_versions")} == {"proposed"}
    imported = CatalogRepo(conn).load_catalog()
    assert [a.id for a in imported.abbs] == [a.id for a in example_catalog.abbs]
    assert all(a.status == "proposed" for a in imported.abbs)

    first_count = conn.execute("select count(*) from item_versions").fetchone()
    again = catalog_import.apply(conn, incoming, user_id=user, filename="c.yaml", content=text)
    assert not any(again.created.values()) and not any(again.changed.values())
    assert conn.execute("select count(*) from item_versions").fetchone() == first_count


def test_import_reports_changes_and_never_deletes(conn: Conn, example_catalog: Catalog) -> None:
    user = make_user(conn)
    text = dump_document(example_catalog, "yaml")
    catalog_import.apply(
        conn, parse_document(text, "yaml"), user_id=user, filename="a", content=text
    )

    smaller = example_catalog.model_copy(
        update={
            "abbs": [
                a.model_copy(update={"name": "Changed"}) if a.id == "audit-log" else a
                for a in example_catalog.abbs
                if a.id != "channel-sms"
            ]
        }
    )
    report = catalog_import.diff(CatalogRepo(conn), smaller)
    assert report.changed["abb"] == ["audit-log"]
    assert report.absent["abb"] == ["channel-sms"]


def test_import_with_validation_errors_is_blocked(conn: Conn, example_catalog: Catalog) -> None:
    user = make_user(conn)
    bad = example_catalog.model_copy(
        update={"rules": [example_catalog.rules[0].model_copy(update={"activates": "nope"})]}
    )
    report = catalog_import.apply(conn, bad, user_id=user, filename="bad", content="x")
    assert report.blocking and report.batch_id is None
    assert conn.execute("select count(*) from catalog_items").fetchone() == (0,)


def test_import_batches_are_append_only_for_the_app(conn: Conn) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("update import_batches set mode = 'applied'")
