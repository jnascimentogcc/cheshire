"""M5: the Interviewer agent and guided capture (suggestions, never silent edits)."""

from collections.abc import Callable
from typing import Any

import psycopg
import pytest

from cheshire.agents.interviewer import validate_suggestions
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
ANSWER = (
    "We use Acme SMS for high volume campaigns in the EU, and it must never get sensitive data."
)


@pytest.fixture
def settings(clean_db: TestDb) -> Settings:
    return Settings(
        database_url=clean_db.app_url,
        cookie_secure=False,
        llm_interpreter_model="interp-model",
        llm_writer_model="writer-model",
        llm_interviewer_model="interviewer-model",
    )


def suggestion(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "sbb",
        "quote": "Acme SMS for high volume campaigns",
        "why": "The architect names a provider for high volume SMS.",
        "id": "acme-sms",
        "name": "Acme SMS",
        "realises": "channel-sms",
        "state": "accepted",
        "when": {"attributes": [{"attribute": "volume", "values": ["high"]}], "abb_present": []},
        "not_when": {
            "attributes": [{"attribute": "personal_data", "values": ["sensitive"]}],
            "abb_present": [],
        },
        "reason": "Not cleared for sensitive data.",
    }
    return {**base, **over}


def reply(*suggestions: dict[str, Any], follow_up: str | None = None) -> dict[str, Any]:
    return {"suggestions": list(suggestions), "follow_up": follow_up}


# --- validation (pure) ------------------------------------------------------------------


def test_a_good_suggestion_becomes_a_draft_with_its_source(example_catalog: Catalog) -> None:
    drafts, follow_up, problems = validate_suggestions(
        reply(suggestion(), follow_up="Which regions?"), example_catalog, ANSWER
    )
    assert problems == [] and follow_up == "Which regions?"
    [d] = drafts
    assert d.kind == "sbb" and d.quote == "Acme SMS for high volume campaigns"
    item = d.payload["item"]
    assert item["id"] == "acme-sms" and item["realises"] == "channel-sms"
    assert item["applies_when"] == {"volume": ["high"]}
    assert item["not_applies_when"] == {"personal_data": ["sensitive"]}
    assert "status" not in item  # the status is decided when a human accepts


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"realises": "no-such-abb"}, "unknown ABB"),
        ({"state": "excellent"}, "state"),
        ({"quote": "never said this"}, "does not appear in the answer"),
        ({"id": "sms-provider-a"}, "already exists"),
        ({"id": "Not A Slug"}, "not a valid new id"),
        (
            {
                "when": {
                    "attributes": [{"attribute": "volume", "values": ["huge"]}],
                    "abb_present": [],
                }
            },
            "no value",
        ),
        (
            {"when": {"attributes": [{"attribute": "nope", "values": ["x"]}], "abb_present": []}},
            "unknown attribute",
        ),
    ],
)
def test_suggestions_are_validated_against_the_catalog(
    example_catalog: Catalog, change: dict[str, Any], expected: str
) -> None:
    drafts, _, problems = validate_suggestions(reply(suggestion(**change)), example_catalog, ANSWER)
    assert drafts == [] and any(expected in p for p in problems), problems


def test_attribute_values_and_rules_are_checked_too(example_catalog: Catalog) -> None:
    ok = {"kind": "attribute_value", "quote": "high volume", "why": "w", "attribute": "volume",
          "value": "very-high"}  # fmt: skip
    drafts, _, problems = validate_suggestions(reply(ok), example_catalog, ANSWER)
    assert problems == [] and drafts[0].payload == {"attribute": "volume", "value": "very-high"}
    for bad, text in [
        ({**ok, "value": "high"}, "already has the value"),
        ({**ok, "attribute": "nope"}, "unknown attribute"),
    ]:
        assert text in " ".join(validate_suggestions(reply(bad), example_catalog, ANSWER)[2])
    rule = {"kind": "rule", "quote": "sensitive data", "why": "w", "id": "R-900",
            "activates": "audit-log", "strength": "requires", "reason": "r",
            "when": {"attributes": [{"attribute": "personal_data", "values": ["sensitive"]}],
                     "abb_present": []}}  # fmt: skip
    drafts, _, problems = validate_suggestions(reply(rule), example_catalog, ANSWER)
    assert problems == [], problems
    assert drafts[0].payload["item"]["activates"] == "audit-log"
    twice = validate_suggestions(reply(rule, rule), example_catalog, ANSWER)
    assert any("already exists" in p for p in twice[2])


