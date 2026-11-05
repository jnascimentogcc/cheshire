"""In-application notifications (discussions.md section 8). No e-mail in v1.

Created as a side effect of discussion activity, plus two reminders derived on read, the
same way the work queue is (no scheduler): the decider's nudge after a quiet period and the
warning that a work-queue claim is about to expire.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import psycopg
from psycopg.rows import dict_row

from cheshire.auth.service import User

Conn = psycopg.Connection[Any]


def architects(conn: Conn) -> list[int]:
    """Active users who can take part in discussions (architects and admins)."""
    rows = conn.execute(
        "select id from users where active and role in ('architect', 'admin') order by id"
    ).fetchall()
    return [int(r[0]) for r in rows]


def notify(
    conn: Conn,
    user_ids: Iterable[int],
    kind: str,
    subject_type: str,
    subject_id: int,
    payload: dict[str, Any],
) -> None:
    for user_id in sorted(set(user_ids)):
        conn.execute(
            "insert into notifications (user_id, kind, subject_type, subject_id, payload)"
            " values (%s, %s, %s, %s, %s::jsonb)",
            (user_id, kind, subject_type, subject_id, json.dumps(payload)),
        )


def refresh(conn: Conn, user: User, nudge_days: int, warning_hours: int) -> None:
    """Reminders for `user`, each created once per cause."""
    # the decider of a discussion that has been quiet for a while
    conn.execute(
        "insert into notifications (user_id, kind, subject_type, subject_id, payload)"
        " select d.decider_id, 'decider_nudge', 'discussion', d.id,"
        "   jsonb_build_object('title', d.title, 'quiet_since', q.last)"
        " from discussions d"
        " cross join lateral (select greatest(d.opened_at,"
        "   coalesce((select max(created_at) from comments c where c.discussion_id = d.id),"
        "   d.opened_at)) as last) q"
        " where d.status = 'open' and d.decider_id = %s"
        "   and q.last < now() - make_interval(days => %s)"
        "   and not exists (select 1 from notifications n where n.user_id = d.decider_id"
        "     and n.kind = 'decider_nudge' and n.subject_id = d.id and n.created_at > q.last)",
        (user.id, nudge_days),
    )
    # a claim that is about to expire (once per expiry date: renewing starts a new cycle)
    conn.execute(
        "insert into notifications (user_id, kind, subject_type, subject_id, payload)"
        " select w.claimed_by, 'claim_expiring', 'work_item', w.id,"
        "   jsonb_build_object('kind', w.kind, 'expires_at', w.claim_expires_at)"
        " from work_items w where w.status = 'claimed' and w.claimed_by = %s"
        "   and w.claim_expires_at < now() + make_interval(hours => %s)"
        "   and w.claim_expires_at > now()"
        "   and not exists (select 1 from notifications n where n.user_id = w.claimed_by"
        "     and n.kind = 'claim_expiring' and n.subject_id = w.id"
        "     and n.payload ->> 'expires_at' = (w.claim_expires_at)::text)",
        (user.id, warning_hours),
    )


def list_for(conn: Conn, user: User, unread_only: bool = False, limit: int = 100) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select id, kind, subject_type, subject_id, payload, created_at, read_at"
            " from notifications where user_id = %s and (%s = false or read_at is null)"
            " order by id desc limit %s",
            (user.id, unread_only, limit),
        )
        items = cur.fetchall()
    unread = conn.execute(
        "select count(*) from notifications where user_id = %s and read_at is null", (user.id,)
    ).fetchone()
    assert unread is not None
    return {"unread": int(unread[0]), "items": items}


def mark_read(conn: Conn, user: User, notification_id: int) -> bool:
    row = conn.execute(
        "update notifications set read_at = coalesce(read_at, now())"
        " where id = %s and user_id = %s returning id",
        (notification_id, user.id),
    ).fetchone()
    return row is not None


def mark_all_read(conn: Conn, user: User) -> int:
    cur = conn.execute(
        "update notifications set read_at = now() where user_id = %s and read_at is null",
        (user.id,),
    )
    return cur.rowcount
