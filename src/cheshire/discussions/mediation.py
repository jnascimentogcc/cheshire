"""The Mediator inside a discussion: collect the facts with code, let the agent phrase them,
post the checked result. It speaks at opening, on request, on *Prepare decision* and when
code detects a problem (discussions.md section 6); it never answers every comment."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from cheshire.agents.base import AgentError
from cheshire.agents.mediator import Fact, Mediation, Mode, mediate
from cheshire.agents.writer import name_pattern
from cheshire.auth.service import User
from cheshire.catalog.models import Abb, Catalog, Sbb
from cheshire.consult.service import Context, _model, record_run
from cheshire.db.catalog_repo import CatalogRepo
from cheshire.discussions import service
from cheshire.discussions.service import Conflict, Forbidden
from cheshire.maintenance import overview

Conn = psycopg.Connection[Any]
MAX_COMMENT_FACT = 400
MAX_IMPACT_FACTS = 20


def _names(text: str, catalog: Catalog) -> tuple[str, ...]:
    candidates = {n for a in catalog.abbs for n in (a.id, a.name) if n.strip()} | {
        n for b in catalog.sbbs for n in (b.id, b.name) if n.strip()
    }
    return tuple(sorted(n for n in candidates if name_pattern(n).search(text)))


def _label(catalog: Catalog, kind: str, slug: str) -> str:
    """ "sbb sms-provider-a (SMS provider A)": the name lets the mediator use it legitimately."""
    item: Abb | Sbb | None = None
    if kind == "abb":
        item = catalog.abb(slug)
    elif kind == "sbb":
        item = next((b for b in catalog.sbbs if b.id == slug), None)
    return f"{kind} {slug} ({item.name})" if item is not None else f"{kind} {slug}"


def build_facts(
    conn: Conn, d: dict[str, Any], catalog: Catalog, impact_content: dict[str, Any]
) -> list[Fact]:
    """Everything the mediator may state about the catalog and the thread, computed by code."""
    texts: list[tuple[str, str]] = []
    kind, slug = d["item_kind"], d["item_slug"]
    repo = CatalogRepo(conn)
    view = service.proposal_view(conn, d)

    counts = conn.execute(
        "select (select count(*) from comments where discussion_id = %s and kind = 'comment'),"
        " (select count(*) from positions where discussion_id = %s and superseded_at is null)",
        (d["id"], d["id"]),
    ).fetchone()
    assert counts is not None
    texts.append(
        (
            "discussion",
            f"Discussion about {_label(catalog, kind, slug)}, opened by {d['opener']}; "
            f"the decider is {d['decider']}; so far {counts[0]} comments and "
            f"{counts[1]} current positions.",
        )
    )
    if view["is_new_item"]:
        texts.append(
            (
                "item",
                f"{_label(catalog, kind, slug)} does not exist yet; the proposal would create it.",
            )
        )
    else:
        effective = conn.execute(
            "select v.number, v.status from effective_versions e join item_versions v"
            " on v.id = e.id where e.item_id = %s",
            (d["item_id"],),
        ).fetchone()
        shown = (
            f"effective version {effective[0]} ({effective[1]})"
            if effective
            else "no effective version"
        )
        texts.append(("item", f"{_label(catalog, kind, slug)} has {shown}."))
    usage = impact_content.get("usage") or {}
    if usage:
        texts.append(
            (
                "usage",
                f"Used in {usage['consultations']} consultations; "
                f"flagged {usage['flagged']} times; "
                f"removed by users {usage['corrected']} times; chosen {usage['chosen']} times.",
            )
        )
    deps = impact_content.get("dependents") or []
    texts.append(
        (
            "dependents",
            "Items that depend on it: "
            + ", ".join(f"{_label(catalog, x['kind'], x['slug'])} ({x['ref_kind']})" for x in deps)
            + "."
            if deps
            else "No other item depends on it.",
        )
    )
    if not view["is_new_item"]:
        reads = repo.find_item_id(kind, slug)
        if reads is not None:
            uses = overview.connections(conn, repo, kind, slug)["uses"]
            if uses:
                texts.append(
                    (
                        "reads",
                        "It refers to: "
                        + ", ".join(
                            f"{_label(catalog, x['kind'], x['slug'])} ({x['ref_kind']})"
                            for x in uses
                        )
                        + ".",
                    )
                )
    if view["version"] is None:
        texts.append(("proposal", "No proposal has been saved yet."))
    else:
        for n, c in enumerate(view["changes"], start=1):
            texts.append((f"proposal:{n}", f"Proposed change: {c['text']}."))
        if not view["changes"]:
            texts.append(("proposal", "The proposal does not differ from the base version."))
    n = 0
    for case in impact_content.get("reference_cases", []):
        for diff in case["differences"]:
            n += 1
            if n <= MAX_IMPACT_FACTS:
                texts.append(
                    (
                        f"impact:{n}",
                        f"Reference case {case['title']!r} would change: {diff['text']}",
                    )
                )
    for cons in impact_content.get("recent_consultations", []):
        for diff in cons["differences"]:
            n += 1
            if n <= MAX_IMPACT_FACTS:
                texts.append(
                    (f"impact:{n}", f"Consultation {cons['title']!r} would change: {diff['text']}")
                )
    s = impact_content.get("summary") or {}
    texts.append(
        (
            "impact",
            f"If accepted: {s.get('reference_cases_changed', 0)} reference cases and "
            f"{s.get('consultations_changed', 0)} recent consultations would change; "
            f"{s.get('new_issues', 0)} new validator findings.",
        )
    )
    for i, issue in enumerate(impact_content.get("new_issues", []), start=1):
        texts.append((f"issue:{i}", f"Validator finding: {issue}"))
    for p in service.current_positions(conn, d["id"]):
        reason = f": {p['reason']}" if p["reason"] else ""
        texts.append(
            (
                f"position:{p['id']}",
                f"{p['participant']} takes the position {p['stance'].replace('_', ' ')}{reason}",
            )
        )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select c.id, a.display_name as author, c.body from comments c"
            " join users a on a.id = c.author_id where c.discussion_id = %s and c.kind = 'comment'"
            " and c.retracted_at is null order by c.seq desc limit 30",
            (d["id"],),
        )
        comments = list(reversed(cur.fetchall()))
    for c in comments:
        body = (
            c["body"]
            if len(c["body"]) <= MAX_COMMENT_FACT
            else c["body"][:MAX_COMMENT_FACT] + "..."
        )
        texts.append((f"comment:{c['id']}", f"{c['author']} wrote: {body}"))
    return [Fact(ref=ref, text=text, names=_names(text, catalog)) for ref, text in texts]


def _body(m: Mediation) -> str:
    lines = [s.text for s in m.sentences]
    if m.suggested_change:
        lines.append(f"Suggested change: {m.suggested_change}")
    return "\n".join(lines)


def speak(
    conn: Conn,
    ctx: Context,
    user: User,
    discussion_id: int,
    mode: Mode,
    question: str = "",
) -> int:
    """Post one mediator message. Raises an `AgentError` when it cannot be posted; the rest
    of the discussion keeps working (the failure is shown inside the mediator region only)."""
    d = service._row(conn, discussion_id)
    if d["status"] != "open":
        raise Conflict("this discussion is closed")
    if mode == "synthesis" and d["decider_id"] != user.id:
        raise Forbidden(f"only {d['decider']} (the decider) can prepare the decision")
    if mode == "ask" and not question.strip():
        raise service.DiscussionError("write the question for the mediator")
    model = _model(ctx.settings, "mediator")
    catalog = CatalogRepo(conn).load_catalog(include_drafts=True)
    impact_content = service.compute_impact(conn, d, ctx.settings)
    facts = build_facts(conn, d, catalog, impact_content)
    opposes = {
        p["id"] for p in service.current_positions(conn, discussion_id) if p["stance"] == "oppose"
    }
    conn.commit()  # nothing below should hold the discussion while the provider is slow
    try:
        result = mediate(
            ctx.llm_factory(),
            model,
            catalog,
            facts,
            mode=mode,
            opposes=opposes,
            question=question.strip(),
            language=ctx.settings.language,
        )
    except AgentError as exc:
        record_run(conn, exc.run, user.id)
        conn.commit()  # the failed run is kept for debugging
        raise
    run_id = record_run(conn, result.run, user.id)
    service._join(conn, discussion_id, user.id)
    grounding = {
        "mode": mode,
        "asked_by": user.id,
        "question": question.strip(),
        "sentences": [{"kind": s.kind, "text": s.text, "refs": s.refs} for s in result.sentences],
        "facts": {f.ref: f.text for f in facts},
        "suggested_change": result.suggested_change,
        "draft_rationale": result.draft_rationale,
        "responses": [
            {"position_id": r.position_id, "accepted": r.accepted, "response": r.response}
            for r in result.responses
        ],
        "checker": {"problems": [], "attempts": result.run.attempts},
    }
    comment_id = service._add_comment(
        conn, discussion_id, "mediator", None, _body(result), run_id, grounding
    )
    d = service._row(conn, discussion_id)
    service._tell_participants(conn, d, user.id, f"mediator ({mode})")
    return comment_id
