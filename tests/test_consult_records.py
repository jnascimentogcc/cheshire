"""M4 backend: choices, feedback, reference cases, export, preferences, SSE stream."""

import json
from collections.abc import Callable
from typing import Any

import psycopg
import pytest

from cheshire.catalog.models import Catalog
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

SENTENCES = {
    "sentences": [{"text": "Channel: SMS is covered conditionally.", "refs": ["abb:channel-sms"]}]
}
Make = Callable[..., World]


def start(make_world: Make, example_catalog: Catalog, *extra: Any) -> tuple[Any, Any, int, World]:
    world = make_world(scripted(scenario_reply("notify-shipped-order"), *extra))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    cid = user.post("/api/consultations", json={"requirement": REQ}, headers=headers).json()["id"]
    return user, headers, cid, world


def sbb_results(view: dict[str, Any], abb: str) -> dict[str, tuple[str, str]]:
    found = next(a for a in view["evaluation"]["result"]["abbs"] if a["id"] == abb)
    return {s["id"]: (s["result"], s["state"]) for s in found["sbbs"]}


# --- view ------------------------------------------------------------------------------


def test_view_carries_the_names_the_page_needs(make_world: Make, example_catalog: Catalog) -> None:
    user, _, cid, _ = start(make_world, example_catalog)
    view = user.get(f"/api/consultations/{cid}").json()
    catalog = view["catalog"]
    assert [a["id"] for a in catalog["abbs"]] == sorted(a["id"] for a in catalog["abbs"])
    assert {s["realises"] for s in catalog["sbbs"]} <= {
        a["id"] for a in view["evaluation"]["result"]["abbs"]
    }
    assert {"message_type", "volume"} <= {a["id"] for a in catalog["attributes"]}
    assert view["choices"] == [] and view["feedback"] == [] and view["pinned"] is None


def test_an_earlier_revision_stays_readable(make_world: Make, example_catalog: Catalog) -> None:
    user, headers, cid, _ = start(
        make_world, example_catalog, scenario_reply("notify-shipped-order")
    )
    new_text = REQ + " Also by push."
    r = user.post(
        f"/api/consultations/{cid}/revisions", json={"requirement": new_text}, headers=headers
    )
    assert r.status_code == 201, r.text
    assert r.json()["revision"]["number"] == 2 and r.json()["latest_revision"] == 2

    first = user.get(f"/api/consultations/{cid}?revision=1").json()
    assert first["revision"]["number"] == 1 and first["revision"]["requirement_text"] == REQ
    assert first["latest_revision"] == 2 and first["evaluation"] is not None
    assert user.get(f"/api/consultations/{cid}?revision=9").status_code == 404
    assert user.get(f"/api/consultations/{cid}").json()["revision"]["requirement_text"] == new_text


# --- choices ---------------------------------------------------------------------------