# --- API ---------------------------------------------------------------------------------


def begin(make_world: Make, example_catalog: Catalog, *replies: Any) -> tuple[Any, Any, World, Any]:
    llm = scripted(*replies)
    world = make_world(llm)
    arch, ah = load_catalog(world, example_catalog)
    return arch, ah, world, llm


def start(arch: Any, ah: Any, subject: str | None = "channel-sms") -> dict[str, Any]:
    r = arch.post("/api/interviews", json={"subject": subject}, headers=ah)
    assert r.status_code == 201, r.text
    view: dict[str, Any] = r.json()
    return view


def test_users_cannot_interview(make_world: Make, example_catalog: Catalog) -> None:
    _, _, world, _ = begin(make_world, example_catalog)
    user, uh = world.add_user("ana@example.org", "user")
    assert user.post("/api/interviews", json={}, headers=uh).status_code == 403
    assert user.get("/api/interviews").status_code == 403


def test_an_interview_starts_with_the_first_lens(
    make_world: Make, example_catalog: Catalog
) -> None:
    arch, ah, _, _ = begin(make_world, example_catalog)
    view = start(arch, ah)
    first = example_catalog.lenses[0]
    [message] = view["messages"]
    assert (message["role"], message["lens"], message["text"]) == (
        "assistant",
        first.id,
        first.question,
    )
    assert view["subject"] == "channel-sms" and view["status"] == "open"
    assert view["progress"] == {"answered": 0, "total": len(example_catalog.lenses) + 1}
    assert arch.post("/api/interviews", json={"subject": "nope"}, headers=ah).status_code == 422
    assert start(arch, ah, None)["subject"] is None


def test_an_answer_produces_suggestions_a_human_accepts(
    make_world: Make, example_catalog: Catalog, settings: Settings
) -> None:
    arch, ah, _, llm = begin(make_world, example_catalog, reply(suggestion()))
    iid = start(arch, ah)["id"]
    r = arch.post(f"/api/interviews/{iid}/answers", json={"text": ANSWER}, headers=ah)
    assert r.status_code == 200, r.text
    view = r.json()
    assert [m["role"] for m in view["messages"]] == ["assistant", "user", "assistant"]
    assert view["messages"][2]["lens"] == example_catalog.lenses[1].id  # on to the next lens
    [s] = view["suggestions"]
    assert s["status"] == "pending" and s["kind"] == "sbb"
    assert s["payload"]["quote"] == "Acme SMS for high volume campaigns"
    # nothing was written to the catalog by suggesting
    assert arch.get("/api/catalog/sbb/acme-sms").status_code == 404
    assert "Focus ABB: channel-sms" in llm.requests[0].user

    accepted = arch.post(
        f"/api/suggestions/{s['id']}/decision", json={"decision": "accept"}, headers=ah
    )
    assert accepted.status_code == 200, accepted.text
    [done] = accepted.json()["suggestions"]
    assert done["status"] == "accepted" and done["decided_by"] == "arch"
    assert (done["resulting_kind"], done["resulting_item"], done["resulting_version"]) == (
        "sbb",
        "acme-sms",
        1,
    )
    item = arch.get("/api/catalog/sbb/acme-sms").json()
    assert item["item"]["status"] == "proposed" and item["versions"][0]["origin"] == "interview"
    again = arch.post(
        f"/api/suggestions/{s['id']}/decision", json={"decision": "accept"}, headers=ah
    )
    assert again.status_code == 409
    with psycopg.connect(settings.database_url) as conn:
        assert conn.execute("select purpose, status, prompt_version from llm_runs").fetchall() == [
            ("interviewer", "ok", "interviewer-1")
        ]
        origin = conn.execute(
            "select origin, origin_ref from item_versions where number = 1 "
            "and kind = 'sbb' and origin = 'interview'"
        ).fetchone()
        assert origin == ("interview", s["id"])  # provenance: the suggestion it came from


