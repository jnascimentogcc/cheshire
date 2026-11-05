"""Consultations end to end: scripted LLM + real PostgreSQL + HTTP API."""

from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from cheshire.api import create_app
from cheshire.auth import service
from cheshire.catalog.models import Catalog
from cheshire.catalog.transfer import dump_document
from cheshire.evaluation import evaluate_scenarios
from cheshire.providers.base import LLMError, LLMUnavailable
from cheshire.providers.fake import ScriptedLLM
from cheshire.settings import Settings
from tests.conftest import ROOT, TestDb
from tests.helpers import all_scenarios, perfect_llm, raw_interpretation

PASSWORD = "correct horse battery"
REQ = "When an order is shipped, the customer must receive a notification by e-mail and SMS."

Headers = dict[str, str]
Session = tuple[TestClient, Headers]


@pytest.fixture
def settings(clean_db: TestDb) -> Settings:
    return Settings(
        database_url=clean_db.app_url,
        cookie_secure=False,
        llm_interpreter_model="interp-model",
        llm_writer_model="writer-model",
    )


class World:
    """Builds clients (admin, architect, users) for one app instance."""

    def __init__(self, settings: Settings, llm: ScriptedLLM | None) -> None:
        self.settings, self.llm = settings, llm
        self.clients: list[TestClient] = []
        with psycopg.connect(settings.database_url) as conn:
            service.create_admin(conn, settings, "admin@example.org", "Admin", PASSWORD)
        self.admin = self.login("admin@example.org")

    def new_client(self) -> TestClient:
        client = TestClient(create_app(self.settings, self.llm))
        client.__enter__()
        self.clients.append(client)
        return client

    def login(self, email: str) -> Session:
        client = self.new_client()
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return client, {"x-csrf-token": r.json()["csrf_token"]}

    def add_user(self, email: str, role: str) -> Session:
        admin, headers = self.admin
        token = admin.post(
            "/api/users/invitations", json={"email": email, "role": role}, headers=headers
        ).json()["token"]
        accepted = self.new_client().post(
            "/api/auth/accept-invitation",
            json={"token": token, "display_name": email.split("@")[0], "password": PASSWORD},
        )
        assert accepted.status_code == 201
        return self.login(email)

    def close(self) -> None:
        for c in self.clients:
            c.__exit__(None, None, None)


@pytest.fixture
def make_world(settings: Settings) -> Iterator[Callable[[ScriptedLLM | None], World]]:
    worlds: list[World] = []

    def factory(llm: ScriptedLLM | None) -> World:
        world = World(settings, llm)
        worlds.append(world)
        return world

    yield factory
    for w in worlds:
        w.close()


