"""M5 backend: version diffs, Try-it, work queue, usage, impact preview, restore, starter pack."""

from collections.abc import Callable
from typing import Any

import psycopg
import pytest

from cheshire.catalog.models import Catalog, Condition
from cheshire.maintenance.diff import diff_items
from cheshire.maintenance.tryit import TryInputError, try_condition
from cheshire.settings import Settings
from tests.test_consult import (  # noqa: F401 - fixtures
    REQ,
    World,
    load_catalog,
    make_world,
    scenario_reply,
    scripted,
    settings,
)

Make = Callable[..., World]


# --- pure: diff and Try-it ---------------------------------------------------------------


def test_diff_describes_every_change_in_words() -> None:
    before = {"id": "x", "name": "Old", "recognition": ["a", "b"], "when": {"k": ["1"]}}
    after = {"id": "x", "name": "New", "recognition": ["b", "c"], "when": {"k": ["1", "2"]}, "n": 1}
    texts = [c.text for c in diff_items(before, after)]
    assert texts == [
        "name changed from 'Old' to 'New'",
        "recognition: added 'c'; removed 'a'",
        "when.k: added '2'",
        "n added: 1",
    ]
    assert diff_items(after, after) == []


def test_try_it_is_three_valued(example_catalog: Catalog) -> None:
    rule = next(r for r in example_catalog.rules if r.id == "R-001")
    abbs = ["channel-email", "channel-sms"]
    full = try_condition(
        example_catalog,
        rule.when,
        {"personal_data": "personal", "message_type": "marketing"},
        abbs,
    )
    assert full.result is True and full.outcome == "true"
    assert any("personal_data" in line for line in full.text)

    missing = try_condition(example_catalog, rule.when, {"personal_data": "personal"}, abbs)
    assert missing.result is None and missing.outcome == "indeterminate"
    assert missing.unknown_attributes == ["message_type"]

    explicit = try_condition(
        example_catalog,
        rule.when,
        {"personal_data": "personal", "message_type": "unknown"},
        abbs,
    )
    assert explicit.result is None

    wrong = try_condition(
        example_catalog,
        rule.when,
        {"personal_data": "none", "message_type": "marketing"},
        abbs,
    )
    assert wrong.result is False


def test_try_it_rejects_what_the_catalog_does_not_know(example_catalog: Catalog) -> None:
    cond = Condition(attributes={"personal_data": ("personal",)})
    with pytest.raises(TryInputError, match="no value"):
        try_condition(example_catalog, cond, {"personal_data": "enormous"}, [])
    with pytest.raises(TryInputError, match="unknown ABB"):
        try_condition(example_catalog, cond, {}, ["nope"])
    with pytest.raises(TryInputError, match="unknown attribute"):
        try_condition(example_catalog, Condition(attributes={"nope": ("x",)}), {}, [])


# --- API -----------------------------------------------------------------------------------


def start(make_world: Make, example_catalog: Catalog) -> tuple[Any, Any, Any, Any, int, World]:
    """An architect with the example catalog loaded and a user who consulted once."""
    world = make_world(scripted(scenario_reply("notify-shipped-order")))
    arch, ah = load_catalog(world, example_catalog)
    user, uh = world.add_user("ana@example.org", "user")
    cid = user.post("/api/consultations", json={"requirement": REQ}, headers=uh).json()["id"]
    return arch, ah, user, uh, cid, world


def test_users_cannot_read_the_queue_but_can_read_health(
    make_world: Make, example_catalog: Catalog
) -> None:
    _, _, user, _, _, _ = start(make_world, example_catalog)
    assert user.get("/api/catalog/work").status_code == 403
    assert user.get("/api/catalog/health").status_code == 200


def test_health_counts_status_gaps_and_the_queue(
    make_world: Make, example_catalog: Catalog
) -> None:
    arch, _, _, _, _, _ = start(make_world, example_catalog)
    arch.get("/api/catalog/work")  # reading the queue fills it
    h = arch.get("/api/catalog/health").json()
    assert h["items_by_status"]["proposed"] > 0 and h["items_by_status"]["validated"] == 0
    assert "event-messaging" in h["abbs_without_sbb"]
    assert h["queue"]["gap"] >= 1 and h["queue"]["validation_backlog"] > 0
    assert h["empty"] is False