def test_rejecting_changes_nothing(make_world: Make, example_catalog: Catalog) -> None:
    arch, ah, _, _ = begin(make_world, example_catalog, reply(suggestion()))
    iid = start(arch, ah)["id"]
    arch.post(f"/api/interviews/{iid}/answers", json={"text": ANSWER}, headers=ah)
    [s] = arch.get(f"/api/interviews/{iid}").json()["suggestions"]
    r = arch.post(f"/api/suggestions/{s['id']}/decision", json={"decision": "reject"}, headers=ah)
    assert r.json()["suggestions"][0]["status"] == "rejected"
    assert arch.get("/api/catalog/sbb/acme-sms").status_code == 404


def test_accepting_an_attribute_value_adds_it_in_a_new_version(
    make_world: Make, example_catalog: Catalog
) -> None:
    value = {"kind": "attribute_value", "quote": "high volume", "why": "w",
             "attribute": "volume", "value": "very-high"}  # fmt: skip
    arch, ah, _, _ = begin(make_world, example_catalog, reply(value))
    iid = start(arch, ah)["id"]
    arch.post(f"/api/interviews/{iid}/answers", json={"text": ANSWER}, headers=ah)
    [s] = arch.get(f"/api/interviews/{iid}").json()["suggestions"]
    r = arch.post(f"/api/suggestions/{s['id']}/decision", json={"decision": "accept"}, headers=ah)
    assert r.status_code == 200, r.text
    attr = arch.get("/api/catalog/attribute/volume").json()
    assert "very-high" in attr["item"]["values"]
    assert [v["number"] for v in attr["versions"]] == [2, 1]
    assert attr["versions"][0]["origin"] == "interview"


def test_an_id_taken_in_the_meantime_cannot_be_accepted(
    make_world: Make, example_catalog: Catalog
) -> None:
    arch, ah, _, _ = begin(make_world, example_catalog, reply(suggestion()))
    iid = start(arch, ah)["id"]
    arch.post(f"/api/interviews/{iid}/answers", json={"text": ANSWER}, headers=ah)
    [s] = arch.get(f"/api/interviews/{iid}").json()["suggestions"]
    taken = {"id": "acme-sms", "name": "Acme", "realises": "channel-sms", "state": "accepted"}
    assert arch.put("/api/catalog/sbb/acme-sms", json=taken, headers=ah).status_code == 200
    r = arch.post(f"/api/suggestions/{s['id']}/decision", json={"decision": "accept"}, headers=ah)
    assert r.status_code == 409 and "already exists" in r.text


def test_not_applicable_skips_the_model(make_world: Make, example_catalog: Catalog) -> None:
    arch, ah, _, llm = begin(make_world, example_catalog)  # no replies: any call would fail
    iid = start(arch, ah)["id"]
    r = arch.post(f"/api/interviews/{iid}/answers", json={"not_applicable": True}, headers=ah)
    assert r.status_code == 200, r.text
    assert llm.requests == [] and r.json()["suggestions"] == []
    assert r.json()["messages"][1]["text"] == "Not applicable."
    empty = arch.post(f"/api/interviews/{iid}/answers", json={"text": "  "}, headers=ah)
    assert empty.status_code == 422


