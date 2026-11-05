"""M6: discussions, positions, the mediator, decisions and notifications."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from cheshire.agents.mediator import Fact, check, output_schema
from cheshire.agents.mediator import _Raw as RawMediation
from cheshire.catalog.models import Catalog
from cheshire.providers.base import LLMUnavailable
from cheshire.settings import Settings
from tests.conftest import TestDb
from tests.test_consult import (  # noqa: F401 - fixtures
    World,
    load_catalog,
    make_world,
    scripted,
)

Make = Callable[..., World]
Session = tuple[TestClient, dict[str, str]]
ITEM = ("abb", "channel-sms")


@pytest.fixture
def settings(clean_db: TestDb) -> Settings:
    return Settings(
        database_url=clean_db.app_url,
        cookie_secure=False,
        llm_interpreter_model="interp-model",
        llm_writer_model="writer-model",
        llm_mediator_model="mediator-model",
        discussion_nudge_days=7,
    )


def med(*sentences: tuple[str, str, list[str]], **extra: Any) -> dict[str, Any]:
    return {
        "sentences": [{"kind": k, "text": t, "refs": r} for k, t, r in sentences],
        "suggested_change": None,
        "draft_rationale": None,
        "responses": [],
        **extra,
    }


BRIEF = med(
    ("fact", "It is used in 0 consultations.", ["usage"]),
    ("question", "When would this change not apply?", []),
)


@dataclass
class Team:
    world: World
    arch: Session  # opens discussions
    bea: Session
    cai: Session
    ana: Session  # a plain user
    ids: dict[str, int]
    llm: Any


def team(make_world: Make, example_catalog: Catalog, *replies: Any) -> Team:
    llm = scripted(*replies)
    world = make_world(llm)
    arch = load_catalog(world, example_catalog)
    bea = world.add_user("bea@example.org", "architect")
    cai = world.add_user("cai@example.org", "architect")
    ana = world.add_user("ana@example.org", "user")
    for abb in ("channel-sms", "channel-email"):  # the import lands as proposed: validate a base
        r = arch[0].post(
            f"/api/catalog/abb/{abb}/versions/1/status",
            json={"status": "validated"},
            headers=arch[1],
        )
        assert r.status_code == 200, r.text
    ids = {
        name: s[0].get("/api/auth/me").json()["user"]["id"]
        for name, s in [("arch", arch), ("bea", bea), ("cai", cai), ("ana", ana)]
    }
    return Team(world, arch, bea, cai, ana, ids, llm)


def open_(
    s: Session, kind: str = ITEM[0], slug: str = ITEM[1], **body: Any
) -> tuple[int, dict[str, Any]]:
    r = s[0].post("/api/discussions", json={"kind": kind, "slug": slug, **body}, headers=s[1])
    assert r.status_code == 201, r.text
    view: dict[str, Any] = r.json()
    return view["id"], view


def call(s: Session, method: str, url: str, **kw: Any) -> Any:
    return getattr(s[0], method)(url, headers=s[1], **kw)


def get(s: Session, did: int) -> dict[str, Any]:
    view: dict[str, Any] = s[0].get(f"/api/discussions/{did}").json()
    return view


def kinds(view: dict[str, Any]) -> list[str]:
    return [c["kind"] for c in view["thread"]]


def pro_sms_item(t: Team) -> dict[str, Any]:
    raw: dict[str, Any] = t.arch[0].get("/api/catalog/abb/channel-sms").json()["item"]
    raw.pop("status", None)
    return raw


# --- who can take part ---------------------------------------------------------


def test_users_cannot_take_part_and_see_only_the_decision_summary(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.arch)
    ana, ah = t.ana
    assert ana.get("/api/discussions").status_code == 403
    assert ana.get(f"/api/discussions/{did}").status_code == 403
    assert (
        ana.post(f"/api/discussions/{did}/comments", json={"body": "hi"}, headers=ah).status_code
        == 403
    )
    assert ana.get("/api/notifications").status_code == 403
    summary = ana.get("/api/catalog/abb/channel-sms/decisions")
    assert summary.status_code == 200
    assert summary.json() == {"decisions": [], "open_discussion": None}  # not even that one is open


# --- opening -------------------------------------------------------------------


def test_opening_makes_the_opener_the_decider_and_tells_every_architect(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, view = open_(t.arch, title="Is SMS still right?")
    assert view["status"] == "open" and view["title"] == "Is SMS still right?"
    assert view["opener"]["id"] == view["decider"]["id"] == t.ids["arch"]
    assert view["can"]["decide"] and view["can"]["edit_proposal"]
    # system entry, then the mediator's brief with its grounding
    assert kinds(view) == ["system", "mediator"]
    brief = view["brief"]
    assert brief["ai"] is True and brief["author"] is None
    assert brief["grounding"]["mode"] == "brief"
    assert brief["grounding"]["sentences"][0]["refs"] == ["usage"]
    assert "usage" in brief["grounding"]["facts"]
    # the impact radius was computed by code and stored when the discussion opened
    assert view["impact"]["opened"]["kind"] == "open"
    assert view["impact"]["current"]["content"]["summary"]["dependents"] >= 1
    # everyone else who can take part is told, with the impact summary; the opener is not
    for who in ("bea", "cai"):
        n = getattr(t, who)[0].get("/api/notifications").json()
        [opened] = [i for i in n["items"] if i["kind"] == "discussion_opened"]
        assert opened["subject_id"] == did and "impact" in opened["payload"]
    mine = t.arch[0].get("/api/notifications").json()
    assert not [i for i in mine["items"] if i["kind"] == "discussion_opened"]
    summary = t.ana[0].get("/api/catalog/abb/channel-sms/decisions").json()
    assert summary["open_discussion"] is None  # users do not even learn that one is open
    assert t.bea[0].get("/api/catalog/abb/channel-sms/decisions").json()["open_discussion"] == did


def test_members_lists_who_can_take_part(make_world: Make, example_catalog: Catalog) -> None:
    t = team(make_world, example_catalog, BRIEF)
    rows = call(t.bea, "get", "/api/discussions/members").json()
    assert {r["name"] for r in rows} == {"Admin", "arch", "bea", "cai"}  # not the plain user
    assert call(t.ana, "get", "/api/discussions/members").status_code == 403


def test_only_one_open_discussion_per_item(make_world: Make, example_catalog: Catalog) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.arch)
    r = call(t.bea, "post", "/api/discussions", json={"kind": "abb", "slug": "channel-sms"})
    assert r.status_code == 409
    assert (
        r.json()["detail"]["code"] == "already_open" and r.json()["detail"]["discussion_id"] == did
    )
    assert call(t.bea, "post", f"/api/discussions/{did}/join").status_code == 200
    assert {p["name"] for p in get(t.bea, did)["participants"]} == {"arch", "bea"}


def test_the_discussion_exists_even_when_the_mediator_is_unavailable(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, LLMUnavailable("down"))
    r = call(t.arch, "post", "/api/discussions", json={"kind": "abb", "slug": "channel-sms"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mediator_error"]["code"] == "llm_unavailable" and body["brief"] is None
    did = body["id"]
    # thread, positions and the decision still work
    assert (
        call(t.bea, "post", f"/api/discussions/{did}/comments", json={"body": "ok"}).status_code
        == 201
    )
    assert (
        call(
            t.bea, "put", f"/api/discussions/{did}/position", json={"stance": "support"}
        ).status_code
        == 200
    )
    done = call(
        t.arch,
        "post",
        f"/api/discussions/{did}/decision",
        json={"outcome": "rejected", "rationale": "No change needed."},
    )
    assert done.status_code == 200 and done.json()["status"] == "rejected"


def test_a_discussion_about_a_new_item_needs_a_proposal(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF, BRIEF)
    r = call(t.arch, "post", "/api/discussions", json={"kind": "abb", "slug": "push-notification"})
    assert r.status_code == 422
    proposal = {
        "id": "push-notification",
        "name": "Push notification",
        "domain": "integration",
        "description": "Notify mobile apps.",
    }
    did, view = open_(t.arch, slug="push-notification", proposal=proposal)
    assert view["proposal"]["is_new_item"] and view["proposal"]["version"] == 1
    assert any("name" in c["text"] for c in view["proposal"]["changes"])
    # a draft never reaches consultations
    [row] = [
        i for i in t.arch[0].get("/api/catalog/abb").json() if i["slug"] == "push-notification"
    ]
    assert row["effective_number"] is None and row["latest_status"] == "draft"
    item = t.arch[0].get("/api/catalog/abb/push-notification?version=1").json()
    assert item["item"]["status"] == "draft" and item["versions"][0]["origin"] == "discussion"
    out = call(
        t.arch,
        "post",
        f"/api/discussions/{did}/decision",
        json={"outcome": "accepted", "status": "proposed", "rationale": "Needed for apps."},
    )
    assert out.status_code == 200, out.text
    item = t.arch[0].get("/api/catalog/abb/push-notification").json()
    assert item["item"]["status"] == "proposed"


# --- comments and positions ----------------------------------------------------


def test_comments_can_be_edited_and_retracted_never_deleted(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.arch)
    view = call(
        t.bea, "post", f"/api/discussions/{did}/comments", json={"body": " First thought "}
    ).json()
    [c] = [c for c in view["thread"] if c["kind"] == "comment"]
    assert c["body"] == "First thought" and c["edited_at"] is None
    url = f"/api/discussions/{did}/comments/{c['id']}"
    assert call(t.cai, "patch", url, json={"body": "hijack"}).status_code == 403  # not the author
    edited = call(t.bea, "patch", url, json={"body": "Second thought"}).json()
    [c] = [c for c in edited["thread"] if c["kind"] == "comment"]
    assert c["body"] == "Second thought" and c["edited_at"] and c["edits"] == 1
    assert (
        call(t.bea, "post", f"/api/discussions/{did}/comments", json={"body": "  "}).status_code
        == 422
    )
    retracted = call(t.bea, "post", url + "/retract").json()
    [c] = [c for c in retracted["thread"] if c["kind"] == "comment"]
    assert c["retracted_at"] and c["body"] == "Second thought"  # marked, the text stays
    assert call(t.bea, "patch", url, json={"body": "x"}).status_code == 409


def test_one_live_position_per_participant_and_history_is_kept(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.arch)
    url = f"/api/discussions/{did}/position"
    assert call(t.bea, "put", url, json={"stance": "oppose"}).status_code == 422  # needs a reason
    assert call(t.bea, "put", url, json={"stance": "maybe"}).status_code == 422
    call(t.bea, "put", url, json={"stance": "oppose", "reason": "Too risky"})
    view = call(
        t.bea, "put", url, json={"stance": "support_with_conditions", "reason": "If tested"}
    ).json()
    [mine] = view["positions"]
    assert mine["stance"] == "support_with_conditions" and mine["revisions"] == 1
    assert [p["stance"] for p in view["position_history"]] == ["oppose", "support_with_conditions"]
    assert view["position_history"][0]["superseded_at"]
    assert kinds(view).count("position") == 2


# --- the proposal and its impact -----------------------------------------------


def test_only_the_decider_edits_the_proposal_and_it_never_reaches_consultations(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, view = open_(t.arch)
    assert view["proposal"]["version"] is None and view["proposal"]["changes"] == []
    raw = pro_sms_item(t)
    raw["description"] = "SMS delivery, including OTP flows."
    url = f"/api/discussions/{did}/proposal"
    assert call(t.bea, "put", url, json={"item": raw}).status_code == 403
    r = call(t.arch, "put", url, json={"item": raw})
    assert r.status_code == 200, r.text
    changes = r.json()["proposal"]["changes"]
    assert any("description" in c["text"] for c in changes)
    # the effective version is still the old one: the proposal is a draft
    current = t.arch[0].get("/api/catalog/abb/channel-sms").json()
    assert current["item"]["description"] != raw["description"]
    assert [v["status"] for v in current["versions"]][:1] == ["draft"]
    assert current["versions"][0]["origin"] == "discussion"
    bad = {**raw, "id": "other"}
    assert call(t.arch, "put", url, json={"item": bad}).status_code == 422
    assert "system" in kinds(get(t.bea, did))


def test_impact_is_snapshotted_at_opening_and_refreshing_shows_what_changed(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, view = open_(t.arch)
    assert view["impact"]["since_opening"] == {"new": [], "gone": []}
    raw = pro_sms_item(t)
    raw["description"] = "Changed."
    call(t.arch, "put", f"/api/discussions/{did}/proposal", json={"item": raw})
    after = call(t.bea, "post", f"/api/discussions/{did}/impact/refresh").json()
    assert after["impact"]["refreshed"] is True
    assert after["impact"]["current"]["kind"] == "refresh"
    assert after["impact"]["opened"]["id"] != after["impact"]["current"]["id"]
    assert "system" in kinds(after)


def test_a_newer_version_makes_the_proposal_stale_until_acknowledged(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.arch)
    raw = pro_sms_item(t)
    call(
        t.arch,
        "put",
        f"/api/discussions/{did}/proposal",
        json={"item": {**raw, "description": "Mine."}},
    )
    # somebody saves the item outside the discussion
    other = {**raw, "description": "Theirs."}
    r = call(t.bea, "put", "/api/catalog/abb/channel-sms?status=validated", json=other)
    assert r.status_code in (200, 201), r.text
    view = get(t.arch, did)
    stale = view["proposal"]["stale"]
    assert stale and stale["latest_version"] > stale["base_version"]
    assert any("description" in c["text"] for c in stale["changes"])
    body = {"outcome": "accepted", "rationale": "Ship it."}
    refused = call(t.arch, "post", f"/api/discussions/{did}/decision", json=body)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "stale"
    assert get(t.arch, did)["status"] == "open"
    ok = call(
        t.arch, "post", f"/api/discussions/{did}/decision", json={**body, "acknowledge_stale": True}
    )
    assert ok.status_code == 200, ok.text


# --- deciding ------------------------------------------------------------------


def test_every_opposing_position_needs_a_response_before_the_decision_is_saved(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.arch)
    raw = pro_sms_item(t)
    call(
        t.arch,
        "put",
        f"/api/discussions/{did}/proposal",
        json={"item": {**raw, "description": "New."}},
    )
    call(
        t.bea,
        "put",
        f"/api/discussions/{did}/position",
        json={"stance": "oppose", "reason": "Breaks OTP"},
    )
    call(t.cai, "put", f"/api/discussions/{did}/position", json={"stance": "support"})
    view = get(t.arch, did)
    [opp] = [p for p in view["positions"] if p["stance"] == "oppose"]
    url = f"/api/discussions/{did}/decision"
    body: dict[str, Any] = {"outcome": "accepted", "rationale": "The benefits win."}
    missing = call(t.arch, "post", url, json=body)
    assert missing.status_code == 422
    detail = missing.json()["detail"]
    assert detail["code"] == "missing_responses" and "bea" in detail["message"]
    assert detail["positions"] == [{"id": opp["id"], "participant": "bea"}]
    assert get(t.arch, did)["status"] == "open"  # nothing was saved
    # a response to a position that is not opposing is refused
    other = next(p for p in view["positions"] if p["stance"] == "support")
    wrong = {**body, "responses": [{"position_id": other["id"], "accepted": True, "response": "x"}]}
    assert call(t.arch, "post", url, json=wrong).status_code == 422
    # the decider needs to say whether the objection was accepted
    ok = {
        **body,
        "responses": [
            {
                "position_id": opp["id"],
                "accepted": False,
                "response": "OTP flows are covered by the proposal.",
            }
        ],
    }
    done = call(t.arch, "post", url, json=ok)
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["status"] == "accepted"
    [resp] = out["decision"]["responses"]
    assert resp["participant"] == "bea" and resp["accepted"] is False
    assert out["decision"]["outcome"] == "accepted" and out["decision"]["version"]


def test_accepting_validates_the_proposal_and_closes_the_discussion(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.arch)
    raw = pro_sms_item(t)
    call(
        t.arch,
        "put",
        f"/api/discussions/{did}/proposal",
        json={"item": {**raw, "description": "Final."}},
    )
    assert (
        call(
            t.bea,
            "post",
            f"/api/discussions/{did}/decision",
            json={"outcome": "accepted", "rationale": "x"},
        ).status_code
        == 403
    )
    assert (
        call(
            t.arch, "post", f"/api/discussions/{did}/decision", json={"outcome": "accepted"}
        ).status_code
        == 422
    )
    bad = call(
        t.arch,
        "post",
        f"/api/discussions/{did}/decision",
        json={"outcome": "accepted", "rationale": "r", "status": "draft"},
    )
    assert bad.status_code == 422
    done = call(
        t.arch,
        "post",
        f"/api/discussions/{did}/decision",
        json={"outcome": "accepted_modified", "rationale": "Clearer description."},
    )
    assert done.status_code == 200, done.text
    item = t.arch[0].get("/api/catalog/abb/channel-sms").json()
    assert item["item"]["description"] == "Final." and item["item"]["status"] == "validated"
    assert (
        item["versions"][0]["origin"] == "discussion"
        and item["versions"][0]["validated_by"] == "arch"
    )
    # the record, and the closed discussion refuses everything
    assert done.json()["decision"]["rationale"] == "Clearer description."
    assert done.json()["decision"]["resulting_status"] == "validated"
    assert done.json()["closed_at"] and not done.json()["can"]["comment"]
    for method, url, body in [
        ("post", f"/api/discussions/{did}/comments", {"body": "late"}),
        ("put", f"/api/discussions/{did}/position", {"stance": "support"}),
        ("put", f"/api/discussions/{did}/proposal", {"item": raw}),
        ("post", f"/api/discussions/{did}/mediator", {"mode": "challenge"}),
        ("post", f"/api/discussions/{did}/decision", {"outcome": "rejected", "rationale": "r"}),
    ]:
        assert call(t.arch, method, url, json=body).status_code == 409, url
    # a new discussion can be opened (closed ones are never reopened)
    assert (
        call(
            t.arch, "post", "/api/discussions", json={"kind": "abb", "slug": "channel-sms"}
        ).status_code
        == 201
    )


def test_accepting_as_proposed_never_replaces_a_validated_version(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.arch)
    raw = pro_sms_item(t)
    call(
        t.arch,
        "put",
        f"/api/discussions/{did}/proposal",
        json={"item": {**raw, "description": "Pending."}},
    )
    call(
        t.arch,
        "post",
        f"/api/discussions/{did}/decision",
        json={"outcome": "accepted", "status": "proposed", "rationale": "Needs another look."},
    )
    item = t.arch[0].get("/api/catalog/abb/channel-sms").json()
    assert item["versions"][0]["status"] == "proposed"
    assert item["item"]["description"] != "Pending."  # the validated version is still in force


def test_rejecting_and_withdrawing_change_nothing(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF, BRIEF)
    before = t.arch[0].get("/api/catalog/abb/channel-sms").json()["versions"]
    did, _ = open_(t.arch)
    raw = pro_sms_item(t)
    call(
        t.arch,
        "put",
        f"/api/discussions/{did}/proposal",
        json={"item": {**raw, "description": "No."}},
    )
    out = call(
        t.arch,
        "post",
        f"/api/discussions/{did}/decision",
        json={"outcome": "rejected", "rationale": "Not worth it."},
    ).json()
    assert out["status"] == "rejected" and out["decision"]["version"] is None
    after = t.arch[0].get("/api/catalog/abb/channel-sms").json()
    assert (
        after["item"]["description"] == raw["description"] or after["item"]["status"] == "validated"
    )
    assert after["versions"][0]["status"] == "draft"  # the rejected proposal stays as history
    assert after["item"]["status"] == "validated" and len(after["versions"]) == len(before) + 1
    # nobody but the people taking part sees the thread; users see the summary of decisions
    summary = t.ana[0].get("/api/catalog/abb/channel-sms/decisions").json()["decisions"]
    assert [d["outcome"] for d in summary] == ["rejected"]
    assert set(summary[0]) == {"outcome", "rationale", "decided_at", "decider", "version", "status"}
    did2, _ = open_(t.arch)
    gone = call(t.arch, "post", f"/api/discussions/{did2}/decision", json={"outcome": "withdrawn"})
    assert gone.status_code == 200 and gone.json()["status"] == "withdrawn"
    assert len(t.ana[0].get("/api/catalog/abb/channel-sms/decisions").json()["decisions"]) == 1


def test_rejecting_a_new_item_leaves_nothing_in_the_catalog(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    proposal = {"id": "fax", "name": "Fax", "domain": "integration", "description": "Fax."}
    did, _ = open_(t.arch, slug="fax", proposal=proposal)
    call(
        t.arch,
        "post",
        f"/api/discussions/{did}/decision",
        json={"outcome": "rejected", "rationale": "No."},
    )
    [row] = [i for i in t.arch[0].get("/api/catalog/abb").json() if i["slug"] == "fax"]
    assert row["archived"] and row["effective_number"] is None


def test_the_database_refuses_a_decision_without_responses(
    make_world: Make, example_catalog: Catalog, clean_db: TestDb
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.arch)
    call(
        t.bea, "put", f"/api/discussions/{did}/position", json={"stance": "oppose", "reason": "No"}
    )
    with psycopg.connect(clean_db.app_url) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "insert into decisions (discussion_id, decider_id, outcome, rationale)"
            " values (%s, %s, 'rejected', 'r')",
            (did, t.ids["arch"]),
        )
        conn.commit()


# --- transfer and reassign -----------------------------------------------------


def test_the_decider_can_transfer_and_an_admin_can_reassign(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.arch)
    url = f"/api/discussions/{did}/transfer"
    assert call(t.bea, "post", url, json={"to_user_id": t.ids["bea"]}).status_code == 403
    assert call(t.arch, "post", url, json={"to_user_id": t.ids["arch"]}).status_code == 422
    assert (
        call(t.arch, "post", url, json={"to_user_id": t.ids["ana"]}).status_code == 422
    )  # not an architect
    moved = call(
        t.arch, "post", url, json={"to_user_id": t.ids["bea"], "reason": "I am away"}
    ).json()
    assert moved["decider"]["id"] == t.ids["bea"] and moved["opener"]["id"] == t.ids["arch"]
    [tr] = moved["transfers"]
    assert (tr["from_user"], tr["to_user"], tr["kind"], tr["reason"]) == (
        "arch",
        "bea",
        "transfer",
        "I am away",
    )
    assert not moved["can"]["decide"]  # the opener lost the role at once
    assert (
        call(
            t.arch,
            "post",
            f"/api/discussions/{did}/decision",
            json={"outcome": "rejected", "rationale": "r"},
        ).status_code
        == 403
    )
    note = [
        i
        for i in t.bea[0].get("/api/notifications").json()["items"]
        if i["kind"] == "discussion_reassigned"
    ]
    assert note and note[0]["subject_id"] == did
    # an admin reassigns; an architect may not
    admin, adh = t.world.admin
    assert (
        call(
            t.cai, "post", f"/api/discussions/{did}/reassign", json={"to_user_id": t.ids["cai"]}
        ).status_code
        == 403
    )
    r = admin.post(
        f"/api/discussions/{did}/reassign", json={"to_user_id": t.ids["cai"]}, headers=adh
    )
    assert r.status_code == 200 and r.json()["decider"]["id"] == t.ids["cai"]
    assert [x["kind"] for x in r.json()["transfers"]] == ["transfer", "reassign"]
    assert (
        call(
            t.cai,
            "post",
            f"/api/discussions/{did}/decision",
            json={"outcome": "rejected", "rationale": "Enough."},
        ).status_code
        == 200
    )


def test_a_discussion_whose_decider_left_shows_in_the_admins_reassign_queue(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.bea)  # bea opens, so bea decides
    admin, adh = t.world.admin
    assert admin.get("/api/discussions?tab=orphaned").json() == []
    assert call(t.arch, "get", "/api/discussions?tab=orphaned").status_code == 403
    r = admin.patch(f"/api/users/{t.ids['bea']}", json={"active": False}, headers=adh)
    assert r.status_code == 200
    [row] = admin.get("/api/discussions?tab=orphaned").json()
    assert row["id"] == did and row["decider_active"] is False
    assert (
        admin.post(
            f"/api/discussions/{did}/reassign", json={"to_user_id": t.ids["bea"]}, headers=adh
        ).status_code
        == 422
    )
    assert (
        admin.post(
            f"/api/discussions/{did}/reassign", json={"to_user_id": t.ids["cai"]}, headers=adh
        ).status_code
        == 200
    )
    assert admin.get("/api/discussions?tab=orphaned").json() == []


# --- the inbox -----------------------------------------------------------------


def test_inbox_tabs_and_filters(make_world: Make, example_catalog: Catalog) -> None:
    t = team(make_world, example_catalog, BRIEF, BRIEF)
    d1, _ = open_(t.arch)
    d2, _ = open_(t.bea, kind="abb", slug="channel-email")

    def ids(s: Session, q: str = "") -> list[int]:
        return [r["id"] for r in s[0].get(f"/api/discussions{q}").json()]

    assert sorted(ids(t.cai)) == [d1, d2]
    assert ids(t.arch, "?tab=mine") == [d1] and ids(t.bea, "?tab=mine") == [d2]
    assert ids(t.cai, "?tab=closed") == []
    assert ids(t.cai, "?kind=sbb") == []
    assert ids(t.cai, "?domain=integration") != [] and ids(t.cai, "?domain=data") == []
    # a new opening needs attention from architects who have not looked yet
    assert sorted(ids(t.cai, "?tab=attention")) == [d1, d2]
    call(t.cai, "post", f"/api/discussions/{d1}/seen")
    assert ids(t.cai, "?tab=attention") == [d2]
    assert ids(t.cai, "?inactive_days=3") == []
    call(t.arch, "post", f"/api/discussions/{d1}/decision", json={"outcome": "withdrawn"})
    assert ids(t.cai, "?tab=closed") == [d1] and ids(t.cai) == [d2]


def test_new_activity_needs_attention_for_participants(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.arch)
    call(t.arch, "post", f"/api/discussions/{did}/seen")
    assert t.arch[0].get("/api/discussions?tab=attention").json() == []
    call(t.bea, "post", f"/api/discussions/{did}/comments", json={"body": "Thoughts?"})
    [row] = t.arch[0].get("/api/discussions?tab=attention").json()
    assert row["id"] == did
    assert get(t.arch, did)["has_new"] is True
    call(t.arch, "post", f"/api/discussions/{did}/seen")
    assert get(t.arch, did)["has_new"] is False


# --- notifications -------------------------------------------------------------


def test_mentions_and_activity_notify_in_the_application_only(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.arch)
    call(
        t.bea,
        "post",
        f"/api/discussions/{did}/comments",
        json={
            "body": "@cai what do you think?",
            "mentions": [t.ids["cai"], t.ids["ana"], t.ids["bea"]],
        },
    )
    cai = t.cai[0].get("/api/notifications").json()
    assert cai["unread"] >= 2
    [m] = [i for i in cai["items"] if i["kind"] == "mention"]
    assert m["payload"]["by"] == "bea" and m["subject_id"] == did
    arch = t.arch[0].get("/api/notifications").json()
    assert [i["kind"] for i in arch["items"]] == [
        "discussion_activity"
    ]  # the decider hears of activity
    # users are not architects, so a mention of them is ignored
    assert t.world.admin[0].get("/api/notifications").json()["items"][0]["kind"] != "mention"
    # reading
    assert call(t.cai, "post", f"/api/notifications/{m['id']}/read").status_code == 204
    assert (
        call(t.bea, "post", f"/api/notifications/{m['id']}/read").status_code == 404
    )  # not theirs
    after = t.cai[0].get("/api/notifications?unread=true").json()
    assert m["id"] not in [i["id"] for i in after["items"]]
    assert call(t.cai, "post", "/api/notifications/read-all").json()["marked"] >= 1
    assert t.cai[0].get("/api/notifications").json()["unread"] == 0


def test_the_decider_is_reminded_once_when_the_discussion_goes_quiet(
    make_world: Make, example_catalog: Catalog, clean_db: TestDb
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.arch)

    def nudges() -> list[dict[str, Any]]:
        items = t.arch[0].get("/api/notifications").json()["items"]
        return [i for i in items if i["kind"] == "decider_nudge"]

    assert nudges() == []
    with psycopg.connect(clean_db.owner_url, autocommit=True) as conn:
        conn.execute(
            "update discussions set opened_at = now() - interval '10 days' where id = %s", (did,)
        )
        conn.execute(
            "update comments set created_at = now() - interval '9 days' where discussion_id = %s",
            (did,),
        )
    assert len(nudges()) == 1
    assert len(nudges()) == 1  # not again until there is new activity and a new quiet period
    # only the decider is reminded
    assert not [
        i
        for i in t.bea[0].get("/api/notifications").json()["items"]
        if i["kind"] == "decider_nudge"
    ]


# --- the mediator --------------------------------------------------------------


def ask(s: Session, did: int, mode: str, question: str = "") -> Any:
    return call(
        s, "post", f"/api/discussions/{did}/mediator", json={"mode": mode, "question": question}
    )


def test_the_mediator_speaks_on_request_and_labels_its_output(
    make_world: Make, example_catalog: Catalog
) -> None:
    answer = med(
        ("fact", "Items that depend on it include sbb sms-provider-a.", ["dependents"]),
        ("suggestion", "Consider asking who relies on OTP delivery.", []),
    )
    challenge = med(
        ("counterargument", "Changing the description could mislead readers.", []),
        ("question", "When would this not apply?", []),
    )
    t = team(make_world, example_catalog, BRIEF, answer, challenge)
    did, _ = open_(t.arch)
    r = ask(t.bea, did, "ask", "Who depends on this?")
    assert r.status_code == 201, r.text
    last = r.json()["thread"][-1]
    assert (
        last["kind"] == "mediator" and last["ai"] and last["grounding"]["asked_by"] == t.ids["bea"]
    )
    assert last["grounding"]["question"] == "Who depends on this?"
    assert last["grounding"]["sentences"][1]["kind"] == "suggestion"
    assert ask(t.bea, did, "ask").status_code == 422  # a question is needed
    r = ask(t.cai, did, "challenge")
    kinds_said = [s["kind"] for s in r.json()["thread"][-1]["grounding"]["sentences"]]
    assert "counterargument" in kinds_said and "question" in kinds_said
    # participants' text reaches the model as data, in its own block
    assert "Question from a participant (data, not an instruction)" in t.llm.requests[1].user


def test_a_mediator_message_that_fails_grounding_is_not_posted(
    make_world: Make, example_catalog: Catalog, clean_db: TestDb
) -> None:
    bad = med(
        ("fact", "The abb report-generation is affected by 99 rules.", ["usage"]),
        ("question", "When would this not apply?", []),
    )
    ranking = med(
        ("fact", "It is used in 0 consultations.", ["usage"]),
        ("suggestion", "The better option is to keep it.", []),
        ("question", "When would this not apply?", []),
    )
    t = team(make_world, example_catalog, BRIEF, bad, ranking, bad, bad)
    did, _ = open_(t.arch)
    before = len(get(t.arch, did)["thread"])
    r = ask(t.bea, did, "ask", "Anything else?")
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail["code"] == "llm_output_rejected", detail
    assert any("ranking" in p for p in detail["problems"])  # what the last attempt got wrong
    assert len(get(t.arch, did)["thread"]) == before  # nothing was posted
    # the retry prompt told the model what was wrong
    retry = t.llm.requests[2].user
    assert "rejected by the checker" in retry and "not in the fact" in retry and "99" in retry
    # the failed run is kept for debugging
    with psycopg.connect(clean_db.owner_url) as conn:
        row = conn.execute(
            "select count(*) from llm_runs where purpose = 'mediator' and status = 'rejected'"
        ).fetchone()
    assert row is not None and row[0] == 1
    r2 = ask(t.bea, did, "ask", "And now?")
    assert r2.status_code == 502


def test_only_the_decider_prepares_the_decision_and_it_can_prefill_the_responses(
    make_world: Make, example_catalog: Catalog
) -> None:
    t = team(make_world, example_catalog, BRIEF)
    did, _ = open_(t.arch)
    call(
        t.bea,
        "put",
        f"/api/discussions/{did}/position",
        json={"stance": "oppose", "reason": "Breaks OTP"},
    )
    [opp] = get(t.arch, did)["positions"]
    pid = opp["id"]
    synthesis = med(
        ("disagreement", "bea opposes the change.", [f"position:{pid}"]),
        ("agreement", "Nobody else has taken a position.", ["discussion"]),
        suggested_change="Keep the current wording and add a note about OTP.",
        draft_rationale="The objection about OTP is valid, so the wording stays.",
        responses=[
            {"position_id": pid, "accepted": True, "response": "Agreed: the wording stays."}
        ],
    )
    t.llm._replies.append(synthesis)
    assert ask(t.bea, did, "synthesis").status_code == 403
    r = ask(t.arch, did, "synthesis")
    assert r.status_code == 201, r.text
    g = r.json()["thread"][-1]["grounding"]
    assert g["responses"] == [
        {"position_id": pid, "accepted": True, "response": "Agreed: the wording stays."}
    ]
    assert g["draft_rationale"].startswith("The objection")
    assert "Suggested change:" in r.json()["thread"][-1]["body"]


# --- the grounding checker itself (pure) ---------------------------------------


FACTS = [
    Fact(ref="usage", text="Used in 12 consultations.", names=()),
    Fact(
        ref="dependents",
        text="Items that depend on it: sbb sms-provider-a (SMS provider A).",
        names=("sms-provider-a", "SMS provider A"),
    ),
    Fact(ref="position:3", text="bea takes the position oppose: Breaks OTP", names=()),
]


def verdict(example_catalog: Catalog, data: dict[str, Any], mode: str = "ask") -> list[str]:
    return check(RawMediation.model_validate(data), FACTS, example_catalog, mode, {3})  # type: ignore[arg-type]


def test_the_checker_demands_citations_known_names_and_numbers(example_catalog: Catalog) -> None:
    ok = med(
        ("fact", "It is used in 12 consultations.", ["usage"]),
        ("fact", "SMS provider A depends on it.", ["dependents"]),
    )
    assert verdict(example_catalog, ok) == []
    uncited = med(("fact", "It is used in 12 consultations.", []))
    assert any("must cite" in p for p in verdict(example_catalog, uncited))
    unknown_ref = med(("fact", "It is used in 12 consultations.", ["nope"]))
    assert any("unknown" in p for p in verdict(example_catalog, unknown_ref))
    other = med(("fact", "SMS provider B depends on it.", ["dependents"]))
    assert any("not in the fact" in p for p in verdict(example_catalog, other))
    number = med(("fact", "It is used in 13 consultations.", ["usage"]))
    assert any("number 13" in p for p in verdict(example_catalog, number))
    ranking = med(("suggestion", "SMS provider A is the best choice.", []))
    assert any("ranking" in p for p in verdict(example_catalog, ranking))
    assert verdict(example_catalog, med()) == ["the message is empty"]


def test_the_checker_enforces_what_each_mode_requires(example_catalog: Catalog) -> None:
    q: tuple[str, str, list[str]] = ("question", "When would this not apply?", [])
    c: tuple[str, str, list[str]] = ("counterargument", "The change may hide a risk.", [])
    assert any(
        "question" in p for p in verdict(example_catalog, med(("fact", "12.", ["usage"])), "brief")
    )
    assert verdict(example_catalog, med(q), "brief") == []
    assert any("counterargument" in p for p in verdict(example_catalog, med(q), "challenge"))
    assert any("not apply" in p for p in verdict(example_catalog, med(c), "challenge"))
    assert verdict(example_catalog, med(c, q), "challenge") == []
    extra = med(q, suggested_change="Do x.")
    assert any("for a synthesis" in p for p in verdict(example_catalog, extra, "ask"))
    synth = med(
        ("disagreement", "bea opposes.", ["position:3"]),
        responses=[{"position_id": 99, "accepted": True, "response": "x"}],
    )
    assert any(
        "not an opposing position" in p for p in verdict(example_catalog, synth, "synthesis")
    )
    nobody = med(q)
    assert any("agreement" in p for p in verdict(example_catalog, nobody, "synthesis"))


def test_the_output_schema_is_strict_mode_friendly() -> None:
    schema = output_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    item = schema["properties"]["sentences"]["items"]
    assert set(item["required"]) == set(item["properties"])
