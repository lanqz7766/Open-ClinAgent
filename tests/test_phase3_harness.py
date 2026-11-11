import os
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from clinagent.platform.execution_profiles import build_route_runtime, resolve_tool_policy
from clinagent.platform.family_registry import get_family_registry_entry, get_workflow_registry_entry
from clinagent.platform.memory_harness import (
    build_memory_context,
    build_reviewed_memory_context,
    derive_reviewed_memory_defaults,
    summarize_memory_context,
)
from clinagent.families.shared.report_quality_demo import report_quality_demo_store
from clinagent.families.shared.report_quality_intake import (
    build_report_quality_analysis_plan,
    build_report_quality_capability_profile,
    build_report_quality_planning_result,
    normalize_report_quality_context,
)
from clinagent.platform.store import SQLiteStore


def _build_client(tmp_path):
    from clinagent.gateway.server import create_app

    with patch.dict(
        os.environ,
        {
            "CLINAGENT_AUTH_DB": str(tmp_path / "auth.sqlite3"),
            "CLINAGENT_PREVIEW_SCOPE": "",
            "CLINAGENT_REQUIRE_USER_AUTH": "0",
        },
    ), patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        app, _, _ = create_app()
        return TestClient(app)


def test_report_quality_planning_result_is_generic_and_executable():
    context = normalize_report_quality_context(
        request_text="Check this radiology report for identifiers and terminology issues.",
        source_kind="curated_case",
        case_id="report_quality_clean_neuro",
        report_text="FINDINGS: No acute intracranial abnormality.",
        template_id="radiology",
        compliance_profile="radiology",
    )
    profile = build_report_quality_capability_profile(context)
    plan = build_report_quality_analysis_plan(context, profile)
    planning_result = build_report_quality_planning_result(context, profile, plan)

    assert plan.can_execute is True
    assert plan.workflow_family == "review"
    assert plan.analysis_track == "review"
    assert plan.dashboard_profile == "report_review"
    assert planning_result.recommended_workflow == "report_quality_review"
    assert planning_result.workflow_family == "review"
    assert planning_result.workflow_id == "review.report_review"
    assert planning_result.family == "review"
    assert planning_result.track == "review"
    assert planning_result.dashboard_profile == "report_review"
    assert planning_result.analysis_plan_summary.viewer_type == "workspace"


def test_report_quality_snapshot_exposes_harness_contract_fields():
    snapshot = report_quality_demo_store.snapshot()
    workspace = snapshot["workspace"]

    assert workspace["planning_result"]["recommended_workflow"] == "report_quality_review"
    assert workspace["workspace_contract"]["module"] == "report_quality"
    assert workspace["workspace_contract"]["workflow_family"] == "review"
    assert workspace["workspace_contract"]["analysis_track"] == "review"
    assert workspace["workspace_contract"]["dashboard_profile"] == "report_review"
    assert workspace["analysis_plan_summary"]["runtime_mode"] == "clinical_safe"


def test_build_route_runtime_exposes_task_policy_and_mcp_registry():
    runtime = build_route_runtime(
        {
            "workflow_id": "report_quality_review",
            "workflow_family": "review",
            "track": "review",
            "primary_goal": "report_review",
            "dashboard_profile": "report_review",
            "context_sources": ["report_quality_demo_store"],
            "workflow": {"id": "report_quality_review", "title": "Report Quality Review", "module": "report_quality"},
            "target_module": "report_quality",
            "suggested_module": "report_quality",
            "confidence": 0.9,
            "reason": "Detected report QA intent.",
            "next_action": "Open report quality workspace.",
            "alternatives": [],
            "fallback": False,
        }
    )

    assert runtime["profile"]["policy_mode"] == "clinical_safe"
    assert runtime["profile"]["workflow_family"] == "review"
    assert runtime["task_summary"]
    assert runtime["tool_policy"]["mode"] == "clinical_safe"
    assert runtime["tool_policy"]["workflow_family"] == "review"
    assert runtime["tool_policy"]["primary_goal"] == "report_review"
    assert runtime["route"]["workflow_task_id"] == "review.report_review"
    assert runtime["task_summary"][0]["primary_goal"] == "report_review"
    assert runtime["stage_summary"][0]["primary_goal"] == "report_review"
    assert runtime["mcp_servers"]
    assert runtime["mcp_snapshot"]["workflow_family"] == "review"
    assert runtime["family_registry"]["family_id"] == "review"
    assert runtime["workflow_registry"]["workflow_id"] == "review.report_review"