def test_gaps_and_the_backlog_appear_with_how_often(
    make_world: Make, example_catalog: Catalog
) -> None:
    arch, _, _, _, _, _ = start(make_world, example_catalog)
    entries = arch.get("/api/catalog/work").json()
    gaps = {e["subject"]: e for e in entries if e["kind"] == "gap"}
    assert gaps["event-messaging"]["sessions"] == 1
    assert gaps["event-messaging"]["payload"] == {"abb": "event-messaging"}
    assert any(e["kind"] == "validation_backlog" for e in entries)
    filtered = arch.get("/api/catalog/work?kind=gap").json()
    assert filtered and all(e["kind"] == "gap" for e in filtered)
    assert arch.get("/api/catalog/work?kind=nope").status_code == 422


def test_claims_prevent_duplicate_work_and_can_be_renewed(
    make_world: Make, example_catalog: Catalog
) -> None:
    arch, ah, _, _, _, world = start(make_world, example_catalog)
    other, oh = world.add_user("bo@example.org", "architect")
    gap = next(e for e in arch.get("/api/catalog/work?kind=gap").json())
    url = f"/api/catalog/work/{gap['id']}"

    claimed = arch.post(f"{url}/claim", headers=ah)
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["status"] == "claimed" and claimed.json()["claimed_by_me"] is True

    second = other.post(f"{url}/claim", headers=oh)
    assert second.status_code == 409 and "already claimed" in second.text
    assert other.post(f"{url}/renew", headers=oh).status_code == 409
    assert other.post(f"{url}/release", headers=oh).status_code == 409

    assert arch.post(f"{url}/renew", headers=ah).status_code == 200
    released = arch.post(f"{url}/release", headers=ah)
    assert released.json()["status"] == "open" and released.json()["claimed_by"] is None
    assert other.post(f"{url}/claim", headers=oh).status_code == 200


def test_an_expired_claim_returns_to_the_queue(
    make_world: Make, example_catalog: Catalog, settings: Settings
) -> None:
    arch, ah, _, _, _, _ = start(make_world, example_catalog)
    gap = arch.get("/api/catalog/work?kind=gap").json()[0]
    arch.post(f"/api/catalog/work/{gap['id']}/claim", headers=ah)
    soon = arch.get("/api/catalog/work?kind=gap&status=claimed").json()[0]
    assert soon["expiring_soon"] is False  # a fresh 7-day claim

    with psycopg.connect(settings.database_url) as conn:
        conn.execute(
            "update work_items set claim_expires_at = now() + interval '2 hours' where id = %s",
            (gap["id"],),
        )
        conn.commit()
    assert arch.get("/api/catalog/work?kind=gap&status=claimed").json()[0]["expiring_soon"]

    with psycopg.connect(settings.database_url) as conn:
        conn.execute(
            "update work_items set claim_expires_at = now() - interval '1 minute' where id = %s",
            (gap["id"],),
        )
        conn.commit()
    back = next(e for e in arch.get("/api/catalog/work?kind=gap").json() if e["id"] == gap["id"])
    assert back["status"] == "open" and back["claimed_by"] is None


def test_dismissing_needs_a_reason_and_the_entry_stays_away(
    make_world: Make, example_catalog: Catalog
) -> None:
    arch, ah, _, _, _, _ = start(make_world, example_catalog)
    gap = arch.get("/api/catalog/work?kind=gap").json()[0]
    url = f"/api/catalog/work/{gap['id']}/dismiss"
    assert arch.post(url, json={"reason": "  "}, headers=ah).status_code == 422
    done = arch.post(url, json={"reason": "Out of scope for this team"}, headers=ah)
    assert done.json()["status"] == "dismissed"
    assert done.json()["resolution"] == "Out of scope for this team"
    ids = [e["id"] for e in arch.get("/api/catalog/work?kind=gap").json()]
    assert gap["id"] not in ids  # refresh does not resurrect it
    assert arch.post(url, json={"reason": "again"}, headers=ah).status_code == 409
    shown = arch.get("/api/catalog/work?status=dismissed").json()
    assert [e["id"] for e in shown] == [gap["id"]]


