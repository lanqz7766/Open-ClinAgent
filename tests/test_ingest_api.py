from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


REAL_DATA_ROOT = os.getenv("CLINAGENT_TEST_LONGITUDINAL_DATA_ROOT", "")
requires_real_data = pytest.mark.skipif(
    not REAL_DATA_ROOT,
    reason="Set CLINAGENT_TEST_LONGITUDINAL_DATA_ROOT to run ingest API tests against real longitudinal data.",
)


def _build_client() -> TestClient:
    from clinagent.gateway.server import create_app

    app, _, _ = create_app()
    return TestClient(app)


@requires_real_data
def test_ingest_profile_returns_standard_response() -> None:
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()
        response = client.post("/api/ingest/profile", json={"source_path": REAL_DATA_ROOT})

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["error"] is None
        assert payload["data"]["detected_type"] == "longitudinal"
        assert len(payload["data"]["patients"]) == 2


@requires_real_data
def test_ingest_confirm_and_workspace_round_trip() -> None:
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()

        profile_response = client.post("/api/ingest/profile", json={"source_path": REAL_DATA_ROOT})
        assert profile_response.json()["ok"] is True

        confirm_response = client.post(
            "/api/ingest/confirm",
            json={
                "source_path": REAL_DATA_ROOT,
                "selected_workflow": "longitudinal_neuro_review",
                "patient_overrides": {"patient_uid": "806"},
            },
        )
        assert confirm_response.status_code == 200
        confirm_payload = confirm_response.json()
        assert confirm_payload["ok"] is True
        assert confirm_payload["data"]["status"] == "assembling"

        workspace_id = confirm_payload["data"]["workspace_id"]
        workspace_response = client.get(f"/api/ingest/workspace/{workspace_id}")
        assert workspace_response.status_code == 200
        workspace_payload = workspace_response.json()
        assert workspace_payload["ok"] is True
        assert workspace_payload["data"]["patient_id"] == "806"
        assert len(workspace_payload["data"]["timepoints"]) == 28


def test_ingest_workspace_returns_error_for_unknown_id() -> None:
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()
        response = client.get("/api/ingest/workspace/missing-workspace")

        assert response.status_code == 200
        payload = response.json()
        assert payload == {
            "ok": False,
            "data": None,
            "error": "Unknown workspace_id: missing-workspace",
        }
