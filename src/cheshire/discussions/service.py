"""Discussions (docs/features/discussions.md): one open discussion per item, whoever opens it
decides and closes it (invariant 9), and the decision is a record (decider, outcome,
rationale, responses to opposing positions) so approval tiers can be added later.

The proposal is a `draft` version of the item: it never reaches a consultation before the
decider accepts it. Accepting sets its status to `validated` or `proposed` and closes the
discussion; every other change to a closed discussion is refused.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from pydantic import ValidationError

from cheshire.auth.service import User
from cheshire.catalog.effective import effective_catalog
from cheshire.catalog.models import Catalog
from cheshire.catalog.transfer import item_to_raw
from cheshire.catalog.validator import validate_catalog
from cheshire.db.catalog_repo import (
    MODEL_FOR_KIND,
    CatalogRefError,
    CatalogRepo,
    CatalogStateError,
    ItemModel,
)
from cheshire.discussions import notifications
from cheshire.maintenance import impact, overview
from cheshire.maintenance.diff import diff_items
from cheshire.settings import Settings

Conn = psycopg.Connection[Any]
Stance = Literal["support", "support_with_conditions", "oppose", "abstain"]
Outcome = Literal["accepted", "accepted_modified", "rejected", "withdrawn"]
STANCES = ("support", "support_with_conditions", "oppose", "abstain")
MAX_BODY = 5000


class DiscussionError(Exception):
    code = "invalid"

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.extra = extra


class NotFound(DiscussionError):
    code = "not_found"


class Forbidden(DiscussionError):
    code = "forbidden"


class Conflict(DiscussionError):
    code = "conflict"


class AlreadyOpen(Conflict):
    code = "already_open"


class Stale(Conflict):
    code = "stale"


class MissingResponses(DiscussionError):
    code = "missing_responses"


# ---------------------------------------------------------------------- helpers


def _row(conn: Conn, discussion_id: int, lock: bool = False) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select d.*, i.kind as item_kind, i.slug as item_slug,"
            " o.display_name as opener, dc.display_name as decider, dc.active as decider_active,"
            " bv.number as base_number, pv.number as pending_number"
            " from discussions d join catalog_items i on i.id = d.item_id"
            " join users o on o.id = d.opener_id join users dc on dc.id = d.decider_id"
            " left join item_versions bv on bv.id = d.base_version_id"
            " left join item_versions pv on pv.id = d.pending_version_id"
            " where d.id = %s" + (" for update of d" if lock else ""),
            (discussion_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise NotFound(f"discussion {discussion_id} not found")
    return row


def _open_row(conn: Conn, discussion_id: int) -> dict[str, Any]:
    d = _row(conn, discussion_id, lock=True)
    if d["status"] != "open":
        raise Conflict("this discussion is closed; start a new one that references it")
    return d


def _join(conn: Conn, discussion_id: int, user_id: int) -> None:
    conn.execute(
        "insert into discussion_participants (discussion_id, user_id) values (%s, %s)"
        " on conflict do nothing",
        (discussion_id, user_id),
    )


def _add_comment(
    conn: Conn,
    discussion_id: int,
    kind: str,
    author_id: int | None,
    body: str,
    llm_run_id: int | None = None,
    grounding: dict[str, Any] | None = None,
) -> int:
    row = conn.execute(
        "insert into comments (discussion_id, seq, kind, author_id, body, llm_run_id, grounding)"
        " values (%s, (select coalesce(max(seq), 0) + 1 from comments where discussion_id = %s),"
        " %s, %s, %s, %s, %s::jsonb) returning id",
        (
            discussion_id,
            discussion_id,
            kind,
            author_id,
            body,
            llm_run_id,
            json.dumps(grounding) if grounding is not None else None,
        ),
    ).fetchone()
    assert row is not None
    return int(row[0])


def system_note(conn: Conn, discussion_id: int, text: str) -> int:
    return _add_comment(conn, discussion_id, "system", None, text)


def _tell_participants(
    conn: Conn, d: dict[str, Any], actor_id: int | None, what: str, extra: set[int] | None = None
) -> None:
    rows = conn.execute(
        "select p.user_id from discussion_participants p join users u on u.id = p.user_id"
        " where p.discussion_id = %s and u.active",
        (d["id"],),
    ).fetchall()
    ids = {int(r[0]) for r in rows} | {d["decider_id"]} | (extra or set())
    ids.discard(actor_id if actor_id is not None else -1)
    notifications.notify(
        conn,
        ids,
        "discussion_activity",
        "discussion",
        d["id"],
        {"title": d["title"], "what": what, "item": f"{d['item_kind']}:{d['item_slug']}"},
    )


def _title(kind: str, slug: str, given: str) -> str:
    return given.strip() or f"{kind} {slug}"


def _active_architect(conn: Conn, user_id: int) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select id, display_name from users where id = %s and active"
            " and role in ('architect', 'admin')",
            (user_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise DiscussionError("that person is not an active architect")
    return row


def _item_raw(model: ItemModel | None) -> dict[str, Any]:
    if model is None:
        return {}
    raw = item_to_raw(model)
    raw.pop("status", None)
    return raw


def _version_item(conn: Conn, kind: str, slug: str, number: int | None) -> ItemModel | None:
    return CatalogRepo(conn).load_item(kind, slug, number) if number is not None else None


def _model(kind: str, slug: str, raw: dict[str, Any], status: str) -> ItemModel:
    try:
        model = MODEL_FOR_KIND[kind].model_validate({**raw, "status": status})
    except ValidationError as exc:
        err = exc.errors(include_url=False, include_context=False)[0]
        raise DiscussionError(f"the proposal is not valid: {err['loc']}: {err['msg']}") from exc
    if model.id != slug:
        raise DiscussionError("the id of the proposal must equal the id of the item")
    return model


# ------------------------------------------------------------------------ impact


def compute_impact(conn: Conn, d: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """The impact radius, by code: dependents, usage and what the proposal would change."""
    repo = CatalogRepo(conn)
    kind, slug = d["item_kind"], d["item_slug"]
    item = _version_item(conn, kind, slug, d["pending_number"])
    if item is None:
        item = repo.load_item(kind, slug)
    exists_in_catalog = repo.find_item_id(kind, slug) is not None
    content: dict[str, Any] = {"item": f"{kind}:{slug}", "has_proposal": d["pending_number"]}
    if item is None:
        content.update(
            effective_now=False, dependents=[], new_issues=[], reference_cases=[],
            recent_consultations=[],
        )  # fmt: skip
    else:
        content.update(
            impact.preview(conn, kind, item, "validated", settings.impact_recent_consultations)
        )
    content["usage"] = overview.usage(conn, repo, kind, slug) if exists_in_catalog else {}
    cases = [c for c in content["reference_cases"] if c["differences"]]
    recent = [c for c in content["recent_consultations"] if c["differences"]]
    content["summary"] = {
        "dependents": len(content["dependents"]),
        "reference_cases_changed": len(cases),
        "consultations_changed": len(recent),
        "new_issues": len(content["new_issues"]),
    }
    out: dict[str, Any] = json.loads(json.dumps(content, default=str))
    return out


def _store_impact(conn: Conn, d: dict[str, Any], kind: str, content: dict[str, Any]) -> int:
    snapshot = CatalogRepo(conn).snapshot()
    row = conn.execute(
        "insert into impact_snapshots (discussion_id, kind, snapshot_id, content)"
        " values (%s, %s, %s, %s::jsonb) returning id",
        (d["id"], kind, snapshot, json.dumps(content)),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _flat(content: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for c in content.get("reference_cases", []):
        out |= {f"Reference case {c['title']!r}: {x['text']}" for x in c["differences"]}
    for c in content.get("recent_consultations", []):
        out |= {f"Consultation {c['title']!r}: {x['text']}" for x in c["differences"]}
    out |= {f"Validator: {i}" for i in content.get("new_issues", [])}
    out |= {f"Dependent: {x['kind']} {x['slug']} ({x['ref_kind']})" for x in content["dependents"]}
    return out


def refresh_impact(conn: Conn, user: User, discussion_id: int, settings: Settings) -> None:
    d = _open_row(conn, discussion_id)
    _join(conn, discussion_id, user.id)
    content = compute_impact(conn, d, settings)
    _store_impact(conn, d, "refresh", content)
    system_note(conn, discussion_id, f"{user.display_name} refreshed the impact radius.")
    _tell_participants(conn, d, user.id, "impact refreshed")


def _impact_view(conn: Conn, discussion_id: int) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select id, kind, content, computed_at from impact_snapshots"
            " where discussion_id = %s order by id",
            (discussion_id,),
        )
        rows = cur.fetchall()
    if not rows:
        return {"current": None, "opened": None, "since_opening": {"new": [], "gone": []}}
    opened, current = rows[0], rows[-1]
    before, after = _flat(opened["content"]), _flat(current["content"])
    return {
        "current": current,
        "opened": opened,
        "refreshed": current["id"] != opened["id"],
        "since_opening": {"new": sorted(after - before), "gone": sorted(before - after)},
    }


# ------------------------------------------------------------------------- open


def open_discussion(
    conn: Conn,
    user: User,
    settings: Settings,
    *,
    kind: str,
    slug: str,
    proposal: dict[str, Any] | None = None,
    related: list[tuple[str, str]] | None = None,
    title: str = "",
    work_item_id: int | None = None,
) -> int:
    """The opener becomes the decider. A new item needs a proposal (it starts as a draft)."""
    if kind not in MODEL_FOR_KIND:
        raise DiscussionError(f"unknown kind {kind!r}")
    repo = CatalogRepo(conn)
    item_id = repo.find_item_id(kind, slug)
    base_id: int | None = None
    if item_id is None:
        if proposal is None:
            raise DiscussionError(
                "this item does not exist yet: give the proposal for the new item"
            )
        _model(kind, slug, proposal, "draft")  # validate before creating anything
        item_id = repo.create_item(kind, slug, user.id)
    else:
        existing = conn.execute(
            "select id from discussions where item_id = %s and status = 'open'", (item_id,)
        ).fetchone()
        if existing is not None:
            raise AlreadyOpen(
                f"{kind} {slug} already has an open discussion", discussion_id=int(existing[0])
            )
        row = conn.execute(
            "select coalesce((select id from effective_versions where item_id = %s),"
            " (select id from item_versions where item_id = %s order by number desc limit 1))",
            (item_id, item_id),
        ).fetchone()
        base_id = int(row[0]) if row and row[0] is not None else None
    if work_item_id is not None:
        w = conn.execute(
            "select status, claimed_by from work_items where id = %s", (work_item_id,)
        ).fetchone()
        if w is None:
            raise NotFound(f"work item {work_item_id} not found")
        if w[0] != "claimed" or w[1] != user.id:
            raise Conflict("claim the work-queue entry before opening a discussion about it")
    created = conn.execute(
        "insert into discussions (item_id, opener_id, decider_id, title, base_version_id,"
        " source_work_item_id) values (%s, %s, %s, %s, %s, %s) returning id",
        (item_id, user.id, user.id, _title(kind, slug, title), base_id, work_item_id),
    ).fetchone()
    assert created is not None
    did = int(created[0])
    _join(conn, did, user.id)
    for rkind, rslug in related or []:
        rid = repo.find_item_id(rkind, rslug)
        if rid is None:
            raise DiscussionError(f"unknown related item {rkind} {rslug!r}")
        if rid != item_id:
            conn.execute(
                "insert into discussion_related_items (discussion_id, item_id) values (%s, %s)"
                " on conflict do nothing",
                (did, rid),
            )
    if proposal is not None:
        _save_proposal(conn, user, did, proposal, note="Opening proposal")
    system_note(conn, did, f"{user.display_name} opened the discussion and is its decider.")
    d = _row(conn, did)
    content = compute_impact(conn, d, settings)
    _store_impact(conn, d, "open", content)
    notifications.notify(
        conn,
        [a for a in notifications.architects(conn) if a != user.id],
        "discussion_opened",
        "discussion",
        did,
        {
            "title": d["title"],
            "item": f"{kind}:{slug}",
            "opened_by": user.display_name,
            "impact": content["summary"],
        },
    )
    return did


# ----------------------------------------------------------------------- comments


def _mentions(conn: Conn, d: dict[str, Any], author: User, ids: list[int], what: str) -> None:
    valid = [i for i in set(ids) if i != author.id]
    if not valid:
        return
    rows = conn.execute(
        "select id from users where id = any(%s) and active and role in ('architect', 'admin')",
        (valid,),
    ).fetchall()
    notifications.notify(
        conn,
        [int(r[0]) for r in rows],
        "mention",
        "discussion",
        d["id"],
        {"title": d["title"], "by": author.display_name, "what": what},
    )


def comment(
    conn: Conn, user: User, discussion_id: int, body: str, mentions: list[int] | None = None
) -> int:
    d = _open_row(conn, discussion_id)
    body = body.strip()
    if not body:
        raise DiscussionError("a comment cannot be empty")
    if len(body) > MAX_BODY:
        raise DiscussionError(f"a comment is limited to {MAX_BODY} characters")
    _join(conn, discussion_id, user.id)
    comment_id = _add_comment(conn, discussion_id, "comment", user.id, body)
    mentioned = set(mentions or [])
    _mentions(conn, d, user, list(mentioned), "mentioned you in a comment")
    _tell_participants(conn, d, user.id, "new comment", extra=None)
    return comment_id


def _own_comment(conn: Conn, user: User, discussion_id: int, comment_id: int) -> dict[str, Any]:
    _open_row(conn, discussion_id)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select * from comments where id = %s and discussion_id = %s for update",
            (comment_id, discussion_id),
        )
        row = cur.fetchone()
    if row is None:
        raise NotFound("comment not found")
    if row["kind"] != "comment" or row["author_id"] != user.id:
        raise Forbidden("only the author can change a comment")
    if row["retracted_at"] is not None:
        raise Conflict("this comment was retracted")
    return row


def edit_comment(conn: Conn, user: User, discussion_id: int, comment_id: int, body: str) -> None:
    row = _own_comment(conn, user, discussion_id, comment_id)
    body = body.strip()
    if not body:
        raise DiscussionError("a comment cannot be empty")
    if len(body) > MAX_BODY:
        raise DiscussionError(f"a comment is limited to {MAX_BODY} characters")
    if body == row["body"]:
        return
    conn.execute(
        "insert into comment_edits (comment_id, old_body) values (%s, %s)",
        (comment_id, row["body"]),
    )
    conn.execute(
        "update comments set body = %s, edited_at = now() where id = %s", (body, comment_id)
    )


def retract_comment(conn: Conn, user: User, discussion_id: int, comment_id: int) -> None:
    """Marked, not deleted: the text stays in the record."""
    _own_comment(conn, user, discussion_id, comment_id)
    conn.execute("update comments set retracted_at = now() where id = %s", (comment_id,))


# ---------------------------------------------------------------------- positions


def set_position(conn: Conn, user: User, discussion_id: int, stance: str, reason: str) -> int:
    """One live position per participant; the earlier ones stay as history."""
    d = _open_row(conn, discussion_id)
    if stance not in STANCES:
        raise DiscussionError(f"stance must be one of {', '.join(STANCES)}")
    reason = reason.strip()
    if stance in ("support_with_conditions", "oppose") and not reason:
        raise DiscussionError("say why: a position that is not plain support needs a reason")
    _join(conn, discussion_id, user.id)
    conn.execute(
        "update positions set superseded_at = now()"
        " where discussion_id = %s and participant_id = %s and superseded_at is null",
        (discussion_id, user.id),
    )
    label = stance.replace("_", " ")
    comment_id = _add_comment(
        conn, discussion_id, "position", user.id, f"{label}: {reason}" if reason else label
    )
    row = conn.execute(
        "insert into positions (discussion_id, participant_id, stance, reason, comment_id)"
        " values (%s, %s, %s, %s, %s) returning id",
        (discussion_id, user.id, stance, reason, comment_id),
    ).fetchone()
    assert row is not None
    _tell_participants(conn, d, user.id, f"position: {label}")
    return int(row[0])


def current_positions(conn: Conn, discussion_id: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select p.id, p.participant_id, u.display_name as participant, p.stance, p.reason,"
            " p.created_at, (select count(*) from positions h"
            "   where h.discussion_id = p.discussion_id"
            "   and h.participant_id = p.participant_id and h.superseded_at is not null)"
            "   as revisions"
            " from positions p join users u on u.id = p.participant_id"
            " where p.discussion_id = %s and p.superseded_at is null order by p.id",
            (discussion_id,),
        )
        return cur.fetchall()


# ----------------------------------------------------------------------- proposal


def _newer_version(conn: Conn, d: dict[str, Any]) -> int | None:
    """A version saved by someone else since the discussion opened (the proposal is stale)."""
    if d["base_number"] is None:
        return None
    row = conn.execute(
        "select max(number) from item_versions where item_id = %s"
        " and not (origin = 'discussion' and origin_ref = %s)",
        (d["item_id"], d["id"]),
    ).fetchone()
    newest = int(row[0]) if row and row[0] is not None else None
    return newest if newest is not None and newest > d["base_number"] else None


def _issues_with(conn: Conn, kind: str, model: ItemModel) -> list[str]:
    repo = CatalogRepo(conn)
    before = {str(i) for i in validate_catalog(effective_catalog(repo.load_catalog()))}
    candidate = model.model_copy(update={"status": "validated"})
    after = effective_catalog(impact.with_item(repo.load_catalog(), kind, candidate))
    return [str(i) for i in validate_catalog(after) if str(i) not in before]


def _save_proposal(
    conn: Conn, user: User, discussion_id: int, raw: dict[str, Any], note: str = ""
) -> int:
    d = _row(conn, discussion_id)
    kind, slug = d["item_kind"], d["item_slug"]
    model = _model(kind, slug, raw, "draft")
    repo = CatalogRepo(conn)
    try:
        version_id = repo.save_version(
            kind,
            model,
            status="draft",
            author_id=user.id,
            origin="discussion",
            origin_ref=discussion_id,
            change_note=note or f"Proposal in discussion {discussion_id}",
        )
    except (CatalogRefError, CatalogStateError, psycopg.errors.IntegrityError) as exc:
        raise DiscussionError(f"the proposal cannot be saved: {exc}") from exc
    conn.execute(
        "update discussions set pending_version_id = %s where id = %s", (version_id, discussion_id)
    )
    return version_id


def propose(conn: Conn, user: User, discussion_id: int, raw: dict[str, Any]) -> list[str]:
    """Save the pending change (decider only). Returns the problems code found in it."""
    d = _open_row(conn, discussion_id)
    if d["decider_id"] != user.id:
        raise Forbidden(f"only {d['decider']} (the decider) can edit the proposal")
    _save_proposal(conn, user, discussion_id, raw)
    system_note(conn, discussion_id, f"{user.display_name} changed the proposal.")
    _tell_participants(conn, d, user.id, "proposal changed")
    model = _model(d["item_kind"], d["item_slug"], raw, "draft")
    issues = _issues_with(conn, d["item_kind"], model)
    _post_detected(conn, discussion_id, issues)
    return issues


def _post_detected(conn: Conn, discussion_id: int, issues: list[str]) -> None:
    """Problems found by the validator are facts: the mediator posts them without the LLM."""
    last = conn.execute(
        "select grounding from comments where discussion_id = %s and kind = 'mediator'"
        " and grounding ->> 'source' = 'validator' order by seq desc limit 1",
        (discussion_id,),
    ).fetchone()
    previous = last[0]["issues"] if last and last[0] else []
    if issues == previous or (not issues and not previous):
        return
    if issues:
        body = "The validator found problems with this proposal:\n- " + "\n- ".join(issues)
    else:
        body = "The validator no longer finds problems with this proposal."
    _add_comment(
        conn,
        discussion_id,
        "mediator",
        None,
        body,
        grounding={"source": "validator", "issues": issues, "mode": "detected"},
    )


def proposal_view(conn: Conn, d: dict[str, Any]) -> dict[str, Any]:
    """The pending change as sentences, against the version it started from."""
    kind, slug = d["item_kind"], d["item_slug"]
    pending = _version_item(conn, kind, slug, d["pending_number"])
    base = _version_item(conn, kind, slug, d["base_number"])
    changes = (
        [c.model_dump() for c in diff_items(_item_raw(base), _item_raw(pending))]
        if pending is not None
        else []
    )
    newer = _newer_version(conn, d) if d["status"] == "open" else None
    stale = None
    if newer is not None:
        latest = _version_item(conn, kind, slug, newer)
        stale = {
            "latest_version": newer,
            "base_version": d["base_number"],
            "changes": [c.model_dump() for c in diff_items(_item_raw(base), _item_raw(latest))],
        }
    return {
        "version": d["pending_number"],
        "item": _item_raw(pending),
        "base_item": _item_raw(base),  # what the editor starts from when nothing is proposed
        "base_version": d["base_number"],
        "is_new_item": d["base_version_id"] is None,
        "changes": changes,
        "stale": stale,
    }


# ----------------------------------------------------------------- transfer / reassign


def _hand_over(
    conn: Conn, actor: User, d: dict[str, Any], to_user: int, kind: str, reason: str
) -> None:
    if to_user == d["decider_id"]:
        raise DiscussionError("that person is already the decider")
    target = _active_architect(conn, to_user)
    conn.execute("update discussions set decider_id = %s where id = %s", (to_user, d["id"]))
    conn.execute(
        "insert into discussion_transfers"
        " (discussion_id, from_user, to_user, by_user, kind, reason)"
        " values (%s, %s, %s, %s, %s, %s)",
        (d["id"], d["decider_id"], to_user, actor.id, kind, reason.strip()),
    )
    _join(conn, d["id"], to_user)
    verb = "transferred" if kind == "transfer" else "reassigned"
    system_note(
        conn,
        d["id"],
        f"{actor.display_name} {verb} the discussion: {d['decider']} -> "
        f"{target['display_name']}." + (f" Reason: {reason.strip()}" if reason.strip() else ""),
    )
    notifications.notify(
        conn,
        [to_user],
        "discussion_reassigned",
        "discussion",
        d["id"],
        {"title": d["title"], "by": actor.display_name, "kind": kind},
    )
    _tell_participants(conn, d, actor.id, f"decider changed to {target['display_name']}")


def transfer(conn: Conn, user: User, discussion_id: int, to_user: int, reason: str = "") -> None:
    d = _open_row(conn, discussion_id)
    if d["decider_id"] != user.id:
        raise Forbidden(f"only {d['decider']} (the decider) can transfer the discussion")
    _hand_over(conn, user, d, to_user, "transfer", reason)


def reassign(conn: Conn, admin: User, discussion_id: int, to_user: int, reason: str = "") -> None:
    d = _open_row(conn, discussion_id)
    _hand_over(conn, admin, d, to_user, "reassign", reason)


def join(conn: Conn, user: User, discussion_id: int) -> None:
    _open_row(conn, discussion_id)
    _join(conn, discussion_id, user.id)


def mark_seen(conn: Conn, user: User, discussion_id: int) -> None:
    conn.execute(
        "update discussion_participants set last_seen_seq = (select coalesce(max(seq), 0)"
        " from comments where discussion_id = %s) where discussion_id = %s and user_id = %s",
        (discussion_id, discussion_id, user.id),
    )
    conn.execute(
        "update notifications set read_at = now() where user_id = %s and read_at is null"
        " and subject_type = 'discussion' and subject_id = %s",
        (user.id, discussion_id),
    )


# ---------------------------------------------------------------------- decision


def decide(
    conn: Conn,
    user: User,
    settings: Settings,
    discussion_id: int,
    *,
    outcome: str,
    status: str = "validated",
    rationale: str = "",
    responses: list[dict[str, Any]] | None = None,
    acknowledge_stale: bool = False,
) -> dict[str, Any]:
    """Close the discussion with a decision record. Only the decider; every live `oppose`
    needs a response, or nothing is saved."""
    d = _open_row(conn, discussion_id)
    if d["decider_id"] != user.id:
        raise Forbidden(f"only {d['decider']} (the decider) can decide")
    if outcome not in ("accepted", "accepted_modified", "rejected", "withdrawn"):
        raise DiscussionError("outcome must be accepted, accepted_modified, rejected or withdrawn")
    accepting = outcome in ("accepted", "accepted_modified")
    if accepting and d["pending_version_id"] is None:
        raise DiscussionError("there is no proposal to accept: save the proposed change first")
    if accepting and status not in ("validated", "proposed"):
        raise DiscussionError("the resulting status must be validated or proposed")
    rationale = rationale.strip()
    if outcome != "withdrawn" and not rationale:
        raise DiscussionError("the decision needs a rationale")

    opposes = [p for p in current_positions(conn, discussion_id) if p["stance"] == "oppose"]
    given = {r["position_id"]: r for r in (responses or [])}
    for pid in given:
        if pid not in {p["id"] for p in opposes}:
            raise DiscussionError(f"position {pid} is not a current opposing position")
    if outcome != "withdrawn":
        missing = [
            p for p in opposes if not str(given.get(p["id"], {}).get("response", "")).strip()
        ]
        if missing:
            raise MissingResponses(
                "answer every opposing position before deciding: "
                + ", ".join(p["participant"] for p in missing),
                positions=[{"id": p["id"], "participant": p["participant"]} for p in missing],
            )
        for p in opposes:
            if not isinstance(given[p["id"]].get("accepted"), bool):
                raise DiscussionError(
                    f"say whether the objection of {p['participant']} was accepted"
                )
    if accepting and _newer_version(conn, d) is not None and not acknowledge_stale:
        raise Stale(
            "the item changed after this discussion opened; review the newer version first",
            **proposal_view(conn, d)["stale"],
        )

    repo = CatalogRepo(conn)
    content = compute_impact(conn, d, settings)
    snapshot_id = _store_impact(conn, d, "decision", content)
    resulting_version: int | None = None
    if accepting:
        resulting_version = d["pending_version_id"]
        repo.set_status(resulting_version, status, user.id)  # type: ignore[arg-type]
    elif d["base_version_id"] is None:  # a new item that was never accepted leaves no trace
        with contextlib.suppress(CatalogStateError):
            repo.archive_item(d["item_kind"], d["item_slug"], user.id)
    row = conn.execute(
        "insert into decisions (discussion_id, decider_id, outcome, resulting_version_id,"
        " resulting_status, rationale, impact_snapshot_id) values (%s, %s, %s, %s, %s, %s, %s)"
        " returning id",
        (
            discussion_id,
            user.id,
            outcome,
            resulting_version,
            status if accepting else None,
            rationale,
            snapshot_id,
        ),
    ).fetchone()
    assert row is not None
    decision_id = int(row[0])
    if outcome != "withdrawn":
        for p in opposes:
            r = given[p["id"]]
            conn.execute(
                "insert into decision_responses (decision_id, position_id, accepted, response)"
                " values (%s, %s, %s, %s)",
                (decision_id, p["id"], r["accepted"], str(r["response"]).strip()),
            )
    final = {"accepted": "accepted", "accepted_modified": "accepted", "rejected": "rejected",
             "withdrawn": "withdrawn"}[outcome]  # fmt: skip
    conn.execute(
        "update discussions set status = %s, closed_at = now() where id = %s",
        (final, discussion_id),
    )
    label = outcome.replace("_", " ")
    system_note(
        conn, discussion_id, f"{user.display_name} decided: {label}. The discussion is closed."
    )
    _tell_participants(conn, d, user.id, f"decided: {label}")
    return {"decision_id": decision_id, "outcome": outcome}


# --------------------------------------------------------------------------- views


def _decision(conn: Conn, discussion_id: int) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select x.id, x.outcome, x.rationale, x.resulting_status, x.decided_at,"
            " u.display_name as decider, v.number as version, x.impact_snapshot_id"
            " from decisions x join users u on u.id = x.decider_id"
            " left join item_versions v on v.id = x.resulting_version_id"
            " where x.discussion_id = %s",
            (discussion_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            "select r.position_id, r.accepted, r.response, u.display_name as participant,"
            " p.stance, p.reason from decision_responses r"
            " join positions p on p.id = r.position_id"
            " join users u on u.id = p.participant_id where r.decision_id = %s"
            " order by r.position_id",
            (row["id"],),
        )
        row["responses"] = cur.fetchall()
    return row


def view(conn: Conn, user: User, discussion_id: int) -> dict[str, Any]:
    d = _row(conn, discussion_id)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select c.id, c.seq, c.kind, c.author_id, a.display_name as author, c.body,"
            " c.grounding, c.llm_run_id is not null as ai, c.created_at, c.edited_at,"
            " c.retracted_at, (select count(*) from comment_edits e where e.comment_id = c.id)"
            " as edits from comments c left join users a on a.id = c.author_id"
            " where c.discussion_id = %s order by c.seq",
            (discussion_id,),
        )
        thread = cur.fetchall()
        cur.execute(
            "select u.id, u.display_name as name, u.active, p.joined_at,"
            " p.last_seen_seq from discussion_participants p join users u on u.id = p.user_id"
            " where p.discussion_id = %s order by p.joined_at, u.id",
            (discussion_id,),
        )
        participants = cur.fetchall()
        cur.execute(
            "select t.id, f.display_name as from_user, x.display_name as to_user,"
            " b.display_name as by_user, t.kind, t.reason, t.at from discussion_transfers t"
            " join users f on f.id = t.from_user join users x on x.id = t.to_user"
            " join users b on b.id = t.by_user where t.discussion_id = %s order by t.id",
            (discussion_id,),
        )
        transfers = cur.fetchall()
        cur.execute(
            "select i.kind, i.slug from discussion_related_items r"
            " join catalog_items i on i.id = r.item_id where r.discussion_id = %s"
            " order by i.kind, i.slug",
            (discussion_id,),
        )
        related = cur.fetchall()
        cur.execute(
            "select p.id, u.display_name as participant, p.stance, p.reason, p.created_at,"
            " p.superseded_at from positions p join users u on u.id = p.participant_id"
            " where p.discussion_id = %s order by p.id",
            (discussion_id,),
        )
        history = cur.fetchall()
    me = next((p for p in participants if p["id"] == user.id), None)
    brief = next(
        (
            c
            for c in reversed(thread)
            if c["kind"] == "mediator" and (c["grounding"] or {}).get("mode") == "brief"
        ),
        None,
    )
    is_open = d["status"] == "open"
    is_decider = d["decider_id"] == user.id
    return {
        "id": d["id"],
        "title": d["title"],
        "status": d["status"],
        "item": {"kind": d["item_kind"], "slug": d["item_slug"]},
        "opener": {"id": d["opener_id"], "name": d["opener"]},
        "decider": {"id": d["decider_id"], "name": d["decider"], "active": d["decider_active"]},
        "opened_at": d["opened_at"],
        "closed_at": d["closed_at"],
        "participants": participants,
        "related": related,
        "transfers": transfers,
        "proposal": proposal_view(conn, d),
        "impact": _impact_view(conn, discussion_id),
        "brief": brief,
        "thread": thread,
        "positions": current_positions(conn, discussion_id),
        "position_history": history,
        "decision": _decision(conn, discussion_id),
        "has_new": me is not None and any(c["seq"] > me["last_seen_seq"] for c in thread),
        "can": {
            "comment": is_open,
            "edit_proposal": is_open and is_decider,
            "decide": is_open and is_decider,
            "transfer": is_open and is_decider,
            "joined": me is not None,
        },
    }


def _domains(catalog: Catalog) -> dict[tuple[str, str], str]:
    abbs = {a.id: a.domain for a in catalog.abbs}
    out: dict[tuple[str, str], str] = {("abb", k): v for k, v in abbs.items()}
    out |= {("sbb", s.id): abbs.get(s.realises, "") for s in catalog.sbbs}
    out |= {("rule", r.id): abbs.get(r.activates, "") for r in catalog.rules}
    return out


def list_discussions(
    conn: Conn,
    user: User,
    tab: str = "open",
    *,
    kind: str | None = None,
    domain: str | None = None,
    older_than_days: int | None = None,
    inactive_days: int | None = None,
) -> list[dict[str, Any]]:
    if tab not in ("attention", "mine", "open", "closed", "orphaned"):
        raise DiscussionError("tab must be attention, mine, open, closed or orphaned")
    where = ["d.status = 'open'"]
    params: list[Any] = [user.id]
    if tab == "closed":
        where = ["d.status <> 'open'"]
    elif tab == "mine":
        where.append("d.opener_id = %s")
        params.append(user.id)
    elif tab == "orphaned":
        where.append("not dc.active")
    elif tab == "attention":
        where.append(
            "(exists (select 1 from discussion_participants p where p.discussion_id = d.id"
            "   and p.user_id = %s and exists (select 1 from comments c"
            "   where c.discussion_id = d.id"
            "   and c.seq > p.last_seen_seq and (c.author_id is distinct from %s)))"
            " or exists (select 1 from notifications n where n.user_id = %s and n.read_at is null"
            "   and n.subject_type = 'discussion' and n.subject_id = d.id"
            "   and n.kind in ('mention', 'decider_nudge', 'discussion_reassigned',"
            "   'discussion_opened')))"
        )
        params += [user.id, user.id, user.id]
    if kind:
        where.append("i.kind = %s")
        params.append(kind)
    if older_than_days is not None:
        where.append("d.opened_at < now() - make_interval(days => %s)")
        params.append(older_than_days)
    sql = (
        "select d.id, d.title, d.status, i.kind as item_kind, i.slug as item_slug,"
        " o.display_name as opener, dc.display_name as decider, dc.active as decider_active,"
        " d.opened_at, d.closed_at, a.last_activity,"
        " (select count(*) from discussion_participants p where p.discussion_id = d.id)"
        "   as participants,"
        " (select count(*) from comments c where c.discussion_id = d.id and c.kind = 'comment')"
        "   as comments,"
        " extract(day from now() - a.last_activity)::int as inactive_days,"
        " d.decider_id = %s as i_decide"
        " from discussions d join catalog_items i on i.id = d.item_id"
        " join users o on o.id = d.opener_id join users dc on dc.id = d.decider_id"
        " cross join lateral (select greatest(d.opened_at, coalesce((select max(created_at)"
        "   from comments c where c.discussion_id = d.id), d.opened_at)) as last_activity) a"
        " where " + " and ".join(where) + " order by a.last_activity desc, d.id desc"
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    domains = _domains(CatalogRepo(conn).load_catalog(include_drafts=True))
    out = []
    for r in rows:
        r["domain"] = domains.get((r["item_kind"], r["item_slug"]), "")
        if domain and r["domain"] != domain:
            continue
        if inactive_days is not None and r["inactive_days"] < inactive_days:
            continue
        out.append(r)
    return out


def decision_summaries(conn: Conn, kind: str, slug: str) -> list[dict[str, Any]]:
    """What everybody may see about an item's decisions: who decided, what, why and when.
    Never the thread, the positions or the impact (discussions.md section 12)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select x.discussion_id, x.outcome, x.rationale, x.decided_at,"
            " u.display_name as decider, v.number as version, x.resulting_status as status"
            " from decisions x join discussions d on d.id = x.discussion_id"
            " join catalog_items i on i.id = d.item_id join users u on u.id = x.decider_id"
            " left join item_versions v on v.id = x.resulting_version_id"
            " where i.kind = %s and i.slug = %s and x.outcome <> 'withdrawn'"
            " order by x.decided_at desc",
            (kind, slug),
        )
        return cur.fetchall()


def open_for_item(conn: Conn, kind: str, slug: str) -> int | None:
    row = conn.execute(
        "select d.id from discussions d join catalog_items i on i.id = d.item_id"
        " where i.kind = %s and i.slug = %s and d.status = 'open'",
        (kind, slug),
    ).fetchone()
    return int(row[0]) if row else None
