from datetime import UTC, datetime, timedelta
import io
import json
import sqlite3

import pytest
from fastapi import Request
from starlette.websockets import WebSocketDisconnect

from clinagent.gateway.auth import ClinAgentAuthStore
from tests.test_gateway_auth import _build_client


INITIAL = "initial example password"
PERSONAL = "personal example password"


def provision(store, email="reader@example.org", role="radiologist"):
    return store.provision_user(email=email, password=INITIAL, name="Test Reader", role=role)


def complete(store, user):
    return store.complete_account_setup(user_id=user["id"], current_password=INITIAL,
                                        new_password=PERSONAL, dua_accepted=True)


def request():
    return Request({"type": "http", "headers": [], "client": ("testclient", 1)})


def test_permanent_account_first_login_and_no_fabricated_consent(tmp_path, monkeypatch):
    from clinagent.gateway import auth
    store = ClinAgentAuthStore(tmp_path / "auth.sqlite3", allow_self_registration=False)
    user = provision(store)
    assert user["account_setup_required"] and user["must_change_password"]
    assert not user["dua_accepted_at"] and not user["email_verified_at"]
    reopened = ClinAgentAuthStore(store.db_path, allow_self_registration=False)
    assert reopened.get_user(user["id"])["email_verified_at"] is None
    assert reopened.schema_version == 4
    with pytest.raises(ValueError, match="agreement"):
        store.complete_account_setup(user_id=user["id"], current_password=INITIAL,
                                     new_password=PERSONAL, dua_accepted=False)
    with pytest.raises(ValueError, match="different"):
        store.complete_account_setup(user_id=user["id"], current_password=INITIAL,
                                     new_password=INITIAL, dua_accepted=True)
    old_session = store.create_session(user["id"], request())
    updated = complete(store, user)
    assert not updated["account_setup_required"]
    assert updated["dua_accepted_at"] and not updated["email_verified_at"]
    assert store.user_from_token(old_session.token) is None
    assert store.verify_user(user["email"], INITIAL) is None
    later = datetime.now(UTC) + timedelta(days=365)
    monkeypatch.setattr(auth, "_utc_now", lambda: later)
    assert store.verify_user(user["email"], PERSONAL)["id"] == user["id"]


def test_suspend_reset_and_resume_preserve_ownership(tmp_path):
    store = ClinAgentAuthStore(tmp_path / "auth.sqlite3")
    user = complete(store, provision(store))
    store.register_case_access(case_id="case-one", owner_user_id=user["id"], source="test", shared=False)
    token = store.create_session(user["id"], request()).token
    reset_link = store.create_password_reset_token(user["email"], request())
    store.set_user_status(user["id"], "suspended")
    assert store.user_from_token(token) is None
    assert store.verify_user(user["email"], PERSONAL) is None
    with pytest.raises(ValueError):
        store.reset_password_with_token(reset_link, "different secure password")
    store.set_user_status(user["id"], "active")
    assert store.user_from_token(token) is None
    assert store.verify_user(user["email"], PERSONAL)
    assert store.can_access_case(case_id="case-one", user_id=user["id"])
    token = store.create_session(user["id"], request()).token
    reset_link = store.create_password_reset_token(user["email"], request())
    updated = store.set_temporary_password(user["id"], INITIAL)
    assert updated["account_setup_required"]
    assert store.user_from_token(token) is None
    with pytest.raises(ValueError):
        store.reset_password_with_token(reset_link, "different secure password")
    assert store.verify_user(user["email"], PERSONAL) is None


def test_admin_api_and_first_login_are_enforced_on_server(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path, require_auth=True, self_registration=False, preview_scope="brain_tumor")
    store = ClinAgentAuthStore(tmp_path / "auth.sqlite3", allow_self_registration=False)
    admin = complete(store, provision(store, "operator@example.org", "admin"))
    assert client.get("/api/auth/admin/users").status_code == 401
    client.post("/api/auth/login", json={"email": admin["email"], "password": PERSONAL})
    created = client.post("/api/auth/admin/users", json={"email": "new@example.org", "name": "New Reader", "password": INITIAL})
    assert created.status_code == 200
    user = created.json()["user"]
    assert INITIAL not in created.text and "password_hash" not in created.text
    assert len(client.get("/api/auth/admin/users").json()["users"]) == 2
    assert client.post("/api/auth/admin/users", json={"email": "new@example.org", "name": "Duplicate", "password": INITIAL}).status_code == 400
    assert client.post("/api/auth/admin/users", json={"email": "bad@example.org", "name": "Elevate", "role": "admin", "password": INITIAL}).status_code == 422
    assert client.patch(f"/api/auth/admin/users/{admin['id']}/status", json={"status": "suspended"}).status_code == 400
    assert client.post(f"/api/auth/admin/users/{admin['id']}/password", json={"password": INITIAL}).status_code == 400
    assert client.patch(f"/api/auth/admin/users/{user['id']}/status", json={"status": "suspended"}).status_code == 200
    assert client.patch(f"/api/auth/admin/users/{user['id']}/status", json={"status": "active"}).status_code == 200
    assert client.post(f"/api/auth/admin/users/{user['id']}/password", json={"password": INITIAL}).status_code == 200
    audit = client.get("/api/auth/audit/recent").text
    assert "account_provisioned" in audit and INITIAL not in audit
    client.post("/api/auth/logout")
    login = client.post("/api/auth/login", json={"email": user["email"], "password": INITIAL})
    assert login.json()["user"]["account_setup_required"]
    assert client.get("/api/version").status_code == 403
    assert client.get("/api/auth/admin/users").status_code == 403
    assert client.get("/api/demo/brain-tumor/uploads").status_code == 403
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/account/setup", json={"current_password": INITIAL, "new_password": PERSONAL, "dua_accepted": "false"}).status_code == 400
    result = client.post("/api/auth/account/setup", json={"current_password": INITIAL, "new_password": PERSONAL, "dua_accepted": True})
    assert result.status_code == 200 and not result.json()["user"]["account_setup_required"]
    assert client.get("/api/version").status_code == 200
    assert client.get("/api/demo/brain-tumor/uploads").status_code == 200
    assert client.get("/api/auth/admin/users").status_code == 404
    assert client.post("/api/auth/admin/users", json={"email": "bad@example.org", "name": "Bad", "password": INITIAL}).status_code == 404