def test_a_provider_failure_keeps_the_answer_and_can_be_retried(
    make_world: Make, example_catalog: Catalog, settings: Settings
) -> None:
    arch, ah, _, _ = begin(
        make_world, example_catalog, LLMUnavailable("timeout"), reply(suggestion())
    )
    iid = start(arch, ah)["id"]
    failed = arch.post(f"/api/interviews/{iid}/answers", json={"text": ANSWER}, headers=ah)
    assert failed.status_code == 502 and failed.json()["detail"]["code"] == "llm_unavailable"
    view = arch.get(f"/api/interviews/{iid}").json()
    assert view["needs_retry"] is True and view["messages"][-1]["text"] == ANSWER
    blocked = arch.post(f"/api/interviews/{iid}/answers", json={"text": "more"}, headers=ah)
    assert blocked.status_code == 409  # one answer at a time

    ok = arch.post(f"/api/interviews/{iid}/retry", headers=ah)
    assert ok.status_code == 200, ok.text
    assert ok.json()["needs_retry"] is False and len(ok.json()["suggestions"]) == 1
    assert arch.post(f"/api/interviews/{iid}/retry", headers=ah).status_code == 409
    with psycopg.connect(settings.database_url) as conn:
        assert conn.execute("select status from llm_runs order by id").fetchall() == [
            ("error",),
            ("ok",),
        ]


def test_invalid_output_is_retried_once_then_refused(
    make_world: Make, example_catalog: Catalog
) -> None:
    bad = reply(suggestion(realises="no-such-abb"))
    arch, ah, _, llm = begin(make_world, example_catalog, bad, reply(suggestion()), bad, bad)
    iid = start(arch, ah)["id"]
    ok = arch.post(f"/api/interviews/{iid}/answers", json={"text": ANSWER}, headers=ah)
    assert ok.status_code == 200 and len(ok.json()["suggestions"]) == 1
    assert "rejected for these reasons" in llm.requests[1].user  # the retry lists the problems

    refused = arch.post(f"/api/interviews/{iid}/answers", json={"text": ANSWER}, headers=ah)
    assert refused.status_code == 502
    assert refused.json()["detail"]["code"] == "llm_output_rejected"
    assert any("unknown ABB" in p for p in refused.json()["detail"]["problems"])


def test_it_depends_asks_for_a_refined_suggestion(
    make_world: Make, example_catalog: Catalog
) -> None:
    refined = suggestion(
        id="acme-sms-eu",
        quote="only inside the EU",
        when={"attributes": [{"attribute": "volume", "values": ["high"]}], "abb_present": []},
    )
    arch, ah, _, llm = begin(make_world, example_catalog, reply(suggestion()), reply(refined))
    iid = start(arch, ah)["id"]
    arch.post(f"/api/interviews/{iid}/answers", json={"text": ANSWER}, headers=ah)
    [s] = arch.get(f"/api/interviews/{iid}").json()["suggestions"]
    url = f"/api/suggestions/{s['id']}/decision"
    assert arch.post(url, json={"decision": "depends"}, headers=ah).status_code == 422

    r = arch.post(url, json={"decision": "depends", "note": "only inside the EU"}, headers=ah)
    assert r.status_code == 200, r.text
    first, second = r.json()["suggestions"]
    assert (first["status"], first["follow_up"]) == ("depends", "only inside the EU")
    assert second["status"] == "pending" and second["payload"]["item"]["id"] == "acme-sms-eu"
    assert "Earlier suggestion" in llm.requests[1].user


def test_all_lenses_then_the_pre_mortem_finish_the_interview(
    make_world: Make, example_catalog: Catalog
) -> None:
    arch, ah, _, _ = begin(make_world, example_catalog)
    iid = start(arch, ah)["id"]
    total = len(example_catalog.lenses) + 1
    for _ in range(total):
        r = arch.post(f"/api/interviews/{iid}/answers", json={"not_applicable": True}, headers=ah)
        assert r.status_code == 200, r.text
    view = r.json()
    assert view["finished"] is True and view["progress"] == {"answered": total, "total": total}
    assert "pre-mortem" not in view["messages"][-2]["text"].lower()
    assert view["messages"][-2]["lens"] is None  # the last question has no lens
    over = arch.post(f"/api/interviews/{iid}/answers", json={"not_applicable": True}, headers=ah)
    assert over.status_code == 409
    closed = arch.post(f"/api/interviews/{iid}/close", headers=ah)
    assert closed.json()["status"] == "closed"
    late = arch.post(f"/api/interviews/{iid}/answers", json={"text": "x"}, headers=ah)
    assert late.status_code == 409
    assert [i["id"] for i in arch.get("/api/interviews").json()] == [iid]
