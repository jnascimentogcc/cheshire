"""The architects' work queue (catalog-maintenance.md section 3).

Entries are *derived* from stored facts every time the queue is read (`refresh`): gaps and
unrecognised requirements from consultations, feedback, items waiting for review or
validation, and validator findings. That keeps the queue honest: an entry whose cause
disappeared closes itself, and nothing depends on a hook having fired. Claims, dismissals
and resolutions are the only human state, and they are stored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from cheshire.auth.service import User
from cheshire.catalog.validator import validate_catalog
from cheshire.db.catalog_repo import CatalogRepo

Conn = psycopg.Connection[Any]

KINDS = (
    "gap",
    "unrecognised",
    "feedback",
    "draft_review",
    "validation_backlog",
    "validator_finding",
)


class QueueError(Exception):
    code = "invalid"


class QueueNotFound(QueueError):
    code = "not_found"


class QueueConflict(QueueError):
    code = "conflict"


@dataclass
class Candidate:
    kind: str
    key: str
    subject_item_id: int | None
    payload: dict[str, Any]
    # consultations / feedback rows that made the entry appear
    occurrences: list[tuple[int | None, int | None, datetime]] = field(default_factory=list)

    @property
    def latest(self) -> datetime | None:
        return max((at for _, _, at in self.occurrences), default=None)


# ------------------------------------------------------------------ candidates


def _gaps(conn: Conn, repo: CatalogRepo) -> list[Candidate]:
    catalog = repo.load_catalog()
    covered = {s.realises for s in catalog.sbbs}
    live_abbs = {a.id for a in catalog.abbs}
    found: dict[str, Candidate] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "with latest as (select distinct on (e.revision_id) e.id, e.revision_id, e.created_at"
            " from evaluations e order by e.revision_id, e.id desc)"
            " select u.item_id, i.slug, rev.consultation_id, l.created_at"
            " from latest l"
            " join evaluation_item_uses u on u.evaluation_id = l.id and u.role = 'abb'"
            "  and u.outcome = 'gap'"
            " join catalog_items i on i.id = u.item_id and i.archived_at is null"
            " join consultation_revisions rev on rev.id = l.revision_id"
            " where rev.id = (select max(id) from consultation_revisions"
            "  where consultation_id = rev.consultation_id)"
            " order by i.slug, rev.consultation_id"
        )
        rows = cur.fetchall()
    for r in rows:
        slug = r["slug"]
        if slug in covered or slug not in live_abbs:
            continue
        cand = found.setdefault(slug, Candidate("gap", f"gap:{slug}", r["item_id"], {"abb": slug}))
        cand.occurrences.append((r["consultation_id"], None, r["created_at"]))
    return list(found.values())


def _unrecognised(conn: Conn) -> list[Candidate]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select rev.id, rev.consultation_id, rev.number, rev.requirement_text, rev.created_at"
            " from consultation_revisions rev where rev.unrecognised"
            " and rev.id = (select max(id) from consultation_revisions"
            "  where consultation_id = rev.consultation_id) order by rev.id"
        )
        return [
            Candidate(
                "unrecognised",
                f"unrecognised:{r['id']}",
                None,
                {
                    "requirement": r["requirement_text"],
                    "consultation_id": r["consultation_id"],
                    "revision": r["number"],
                },
                [(r["consultation_id"], None, r["created_at"])],
            )
            for r in cur.fetchall()
        ]


def _feedback(conn: Conn) -> list[Candidate]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select f.id, f.consultation_id, f.kind, f.text, f.abb_item_id, f.at, a.slug as abb,"
            " u.display_name as author from feedback f"
            " left join catalog_items a on a.id = f.abb_item_id"
            " join users u on u.id = f.author_id order by f.id"
        )
        return [
            Candidate(
                "feedback",
                f"feedback:{r['id']}",
                r["abb_item_id"],
                {
                    "feedback_kind": r["kind"],
                    "text": r["text"],
                    "abb": r["abb"],
                    "consultation_id": r["consultation_id"],
                    "author": r["author"],
                },
                [(r["consultation_id"], r["id"], r["at"])],
            )
            for r in cur.fetchall()
        ]


def _pending_versions(conn: Conn, status: str, kind: str, prefix: str) -> list[Candidate]:
    """Items whose latest version has the given status (waiting for review or validation)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select i.id, i.kind, i.slug, v.number, v.origin, v.created_at,"
            " a.display_name as author from catalog_items i"
            " join lateral (select * from item_versions where item_id = i.id"
            "   order by number desc limit 1) v on true"
            " left join users a on a.id = v.author_id"
            " where i.archived_at is null and v.status = %s order by i.kind, i.slug",
            (status,),
        )
        return [
            Candidate(
                kind,
                f"{prefix}:{r['kind']}:{r['slug']}:{r['number']}",
                r["id"],
                {
                    "item_kind": r["kind"],
                    "item": r["slug"],
                    "version": r["number"],
                    "origin": r["origin"],
                    "author": r["author"],
                },
            )
            for r in cur.fetchall()
        ]


