from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.test_gateway_auth import _build_client


def register(client, email="reader-a@example.org", role="radiologist"):
    response = client.post("/api/auth/register", json={
        "email": email, "password": "test reader passphrase", "name": "Test Reader",
        "organization": "Test", "role": role, "dua_accepted": True,
    })
    assert response.status_code == 200, response.text
    return response.json()["user"]["id"]


@pytest.mark.parametrize("path,method", [
    ("/chat", "post"), ("/chat/stream", "post"), ("/queue", "get"),
    ("/api/demo/execute-stream", "post"), ("/api/demo/console", "get"),
    ("/api/demo/upload", "post"), ("/api/dev/console", "get"),
    ("/api/demo/radonc-plan/session", "get"), ("/api/neuro-knowledge/health", "get"),
])
def test_operator_routes_are_not_physician_routes(monkeypatch, tmp_path, path, method):
    client = _build_client(monkeypatch, tmp_path, require_auth=True)
    assert getattr(client, method)(path).status_code == 401
    register(client)
    assert getattr(client, method)(path).status_code == 404


def test_self_registration_cannot_assign_admin(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path, require_auth=True)
    response = client.post("/api/auth/register", json={
        "email": "admin@example.org", "password": "test admin passphrase",
        "name": "Reader", "role": "admin", "dua_accepted": True,
    })
    assert response.status_code == 400


@pytest.mark.parametrize("path", ["/ws", "/api/demo/radonc-plan/ws/test-session"])
def test_physician_websockets_cannot_enter_operator_runtime(monkeypatch, tmp_path, path):
    client = _build_client(monkeypatch, tmp_path, require_auth=True)
    register(client)
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect(path, headers={"Origin": "http://testserver"}):
            pass
    assert denied.value.code == 4003


@pytest.mark.parametrize("path", ["/ws", "/api/demo/radonc-plan/ws/test-session"])
def test_brain_tumor_scope_closes_legacy_websockets(monkeypatch, tmp_path, path):
    client = _build_client(monkeypatch, tmp_path, preview_scope="brain_tumor")
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect(path):
            pass
    assert denied.value.code == 4003


def test_websocket_origin_is_exact_and_required(monkeypatch):
    from clinagent.gateway.ws import websocket_origin_allowed

    monkeypatch.setenv("CLINAGENT_CORS_ORIGINS", "https://preview.example.org:7734")
    monkeypatch.delenv("CLINAGENT_PUBLIC_URL", raising=False)
    headers = {"host": "preview.example.org:7734", "x-forwarded-proto": "https"}
    ws = SimpleNamespace(headers=headers, url=SimpleNamespace(scheme="ws"))
    assert not websocket_origin_allowed(ws)
    headers["origin"] = "https://preview.example.org:7734"
    assert websocket_origin_allowed(ws)
    headers["origin"] = "https://preview.example.org.attacker.invalid:7734"
    assert not websocket_origin_allowed(ws)


def test_invited_admin_websocket_validates_origin_and_revocation(monkeypatch, tmp_path):
    from clinagent.gateway.auth import ClinAgentAuthStore

    client = _build_client(monkeypatch, tmp_path, require_auth=True, self_registration=False)
    auth = ClinAgentAuthStore.from_env()
    _, token = auth.create_invitation(email="operator@example.org", name="Operator", organization="Test", role="admin")
    accepted = client.post("/api/auth/invitations/accept", json={
        "token": token, "password": "test operator passphrase", "dua_accepted": True,
    })
    assert accepted.status_code == 200
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect("/ws", headers={"Origin": "https://untrusted.example.org"}):
            pass
    assert denied.value.code == 4003
    with client.websocket_connect("/ws", headers={"Origin": "http://testserver"}) as ws:
        ws.send_json({"type": "req", "id": "one", "method": "ping", "params": {}})
        assert ws.receive_json()["ok"] is True
        client.post("/api/auth/logout")
        ws.send_json({"type": "req", "id": "two", "method": "ping", "params": {}})
        with pytest.raises(WebSocketDisconnect) as expired:
            ws.receive_json()
        assert expired.value.code == 4001