def load_catalog(world: World, example_catalog: Catalog) -> Session:
    arch = world.add_user("arch@example.org", "architect")
    client, headers = arch
    r = client.post(
        "/api/catalog/import",
        json={"content": dump_document(example_catalog, "yaml"), "dry_run": False},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return arch


def scripted(*replies: Any) -> ScriptedLLM:
    return ScriptedLLM(*replies)


def scenario_reply(scenario_id: str) -> dict[str, Any]:
    s = next(s for s in all_scenarios() if s.id == scenario_id)
    return raw_interpretation(s.interpreter_output)


# ---------------------------------------------------------------------------------------


def test_requires_login(make_world: Callable[..., World]) -> None:
    world = make_world(scripted())
    anon = world.new_client()
    assert anon.get("/api/consultations").status_code == 401
    assert anon.post("/api/consultations", json={"requirement": REQ}).status_code == 401


def test_analyze_stores_everything_and_shows_the_result(
    make_world: Callable[..., World], example_catalog: Catalog, settings: Settings
) -> None:
    llm = scripted(scenario_reply("notify-shipped-order"))
    world = make_world(llm)
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")

    r = user.post("/api/consultations", json={"requirement": REQ}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["revision"]["requirement_text"] == REQ and not body["revision"]["unrecognised"]
    assert body["facts"]["personal_data"]["source"] == "inferred"
    assert {a["id"] for a in body["identified_abbs"]} == {
        "notification-orchestration", "channel-email", "channel-sms"
    }  # fmt: skip
    result = body["evaluation"]["result"]
    sms = next(a for a in result["abbs"] if a["id"] == "channel-sms")
    assert sms["coverage"] == "conditional"
    assert [q["attribute"] for q in result["pending_questions"]] == ["message_type", "volume"]
    assert body["rationale"] is None  # generated on request here; automatic streaming is M4
    assert any(e["ref"] == "abb:channel-sms" for e in body["evaluation"]["trace"])

    with psycopg.connect(settings.database_url) as conn:
        run = conn.execute(
            "select purpose, provider, model, status, attempts, prompt_version from llm_runs"
        ).fetchall()
        assert run == [("interpreter", "scripted", "interp-model", "ok", 1, "interpreter-1")]
        assert conn.execute("select count(*) from consultation_facts").fetchone() == (2,)
        assert conn.execute("select count(*) from evaluations").fetchone() == (1,)
        gaps = conn.execute(
            "select count(*) from evaluation_item_uses where role = 'abb' and outcome = 'gap'"
        ).fetchone()
        assert gaps == (
            5,
        )  # failure-handling, event-messaging, template, delivery-log, channel-abstraction


def test_answers_update_the_result_and_are_append_only(
    make_world: Callable[..., World], example_catalog: Catalog, settings: Settings
) -> None:
    world = make_world(scripted(scenario_reply("notify-shipped-order")))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    cid = user.post("/api/consultations", json={"requirement": REQ}, headers=headers).json()["id"]

    r = user.post(
        f"/api/consultations/{cid}/answers",
        json={"attribute": "message_type", "value": "transactional"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    r = user.post(
        f"/api/consultations/{cid}/answers",
        json={"attribute": "volume", "value": "medium"},
        headers=headers,
    ).json()
    result = r["evaluation"]["result"]
    assert result["pending_questions"] == []
    sms = next(a for a in result["abbs"] if a["id"] == "channel-sms")
    assert [s["id"] for s in sms["sbbs"] if s["result"] == "eligible"] == ["sms-provider-a"]
    assert r["facts"]["volume"]["source"] == "answered"

    # changing the answer adds a fact; the first one is still there
    user.post(
        f"/api/consultations/{cid}/answers",
        json={"attribute": "volume", "value": "high"},
        headers=headers,
    )
    with psycopg.connect(settings.database_url) as conn:
        assert conn.execute(
            "select count(*) from consultation_facts f join catalog_items i on "
            "i.id = f.attribute_item_id where i.slug = 'volume'"
        ).fetchone() == (2,)
        assert conn.execute("select count(*) from evaluations").fetchone() == (4,)
    with psycopg.connect(settings.database_url, autocommit=True) as auto:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            auto.execute("update consultation_facts set source = 'stated'")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            auto.execute("delete from evaluations")


def test_unknown_is_a_valid_answer_and_stays_unknown(
    make_world: Callable[..., World], example_catalog: Catalog
) -> None:
    world = make_world(scripted(scenario_reply("notify-shipped-order")))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    cid = user.post("/api/consultations", json={"requirement": REQ}, headers=headers).json()["id"]
    r = user.post(
        f"/api/consultations/{cid}/answers",
        json={"attribute": "volume", "value": "unknown"},
        headers=headers,
    ).json()
    assert r["answered_unknown"] == ["volume"] and "volume" not in r["facts"]
    assert "volume" in [q["attribute"] for q in r["evaluation"]["result"]["pending_questions"]]


def test_invalid_answers_are_rejected(
    make_world: Callable[..., World], example_catalog: Catalog
) -> None:
    world = make_world(scripted(scenario_reply("notify-shipped-order")))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    cid = user.post("/api/consultations", json={"requirement": REQ}, headers=headers).json()["id"]
    for body in (
        {"attribute": "volume", "value": "gigantic"},
        {"attribute": "nonexistent", "value": "low"},
        {"attribute": "volume", "value": ["low", "high"]},
    ):
        r = user.post(f"/api/consultations/{cid}/answers", json=body, headers=headers)
        assert r.status_code == 422, body


def test_same_inputs_reuse_the_evaluation(
    make_world: Callable[..., World], example_catalog: Catalog, settings: Settings
) -> None:
    world = make_world(scripted(scenario_reply("notify-shipped-order")))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    cid = user.post("/api/consultations", json={"requirement": REQ}, headers=headers).json()["id"]
    answer = {"attribute": "volume", "value": "medium"}
    user.post(f"/api/consultations/{cid}/answers", json=answer, headers=headers)
    before = _count(settings, "evaluations")
    user.post(f"/api/consultations/{cid}/answers", json=answer, headers=headers)
    assert _count(settings, "evaluations") == before  # nothing changed, nothing new to store


def _count(settings: Settings, table: str) -> int:
    with psycopg.connect(settings.database_url) as conn:
        row = conn.execute(f"select count(*) from {table}").fetchone()
    assert row is not None
    return int(row[0])


def test_edit_fact_marks_it_edited_and_abbs_can_be_added_and_removed(
    make_world: Callable[..., World], example_catalog: Catalog
) -> None:
    world = make_world(scripted(scenario_reply("notify-shipped-order")))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    cid = user.post("/api/consultations", json={"requirement": REQ}, headers=headers).json()["id"]

    r = user.put(
        f"/api/consultations/{cid}/facts/personal_data",
        json={"value": "sensitive"},
        headers=headers,
    ).json()
    assert r["facts"]["personal_data"]["source"] == "edited"

    removed = user.delete(f"/api/consultations/{cid}/abbs/channel-email", headers=headers).json()
    assert "channel-email" not in {a["id"] for a in removed["identified_abbs"]}
    assert all(a["id"] != "channel-email" for a in removed["evaluation"]["result"]["abbs"])

    # an ABB activated by a rule cannot be removed here
    assert (
        user.delete(
            f"/api/consultations/{cid}/abbs/secrets-management", headers=headers
        ).status_code
        == 422
    )
    added = user.post(f"/api/consultations/{cid}/abbs", json={"abb": "audit-log"}, headers=headers)
    assert added.status_code == 200
    assert "audit-log" in {a["id"] for a in added.json()["identified_abbs"]}
    assert (
        user.post(
            f"/api/consultations/{cid}/abbs", json={"abb": "nope"}, headers=headers
        ).status_code
        == 422
    )


def test_visibility_owner_and_architects_only(
    make_world: Callable[..., World], example_catalog: Catalog
) -> None:
    world = make_world(scripted(scenario_reply("notify-shipped-order")))
    arch, _ = load_catalog(world, example_catalog)
    ana, ah = world.add_user("ana@example.org", "user")
    bob, bh = world.add_user("bob@example.org", "user")
    cid = ana.post("/api/consultations", json={"requirement": REQ}, headers=ah).json()["id"]

    assert bob.get(f"/api/consultations/{cid}").status_code == 404
    assert (
        bob.post(
            f"/api/consultations/{cid}/answers",
            json={"attribute": "volume", "value": "low"},
            headers=bh,
        ).status_code
        == 404
    )
    assert bob.get("/api/consultations").json() == []
    assert arch.get(f"/api/consultations/{cid}").status_code == 200
    assert [c["id"] for c in arch.get("/api/consultations").json()] == [cid]
    assert [c["id"] for c in ana.get("/api/consultations").json()] == [cid]


def test_new_revision_keeps_the_old_ones(
    make_world: Callable[..., World], example_catalog: Catalog
) -> None:
    world = make_world(
        scripted(scenario_reply("notify-shipped-order"), scenario_reply("partner-report-export"))
    )
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    cid = user.post("/api/consultations", json={"requirement": REQ}, headers=headers).json()["id"]
    r = user.post(
        f"/api/consultations/{cid}/revisions",
        json={"requirement": "Export monthly reports to an external partner."},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["revision"]["number"] == 2 and [x["number"] for x in body["revisions"]] == [1, 2]
    assert "report-generation" in {a["id"] for a in body["identified_abbs"]}
    assert "channel-sms" not in {a["id"] for a in body["identified_abbs"]}  # facts are per revision


# --- failures ----------------------------------------------------------------------------


def test_provider_failure_keeps_the_text_and_the_failed_run(
    make_world: Callable[..., World], example_catalog: Catalog, settings: Settings
) -> None:
    world = make_world(scripted(LLMUnavailable("timeout"), scenario_reply("notify-shipped-order")))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")

    r = user.post("/api/consultations", json={"requirement": REQ}, headers=headers)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "llm_unavailable"
    listed = user.get("/api/consultations").json()
    assert len(listed) == 1  # the consultation and its text survived
    cid = listed[0]["id"]
    assert user.get(f"/api/consultations/{cid}").json()["revision"]["requirement_text"] == REQ
    with psycopg.connect(settings.database_url) as conn:
        assert conn.execute("select status, error from llm_runs").fetchall() == [
            ("error", "timeout")
        ]

    # "Try again" works on the same consultation
    again = user.post(f"/api/consultations/{cid}/analyze", headers=headers)
    assert again.status_code == 200 and again.json()["evaluation"] is not None


def test_rejected_interpretation_is_reported_with_problems(
    make_world: Callable[..., World], example_catalog: Catalog, settings: Settings
) -> None:
    bad = {"abbs": [{"id": "invented-abb", "span": "SMS"}], "attributes": []}
    world = make_world(scripted(bad, bad))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    r = user.post("/api/consultations", json={"requirement": REQ}, headers=headers)
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail["code"] == "llm_output_rejected" and "invented-abb" in str(detail["problems"])
    with psycopg.connect(settings.database_url) as conn:
        row = conn.execute("select status, attempts from llm_runs").fetchone()
    assert row == ("rejected", 2)
    assert _count(settings, "consultation_abb_events") == 0  # nothing invented was stored


def test_unrecognised_requirement_is_flagged_for_the_architects(
    make_world: Callable[..., World], example_catalog: Catalog, settings: Settings
) -> None:
    world = make_world(scripted({"abbs": [], "attributes": []}))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    r = user.post(
        "/api/consultations", json={"requirement": "Make coffee."}, headers=headers
    ).json()
    assert r["revision"]["unrecognised"] is True and r["evaluation"] is None
    with psycopg.connect(settings.database_url) as conn:
        assert conn.execute(
            "select requirement_text from consultation_revisions where unrecognised"
        ).fetchall() == [("Make coffee.",)]


def test_empty_catalog_and_missing_llm_configuration(
    make_world: Callable[..., World], settings: Settings
) -> None:
    world = make_world(scripted())
    user, headers = world.add_user("ana@example.org", "user")
    r = user.post("/api/consultations", json={"requirement": REQ}, headers=headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "empty_catalog"

    no_models = Settings(database_url=settings.database_url, cookie_secure=False)
    with TestClient(create_app(no_models, ScriptedLLM())) as client:
        login = client.post(
            "/api/auth/login", json={"email": "ana@example.org", "password": PASSWORD}
        )
        h = {"x-csrf-token": login.json()["csrf_token"]}
        r = client.post("/api/consultations", json={"requirement": REQ}, headers=h)
        # empty catalog is checked before the models
        assert r.status_code == 409


def test_llm_not_configured_is_a_clear_error(
    make_world: Callable[..., World], example_catalog: Catalog, settings: Settings
) -> None:
    world = make_world(scripted())
    load_catalog(world, example_catalog)
    world.add_user("ana@example.org", "user")
    no_models = Settings(database_url=settings.database_url, cookie_secure=False)
    with TestClient(create_app(no_models, ScriptedLLM())) as client:
        login = client.post(
            "/api/auth/login", json={"email": "ana@example.org", "password": PASSWORD}
        )
        h = {"x-csrf-token": login.json()["csrf_token"]}
        r = client.post("/api/consultations", json={"requirement": REQ}, headers=h)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "llm_not_configured"
    # no key at all (default factory)
    with TestClient(create_app(Settings(database_url=settings.database_url, cookie_secure=False,
                                        llm_interpreter_model="m"))) as client:  # fmt: skip
        login = client.post(
            "/api/auth/login", json={"email": "ana@example.org", "password": PASSWORD}
        )
        h = {"x-csrf-token": login.json()["csrf_token"]}
        r = client.post("/api/consultations", json={"requirement": REQ}, headers=h)
        assert r.status_code == 503


# --- rationale ---------------------------------------------------------------------------

SENTENCES = {
    "sentences": [
        {"text": "Channel: SMS is covered conditionally.", "refs": ["abb:channel-sms"]},
        {"text": "The volume question could change it.", "refs": ["question:volume"]},
    ]
}


def test_rationale_is_stored_checked_and_marked_outdated(
    make_world: Callable[..., World], example_catalog: Catalog, settings: Settings
) -> None:
    world = make_world(scripted(scenario_reply("notify-shipped-order"), SENTENCES))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    cid = user.post("/api/consultations", json={"requirement": REQ}, headers=headers).json()["id"]

    r = user.post(
        f"/api/consultations/{cid}/rationale", json={"detail": "detailed"}, headers=headers
    )
    assert r.status_code == 200, r.text
    rationale = r.json()["rationale"]
    assert rationale["status"] == "ok" and rationale["outdated"] is False
    assert rationale["content"]["detail"] == "detailed"
    assert [s["verified"] for s in rationale["content"]["sentences"]] == [True, True]

    # answering changes the evaluation, so the explanation is now outdated (and still shown)
    after = user.post(
        f"/api/consultations/{cid}/answers",
        json={"attribute": "volume", "value": "medium"},
        headers=headers,
    ).json()
    assert after["rationale"]["outdated"] is True
    with psycopg.connect(settings.database_url) as conn:
        assert conn.execute(
            "select purpose, model, prompt_version from llm_runs order by id"
        ).fetchall() == [
            ("interpreter", "interp-model", "interpreter-1"),
            ("writer", "writer-model", "writer-1"),
        ]


def test_rationale_checker_warnings_are_stored_not_hidden(
    make_world: Callable[..., World], example_catalog: Catalog
) -> None:
    extra = {"text": "Use sftp-gateway instead.", "refs": ["abb:channel-sms"]}
    mixed = {"sentences": [*SENTENCES["sentences"], extra]}
    world = make_world(scripted(scenario_reply("notify-shipped-order"), mixed, mixed))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    cid = user.post("/api/consultations", json={"requirement": REQ}, headers=headers).json()["id"]
    r = user.post(f"/api/consultations/{cid}/rationale", json={}, headers=headers).json()[
        "rationale"
    ]
    assert r["status"] == "warnings" and r["checker"]["unverified"] == 1
    assert [s["verified"] for s in r["content"]["sentences"]] == [True, True, False]


def test_rationale_failure_does_not_break_the_page(
    make_world: Callable[..., World], example_catalog: Catalog, settings: Settings
) -> None:
    world = make_world(scripted(scenario_reply("notify-shipped-order"), LLMError("boom")))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    cid = user.post("/api/consultations", json={"requirement": REQ}, headers=headers).json()["id"]
    r = user.post(f"/api/consultations/{cid}/rationale", json={}, headers=headers)
    assert r.status_code == 502
    page = user.get(f"/api/consultations/{cid}").json()
    assert page["evaluation"] is not None and page["rationale"] is None
    with psycopg.connect(settings.database_url) as conn:
        assert ("writer", "error") in conn.execute(
            "select purpose, status from llm_runs"
        ).fetchall()


def test_rationale_needs_an_evaluation(
    make_world: Callable[..., World], example_catalog: Catalog
) -> None:
    world = make_world(scripted({"abbs": [], "attributes": []}))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    cid = user.post(
        "/api/consultations", json={"requirement": "Make coffee."}, headers=headers
    ).json()["id"]
    r = user.post(f"/api/consultations/{cid}/rationale", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "nothing_to_explain"


def test_rationale_uses_the_catalog_of_the_evaluation(
    make_world: Callable[..., World], example_catalog: Catalog
) -> None:
    """If the catalog changes after the analysis, the Writer still sees the old snapshot."""
    seen: list[str] = []

    def writer(request: Any) -> dict[str, Any]:
        seen.append(request.user)
        return SENTENCES

    world = make_world(scripted(scenario_reply("notify-shipped-order"), writer))
    arch, ah = load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    cid = user.post("/api/consultations", json={"requirement": REQ}, headers=headers).json()["id"]

    sms = arch.get("/api/catalog/sbb/sms-provider-a").json()["item"]
    arch.put(
        "/api/catalog/sbb/sms-provider-a?status=validated",
        json={**sms, "when_to_choose": "CHANGED AFTER THE ANALYSIS"},
        headers=ah,
    )
    user.post(f"/api/consultations/{cid}/rationale", json={}, headers=headers)
    assert "CHANGED AFTER THE ANALYSIS" not in seen[0]


# --- schema ------------------------------------------------------------------------------


def test_database_rejects_a_value_of_another_attribute(
    make_world: Callable[..., World], example_catalog: Catalog, settings: Settings
) -> None:
    world = make_world(scripted(scenario_reply("notify-shipped-order")))
    load_catalog(world, example_catalog)
    user, headers = world.add_user("ana@example.org", "user")
    user.post("/api/consultations", json={"requirement": REQ}, headers=headers)
    with psycopg.connect(settings.database_url) as conn:
        fact = conn.execute(
            "select f.id, f.attribute_item_id from consultation_facts f "
            "join catalog_items i on i.id = f.attribute_item_id where i.slug = 'personal_data'"
        ).fetchone()
        other = conn.execute(
            "select av.id from attribute_values av join catalog_items i on "
            "i.id = av.attribute_item_id where i.slug = 'volume' limit 1"
        ).fetchone()
        assert fact is not None and other is not None
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(
                "insert into fact_values (fact_id, attribute_item_id, value_id)"
                " values (%s, %s, %s)",
                (fact[0], fact[1], other[0]),
            )


# --- evaluation set ----------------------------------------------------------------------


def test_evaluation_set_with_a_perfect_model(example_catalog: Catalog) -> None:
    rows = evaluate_scenarios(
        ScriptedLLM(*([perfect_llm] * 8)), "i", "w", example_catalog, ROOT / "scenarios"
    )
    assert len(rows) == 4
    assert all(r.interpreter_exact and r.writer_status == "ok" for r in rows), rows


def test_evaluation_set_reports_differences(example_catalog: Catalog) -> None:
    def sloppy(request: Any) -> dict[str, Any]:
        out = perfect_llm(request)
        if request.schema_name == "interpretation":
            out["abbs"] = [a for a in out["abbs"] if a["id"] != "channel-sms"]
            for a in out["attributes"]:
                if a["attribute"] == "personal_data":
                    a["values"] = ["sensitive"]
        return out

    rows = evaluate_scenarios(
        ScriptedLLM(*([sloppy] * 8)), "i", "w", example_catalog, ROOT / "scenarios"
    )
    first = next(r for r in rows if r.scenario_id == "notify-shipped-order")
    assert first.missing_abbs == ["channel-sms"]
    assert first.wrong_attributes == ["personal_data: expected personal, got sensitive"]
    assert not first.interpreter_exact