def test_a_gap_closes_itself_when_a_solution_exists(
    make_world: Make, example_catalog: Catalog
) -> None:
    arch, ah, _, _, _, _ = start(make_world, example_catalog)
    before = {e["subject"] for e in arch.get("/api/catalog/work?kind=gap").json()}
    assert "event-messaging" in before
    sbb = {
        "id": "broker-x",
        "name": "Broker X",
        "realises": "event-messaging",
        "state": "recommended",
        "characteristics": {},
    }
    r = arch.put("/api/catalog/sbb/broker-x?status=proposed", json=sbb, headers=ah)
    assert r.status_code == 200, r.text
    after = {e["subject"] for e in arch.get("/api/catalog/work?kind=gap").json()}
    assert "event-messaging" not in after
    closed = arch.get("/api/catalog/work?status=done&kind=gap").json()
    assert [e["subject"] for e in closed] == ["event-messaging"]


def test_feedback_unrecognised_and_drafts_reach_the_queue(
    make_world: Make, example_catalog: Catalog
) -> None:
    arch, ah, user, uh, cid, _ = start(make_world, example_catalog)
    user.post(
        f"/api/consultations/{cid}/feedback",
        json={"kind": "missing", "text": "Push is missing", "abb": "channel-sms"},
        headers=uh,
    )
    abb = arch.get("/api/catalog/abb/channel-sms").json()["item"]
    arch.put("/api/catalog/abb/channel-sms?status=draft", json={**abb, "name": "SMS"}, headers=ah)
    entries = arch.get("/api/catalog/work").json()
    feedback = next(e for e in entries if e["kind"] == "feedback")
    assert feedback["payload"]["text"] == "Push is missing"
    assert feedback["payload"]["abb"] == "channel-sms" and feedback["subject"] == "channel-sms"
    draft = next(e for e in entries if e["kind"] == "draft_review")
    assert draft["payload"]["item"] == "channel-sms" and draft["payload"]["version"] == 2
    # moving the draft on removes its entry
    arch.post(
        "/api/catalog/abb/channel-sms/versions/2/status", json={"status": "proposed"}, headers=ah
    )
    assert not [e for e in arch.get("/api/catalog/work").json() if e["kind"] == "draft_review"]


def test_admins_can_assign_work_to_architects_only(
    make_world: Make, example_catalog: Catalog
) -> None:
    arch, _, _, _, _, world = start(make_world, example_catalog)
    admin, adh = world.admin
    gap = arch.get("/api/catalog/work?kind=gap").json()[0]
    url = f"/api/catalog/work/{gap['id']}/assign"
    users = admin.get("/api/users").json()
    architect = next(u["id"] for u in users if u["email"] == "arch@example.org")
    plain = next(u["id"] for u in users if u["email"] == "ana@example.org")
    assert admin.post(url, json={"user_id": plain}, headers=adh).status_code == 422
    done = admin.post(url, json={"user_id": architect}, headers=adh)
    assert done.status_code == 200 and done.json()["claimed_by"] == "arch"
    assert arch.post(url, json={"user_id": architect}, headers={}).status_code in (403, 401)


def test_a_stale_save_is_refused_with_their_version_and_a_diff(
    make_world: Make, example_catalog: Catalog
) -> None:
    arch, ah, _, _, _, world = start(make_world, example_catalog)
    other, oh = world.add_user("bo@example.org", "architect")
    abb = arch.get("/api/catalog/abb/channel-sms").json()["item"]
    # both started from version 1; the other architect saves first
    saved = other.put(
        "/api/catalog/abb/channel-sms?base_version=1",
        json={**abb, "description": "Theirs"},
        headers=oh,
    )
    assert saved.status_code == 200 and saved.json()["version"] == 2
    mine = arch.put(
        "/api/catalog/abb/channel-sms?base_version=1",
        json={**abb, "description": "Mine"},
        headers=ah,
    )
    assert mine.status_code == 409
    detail = mine.json()["detail"]
    assert detail["code"] == "stale" and detail["latest_version"] == 2
    assert detail["latest_item"]["description"] == "Theirs"
    assert [c["path"] for c in detail["changes"]] == ["description"]
    retry = arch.put(
        "/api/catalog/abb/channel-sms?base_version=2",
        json={**abb, "description": "Merged"},
        headers=ah,
    )
    assert retry.status_code == 200 and retry.json()["version"] == 3
    # without base_version nothing changes (API compatibility)
    assert arch.put("/api/catalog/abb/channel-sms", json=abb, headers=ah).status_code == 200


