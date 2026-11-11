from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _build_client() -> TestClient:
    from clinagent.gateway.server import create_app

    app, _, _ = create_app()
    return TestClient(app)


def test_neuro_alignment_demo_job_create_and_status() -> None:
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()
        response = client.post(
            "/api/demo/neuro-report/alignment-jobs",
            json={
                "mode": "demo",
                "workflow": "longitudinal_coregistration",
                "patient_id": "P1",
                "fixed_study_id": "baseline",
                "moving_study_id": "followup",
                "apply_to_segmentation": True,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["mode"] == "demo"
        assert payload["qc"]["resampled_to_reference_grid"] is True
        assert payload["qc"]["nonlinear_deformation_allowed"] is False

        status_response = client.get(f"/api/demo/neuro-report/alignment-jobs/{payload['job_id']}")
        assert status_response.status_code == 200
        assert status_response.json()["job_id"] == payload["job_id"]


def test_neuro_alignment_remote_job_uses_registration_tools(monkeypatch) -> None:
    fake_store = MagicMock()
    fake_store.resolve_analysis_request.side_effect = [
        {"analysis_image_path": "/tmp/baseline.nii.gz", "seg_path": None},
        {"analysis_image_path": "/tmp/followup.nii.gz", "seg_path": "/tmp/followup_seg.nii.gz"},
    ]

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server._get_neuro_report_demo_components", return_value=({"vanilla"}, fake_store)), \
         patch(
             "clinagent.families.neuro.tools.registration.NeuroLongitudinalCoregistrationTool.run",
             return_value={
                 "status": "ok",
                 "output_image_path": "/tmp/out/aligned.nii.gz",
                 "transform_path": "/tmp/out/transform.json",
                 "qc": {
                     "translation_norm_mm": 12.4,
                     "ncc_before": 0.51,
                     "ncc_after": 0.72,
                     "ncc_delta": 0.21,
                     "warnings": ["shape_mismatch"],
                     "nonlinear_deformation_allowed": False,
                 },
             },
         ) as registration_run, \
         patch(
             "clinagent.families.neuro.tools.registration.NeuroTransformApplicationTool.run",
             return_value={"status": "ok", "output_image_path": "/tmp/out/transferred_segmentation_to_reference.nii.gz"},
         ) as transform_run:
        monkeypatch.setenv("CLINAGENT_NEURO_ALIGNMENT_OUTPUT_DIR", "/tmp/out")
        client = _build_client()
        response = client.post(
            "/api/demo/neuro-report/alignment-jobs",
            json={
                "mode": "remote",
                "workflow": "longitudinal_coregistration",
                "patient_id": "P1",
                "fixed_study_id": "baseline",
                "moving_study_id": "followup",
                "apply_to_segmentation": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["mode"] == "remote"
    assert payload["outputs"]["aligned_image_path"] == "/tmp/out/aligned.nii.gz"
    assert payload["outputs"]["transferred_segmentation_path"] == "/tmp/out/transferred_segmentation_to_reference.nii.gz"
    assert "Nonlinear deformation was not used" in payload["qc"]["clinical_warnings"][1]
    registration_run.assert_called_once()
    transform_run.assert_called_once()


def test_neuro_alignment_remote_job_returns_clinical_error_without_output_config() -> None:
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()
        response = client.post(
            "/api/demo/neuro-report/alignment-jobs",
            json={
                "mode": "remote",
                "workflow": "longitudinal_coregistration",
                "patient_id": "P1",
                "fixed_study_id": "baseline",
                "moving_study_id": "followup",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["qc"]["warnings"] == ["alignment_unavailable"]
    assert "not configured" in payload["error"]
