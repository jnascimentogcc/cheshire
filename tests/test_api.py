"""HTTP API against a real PostgreSQL: auth, permissions, catalog CRUD, import/export, engine."""

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from cheshire.api import create_app
from cheshire.auth import service
from cheshire.catalog.models import Catalog
from cheshire.catalog.transfer import dump_document
from cheshire.settings import Settings
from tests.conftest import TestDb

PASSWORD = "correct horse battery"


@pytest.fixture
def settings(clean_db: TestDb) -> Settings:
    return Settings(database_url=clean_db.app_url, cookie_secure=False, login_max_failures=3)


@pytest.fixture
def app_client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client


def make_admin(settings: Settings) -> None:
    with psycopg.connect(settings.database_url) as conn:
        service.create_admin(conn, settings, "admin@example.org", "Admin", PASSWORD)


def login(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    """Log in and return the headers a state-changing request must carry."""
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"x-csrf-token": response.json()["csrf_token"]}


def new_client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def invite_and_accept(
    admin: TestClient, headers: dict[str, str], settings: Settings, email: str, role: str
) -> None:
    r = admin.post("/api/users/invitations", json={"email": email, "role": role}, headers=headers)
    assert r.status_code == 201, r.text
    with TestClient(create_app(settings)) as anon:
        accepted = anon.post(
            "/api/auth/accept-invitation",
            json={"token": r.json()["token"], "display_name": role.title(), "password": PASSWORD},
        )
        assert accepted.status_code == 201, accepted.text


@pytest.fixture
def team(
    settings: Settings, app_client: TestClient
) -> dict[str, tuple[TestClient, dict[str, str]]]:
    """An admin, an architect and a plain user, each with their own logged-in client."""
    make_admin(settings)
    admin_headers = login(app_client, "admin@example.org")
    invite_and_accept(app_client, admin_headers, settings, "arch@example.org", "architect")
    invite_and_accept(app_client, admin_headers, settings, "user@example.org", "user")
    out = {"admin": (app_client, admin_headers)}
    for role, email in (("architect", "arch@example.org"), ("user", "user@example.org")):
        client = new_client(settings)
        client.__enter__()
        out[role] = (client, login(client, email))
    return out


# --- authentication ------------------------------------------------------------------


def test_requires_login(app_client: TestClient) -> None:
    assert app_client.get("/api/auth/me").status_code == 401
    assert app_client.get("/api/catalog/abb").status_code == 401
    assert app_client.post("/api/engine/run", json={}).status_code == 401


def test_login_logout_and_cookie_flags(settings: Settings, app_client: TestClient) -> None:
    make_admin(settings)
    bad = app_client.post("/api/auth/login", json={"email": "admin@example.org", "password": "x"})
    assert bad.status_code == 401
    ok = app_client.post(
        "/api/auth/login", json={"email": "admin@example.org", "password": PASSWORD}
    )
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    me = app_client.get("/api/auth/me").json()
    assert me["user"]["role"] == "admin" and me["csrf_token"]
    assert "password_hash" not in str(me) and "argon2" not in str(me)
    headers = {"x-csrf-token": me["csrf_token"]}
    assert app_client.post("/api/auth/logout", headers=headers).status_code == 204
    assert app_client.get("/api/auth/me").status_code == 401


def test_secure_cookie_by_default() -> None:
    assert Settings().cookie_secure is True


def test_csrf_token_is_required_for_state_changes(
    team: dict[str, tuple[TestClient, dict[str, str]]],
) -> None:
    client, headers = team["architect"]
    body = {"name": "X", "domain": "d"}
    assert client.put("/api/catalog/abb/x", json=body).status_code == 403
    assert (
        client.put("/api/catalog/abb/x", json=body, headers={"x-csrf-token": "wrong"}).status_code
        == 403
    )
    assert (
        client.put("/api/catalog/abb/x", json={"id": "x", **body}, headers=headers).status_code
        == 200
    )