def _findings(repo: CatalogRepo) -> list[Candidate]:
    return [
        Candidate(
            "validator_finding",
            f"finding:{i.code}:{i.subject}",
            None,
            {
                "severity": i.severity,
                "code": i.code,
                "subject": i.subject,
                "message": i.message,
            },
        )
        for i in validate_catalog(repo.load_catalog())
    ]


# ------------------------------------------------------------------------ sync


def _sync(conn: Conn, kind: str, candidates: list[Candidate]) -> None:
    live = {c.key for c in candidates}
    # an entry whose cause disappeared closes itself (no human involved)
    open_rows = conn.execute(
        "select id, dedupe_key from work_items where kind = %s and status in ('open', 'claimed')",
        (kind,),
    ).fetchall()
    for work_id, key in open_rows:
        if key not in live:
            conn.execute(
                "update work_items set status = 'done', resolved_at = now(),"
                " resolution = 'No longer applies.' where id = %s",
                (work_id,),
            )
    for cand in candidates:
        row = conn.execute(
            "select id from work_items where dedupe_key = %s and status in ('open', 'claimed')",
            (cand.key,),
        ).fetchone()
        if row is None:
            last = conn.execute(
                "select resolved_at from work_items where dedupe_key = %s"
                " and resolved_by is not null order by id desc limit 1",
                (cand.key,),
            ).fetchone()
            # a human closed it: it returns only if something new happened since
            if last is not None and (cand.latest is None or cand.latest <= last[0]):
                continue
            created = conn.execute(
                "insert into work_items (kind, dedupe_key, subject_item_id, payload)"
                " values (%s, %s, %s, %s::jsonb) returning id",
                (kind, cand.key, cand.subject_item_id, json.dumps(cand.payload)),
            ).fetchone()
            assert created is not None
            work_id = int(created[0])
        else:
            work_id = int(row[0])
            conn.execute(
                "update work_items set payload = %s::jsonb where id = %s",
                (json.dumps(cand.payload), work_id),
            )
        for consultation_id, feedback_id, at in cand.occurrences:
            conn.execute(
                "insert into work_item_occurrences (work_item_id, consultation_id, feedback_id, at)"
                " select %s, %s, %s, %s where not exists (select 1 from work_item_occurrences"
                " where work_item_id = %s and consultation_id is not distinct from %s"
                " and feedback_id is not distinct from %s)",
                (work_id, consultation_id, feedback_id, at, work_id, consultation_id, feedback_id),
            )


def refresh(conn: Conn) -> None:
    """Release expired claims, then bring every derived kind up to date."""
    conn.execute(
        "update work_items set status = 'open', claimed_by = null, claimed_at = null,"
        " claim_expires_at = null where status = 'claimed' and claim_expires_at <= now()"
    )
    repo = CatalogRepo(conn)
    _sync(conn, "gap", _gaps(conn, repo))
    _sync(conn, "unrecognised", _unrecognised(conn))
    _sync(conn, "feedback", _feedback(conn))
    _sync(conn, "draft_review", _pending_versions(conn, "draft", "draft_review", "draft"))
    _sync(
        conn,
        "validation_backlog",
        _pending_versions(conn, "proposed", "validation_backlog", "proposed"),
    )
    _sync(conn, "validator_finding", _findings(repo))


# --------------------------------------------------------------------- reading

_SELECT = (
    "select w.id, w.kind, w.status, w.payload, w.created_at, w.claimed_at, w.claim_expires_at,"
    " w.resolved_at, w.resolution, c.display_name as claimed_by, w.claimed_by as claimed_by_id,"
    " r.display_name as resolved_by, i.kind as subject_kind, i.slug as subject,"
    " (select count(distinct o.consultation_id) from work_item_occurrences o"
    "   where o.work_item_id = w.id) as sessions,"
    " (select min(o.consultation_id) from work_item_occurrences o"
    "   where o.work_item_id = w.id) as first_consultation_id"
    " from work_items w left join users c on c.id = w.claimed_by"
    " left join users r on r.id = w.resolved_by"
    " left join catalog_items i on i.id = w.subject_item_id"
)


def _present(row: dict[str, Any], user: User, warning_hours: int, now: datetime) -> dict[str, Any]:
    expires = row["claim_expires_at"]
    mine = row["claimed_by_id"] == user.id
    row["claimed_by_me"] = mine
    row["expiring_soon"] = bool(
        row["status"] == "claimed"
        and expires is not None
        and (expires - now).total_seconds() <= warning_hours * 3600
    )
    del row["claimed_by_id"]
    return row