def test_neuro_assets_sessions_and_jobs_are_owned(monkeypatch, tmp_path):
    from clinagent.gateway import server
    from clinagent.gateway.auth import ClinAgentAuthStore
    from clinagent.gateway.neuro_access import NeuroAccess

    monkeypatch.setattr(server, "workspace_root", lambda: tmp_path)
    store = MagicMock()
    store.get_session.return_value = {"report": "Owned report", "label_mapping_path": "/private/labels.csv"}
    store.get_structural_session_slice.return_value = {"image": "owned-pixels"}
    monkeypatch.setattr(server, "_get_neuro_report_demo_components", lambda: ({"vanilla"}, store))
    client = _build_client(monkeypatch, tmp_path, require_auth=True)
    owner = register(client)
    auth = ClinAgentAuthStore.from_env()
    access = NeuroAccess(auth, set())
    asset_key = "/neuro-assets/neuro-report/analysis-unique/viewer/image.nii.gz"
    asset = tmp_path / ".clinagent/derived/neuro_longitudinal/neuro-report/analysis-unique/viewer/image.nii.gz"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"synthetic test asset")
    access.register_result({"session_id": "owned-neuro", "viewer_assets": {"image_url": asset_key}}, owner)
    assert client.get(asset_key).status_code == 200
    assert client.get(asset_key, headers={"Range": "bytes=0-4"}).status_code == 206
    detail = client.get("/api/demo/neuro-report/sessions/owned-neuro")
    assert detail.status_code == 200 and "label_mapping_path" not in detail.json()
    assert client.get("/api/demo/neuro-report/sessions/owned-neuro/slice?plane=axial&index=0").status_code == 200

    client.post("/api/auth/logout")
    assert client.get(asset_key).status_code == 401
    other = register(client, "reader-b@example.org")
    for path in (asset_key, "/api/demo/neuro-report/sessions/owned-neuro",
                 "/api/demo/neuro-report/sessions/owned-neuro/slice?plane=axial&index=0",
                 "/api/demo/neuro-report/sessions/owned-neuro/structural-regions.csv"):
        assert client.get(path).status_code == 404
    assert client.post("/api/demo/neuro-report/chat", json={"session_id": "owned-neuro", "question": "Report?"}).status_code == 404
    assert client.post("/api/demo/neuro-report/analyze", data={"session_id": "owned-neuro"}).status_code == 404
    with pytest.raises(ValueError):
        access.register_result({"session_id": "owned-neuro"}, other)
    auth.mark_case_deleted(case_id="owned-neuro", owner_user_id=owner)
    assert not access.asset_allowed(asset_key, owner)


def test_neuro_curated_allowlist_controls_assets_and_patients(monkeypatch, tmp_path):
    from clinagent.gateway import server
    from clinagent.gateway.auth import ClinAgentAuthStore
    from clinagent.gateway.neuro_access import NeuroAccess

    monkeypatch.setenv("CLINAGENT_NEURO_CURATED_PATIENT_IDS", "approved")
    fake = MagicMock()
    fake.get_patients.return_value = {"patients": [{"id": "approved"}, {"id": "private"}]}
    monkeypatch.setattr(server, "_get_neuro_report_demo_components", lambda: ({"vanilla"}, fake))
    client = _build_client(monkeypatch, tmp_path, require_auth=True)
    user = register(client)
    assert client.get("/api/demo/neuro-report/patients").json()["patients"] == [{"id": "approved"}]
    assert client.get("/api/demo/neuro-report/patients/private").status_code == 404
    fake.get_patient_data.assert_not_called()
    assert client.post("/api/demo/neuro-report/analyze", data={"source_path": "/private/input.nii.gz"}).status_code == 403
    assert client.post("/api/demo/neuro-report/alignment-jobs", json={"patient_id": "approved", "mode": "demo"}).status_code == 422
    assert client.get("/api/demo/neuro-report/alignment-jobs/another-users-job").status_code == 404
    auth = ClinAgentAuthStore.from_env()
    allowed = NeuroAccess(auth, {"approved"})
    key = "/neuro-assets/approved/viewer/image.nii.gz"
    result = allowed.publish_curated("approved", {"image_url": key, "source_path": "/private/input.nii.gz"})
    assert result == {"image_url": key}
    assert allowed.asset_allowed(key, user)
    assert not NeuroAccess(auth, set()).asset_allowed(key, user)


@pytest.mark.parametrize("outcome", ["success", "partial", "failure", "tool_call"])
def test_report_uses_configured_provider_only(monkeypatch, tmp_path, outcome):
    from clinagent.gateway import server

    response = SimpleNamespace(content="**Findings:**\nMeasured volumes reviewed.", model="private-model", partial=outcome == "partial", tool_calls=[{}] if outcome == "tool_call" else None)
    provider = SimpleNamespace(chat=AsyncMock(return_value=response))
    if outcome == "failure":
        provider.chat.side_effect = RuntimeError("Private endpoint unavailable")
    monkeypatch.setattr(server, "create_provider", lambda *args, **kwargs: provider)
    client = _build_client(monkeypatch, tmp_path)
    payload = {"patient_id": "DO_NOT_SEND_PATIENT", "filename": "DO_NOT_SEND_FILENAME",
               "active_measurements": {"et": 42}, "qc_state": "Pending"}
    result = client.post("/api/demo/brain-tumor/report/draft", json=payload)
    assert result.status_code == 200
    assert result.json()["generated"] is (outcome == "success")
    provider.chat.assert_awaited_once()
    sent = " ".join(message.content for message in provider.chat.call_args.args[0])
    assert "DO_NOT_SEND" not in sent
    assert "Private endpoint unavailable" not in json.dumps(result.json())


def test_neuro_session_rejects_other_workflow_memory(monkeypatch):
    from clinagent.families.neuro import report_demo

    store = report_demo.NeuroReportDemoStore.__new__(report_demo.NeuroReportDemoStore)
    store._session_store = {}
    monkeypatch.setattr(report_demo, "get_session_memory", lambda _: {"workflow_id": "chat", "payload": {"report": "foreign"}})
    with pytest.raises(KeyError):
        store.get_session("foreign-session")