def test_history_diff_and_restore(make_world: Make, example_catalog: Catalog) -> None:
    arch, ah, _, _, _, _ = start(make_world, example_catalog)
    abb = arch.get("/api/catalog/abb/channel-sms").json()["item"]
    arch.put(
        "/api/catalog/abb/channel-sms?change_note=reworded",
        json={**abb, "description": "Texts to phones."},
        headers=ah,
    )
    d = arch.get("/api/catalog/abb/channel-sms/diff?from_version=1&to_version=2").json()
    assert [c["text"] for c in d["changes"]] == [
        "description changed from 'Sending text messages to mobile numbers.' to 'Texts to phones.'"
    ]
    assert (
        arch.get("/api/catalog/abb/channel-sms/diff?from_version=1&to_version=9").status_code == 404
    )

    restored = arch.post("/api/catalog/abb/channel-sms/versions/1/restore", headers=ah)
    assert restored.status_code == 200 and restored.json() == {
        "version": 3,
        "status": "proposed",
        "restored_from": 1,
    }
    item = arch.get("/api/catalog/abb/channel-sms").json()
    assert item["item"]["description"] == "Sending text messages to mobile numbers."
    assert [v["number"] for v in item["versions"]] == [3, 2, 1]
    assert item["versions"][0]["origin"] == "restore"  # history is never rewritten


def test_usage_and_connections(make_world: Make, example_catalog: Catalog) -> None:
    arch, _, user, uh, cid, _ = start(make_world, example_catalog)
    user.post(
        f"/api/consultations/{cid}/feedback",
        json={"kind": "wrong", "text": "Not SMS", "abb": "channel-sms"},
        headers=uh,
    )
    u = arch.get("/api/catalog/abb/channel-sms/usage").json()
    assert (u["consultations"], u["flagged"], u["corrected"]) == (1, 1, 0)
    assert u["last_used"] is not None
    assert arch.get("/api/catalog/abb/channel-email/usage").json()["flagged"] == 0

    c = arch.get("/api/catalog/abb/channel-sms/connections").json()
    assert {"kind": "sbb", "slug": "sms-provider-a", "ref_kind": "realises"} in c["used_by"]
    sbb = arch.get("/api/catalog/sbb/sms-provider-a/connections").json()
    assert {"kind": "abb", "slug": "channel-sms", "ref_kind": "realises"} in sbb["uses"]
    assert arch.get("/api/catalog/abb/nope/usage").status_code == 404


def test_tables_are_alphabetical_with_facts(make_world: Make, example_catalog: Catalog) -> None:
    arch, _, _, _, _, _ = start(make_world, example_catalog)
    rows = arch.get("/api/catalog/abb?detail=true").json()
    assert [r["slug"] for r in rows] == sorted(r["slug"] for r in rows)
    sms = next(r for r in rows if r["slug"] == "channel-sms")
    assert sms["facts"]["name"] == "Channel: SMS" and sms["sbbs"] == 3
    assert sms["consultations"] == 1 and sms["effective_status"] == "proposed"
    sbbs = arch.get("/api/catalog/sbb?detail=true").json()
    assert sbbs[0]["facts"].keys() >= {"name", "realises", "state"}
    # the plain list keeps its old shape
    assert "facts" not in arch.get("/api/catalog/abb").json()[0]


def test_try_it_endpoint(make_world: Make, example_catalog: Catalog) -> None:
    arch, ah, user, uh, _, _ = start(make_world, example_catalog)
    body = {
        "condition": {"personal_data": ["personal"], "message_type": ["marketing"]},
        "attributes": {"personal_data": "personal"},
        "abbs": [],
    }
    r = arch.post("/api/catalog/try", json=body, headers=ah)
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "indeterminate"
    assert r.json()["unknown_attributes"] == ["message_type"]
    ok = arch.post(
        "/api/catalog/try",
        json={**body, "attributes": {"personal_data": "personal", "message_type": "marketing"}},
        headers=ah,
    )
    assert ok.json()["outcome"] == "true" and ok.json()["text"]
    bad = arch.post("/api/catalog/try", json={**body, "attributes": {"x": "y"}}, headers=ah)
    assert bad.status_code == 422
    assert user.post("/api/catalog/try", json=body, headers=uh).status_code == 403


