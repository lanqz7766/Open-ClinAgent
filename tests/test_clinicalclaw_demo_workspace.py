import os
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from clinagent.console.demo import DemoWorkspaceStore, demo_workspace_store


def _build_client():
    from clinagent.gateway.server import create_app

    app, _, _ = create_app()
    return TestClient(app)


def test_demo_workspace_snapshot_has_longitudinal_case():
    store = DemoWorkspaceStore()
    payload = store.snapshot()

    assert payload["default_case_id"]
    assert payload["workspace"]["title"]
    assert len(payload["workspace"]["timeline"]) >= 4
    assert payload["workspace"]["analysis"]["risk_level"]
    assert payload["workspace"]["patient"]["display_name"].startswith("Subject ")


def test_demo_workspace_prefers_real_proteas_case_when_env_is_set(monkeypatch):
    real_proteas_root = os.getenv("CLINAGENT_TEST_PROTEAS_DATA_ROOT")
    if not real_proteas_root:
        pytest.skip("Set CLINAGENT_TEST_PROTEAS_DATA_ROOT to run the real demo workspace preference test.")

    monkeypatch.setenv("CLINAGENT_NEURO_LONGITUDINAL_DATA_ROOT", real_proteas_root)
    store = DemoWorkspaceStore()

    payload = store.snapshot()

    assert payload["default_case_id"].startswith("proteas-")
    assert payload["workspace"]["id"].startswith("proteas-")
    assert len(payload["workspace"]["timeline"]) >= 4
    assert payload["workspace"]["visualizations"]["trend_svg"].startswith("<svg")
    assert len(payload["workspace"]["visualizations"]["comparison_panels"]) == 3
    assert payload["workspace"]["viewer"]["available"] is True
    assert payload["workspace"]["viewer"]["enabled"] is True
    assert "neuro-report-surface" in payload["workspace"]["report"]["rendered_html"]
    assert payload["workspace"]["report"]["quality_review"]["template_id"] == "radiology"


def test_demo_workspace_chat_updates_messages():
    store = DemoWorkspaceStore()
    case_id = store.snapshot()["default_case_id"]
    response = store.chat(
        case_id=case_id,
        message="Generate the longitudinal review brief for this patient.",
    )

    assert response["assistant"]["content"]
    assert response["workspace"]["review"]["status"] == "in_review"


def test_demo_workspace_review_updates_status():
    store = DemoWorkspaceStore()
    case_id = store.snapshot()["default_case_id"]
    workspace = store.review(
        case_id=case_id,
        action="approve",
        comment="Mock reviewer approved the longitudinal report.",
    )

    assert workspace["review"]["status"] == "approved"
    assert "approved" in workspace["review"]["comment"].lower()


def test_demo_routes_expose_workspace_and_chat():
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()

        console_response = client.get("/api/demo/console")
        assert console_response.status_code == 200
        assert console_response.json()["title"] == "ClinAgent Console"
        assert any(item["id"] == "report_quality_review" for item in console_response.json()["workflows"])

        workspace_response = client.get("/api/demo/workspace")
        assert workspace_response.status_code == 200
        assert workspace_response.json()["workspace"]["patient"]["display_name"].startswith("Subject ")
        assert workspace_response.json()["workspace"]["report"]["title"]

        report_response = client.get(f"/api/demo/cases/{workspace_response.json()['default_case_id']}/report")
        assert report_response.status_code == 200
        assert report_response.json()["report"]["title"]

        command_response = client.post(
            "/api/demo/command",
            json={"message": "Check whether this radiation incident should trigger an alert."},
        )
        assert command_response.status_code == 200
        assert command_response.json()["target_module"] == "safety"

        findings_command_response = client.post(
            "/api/demo/command",
            json={"message": "Does this critical potassium result need urgent escalation?"},
        )
        assert findings_command_response.status_code == 200
        assert findings_command_response.json()["target_module"] == "findings"

        queue_command_response = client.post(
            "/api/demo/command",
            json={"message": "Should this referral move into the urgent queue today?"},
        )
        assert queue_command_response.status_code == 200
        assert queue_command_response.json()["target_module"] == "queue"

        diagnosis_command_response = client.post(
            "/api/demo/command",
            json={"message": "Does this report suggest a missed vertebral fracture workup gap?"},
        )
        assert diagnosis_command_response.status_code == 200
        assert diagnosis_command_response.json()["target_module"] == "diagnosis"

        chat_response = client.post(
            "/api/demo/chat",
            json={
                "case_id": workspace_response.json()["default_case_id"],
                "message": "Explain why this case is considered high risk.",
            },
        )
        assert chat_response.status_code == 200
        assert chat_response.json()["assistant"]["content"]

        demo_page = client.get("/demo")
        assert demo_page.status_code == 200
        # Note: pre-built dist may still have old branding until frontend is rebuilt
        assert '<div id="root"></div>' in demo_page.text
        assert '/demo-static/assets/' in demo_page.text
