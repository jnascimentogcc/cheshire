"""Forward-only numbered SQL migrations, applied with the owner role."""

from __future__ import annotations

import re
from importlib import resources

import psycopg
from psycopg import sql

_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
_LOCK_KEY = 726_001  # arbitrary advisory-lock id: one migrator at a time


def available_migrations() -> list[tuple[str, str]]:
    """(name, sql) pairs ordered by number."""
    found: list[tuple[str, str]] = []
    for entry in resources.files("cheshire.db").joinpath("migrations").iterdir():
        if _NAME.match(entry.name):
            found.append((entry.name, entry.read_text(encoding="utf-8")))
    return sorted(found)


def migrate(owner_url: str, app_password: str | None = None) -> list[str]:
    """Apply pending migrations; returns the names applied. Each runs in one transaction."""
    applied: list[str] = []
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(sql.SQL("select pg_advisory_lock({})").format(_LOCK_KEY))
        try:
            conn.execute(
                "create table if not exists schema_migrations ("
                "name text primary key, applied_at timestamptz not null default now())"
            )
            done = {r[0] for r in conn.execute("select name from schema_migrations")}
            for name, script in available_migrations():
                if name in done:
                    continue
                with conn.transaction():
                    conn.execute(script.encode())  # no parameters: multi-statement script
                    conn.execute("insert into schema_migrations (name) values (%s)", (name,))
                applied.append(name)
            if app_password:
                conn.execute(
                    sql.SQL("alter role cheshire_app with login password {}").format(
                        sql.Literal(app_password)
                    )
                )
        finally:
            conn.execute(sql.SQL("select pg_advisory_unlock({})").format(_LOCK_KEY))
    return applied
