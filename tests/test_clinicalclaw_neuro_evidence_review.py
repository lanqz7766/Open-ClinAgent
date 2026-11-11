from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from clinagent.console.demo import DemoWorkspaceStore
from clinagent.families.neuro.evidence_review import VerifyEvidenceBoardRequest, verify_evidence_board


def _build_client():
    from clinagent.gateway.server import create_app

    app, _, _ = create_app()
    return TestClient(app)


def test_verify_evidence_board_marks_missing_evidence_and_requires_review():
    payload = VerifyEvidenceBoardRequest.model_validate(
        {
            "case_id": "demo-case",
            "current_study": {
                "study_id": "current-mri",
                "study_date": "2026-03-23",
                "sequence": "T1C",
                "summary": "Current MRI shows lesion burden 5.3 mL compared with 4.6 mL on the prior MRI.",
                "available_sequences": ["T1C", "FLAIR"],
                "structured_findings": {"lesion_volume_ml": 5.3},
            },
            "prior_study": {
                "study_id": "prior-mri",
                "study_date": "2026-01-12",
                "sequence": "T1C",
                "summary": "Prior MRI showed lesion burden 4.6 mL.",
                "available_sequences": ["T1C"],
                "structured_findings": {"lesion_volume_ml": 4.6},
            },
            "prior_report": "Prior MRI described a treated lesion without new acute complication.",
            "draft_report": "There is interval progression of the treated lesion. No acute hemorrhage identified on the available review.",
            "require_comparison": True,
            "required_sequences": ["T1C"],
            "structured_fields": {"current_volume_ml": 5.3, "prior_volume_ml": 4.6},
        }
    )

    result = verify_evidence_board(payload)

    assert result.summary["claim_count"] == 2
    assert result.summary["status_counts"]["supported"] >= 1
    assert result.summary["status_counts"]["missing_evidence"] >= 1
    assert result.workflow_run.status == "needs_human_review"
    assert any(item.code == "claim_missing_evidence" for item in result.stop_conditions)


def test_demo_workspace_snapshot_includes_evidence_review():
    store = DemoWorkspaceStore()

    payload = store.snapshot()

    assert payload["workspace"]["evidence_review"]["workflow_run"]["status"] in {
        "ready_for_review",
        "needs_human_review",
    }
    assert payload["workspace"]["evidence_review"]["summary"]["claim_count"] >= 1
    assert payload["cases"][0]["evidence_status"] in {"ready_for_review", "needs_human_review"}


def test_demo_evidence_board_routes_expose_case_board_and_verify_endpoint():
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()

        workspace_response = client.get("/api/demo/workspace")
        assert workspace_response.status_code == 200
        case_id = workspace_response.json()["default_case_id"]

        board_response = client.get(f"/api/demo/cases/{case_id}/evidence-board")
        assert board_response.status_code == 200
        board_payload = board_response.json()["evidence_review"]
        assert board_payload["summary"]["claim_count"] >= 1
        assert board_payload["workflow_run"]["status"] in {"ready_for_review", "needs_human_review"}

        verify_response = client.post(
            "/api/demo/evidence-board/verify",
            json={
                "case_id": "api-demo",
                "current_study": {
                    "study_id": "curr",
                    "study_date": "2026-03-23",
                    "sequence": "T1C",
                    "summary": "Current MRI shows lesion burden 5.0 mL compared with 4.0 mL on the prior MRI.",
                    "available_sequences": ["T1C"],
                    "structured_findings": {"lesion_volume_ml": 5.0},
                },
                "prior_study": {
                    "study_id": "prev",
                    "study_date": "2025-12-10",
                    "sequence": "T1C",
                    "summary": "Prior MRI showed lesion burden 4.0 mL.",
                    "available_sequences": ["T1C"],
                    "structured_findings": {"lesion_volume_ml": 4.0},
                },
                "prior_report": "Prior MRI showed a treated lesion.",
                "draft_report": "There is interval progression of the treated lesion.",
                "require_comparison": True,
                "required_sequences": ["T1C"],
                "structured_fields": {"current_volume_ml": 5.0, "prior_volume_ml": 4.0},
            },
        )
        assert verify_response.status_code == 200
        verify_payload = verify_response.json()
        assert verify_payload["summary"]["claim_count"] == 1
        assert verify_payload["claims"][0]["verification"]["status"] == "supported"