def test_cli_provisions_without_claiming_recipient_acceptance(tmp_path, monkeypatch, capsys):
    from clinagent.gateway import auth_admin
    store = ClinAgentAuthStore(tmp_path / "auth.sqlite3", allow_self_registration=False)
    monkeypatch.setattr(auth_admin, "load_settings", lambda: None)
    monkeypatch.setattr(auth_admin.ClinAgentAuthStore, "from_env", lambda: store)
    monkeypatch.setattr("sys.stdin", io.StringIO(INITIAL + "\n"))
    assert auth_admin.main(["create-user", "--email", "operator@example.org", "--name", "Operator", "--role", "admin", "--password-stdin"]) == 0
    output = capsys.readouterr().out
    assert INITIAL not in output and "password_hash" not in output
    user = json.loads(output)
    assert user["account_setup_required"] and not user["dua_accepted_at"]
    assert auth_admin.main(["list-users"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    assert auth_admin.main(["set-status", "--email", "operator@example.org", "--status", "suspended"]) == 1


def test_database_migration_and_reopen_preserve_accounts(tmp_path):
    path = tmp_path / "auth.sqlite3"
    store = ClinAgentAuthStore(path)
    legacy = store.create_user(email="legacy@example.org", password=PERSONAL, name="Legacy", organization="", role="researcher", dua_accepted=True)
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE users DROP COLUMN must_change_password")
        conn.execute("DELETE FROM schema_migrations WHERE version = 4")
        conn.execute("INSERT OR IGNORE INTO schema_migrations VALUES (3, '2026-01-01')")
    upgraded = ClinAgentAuthStore(path)
    assert upgraded.verify_user("legacy@example.org", PERSONAL)["id"] == legacy["id"]
    assert not upgraded.get_user(legacy["id"])["account_setup_required"]
    assert upgraded.schema_version == 4


def test_public_address_and_password_policy_are_exposed_consistently(monkeypatch, tmp_path):
    monkeypatch.setenv("CLINAGENT_PUBLIC_URL", "https://preview.example.org:7740")
    client = _build_client(monkeypatch, tmp_path)
    cfg = client.get("/api/auth/config").json()
    assert cfg["public_url"] == "https://preview.example.org:7740"
    assert cfg["password_min_length"] == 12


@pytest.mark.parametrize("path", ["/ws", "/api/demo/radonc-plan/ws/example-case"])
def test_pending_administrator_cannot_bypass_setup_via_websocket(monkeypatch, tmp_path, path):
    client = _build_client(monkeypatch, tmp_path, require_auth=True, self_registration=False)
    store = ClinAgentAuthStore(tmp_path / "auth.sqlite3")
    admin = provision(store, "pending-operator@example.org", "admin")
    assert client.post("/api/auth/login", json={"email": admin["email"], "password": INITIAL}).status_code == 200
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect(path, headers={"Origin": "http://testserver"}):
            pass
    assert denied.value.code == 4003


def test_account_operations_reject_foreign_origin(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path, require_auth=True, self_registration=False)
    store = ClinAgentAuthStore(tmp_path / "auth.sqlite3")
    admin = complete(store, provision(store, "operator@example.org", "admin"))
    client.post("/api/auth/login", json={"email": admin["email"], "password": PERSONAL})
    response = client.post("/api/auth/admin/users", headers={"Origin": "https://untrusted.example.org"},
                           json={"email": "new@example.org", "name": "New Reader", "password": INITIAL})
    assert response.status_code == 403
    assert len(store.list_users()) == 1