def test_login_is_rate_limited_per_account(settings: Settings, app_client: TestClient) -> None:
    make_admin(settings)
    for _ in range(3):
        assert (
            app_client.post(
                "/api/auth/login", json={"email": "admin@example.org", "password": "wrong"}
            ).status_code
            == 401
        )
    # even the right password is refused now
    locked = app_client.post(
        "/api/auth/login", json={"email": "admin@example.org", "password": PASSWORD}
    )
    assert locked.status_code == 429


def test_unknown_email_looks_like_wrong_password(app_client: TestClient) -> None:
    r = app_client.post("/api/auth/login", json={"email": "nobody@example.org", "password": "x"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_credentials"


def test_invitations_are_single_use_and_passwords_must_be_strong(
    settings: Settings, app_client: TestClient
) -> None:
    make_admin(settings)
    headers = login(app_client, "admin@example.org")
    token = app_client.post(
        "/api/users/invitations", json={"email": "n@example.org", "role": "user"}, headers=headers
    ).json()["token"]
    with new_client(settings) as anon:
        weak = anon.post(
            "/api/auth/accept-invitation",
            json={"token": token, "display_name": "N", "password": "short"},
        )
        assert weak.status_code == 422
        ok = anon.post(
            "/api/auth/accept-invitation",
            json={"token": token, "display_name": "N", "password": PASSWORD},
        )
        assert ok.status_code == 201
        again = anon.post(
            "/api/auth/accept-invitation",
            json={"token": token, "display_name": "N", "password": PASSWORD},
        )
        assert again.status_code == 400
        wrong = anon.post(
            "/api/auth/accept-invitation",
            json={"token": "nope", "display_name": "N", "password": PASSWORD},
        )
        assert wrong.status_code == 400


def test_token_is_stored_hashed(settings: Settings, app_client: TestClient) -> None:
    make_admin(settings)
    headers = login(app_client, "admin@example.org")
    token = app_client.post(
        "/api/users/invitations", json={"email": "n@example.org", "role": "user"}, headers=headers
    ).json()["token"]
    with psycopg.connect(settings.database_url) as conn:
        stored = conn.execute("select token_hash from invitations").fetchone()
        cookie = conn.execute("select id from auth_sessions").fetchone()
        hashes = conn.execute("select password_hash from users").fetchone()
    assert stored is not None and token not in stored[0]
    session_cookie = app_client.cookies.get("cheshire_session")
    assert cookie is not None and session_cookie not in cookie[0]
    assert hashes is not None and hashes[0].startswith("$argon2")


def test_only_admin_manages_users_and_roles(
    team: dict[str, tuple[TestClient, dict[str, str]]],
) -> None:
    for role in ("architect", "user"):
        client, headers = team[role]
        assert client.get("/api/users").status_code == 403
        assert (
            client.post(
                "/api/users/invitations",
                json={"email": "z@example.org", "role": "user"},
                headers=headers,
            ).status_code
            == 403
        )
        assert (
            client.patch("/api/users/2", json={"role": "admin"}, headers=headers).status_code == 403
        )

    admin, headers = team["admin"]
    users = {u["email"]: u for u in admin.get("/api/users").json()}
    arch_id = users["arch@example.org"]["id"]
    assert (
        admin.patch(f"/api/users/{arch_id}", json={"role": "user"}, headers=headers).status_code
        == 200
    )


def test_deactivated_user_loses_access_but_is_kept(
    settings: Settings, team: dict[str, tuple[TestClient, dict[str, str]]]
) -> None:
    admin, headers = team["admin"]
    user_client, _ = team["user"]
    uid = next(u["id"] for u in admin.get("/api/users").json() if u["email"] == "user@example.org")
    assert user_client.get("/api/auth/me").status_code == 200
    assert (
        admin.patch(f"/api/users/{uid}", json={"active": False}, headers=headers).status_code == 200
    )
    assert user_client.get("/api/auth/me").status_code == 401
    with new_client(settings) as fresh:
        relog = fresh.post(
            "/api/auth/login", json={"email": "user@example.org", "password": PASSWORD}
        )
    assert relog.status_code == 401
    assert any(
        u["email"] == "user@example.org" and not u["active"] for u in admin.get("/api/users").json()
    )


def test_last_admin_cannot_be_demoted_or_deactivated(
    team: dict[str, tuple[TestClient, dict[str, str]]],
) -> None:
    admin, headers = team["admin"]
    me = admin.get("/api/auth/me").json()["user"]["id"]
    assert (
        admin.patch(f"/api/users/{me}", json={"role": "architect"}, headers=headers).status_code
        == 409
    )
    assert (
        admin.patch(f"/api/users/{me}", json={"active": False}, headers=headers).status_code == 409
    )


def test_audit_log_records_sensitive_actions(
    settings: Settings, team: dict[str, tuple[TestClient, dict[str, str]]]
) -> None:
    admin, headers = team["admin"]
    uid = next(u["id"] for u in admin.get("/api/users").json() if u["email"] == "user@example.org")
    admin.patch(f"/api/users/{uid}", json={"role": "architect"}, headers=headers)
    with psycopg.connect(settings.database_url) as conn:
        actions = {r[0] for r in conn.execute("select action from audit_log")}
    assert {
        "user.create_admin",
        "user.invite",
        "user.accept_invitation",
        "user.role_change",
    } <= actions


def test_change_password_closes_sessions(
    settings: Settings, team: dict[str, tuple[TestClient, dict[str, str]]]
) -> None:
    client, headers = team["user"]
    r = client.post(
        "/api/auth/password",
        json={"current": PASSWORD, "new": "another long password"},
        headers=headers,
    )
    assert r.status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    login(client, "user@example.org", "another long password")


# --- catalog ---------------------------------------------------------------------------


def import_example(
    team: dict[str, tuple[TestClient, dict[str, str]]], example_catalog: Catalog
) -> None:
    client, headers = team["architect"]
    content = dump_document(example_catalog, "yaml")
    r = client.post(
        "/api/catalog/import",
        json={"content": content, "format": "yaml", "dry_run": False, "filename": "c.yaml"},
        headers=headers,
    )
    assert r.status_code == 200, r.text


def test_catalog_permissions(
    team: dict[str, tuple[TestClient, dict[str, str]]], example_catalog: Catalog
) -> None:
    import_example(team, example_catalog)
    user, uh = team["user"]
    assert user.get("/api/catalog/abb").status_code == 200  # everyone can read
    assert (
        user.put(
            "/api/catalog/abb/x", json={"id": "x", "name": "X", "domain": "d"}, headers=uh
        ).status_code
        == 403
    )
    assert (
        user.post("/api/catalog/import", json={"content": "abbs: []"}, headers=uh).status_code
        == 403
    )
    assert user.get("/api/catalog/export").status_code == 403
    assert (
        user.post(
            "/api/catalog/abb/audit-log/versions/1/status", json={"status": "validated"}, headers=uh
        ).status_code
        == 403
    )


def test_import_dry_run_then_apply_then_export(
    team: dict[str, tuple[TestClient, dict[str, str]]], example_catalog: Catalog
) -> None:
    client, headers = team["architect"]
    content = dump_document(example_catalog, "json")
    dry = client.post(
        "/api/catalog/import", json={"content": content, "format": "json"}, headers=headers
    )
    assert (
        dry.status_code == 200 and dry.json()["created"]["abb"] and dry.json()["batch_id"] is None
    )
    assert client.get("/api/catalog/abb").json() == []  # nothing was written

    import_example(team, example_catalog)
    items = client.get("/api/catalog/abb").json()
    assert len(items) == len(example_catalog.abbs)
    assert {i["effective_status"] for i in items} == {"proposed"}  # imports land as proposed

    exported = client.get("/api/catalog/export?format=yaml")
    assert exported.status_code == 200 and "audit-log" in exported.text
    assert "errors" in client.get("/api/catalog/validation").json()


def test_import_rejects_bad_documents(team: dict[str, tuple[TestClient, dict[str, str]]]) -> None:
    client, headers = team["architect"]
    bad = client.post("/api/catalog/import", json={"content": "abbs: [{id: x}]"}, headers=headers)
    assert bad.status_code == 422
    junk = client.post("/api/catalog/import", json={"content": "- a\n- b"}, headers=headers)
    assert junk.status_code == 422


def test_save_versions_and_status_flow(
    team: dict[str, tuple[TestClient, dict[str, str]]], example_catalog: Catalog
) -> None:
    import_example(team, example_catalog)
    client, headers = team["architect"]
    current: dict[str, Any] = client.get("/api/catalog/abb/audit-log").json()["item"]
    current["name"] = "Audit log, revised"
    saved = client.put(
        "/api/catalog/abb/audit-log?status=proposed&change_note=rename",
        json=current,
        headers=headers,
    )
    assert saved.status_code == 200 and saved.json()["version"] == 2

    detail = client.get("/api/catalog/abb/audit-log").json()
    assert detail["item"]["name"] == "Audit log, revised"  # only proposed existed
    assert [v["number"] for v in detail["versions"]] == [2, 1]

    ok = client.post(
        "/api/catalog/abb/audit-log/versions/2/status",
        json={"status": "validated"},
        headers=headers,
    )
    assert ok.status_code == 200
    again = client.get("/api/catalog/abb/audit-log").json()["versions"][0]
    assert again["status"] == "validated" and again["validated_by"] == "Architect"

    current["name"] = "pending change"
    client.put("/api/catalog/abb/audit-log?status=proposed", json=current, headers=headers)
    # the pending change does not replace the validated version
    assert client.get("/api/catalog/abb/audit-log").json()["item"]["name"] == "Audit log, revised"
    assert (
        client.get("/api/catalog/abb/audit-log?version=3").json()["item"]["name"]
        == "pending change"
    )


def test_save_rejects_invalid_input(
    team: dict[str, tuple[TestClient, dict[str, str]]], example_catalog: Catalog
) -> None:
    import_example(team, example_catalog)
    client, headers = team["architect"]
    sbb: dict[str, Any] = client.get("/api/catalog/sbb/sms-provider-a").json()["item"]
    # unknown reference
    r = client.put(
        "/api/catalog/sbb/sms-provider-a", json={**sbb, "realises": "nope"}, headers=headers
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_reference"
    # unknown attribute value in a condition
    r = client.put(
        "/api/catalog/sbb/sms-provider-a",
        json={**sbb, "applies_when": {"volume": ["gigantic"]}},
        headers=headers,
    )
    assert r.status_code == 422
    # schema violation
    r = client.put(
        "/api/catalog/sbb/sms-provider-a", json={**sbb, "state": "great"}, headers=headers
    )
    assert r.status_code == 422
    # slug is immutable: body id must match
    r = client.put("/api/catalog/sbb/other", json=sbb, headers=headers)
    assert r.status_code == 422
    # prohibited without a reason is rejected by the database constraint
    r = client.put(
        "/api/catalog/sbb/sms-provider-a",
        json={**sbb, "state": "prohibited", "reason_prohibited": ""},
        headers=headers,
    )
    assert r.status_code == 422
    # nothing above created a version
    assert len(client.get("/api/catalog/sbb/sms-provider-a").json()["versions"]) == 1
    assert client.get("/api/catalog/abb/missing").status_code == 404
    assert client.get("/api/catalog/widget").status_code == 422


def test_dependents_and_archive(
    team: dict[str, tuple[TestClient, dict[str, str]]], example_catalog: Catalog
) -> None:
    import_example(team, example_catalog)
    client, headers = team["architect"]
    deps = client.get("/api/catalog/abb/channel-sms/dependents").json()
    assert {"kind": "sbb", "slug": "sms-provider-a", "ref_kind": "realises"} in deps
    assert client.post("/api/catalog/abb/channel-sms/archive", headers=headers).status_code == 409


# --- engine ----------------------------------------------------------------------------

SCENARIO: dict[str, Any] = {
    "interpreter_output": {
        "abbs": [
            {"id": "notification-orchestration"},
            {"id": "channel-email"},
            {"id": "channel-sms"},
        ],
        "attributes": {
            "interaction_mode": {"value": "event", "source": "inferred"},
            "personal_data": {"value": "personal", "source": "inferred"},
        },
    },
    "answers": {},
}


def test_engine_run_on_the_database_catalog(
    team: dict[str, tuple[TestClient, dict[str, str]]], example_catalog: Catalog
) -> None:
    import_example(team, example_catalog)
    user, uh = team["user"]  # plain users can consult
    r = user.post("/api/engine/run", json=SCENARIO, headers=uh)
    assert r.status_code == 200, r.text
    body = r.json()
    result = body["result"]
    sms = next(a for a in result["abbs"] if a["id"] == "channel-sms")
    assert sms["coverage"] == "conditional"
    assert [q["attribute"] for q in result["pending_questions"]] == ["message_type", "volume"]
    # imported items are `proposed`, and the result says so
    abb = next(a for a in result["abbs"] if a["id"] == "channel-abstraction")
    assert abb["validation"] == "proposed"
    # the exact catalog state is recorded and reproducible
    again = user.post("/api/engine/run", json=SCENARIO, headers=uh).json()
    assert again["snapshot_id"] == body["snapshot_id"]


def test_engine_rejects_unknown_ids_and_draft_runs_for_users(
    team: dict[str, tuple[TestClient, dict[str, str]]], example_catalog: Catalog
) -> None:
    import_example(team, example_catalog)
    user, uh = team["user"]
    bad = {"interpreter_output": {"abbs": [{"id": "invented"}]}}
    assert user.post("/api/engine/run", json=bad, headers=uh).status_code == 422
    assert (
        user.post("/api/engine/run", json={"include_drafts": True}, headers=uh).status_code == 403
    )
    arch, ah = team["architect"]
    assert (
        arch.post("/api/engine/run", json={"include_drafts": True}, headers=ah).status_code == 200
    )


def test_engine_excludes_drafts_by_default(
    team: dict[str, tuple[TestClient, dict[str, str]]], example_catalog: Catalog
) -> None:
    import_example(team, example_catalog)
    client, headers = team["architect"]
    sbb: dict[str, Any] = client.get("/api/catalog/sbb/sms-provider-a").json()["item"]
    client.put(
        "/api/catalog/sbb/sms-provider-a?status=draft",
        json={**sbb, "name": "Draft"},
        headers=headers,
    )
    run = client.post("/api/engine/run", json=SCENARIO, headers=headers).json()
    names = [
        s["name"] for a in run["result"]["abbs"] if a["id"] == "channel-sms" for s in a["sbbs"]
    ]
    assert "Draft" not in names and "SMS provider A" in names


def test_engine_refuses_to_run_on_an_invalid_catalog(
    team: dict[str, tuple[TestClient, dict[str, str]]], example_catalog: Catalog
) -> None:
    import_example(team, example_catalog)
    client, headers = team["architect"]
    # R-003 already makes channel-sms activate failure-handling: this closes a cycle
    cycle = {
        "id": "R-900",
        "when": {"abb_present": ["failure-handling"]},
        "activates": "channel-sms",
        "strength": "considers",
    }
    saved = client.put("/api/catalog/rule/R-900", json=cycle, headers=headers)
    assert saved.status_code == 200
    assert any("cycle" in issue for issue in saved.json()["issues"])  # reported, not blocked
    run = client.post("/api/engine/run", json=SCENARIO, headers=headers)
    assert run.status_code == 409 and run.json()["detail"]["code"] == "catalog_invalid"