def test_impact_preview_replays_reference_cases(
    make_world: Make, example_catalog: Catalog, settings: Settings
) -> None:
    arch, ah, _, _, cid, _ = start(make_world, example_catalog)
    pinned = arch.put(
        f"/api/consultations/{cid}/pin", json={"title": "Notify on shipping"}, headers=ah
    )
    assert pinned.status_code == 200, pinned.text

    sbb = arch.get("/api/catalog/sbb/sms-provider-c").json()["item"]
    prohibit = {**sbb, "state": "prohibited", "reason_prohibited": "Contract ended."}
    body = {"kind": "sbb", "item": prohibit, "status": "proposed"}
    r = arch.post("/api/catalog/impact", json=body, headers=ah)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["effective_now"] is True
    [case] = out["reference_cases"]
    assert case["title"] == "Notify on shipping" and case["already_differs"] is False
    texts = [d["text"] for d in case["differences"]]
    assert any("sms-provider-c" in t and "excluded" in t for t in texts), texts
    assert {d["label"] for d in case["differences"]} <= {"added", "removed", "changed", "question"}
    # the same consultation is also among the recent ones? No: pinned ones are listed once
    assert out["recent_consultations"] == []

    unchanged = arch.post(
        "/api/catalog/impact", json={"kind": "sbb", "item": sbb, "status": "proposed"}, headers=ah
    ).json()
    assert unchanged["reference_cases"][0]["differences"] == []


def test_impact_preview_for_recent_consultations_and_new_questions(
    make_world: Make, example_catalog: Catalog
) -> None:
    arch, ah, _, _, _, _ = start(make_world, example_catalog)
    # a new SBB for a gap changes the coverage of that ABB for the recent consultation
    sbb = {
        "id": "broker-x",
        "name": "Broker X",
        "realises": "event-messaging",
        "state": "recommended",
    }
    out = arch.post(
        "/api/catalog/impact", json={"kind": "sbb", "item": sbb, "status": "proposed"}, headers=ah
    ).json()
    [recent] = out["recent_consultations"]
    texts = [d["text"] for d in recent["differences"]]
    assert "Coverage of event-messaging would change from gap to covered." in texts
    assert any("broker-x" in t for t in texts)
    assert out["reference_cases"] == [] and out["new_issues"] == []


def test_impact_preview_reports_new_findings_and_effectiveness(
    make_world: Make, example_catalog: Catalog
) -> None:
    arch, ah, _, _, _, _ = start(make_world, example_catalog)
    sbb = arch.get("/api/catalog/sbb/sms-provider-a").json()["item"]
    # validate the current version so a pending change cannot replace it
    arch.post(
        "/api/catalog/sbb/sms-provider-a/versions/1/status",
        json={"status": "validated"},
        headers=ah,
    )

    def preview(status: str, item: dict[str, Any]) -> dict[str, Any]:
        r = arch.post(
            "/api/catalog/impact", json={"kind": "sbb", "item": item, "status": status}, headers=ah
        )
        assert r.status_code == 200, r.text
        out: dict[str, Any] = r.json()
        return out

    assert preview("proposed", sbb)["effective_now"] is False  # a validated version stays effective
    assert preview("validated", sbb)["effective_now"] is True
    assert preview("draft", sbb)["effective_now"] is False
    broken = {**sbb, "realises": "no-such-abb"}
    assert arch.post(
        "/api/catalog/impact",
        json={"kind": "sbb", "item": broken, "status": "proposed"},
        headers=ah,
    ).status_code in (200, 422)
    assert (
        arch.post(
            "/api/catalog/impact",
            json={"kind": "sbb", "item": {"id": "x"}, "status": "proposed"},
            headers=ah,
        ).status_code
        == 422
    )


def test_starter_pack_goes_through_the_normal_import(make_world: Make) -> None:
    world = make_world(scripted())
    arch, ah = world.add_user("arch@example.org", "architect")
    packs = arch.get("/api/catalog/starter-packs").json()
    assert [p["name"] for p in packs] == ["example"] and packs[0]["counts"]["abbs"] > 0
    assert arch.get("/api/catalog/health").json()["empty"] is True

    dry = arch.post("/api/catalog/starter-packs/example/import", json={}, headers=ah).json()
    assert len(dry["created"]["abb"]) == packs[0]["counts"]["abbs"] and not dry["blocking"]
    assert arch.get("/api/catalog/abb").json() == []  # a dry run writes nothing

    applied = arch.post(
        "/api/catalog/starter-packs/example/import", json={"dry_run": False}, headers=ah
    )
    assert applied.status_code == 200, applied.text
    assert {r["effective_status"] for r in arch.get("/api/catalog/abb").json()} == {"proposed"}
    assert arch.get("/api/catalog/health").json()["empty"] is False
    assert (
        arch.post("/api/catalog/starter-packs/nope/import", json={}, headers=ah).status_code == 404
    )