def test_family_and_workflow_registry_expose_neuro_and_radonc_contracts():
    neuro = get_family_registry_entry("neuro")
    radonc = get_family_registry_entry("radonc")
    response = get_workflow_registry_entry("neuro.response_review")
    dose_prediction = get_workflow_registry_entry("radonc.dose_prediction")
    plan_optimization = get_workflow_registry_entry("radonc.plan_optimization")

    assert neuro is not None
    assert neuro["flagship"] is True
    assert "neuro.response_review" in neuro["supported_workflows"]
    assert radonc is not None
    assert "radonc.plan_review" in radonc["supported_workflows"]
    assert "radonc.plan_optimization" in radonc["supported_workflows"]
    assert response is not None
    assert response["runtime_workflow_id"] == "neuro_report"
    assert response["dashboard_profile"] == "longitudinal_response"
    assert dose_prediction is not None
    assert dose_prediction["executable"] is False
    assert plan_optimization is not None
    assert plan_optimization["runtime_workflow_id"] == "radonc_plan_optimization"
    assert plan_optimization["dashboard_profile"] == "plan_optimization"
    assert plan_optimization["executable"] is True


def test_sqlite_store_supports_session_workflow_and_entity_memory(tmp_path):
    store = SQLiteStore(str(tmp_path / "phase3-memory.db"))
    store.save_user_memory(user_id="user-1", payload={"preferred_dashboard_profile": "volumetry"})
    store.save_session_memory(session_id="session-1", workflow_id="neuro_report", payload={"summary": "demo"})
    store.save_workflow_memory(workflow_id="report_quality_review", memory_key="default", payload={"case_id": "case-1"})
    store.save_entity_memory(entity_type="neuro_study", entity_id="patient:study", payload={"z_score": 1.2})
    store.save_proposed_pattern_memory(workflow_family="neuro", pattern_id="response-bundle", payload={"tool_bundle": ["brain_met_response_tracker"]})
    store.save_reviewed_pattern_memory(workflow_family="neuro", pattern_id="structural-bundle", payload={"tool_bundle": ["volumetric_analysis"]})

    assert store.get_user_memory("user-1")["payload"]["preferred_dashboard_profile"] == "volumetry"
    assert store.get_session_memory("session-1")["payload"]["summary"] == "demo"
    assert store.get_workflow_memory("report_quality_review", "default")["payload"]["case_id"] == "case-1"
    assert store.get_entity_memory("neuro_study", "patient:study")["payload"]["z_score"] == 1.2
    assert store.get_proposed_pattern_memory("neuro", "response-bundle")["payload"]["tool_bundle"] == ["brain_met_response_tracker"]
    assert store.get_reviewed_pattern_memory("neuro", "structural-bundle")["payload"]["tool_bundle"] == ["volumetric_analysis"]


def test_memory_harness_summarizes_structured_retrieval_order(tmp_path):
    store = SQLiteStore(str(tmp_path / "phase3-memory-harness.db"))
    store.save_user_memory(user_id="user-7", payload={"preferred_dashboard_profile": "report_review"})
    store.save_session_memory(session_id="session-7", workflow_id="neuro_report", payload={"status": "running"})
    store.save_workflow_memory(workflow_id="neuro_report", memory_key="defaults", payload={"track": "structural"})
    store.save_entity_memory(entity_type="neuro_study", entity_id="patient:study", payload={"z_score": 1.8})

    with patch("clinagent.platform.memory_harness.get_harness_memory_store", return_value=store):
        memory_context = build_memory_context(
            entity_keys=[("neuro_study", "patient:study")],
            workflow_keys=[("neuro_report", "defaults")],
            user_id="user-7",
            session_id="session-7",
        )
        summary = summarize_memory_context(memory_context)

    assert memory_context["retrieval_order"] == ["entity", "workflow", "user", "session"]
    assert summary["entity_memory_count"] == 1
    assert summary["workflow_memory_count"] == 1
    assert summary["has_user_memory"] is True
    assert summary["has_session_memory"] is True


