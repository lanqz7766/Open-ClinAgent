from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient


def _build_client():
    from clinagent.gateway.server import create_app

    app, _, _ = create_app()
    return TestClient(app)


def test_chat_without_scenario_uses_default_gateway_path():
    fake_result = MagicMock(status="completed", result="plain-output", iterations=2)

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server.create_agent") as create_agent, \
         patch("clinagent.gateway.server.enqueue_command_in_lane", new_callable=AsyncMock) as enqueue:
        create_agent.return_value.invoke = AsyncMock(return_value=fake_result)

        async def passthrough(_lane, fn):
            return await fn()

        enqueue.side_effect = passthrough

        client = _build_client()
        response = client.post("/chat", json={"task": "hello"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["result"] == "plain-output"
        create_agent.assert_called_once()


def test_chat_with_scenario_routes_to_clinagent_service():
    fake_agent_result = MagicMock(status="completed", result="scenario-output", iterations=4)
    fake_scenario_result = MagicMock(
        scenario=MagicMock(id="diagnostic_prep"),
        task_run_id="task_123",
        review_required=True,
        artifact_ids=["artifact_1"],
        access_event_ids=["access_1"],
        result=fake_agent_result,
    )

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server.enqueue_command_in_lane", new_callable=AsyncMock) as enqueue, \
         patch("clinagent.gateway.server.ClinAgentService") as service_cls:
        service = service_cls.return_value
        service.scenario_map = {"diagnostic_prep": MagicMock()}
        service.get_scenario.return_value = MagicMock()
        service.invoke_scenario = AsyncMock(return_value=fake_scenario_result)

        async def passthrough(_lane, fn):
            return await fn()

        enqueue.side_effect = passthrough

        client = _build_client()
        response = client.post(
            "/chat",
            json={
                "task": "prepare chart brief",
                "scenario_id": "diagnostic_prep",
                "requested_by": "tester",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["scenario_id"] == "diagnostic_prep"
        assert payload["task_run_id"] == "task_123"
        assert payload["review_required"] is True
        assert payload["result"] == "scenario-output"
        service.invoke_scenario.assert_called_once()


def test_chat_with_scenario_reauth_required_returns_structured_payload():
    fake_agent_result = MagicMock(
        status="reauth_required",
        result={
            "status": "reauth_required",
            "reason": "SMART token expired and no refresh_token is available.",
            "action": "launch SMART auth",
        },
        iterations=0,
    )
    fake_scenario_result = MagicMock(
        scenario=MagicMock(id="diagnostic_prep"),
        task_run_id="task_reauth",
        review_required=True,
        artifact_ids=[],
        access_event_ids=["access_1"],
        result=fake_agent_result,
    )

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server.enqueue_command_in_lane", new_callable=AsyncMock) as enqueue, \
         patch("clinagent.gateway.server.ClinAgentService") as service_cls:
        service = service_cls.return_value
        service.scenario_map = {"diagnostic_prep": MagicMock()}
        service.get_scenario.return_value = MagicMock()
        service.invoke_scenario = AsyncMock(return_value=fake_scenario_result)

        async def passthrough(_lane, fn):
            return await fn()

        enqueue.side_effect = passthrough

        client = _build_client()
        response = client.post(
            "/chat",
            json={
                "task": "prepare chart brief",
                "scenario_id": "diagnostic_prep",
                "requested_by": "tester",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is False
        assert payload["status"] == "reauth_required"
        assert payload["result"]["action"] == "launch SMART auth"


def test_neuro_knowledge_proxy_routes_forward_json():
    fake_client = MagicMock()
    fake_client.health.return_value = {"ok": True, "counts": {"cases": 16}}
    fake_client.get_cohort.return_value = {"ok": True, "cohort": [{"patient_uid": "case-001"}]}
    fake_client.search.return_value = {"ok": True, "query": "lesion", "results": [{"patient_uid": "case-001"}]}
    fake_client.get_case.return_value = {"ok": True, "case": {"patient_uid": "case-001"}, "studies": []}
    fake_client.get_case_assets.return_value = {"ok": True, "patient_uid": "case-001", "assets": []}
    fake_client.get_study.return_value = {"ok": True, "study": {"study_uid": "study-001"}}

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server.MRRateKnowledgeServiceClient", return_value=fake_client):
        client = _build_client()

        assert client.get("/api/neuro-knowledge/health").json()["counts"]["cases"] == 16
        assert client.get("/api/neuro-knowledge/cohorts/v1").json()["cohort"][0]["patient_uid"] == "case-001"
        assert client.get("/api/neuro-knowledge/search", params={"q": "lesion"}).json()["query"] == "lesion"
        assert client.get("/api/neuro-knowledge/cases/case-001").json()["case"]["patient_uid"] == "case-001"
        assert client.get("/api/neuro-knowledge/cases/case-001/assets").json()["patient_uid"] == "case-001"
        assert client.get("/api/neuro-knowledge/studies/study-001").json()["study"]["study_uid"] == "study-001"


def test_neuro_knowledge_proxy_preserves_upstream_404():
    fake_client = MagicMock()
    request = httpx.Request("GET", "http://127.0.0.1:18120/cases/missing-case")
    response = httpx.Response(404, request=request, json={"error": "missing case"})
    fake_client.get_case.side_effect = httpx.HTTPStatusError("not found", request=request, response=response)

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server.MRRateKnowledgeServiceClient", return_value=fake_client):
        client = _build_client()
        result = client.get("/api/neuro-knowledge/cases/missing-case")

    assert result.status_code == 404
    assert result.json()["error"] == "missing case"


def test_neuro_knowledge_proxy_maps_timeout_to_503():
    fake_client = MagicMock()
    fake_client.search.side_effect = httpx.TimeoutException("timed out")

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server.MRRateKnowledgeServiceClient", return_value=fake_client):
        client = _build_client()
        result = client.get("/api/neuro-knowledge/search", params={"q": "lesion"})

    assert result.status_code == 503
    assert "timed out" in result.json()["error"].lower()


def test_neuro_knowledge_launch_downloads_once_and_then_reuses_local_bundle(tmp_path):
    fake_client = MagicMock()
    fake_client.create_analysis_launch.return_value = {"ok": True, "launch_id": "launch-001"}
    fake_client.get_analysis_launch_manifest.return_value = {
        "ok": True,
        "launch_id": "launch-001",
        "patient_uid": "P2",
        "study_uid": "S2",
        "has_segmentation": True,
        "knowledge_context": {
            "study": {"patient_age": 54, "patient_sex": "F"},
            "report": {"impression": "Enhancing lesion."},
            "study_summary": {"summary_text": "Study S2 summary."},
        },
    }
    fake_client.download_analysis_launch_file.side_effect = [b"image-bytes", b"seg-bytes"]
    fake_settings = MagicMock(
        mr_rate_base_url="http://127.0.0.1:18120",
        mr_rate_local_root=str(tmp_path / "mr-rate-local"),
        connector_timeout_s=15.0,
        dicomweb_base_url="",
        ohif_base_url="",
    )

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.load_settings", return_value=fake_settings), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server.MRRateKnowledgeServiceClient", return_value=fake_client):
        client = _build_client()
        first = client.post("/api/neuro-knowledge/launch", json={"patient_uid": "P2", "study_uid": "S2"})
        second = client.post("/api/neuro-knowledge/launch", json={"patient_uid": "P2", "study_uid": "S2"})

    assert first.status_code == 200
    assert first.json()["local_status"] == "downloaded"
    assert first.json()["local_bundle"]["age"] == 54
    assert first.json()["local_bundle"]["sex"] == "F"
    assert second.status_code == 200
    assert second.json()["local_status"] == "ready_local"
    assert second.json()["local_bundle"]["age"] == 54
    assert second.json()["local_bundle"]["sex"] == "F"
    assert fake_client.create_analysis_launch.call_count == 1


def test_neuro_report_analyze_accepts_knowledge_launch(tmp_path):
    fake_client = MagicMock()
    fake_client.create_analysis_launch.return_value = {"ok": True, "launch_id": "launch-001"}
    fake_client.get_analysis_launch_manifest.return_value = {
        "ok": True,
        "launch_id": "launch-001",
        "patient_uid": "P2",
        "study_uid": "S2",
        "has_segmentation": False,
        "knowledge_context": {
            "study": {"patient_age": 47, "patient_sex": "F"},
            "report": {"clinical_information": "Seizure workup"},
            "study_summary": {"summary_text": "Study S2 summary."},
        },
    }
    fake_client.download_analysis_launch_file.return_value = b"image-bytes"
    fake_settings = MagicMock(
        mr_rate_base_url="http://127.0.0.1:18120",
        mr_rate_local_root=str(tmp_path / "mr-rate-local"),
        connector_timeout_s=15.0,
        dicomweb_base_url="",
        ohif_base_url="",
    )

    fake_store = MagicMock()
    fake_store.find_session.return_value = None
    fake_store.analyze = AsyncMock(
        return_value={
            "session_id": "session-001",
            "patient_id": "P2",
            "study_id": "S2",
            "case_id": None,
            "mode": "vanilla",
            "requested_mode": "full_agent",
            "report": "Generated report",
            "report_sections": {
                "clinical_information": "Seizure workup",
                "technique": "T1",
                "findings": "Lesion present",
                "impression": "Abnormal lesion",
            },
            "viewer_assets": {"viewer_type": "nifti"},
            "analysis_plan": {},
            "analysis_plan_summary": {},
            "capability_profile": {},
            "capability_profile_summary": {},
            "planning_result": {},
            "dashboard_payloads": None,
            "workspace_contract": {},
            "slice_manifest": None,
            "slice_source": "on_demand",
            "raw_slices": None,
            "overlay_slices": None,
            "slices": None,
            "volumetrics": None,
        }
    )

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.load_settings", return_value=fake_settings), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server.MRRateKnowledgeServiceClient", return_value=fake_client), \
         patch("clinagent.gateway.server._get_neuro_report_demo_components", return_value=({"vanilla", "seg_overlay", "full_agent"}, fake_store)):
        client = _build_client()
        response = client.post(
            "/api/demo/neuro-report/analyze",
            data={
                "knowledge_launch_patient_uid": "P2",
                "knowledge_launch_study_uid": "S2",
                "mode": "full_agent",
            },
        )

    assert response.status_code == 200
    assert "event: complete" in response.text
    fake_store.analyze.assert_awaited_once()
    analyze_kwargs = fake_store.analyze.await_args.kwargs
    assert analyze_kwargs["age"] == 47
    assert analyze_kwargs["sex"] == "F"


def test_neuro_report_session_detail_exposes_restorable_payload():
    fake_session = {
        "patient_id": "P2",
        "study_id": "S2",
        "case_id": None,
        "source": "knowledge",
        "mode": "seg_overlay",
        "requested_mode": "full_agent",
        "age": 54,
        "sex": "F",
        "indication": "Seizure workup",
        "image_name": "image.nii.gz",
        "segmentation_name": "segmentation.nii.gz",
        "report": "Generated report",
        "report_sections": {"clinical_information": "Seizure workup", "technique": "", "findings": "", "impression": ""},
        "viewer_assets": {"viewer_type": "nifti"},
        "slice_manifest": {"mode": "on_demand", "planes": {"axial": {"slice_count": 10, "default_index": 5}}},
        "slice_source": "on_demand",
        "volumetrics": None,
        "segmentation_regions": [],
        "label_source": "vista_tsv",
        "analysis_plan": {},
        "analysis_plan_summary": {},
        "capability_profile": {},
        "capability_profile_summary": {},
        "planning_result": {},
        "workspace_contract": {},
        "dashboard_payloads": None,
        "segmentation_backend": None,
        "preprocessing_profile": None,
        "csv_export_url": None,
        "_slice_image_path": "/tmp/private/image.nii.gz",
        "_slice_seg_path": "/tmp/private/seg.nii.gz",
    }
    fake_store = MagicMock()
    fake_store.get_session.return_value = fake_session

    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")), \
         patch("clinagent.gateway.server._get_neuro_report_demo_components", return_value=({"vanilla", "seg_overlay", "full_agent"}, fake_store)):
        client = _build_client()
        response = client.get("/api/demo/neuro-report/sessions/session-123")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "session-123"
    assert payload["source"] == "knowledge"
    assert payload["age"] == 54
    assert "_slice_image_path" not in payload


def test_queue_routes_expose_workspace_and_case():
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()

        queue_page = client.get("/queue-demo")
        assert queue_page.status_code == 200
        assert "Queue Triage" in queue_page.text

        workspace_response = client.get("/api/queue/workspace")
        assert workspace_response.status_code == 200
        payload = workspace_response.json()
        assert payload["default_case_id"]
        assert payload["workspace"]["title"]

        case_response = client.get(f"/api/queue/cases/{payload['default_case_id']}")
        assert case_response.status_code == 200
        assert case_response.json()["workflow_id"] in {"high_risk_referral_triage", "post_discharge_followup"}


def test_report_quality_routes_expose_workspace_and_case():
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()

        page_response = client.get("/report-quality-demo")
        assert page_response.status_code == 200
        assert "Report Quality" in page_response.text

        workspace_response = client.get("/api/report-quality/workspace")
        assert workspace_response.status_code == 200
        payload = workspace_response.json()
        assert payload["default_case_id"]
        assert payload["workspace"]["status_label"]
        assert payload["workspace"]["report_html"].startswith("<!doctype html>")

        case_response = client.get(f"/api/report-quality/cases/{payload['default_case_id']}")
        assert case_response.status_code == 200
        assert case_response.json()["focus"]


def test_queue_routes_cover_rerun_review_explain_and_errors():
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()

        rerun_response = client.post("/api/queue/rerun", json={"case_id": "triage_case_001"})
        assert rerun_response.status_code == 200
        assert rerun_response.json()["workflow_id"] in {"high_risk_referral_triage", "post_discharge_followup"}

        review_response = client.post(
            "/api/queue/review",
            json={"case_id": "triage_case_001", "action": "approve", "comment": "Fast-track confirmed."},
        )
        assert review_response.status_code == 200
        assert review_response.json()["review"]["status"] == "approve"

        explain_response = client.post(
            "/api/queue/explain",
            json={"case_id": "triage_case_001", "question": "Why was this queued urgently?"},
        )
        assert explain_response.status_code == 200
        assert explain_response.json()["case_id"] == "triage_case_001"

        assert client.post("/api/queue/rerun", content="{").status_code == 400
        assert client.post("/api/queue/review", json={"case_id": "triage_case_001"}).status_code == 400
        assert client.post("/api/queue/explain", json={"case_id": "triage_case_001"}).status_code == 400
        assert client.post("/api/queue/rerun", json={"case_id": "missing-case"}).status_code == 404


def test_diagnosis_routes_expose_workspace_and_case():
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()

        workspace_response = client.get("/api/diagnosis/workspace")
        assert workspace_response.status_code == 200
        payload = workspace_response.json()
        assert payload["default_case_id"]
        assert payload["workspace"]["title"]

        case_response = client.get(f"/api/diagnosis/cases/{payload['default_case_id']}")
        assert case_response.status_code == 200
        assert case_response.json()["workflow_id"] == "missed_vertebral_fracture_detection"


def test_diagnosis_routes_cover_rerun_review_explain_and_errors():
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()

        rerun_response = client.post("/api/diagnosis/rerun", json={"case_id": "md_case_001"})
        assert rerun_response.status_code == 200
        assert rerun_response.json()["workflow_id"] == "missed_vertebral_fracture_detection"

        review_response = client.post(
            "/api/diagnosis/review",
            json={"case_id": "md_case_001", "action": "approve", "comment": "Workup started."},
        )
        assert review_response.status_code == 200
        assert review_response.json()["review"]["status"] == "approve"

        explain_response = client.post(
            "/api/diagnosis/explain",
            json={"case_id": "md_case_001", "question": "Why was this escalated?"},
        )
        assert explain_response.status_code == 200
        assert explain_response.json()["workspace"]["id"] == "md_case_001"

        assert client.post("/api/diagnosis/rerun", content="{").status_code == 400
        assert client.post("/api/diagnosis/review", json={"case_id": "md_case_001"}).status_code == 400
        assert client.post("/api/diagnosis/explain", json={"case_id": "md_case_001"}).status_code == 400
        assert client.post("/api/diagnosis/rerun", json={"case_id": "missing-case"}).status_code == 404


def test_screening_routes_expose_workspace_and_case():
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()

        workspace_response = client.get("/api/screening/workspace")
        assert workspace_response.status_code == 200
        payload = workspace_response.json()
        assert payload["default_case_id"]
        assert payload["workspace"]["title"]

        case_response = client.get(f"/api/screening/cases/{payload['default_case_id']}")
        assert case_response.status_code == 200
        assert case_response.json()["workflow_id"] == "screening_gap_positive_fit_followup"


def test_screening_routes_cover_rerun_review_explain_and_errors():
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()

        rerun_response = client.post("/api/screening/rerun", json={"case_id": "sg_case_001"})
        assert rerun_response.status_code == 200
        assert rerun_response.json()["workflow_id"] == "screening_gap_positive_fit_followup"

        review_response = client.post(
            "/api/screening/review",
            json={"case_id": "sg_case_001", "action": "approve", "comment": "Navigator outreach started."},
        )
        assert review_response.status_code == 200
        assert review_response.json()["review"]["status"] == "approve"

        explain_response = client.post(
            "/api/screening/explain",
            json={"case_id": "sg_case_001", "question": "Why is this gap still open?"},
        )
        assert explain_response.status_code == 200
        assert explain_response.json()["workspace"]["id"] == "sg_case_001"

        assert client.post("/api/screening/rerun", content="{").status_code == 400
        assert client.post("/api/screening/review", json={"case_id": "sg_case_001"}).status_code == 400
        assert client.post("/api/screening/explain", json={"case_id": "sg_case_001"}).status_code == 400
        assert client.post("/api/screening/rerun", json={"case_id": "missing-case"}).status_code == 404