def list_work(
    conn: Conn,
    user: User,
    *,
    warning_hours: int,
    status: str = "active",
    kind: str | None = None,
) -> list[dict[str, Any]]:
    """`status`: `active` (open + claimed), or one of open, claimed, done, dismissed."""
    refresh(conn)
    where, params = [], []
    if status == "active":
        where.append("w.status in ('open', 'claimed')")
    else:
        where.append("w.status = %s")
        params.append(status)
    if kind:
        where.append("w.kind = %s")
        params.append(kind)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"{_SELECT} where {' and '.join(where)} order by w.kind, sessions desc, w.id",
            params,
        )
        rows = cur.fetchall()
        now = conn.execute("select now()").fetchone()
    assert now is not None
    return [_present(r, user, warning_hours, now[0]) for r in rows]


def counts(conn: Conn) -> dict[str, int]:
    rows = conn.execute(
        "select kind, count(*) from work_items where status in ('open', 'claimed') group by kind"
    ).fetchall()
    found = {k: n for k, n in rows}
    return {k: int(found.get(k, 0)) for k in KINDS}


def get_work(conn: Conn, user: User, work_id: int, warning_hours: int) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"{_SELECT} where w.id = %s", (work_id,))
        row = cur.fetchone()
        now = conn.execute("select now()").fetchone()
    if row is None:
        raise QueueNotFound(f"work item {work_id} not found")
    assert now is not None
    return _present(row, user, warning_hours, now[0])


# --------------------------------------------------------------------- actions


def _locked(conn: Conn, work_id: int) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select * from work_items where id = %s for update", (work_id,))
        row = cur.fetchone()
    if row is None:
        raise QueueNotFound(f"work item {work_id} not found")
    return row


def claim(conn: Conn, user: User, work_id: int, ttl_days: int) -> None:
    refresh(conn)  # a stale claim must not block a new one
    row = _locked(conn, work_id)
    if row["status"] == "claimed":
        who = conn.execute("select display_name from users where id = %s", (row["claimed_by"],))
        name = who.fetchone()
        raise QueueConflict(f"already claimed by {name[0] if name else 'someone else'}")
    if row["status"] != "open":
        raise QueueConflict(f"this entry is {row['status']}")
    conn.execute(
        "update work_items set status = 'claimed', claimed_by = %s, claimed_at = now(),"
        " claim_expires_at = now() + make_interval(days => %s) where id = %s",
        (user.id, ttl_days, work_id),
    )


def renew(conn: Conn, user: User, work_id: int, ttl_days: int) -> None:
    row = _locked(conn, work_id)
    if row["status"] != "claimed" or row["claimed_by"] != user.id:
        raise QueueConflict("only the person who claimed an entry can renew it")
    conn.execute(
        "update work_items set claim_expires_at = now() + make_interval(days => %s) where id = %s",
        (ttl_days, work_id),
    )


def release(conn: Conn, user: User, work_id: int) -> None:
    row = _locked(conn, work_id)
    if row["status"] != "claimed":
        raise QueueConflict("this entry is not claimed")
    if row["claimed_by"] != user.id and user.role != "admin":
        raise QueueConflict("only the claimer (or an admin) can release a claim")
    conn.execute(
        "update work_items set status = 'open', claimed_by = null, claimed_at = null,"
        " claim_expires_at = null where id = %s",
        (work_id,),
    )


def reassign(conn: Conn, admin: User, work_id: int, to_user_id: int, ttl_days: int) -> None:
    """Admins hand an entry to an architect (docs: Admin can reassign work)."""
    row = _locked(conn, work_id)
    if row["status"] not in ("open", "claimed"):
        raise QueueConflict(f"this entry is {row['status']}")
    target = conn.execute("select role, active from users where id = %s", (to_user_id,)).fetchone()
    if target is None or not target[1] or target[0] == "user":
        raise QueueError("work can only be assigned to an active architect or admin")
    conn.execute(
        "update work_items set status = 'claimed', claimed_by = %s, claimed_at = now(),"
        " claim_expires_at = now() + make_interval(days => %s) where id = %s",
        (to_user_id, ttl_days, work_id),
    )


def dismiss(conn: Conn, user: User, work_id: int, reason: str) -> None:
    reason = reason.strip()
    if not reason:
        raise QueueError("a dismissal needs a reason")
    row = _locked(conn, work_id)
    if row["status"] not in ("open", "claimed"):
        raise QueueConflict(f"this entry is already {row['status']}")
    conn.execute(
        "update work_items set status = 'dismissed', resolved_by = %s, resolved_at = now(),"
        " resolution = %s where id = %s",
        (user.id, reason, work_id),
    )


def resolve(conn: Conn, user: User, work_id: int, note: str = "") -> None:
    """Mark as handled by hand (most entries close themselves when their cause is gone)."""
    row = _locked(conn, work_id)
    if row["status"] not in ("open", "claimed"):
        raise QueueConflict(f"this entry is already {row['status']}")
    conn.execute(
        "update work_items set status = 'done', resolved_by = %s, resolved_at = now(),"
        " resolution = %s where id = %s",
        (user.id, note.strip() or "Handled.", work_id),
    )