def test_reviewed_memory_defaults_only_influence_preferences(tmp_path):
    store = SQLiteStore(str(tmp_path / "phase3-reviewed-memory.db"))
    store.save_user_memory(
        user_id="user-9",
        payload={
            "preferred_dashboard_profile": "report_review",
            "autorun_examples": True,
            "output_style": "compact_clinical",
        },
    )
    store.save_workflow_memory(
        workflow_id="neuro_report",
        memory_key="examples",
        payload={"default_case_id": "case-1"},
    )
    store.save_reviewed_pattern_memory(
        workflow_family="neuro",
        pattern_id="review_default_bundle",
        payload={
            "tool_bundle": ["report_section_parser"],
            "dashboard_profile": "report_review",
            "review_lane_default_open": True,
        },
    )

    with patch("clinagent.platform.memory_harness.get_harness_memory_store", return_value=store):
        context = build_reviewed_memory_context(
            workflow_family="neuro",
            reviewed_pattern_ids=["review_default_bundle"],
            workflow_keys=[("neuro_report", "examples")],
            user_id="user-9",
        )
        defaults = derive_reviewed_memory_defaults(context)

    assert defaults["preferred_dashboard_profile"] == "report_review"
    assert defaults["autorun_examples"] is True
    assert defaults["review_lane_default_open"] is True
    assert defaults["output_style"] == "compact_clinical"
    assert defaults["reviewed_tool_bundles"][0]["tool_bundle"] == ["report_section_parser"]


def test_goal_aware_tool_policy_for_neuro_response():
    tool_policy = resolve_tool_policy(
        "neuro_report",
        workflow_family="neuro",
        primary_goal="response_review",
        policy_mode="demo",
    )

    assert tool_policy["mode"] == "demo"
    assert tool_policy["workflow_family"] == "neuro"
    assert tool_policy["primary_goal"] == "response_review"
    assert tool_policy["allowed_tools"] == [
        "lesion_segmentation_ingestion",
        "lesion_volume_calculator",
        "response_delta_calculator",
        "longitudinal_response_synthesizer",
    ]
    assert "brain_segmentation" in tool_policy["blocked_tools"]


def test_execute_stream_returns_report_quality_artifact_with_planning(tmp_path):
    client = _build_client(tmp_path)
    with patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        response = client.post("/api/demo/execute-stream", json={"message": "Run quality review on this radiology report draft"})

    assert response.status_code == 200
    assert "event: routed" in response.text
    assert "event: done" in response.text
    assert "report_quality_review" in response.text
    assert "report_review" in response.text


def test_build_route_runtime_supports_radonc_plan_optimization():
    runtime = build_route_runtime(
        {
            "workflow_id": "radonc_plan_optimization",
            "workflow_family": "radonc",
            "track": "optimization",
            "primary_goal": "plan_optimization",
            "dashboard_profile": "plan_optimization",
            "context_sources": ["radonc_context", "mock_tps_connector"],
            "workflow": {"id": "radonc_plan_optimization", "title": "RadOnc Plan Optimization", "module": "radonc_plan"},
            "target_module": "radonc_plan",
            "suggested_module": "radonc_plan",
            "confidence": 0.92,
            "reason": "Detected radiation planning optimization intent.",
            "next_action": "Open the radonc planning workspace.",
            "alternatives": [],
            "fallback": False,
        }
    )

    assert runtime["profile"]["policy_mode"] == "planning_controlled_writeback"
    assert runtime["profile"]["workflow_family"] == "radonc"
    assert runtime["tool_policy"]["primary_goal"] == "plan_optimization"
    assert runtime["route"]["workflow_task_id"] == "radonc.plan_optimization"
    assert runtime["mcp_snapshot"]["workflow_family"] == "radonc"