def test_choosing_an_eligible_solution_needs_no_reason(
    make_world: Make, example_catalog: Catalog
) -> None:
    user, headers, cid, _ = start(make_world, example_catalog)
    view = user.get(f"/api/consultations/{cid}").json()
    eligible = [
        (abb["id"], s["id"])
        for abb in view["evaluation"]["result"]["abbs"]
        for s in abb["sbbs"]
        if s["result"] == "eligible" and s["state"] != "deprecating"
    ]
    assert eligible
    abb, sbb = eligible[0]
    r = user.post(
        f"/api/consultations/{cid}/choices",
        json={"abb": abb, "kind": "chosen", "sbb": sbb},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    [choice] = [c for c in r.json()["choices"] if c["abb"] == abb]
    assert (choice["sbb"], choice["sbb_result"], choice["actor"]) == (sbb, "eligible", "ana")


def test_a_conditional_choice_needs_a_reason_and_keeps_the_open_questions(
    make_world: Make, example_catalog: Catalog
) -> None:
    user, headers, cid, _ = start(make_world, example_catalog)
    view = user.get(f"/api/consultations/{cid}").json()
    conditional = next(
        s["id"]
        for a in view["evaluation"]["result"]["abbs"]
        if a["id"] == "channel-sms"
        for s in a["sbbs"]
        if s["result"] == "conditional"
    )
    body = {"abb": "channel-sms", "kind": "chosen", "sbb": conditional}
    url = f"/api/consultations/{cid}/choices"
    refused = user.post(url, json=body, headers=headers)
    assert refused.status_code == 422 and "reason" in refused.text
    ok = user.post(url, json={**body, "reason": "  Contract already signed  "}, headers=headers)
    assert ok.status_code == 201, ok.text
    [choice] = ok.json()["choices"]
    assert choice["reason"] == "Contract already signed"
    assert choice["sbb_result"] == "conditional"
    assert choice["unresolved_questions"]  # the answers that would resolve it


def test_the_latest_choice_is_current_and_history_is_kept(
    make_world: Make, example_catalog: Catalog, settings: Settings
) -> None:
    user, headers, cid, _ = start(make_world, example_catalog)
    url = f"/api/consultations/{cid}/choices"
    user.post(url, json={"abb": "channel-sms", "kind": "decide_later"}, headers=headers)
    r = user.post(
        url, json={"abb": "channel-sms", "kind": "decide_later", "reason": "x"}, headers=headers
    )
    assert [c["kind"] for c in r.json()["choices"]] == ["decide_later"]
    with psycopg.connect(settings.database_url) as conn:
        assert conn.execute("select count(*) from choice_records").fetchone() == (2,)


@pytest.mark.parametrize(
    "body",
    [
        {"abb": "channel-sms", "kind": "chosen"},  # no solution
        {"abb": "channel-sms", "kind": "chosen", "sbb": "no-such-sbb"},
        {"abb": "channel-sms", "kind": "decide_later", "sbb": "sms-provider-a"},
        {"abb": "channel-sms", "kind": "outside_catalog"},  # covered, not a gap
        {"abb": "report-generation", "kind": "decide_later"},  # not in the result
    ],
)
def test_invalid_choices_are_rejected(
    body: dict[str, Any], make_world: Make, example_catalog: Catalog
) -> None:
    user, headers, cid, _ = start(make_world, example_catalog)
    r = user.post(f"/api/consultations/{cid}/choices", json=body, headers=headers)
    assert r.status_code == 422, r.text


def test_excluded_solutions_cannot_be_chosen(make_world: Make, example_catalog: Catalog) -> None:
    user, headers, cid, _ = start(make_world, example_catalog)
    view = user.get(f"/api/consultations/{cid}").json()
    excluded = next(
        (a["id"], s["id"])
        for a in view["evaluation"]["result"]["abbs"]
        for s in a["sbbs"]
        if s["result"] == "excluded"
    )
    r = user.post(
        f"/api/consultations/{cid}/choices",
        json={"abb": excluded[0], "kind": "chosen", "sbb": excluded[1], "reason": "please"},
        headers=headers,
    )
    assert r.status_code == 422 and "excluded" in r.text


def test_a_gap_can_be_handled_outside_the_catalog(
    make_world: Make, example_catalog: Catalog
) -> None:
    user, headers, cid, _ = start(make_world, example_catalog)
    view = user.get(f"/api/consultations/{cid}").json()
    gap = next(a["id"] for a in view["evaluation"]["result"]["abbs"] if a["coverage"] == "gap")
    r = user.post(
        f"/api/consultations/{cid}/choices",
        json={"abb": gap, "kind": "outside_catalog"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["choices"][0]["kind"] == "outside_catalog"


def test_the_database_enforces_the_reason_rule(
    make_world: Make, example_catalog: Catalog, settings: Settings
) -> None:
    """Even a bug in the service cannot store a conditional choice without a reason."""
    _, _, cid, _ = start(make_world, example_catalog)
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        ids = conn.execute(
            "select e.id, e.revision_id, "
            "(select id from catalog_items where slug = 'channel-sms' and kind = 'abb'), "
            "(select id from catalog_items where slug = 'sms-provider-a' and kind = 'sbb'), "
            "(select id from users limit 1) from evaluations e"
        ).fetchone()
        assert ids is not None
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "insert into choice_records (consultation_id, revision_id, evaluation_id,"
                " abb_item_id, kind, sbb_item_id, sbb_kind, sbb_result, sbb_state, reason,"
                " actor_id)"
                " values (%s, %s, %s, %s, 'chosen', %s, 'sbb', 'conditional', 'accepted', '', %s)",
                (cid, ids[1], ids[0], ids[2], ids[3], ids[4]),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("update choice_records set reason = 'x'")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("delete from choice_records")


def test_others_cannot_record_on_my_consultation(
    make_world: Make, example_catalog: Catalog
) -> None:
    _, _, cid, world = start(make_world, example_catalog)
    other, headers = world.add_user("bob@example.org", "user")
    r = other.post(
        f"/api/consultations/{cid}/choices",
        json={"abb": "channel-sms", "kind": "decide_later"},
        headers=headers,
    )
    assert r.status_code == 404


# --- feedback --------------------------------------------------------------------------


def test_feedback_is_stored_for_the_architects(
    make_world: Make, example_catalog: Catalog, settings: Settings
) -> None:
    user, headers, cid, _ = start(make_world, example_catalog)
    url = f"/api/consultations/{cid}/feedback"
    r = user.post(
        url,
        json={"kind": "wrong", "text": "SMS B is allowed for us", "abb": "channel-sms"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    user.post(url, json={"kind": "missing", "text": "Where is push?"}, headers=headers)
    items = user.get(f"/api/consultations/{cid}").json()["feedback"]
    assert [(f["kind"], f["abb"]) for f in items] == [("wrong", "channel-sms"), ("missing", None)]
    assert user.post(url, json={"kind": "wrong", "text": "  "}, headers=headers).status_code == 422
    assert (
        user.post(
            url, json={"kind": "wrong", "text": "x", "abb": "nope"}, headers=headers
        ).status_code
        == 422
    )
    with psycopg.connect(settings.database_url) as conn:
        assert conn.execute("select count(*) from feedback").fetchone() == (2,)


# --- reference cases -------------------------------------------------------------------


def test_only_architects_pin_reference_cases(make_world: Make, example_catalog: Catalog) -> None:
    user, headers, cid, world = start(make_world, example_catalog)
    url = f"/api/consultations/{cid}/pin"
    assert user.put(url, json={"title": "Order shipped"}, headers=headers).status_code == 403

    arch, arch_headers = world.login("arch@example.org")
    pinned = arch.put(url, json={"title": "Order shipped"}, headers=arch_headers)
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["pinned"]["title"] == "Order shipped"
    assert arch.put(url, json={"title": "again"}, headers=arch_headers).status_code == 422

    [case] = arch.get("/api/reference-cases").json()
    assert case["expected"]["abbs"]["channel-sms"]["coverage"] == "conditional"
    assert user.get("/api/reference-cases").status_code == 403

    assert arch.delete(url, headers=arch_headers).json()["pinned"] is None
    assert arch.get("/api/reference-cases").json() == []
    assert arch.delete(url, headers=arch_headers).status_code == 422


# --- export ----------------------------------------------------------------------------


def test_markdown_and_json_export(make_world: Make, example_catalog: Catalog) -> None:
    user, headers, cid, _ = start(make_world, example_catalog, SENTENCES)
    user.post(f"/api/consultations/{cid}/rationale", json={}, headers=headers)
    user.post(
        f"/api/consultations/{cid}/choices",
        json={"abb": "channel-sms", "kind": "decide_later"},
        headers=headers,
    )
    md = user.get(f"/api/consultations/{cid}/export")
    assert md.status_code == 200 and "attachment" in md.headers["content-disposition"]
    text = md.text
    for heading in (
        "## Requirement",
        "## What was understood",
        "## Result",
        "## Rationale",
        "## Choices",
    ):
        assert heading in text
    assert REQ in text and "`abb:channel-sms`" in text and "decides later" in text
    assert "[abb:channel-sms]" not in text  # would render as a Markdown link reference
    assert "- " in text.split("## Rationale")[1].split("## Choices")[0]  # one bullet per sentence
    assert "best" not in text.lower()  # no ranking vocabulary leaks in

    data = json.loads(user.get(f"/api/consultations/{cid}/export?format=json").text)
    assert data["revision"]["requirement_text"] == REQ
    assert data["evaluation"]["result"]["abbs"] and data["choices"][0]["kind"] == "decide_later"
    assert user.get(f"/api/consultations/{cid}/export?format=pdf").status_code == 422


def test_export_lists_solutions_alphabetically(make_world: Make, example_catalog: Catalog) -> None:
    user, _, cid, _ = start(make_world, example_catalog)
    text = user.get(f"/api/consultations/{cid}/export").text
    section = text.split("### Channel: SMS")[1].split("###")[0]
    ids = [line.split("`")[1] for line in section.splitlines() if line.startswith("- **")]
    assert ids == sorted(ids) and len(ids) >= 2


def test_export_is_visible_only_to_those_who_can_see_it(
    make_world: Make, example_catalog: Catalog
) -> None:
    _, _, cid, world = start(make_world, example_catalog)
    other, _ = world.add_user("bob@example.org", "user")
    assert other.get(f"/api/consultations/{cid}/export").status_code == 404


# --- preferences -----------------------------------------------------------------------


def test_preferences_follow_the_user(make_world: Make, example_catalog: Catalog) -> None:
    user, headers, _, world = start(make_world, example_catalog)
    assert user.get("/api/preferences").json() == {
        "detail_level": "summary",
        "locale": "en",
        "theme": "system",
    }
    r = user.put(
        "/api/preferences", json={"detail_level": "detailed", "theme": "dark"}, headers=headers
    )
    assert r.json() == {"detail_level": "detailed", "locale": "en", "theme": "dark"}
    r = user.put("/api/preferences", json={"locale": "pt-BR"}, headers=headers)
    assert r.json() == {"detail_level": "detailed", "locale": "pt-BR", "theme": "dark"}
    again, _ = world.login("ana@example.org")
    assert again.get("/api/preferences").json()["theme"] == "dark"
    assert user.put("/api/preferences", json={"theme": "neon"}, headers=headers).status_code == 422
    assert user.put("/api/preferences", json={"locale": "../x"}, headers=headers).status_code == 422


# --- SSE -------------------------------------------------------------------------------


def events(response: Any) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for block in response.text.strip().split("\n\n"):
        name, data = block.split("\n", 1)
        out.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_stream_reports_stages_then_result_then_the_first_rationale(
    make_world: Make, example_catalog: Catalog, settings: Settings
) -> None:
    world = make_world(scripted(scenario_reply("notify-shipped-order"), SENTENCES))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    r = user.post("/api/consultations/stream", json={"requirement": REQ}, headers=headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    got = events(r)
    names = [n for n, _ in got]
    assert names == [
        "created", "stage", "stage", "stage", "result", "stage", "rationale", "done"
    ]  # fmt: skip
    assert [d["stage"] for n, d in got if n == "stage"] == [
        "interpreting", "checking", "evaluating", "writing"
    ]  # fmt: skip
    result = dict(got)["result"]
    assert result["rationale"] is None and result["evaluation"]["result"]["abbs"]
    final = dict(got)["rationale"]
    assert final["rationale"]["status"] == "ok" and final["id"] == dict(got)["created"]["id"]


def test_stream_keeps_the_page_usable_when_the_explanation_fails(
    make_world: Make, example_catalog: Catalog
) -> None:
    from cheshire.providers.base import LLMUnavailable

    world = make_world(scripted(scenario_reply("notify-shipped-order"), LLMUnavailable("down")))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    got = events(user.post("/api/consultations/stream", json={"requirement": REQ}, headers=headers))
    names = [n for n, _ in got]
    assert "result" in names and "rationale_error" in names and names[-1] == "done"
    assert dict(got)["rationale_error"]["code"] == "llm_unavailable"


def test_stream_error_keeps_the_text_and_allows_retry(
    make_world: Make, example_catalog: Catalog
) -> None:
    from cheshire.providers.base import LLMUnavailable

    world = make_world(
        scripted(LLMUnavailable("down"), scenario_reply("notify-shipped-order"), SENTENCES)
    )
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    got = events(user.post("/api/consultations/stream", json={"requirement": REQ}, headers=headers))
    assert [n for n, _ in got][-1] == "error" and dict(got)["error"]["code"] == "llm_unavailable"
    cid = dict(got)["created"]["id"]
    assert user.get(f"/api/consultations/{cid}").json()["revision"]["requirement_text"] == REQ

    retry = events(user.post(f"/api/consultations/{cid}/analyze/stream", headers=headers))
    assert "result" in [n for n, _ in retry] and "rationale" in [n for n, _ in retry]


def test_stream_does_not_regenerate_an_existing_explanation(
    make_world: Make, example_catalog: Catalog
) -> None:
    user, headers, cid, _ = start(
        make_world, example_catalog, SENTENCES, scenario_reply("notify-shipped-order")
    )
    user.post(f"/api/consultations/{cid}/rationale", json={}, headers=headers)
    got = events(user.post(f"/api/consultations/{cid}/analyze/stream", headers=headers))
    assert "result" in [n for n, _ in got] and "rationale" not in [n for n, _ in got]


def test_stream_requires_login_and_csrf(make_world: Make, example_catalog: Catalog) -> None:
    user, _, _, world = start(make_world, example_catalog)
    assert (
        world.new_client().post("/api/consultations/stream", json={"requirement": REQ}).status_code
        == 401
    )
    assert user.post("/api/consultations/stream", json={"requirement": REQ}).status_code == 403
