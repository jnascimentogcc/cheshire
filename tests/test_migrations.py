import psycopg
import pytest

from cheshire.db.migrate import available_migrations, migrate
from tests.conftest import TestDb


def test_migrations_are_numbered_without_gaps() -> None:
    names = [n for n, _ in available_migrations()]
    assert names[:3] == ["001_identity.sql", "002_catalog_core.sql", "003_catalog_data.sql"]
    assert [int(n[:3]) for n in names] == list(range(1, len(names) + 1))


def test_migrate_is_idempotent(test_db: TestDb) -> None:
    assert migrate(test_db.owner_url) == []


def test_app_role_cannot_do_ddl_or_delete_users(clean_db: TestDb) -> None:
    with psycopg.connect(clean_db.app_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("create table x (id int)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("delete from users")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("update audit_log set action = 'x'")


def test_versions_are_immutable_except_status(clean_db: TestDb) -> None:
    with psycopg.connect(clean_db.app_url, autocommit=True) as conn:
        conn.execute("insert into catalog_items (kind, slug) values ('abb', 'a')")
        conn.execute(
            "insert into item_versions (item_id, kind, number, status)"
            " values (1, 'abb', 1, 'draft')"
        )
        conn.execute("update item_versions set status = 'proposed' where id = 1")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("update item_versions set change_note = 'x' where id = 1")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("delete from item_versions")
