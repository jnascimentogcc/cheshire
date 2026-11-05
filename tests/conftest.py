import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from cheshire.catalog.loader import load_catalog
from cheshire.catalog.models import Catalog

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def example_catalog() -> Catalog:
    return load_catalog(ROOT / "catalog")


@pytest.fixture
def scenarios_dir() -> Path:
    return ROOT / "scenarios"


# --- PostgreSQL (needs CHESHIRE_TEST_DATABASE_URL, a superuser URL of a throwaway server) ----


@dataclass(frozen=True)
class TestDb:
    __test__ = False

    owner_url: str
    app_url: str


@pytest.fixture(scope="session")
def test_db() -> Iterator[TestDb]:
    admin_url = os.environ.get("CHESHIRE_TEST_DATABASE_URL")
    if not admin_url:
        pytest.skip("CHESHIRE_TEST_DATABASE_URL not set")
    from cheshire.db.migrate import migrate

    name = f"cheshire_test_{secrets.token_hex(4)}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'create database "{name}"')
    base = conninfo_to_dict(admin_url)
    owner = make_conninfo(**{**base, "dbname": name})  # type: ignore[arg-type]
    app_password = secrets.token_hex(8)
    app = make_conninfo(
        **{**base, "dbname": name, "user": "cheshire_app", "password": app_password}  # type: ignore[arg-type]
    )
    migrate(owner, app_password)
    try:
        yield TestDb(owner, app)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'drop database if exists "{name}" with (force)')


@pytest.fixture
def clean_db(test_db: TestDb) -> TestDb:
    """Empty every table (as owner) so each test starts from nothing."""
    with psycopg.connect(test_db.owner_url, autocommit=True) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "select tablename from pg_tables where schemaname='public' "
                "and tablename <> 'schema_migrations'"
            )
        ]
        conn.execute(
            "truncate " + ", ".join(f'"{t}"' for t in tables) + " restart identity cascade"
        )
    return test_db
