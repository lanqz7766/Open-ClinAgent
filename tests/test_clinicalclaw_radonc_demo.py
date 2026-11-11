import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from clinagent.families.radonc import radonc_plan_demo_store
from clinagent.families.radonc.airt import default_airt_patient_dir, load_airt_iteration_bundle, parse_dvh_file
from clinagent.families.radonc.connectors import AirtMockPlanningConnector
from clinagent.families.radonc.engine import (
    LLMAdvisor,
    OptimizationOrchestrator,
    RuleEngine,
    apply_planner_command_update,
)


@pytest.fixture(autouse=True)
def isolated_gateway(monkeypatch, tmp_path):
    # These tests exercise the simulated planner, not an external LLM provider.
    monkeypatch.setattr("clinagent.gateway.server.create_provider", lambda *args: MagicMock())
    monkeypatch.setenv("CLINAGENT_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("CLINAGENT_DATABASE_PATH", str(tmp_path / "state.sqlite3"))
    monkeypatch.setenv("CLINAGENT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CLINAGENT_REQUIRE_USER_AUTH", "false")
    monkeypatch.setenv("CLINAGENT_PREVIEW_SCOPE", "full")


def test_radonc_demo_snapshot_exposes_default_session_contract():
    snapshot = radonc_plan_demo_store.snapshot()
    session = snapshot["session"]

    assert snapshot["default_patient_id"] == "Patient001"
    assert snapshot["default_session_id"] == "radonc-plan-apbi-patient001"
    assert snapshot["active_patient_id"] == "Patient001"
    assert session["id"] == snapshot["default_session_id"]
    assert session["data_source_type"] == "airt_mock"
    assert session["data_source_id"] == "Patient001"
    assert session["start_iteration_number"] == 1
    assert session["reference_iteration_number"] == 2
    assert session["simulation_max_iterations"] == 20
    assert session["planning_result"]["recommended_workflow"] == "radonc_plan_optimization"
    assert session["workspace_contract"]["module"] == "radonc_plan"
    assert session["workspace_contract"]["workflow_family"] == "radonc"
    assert session["workspace_contract"]["dashboard_profile"] == "plan_optimization"
    assert session["workspace_contract"]["workspace_url"].endswith("patient_id=Patient001")


def test_radonc_demo_store_discovers_multiple_patients():
    patients = radonc_plan_demo_store.get_patients()

    assert patients["default_patient_id"] == "Patient001"
    assert "Patient001" in [item["id"] for item in patients["patients"]]
    assert "Patient002" in [item["id"] for item in patients["patients"]]
    patient_two = next(item for item in patients["patients"] if item["id"] == "Patient002")
    assert patient_two["default_session_id"] == "radonc-plan-patient002"
    assert patient_two["available_iterations"] == [1, 2]


def test_radonc_demo_snapshot_supports_patient_queries():
    snapshot = radonc_plan_demo_store.snapshot(patient_id="Patient002")
    session = snapshot["session"]

    assert snapshot["active_patient_id"] == "Patient002"
    assert session["id"] == "radonc-plan-patient002"
    assert session["data_source_id"] == "Patient002"
    assert session["workspace_contract"]["workspace_url"].endswith("patient_id=Patient002")


def test_airt_loader_parses_goal_and_dvh_data():
    bundle = load_airt_iteration_bundle(default_airt_patient_dir(), 1)
    dvh_map = parse_dvh_file(default_airt_patient_dir() / "Output_Iteration001_DVH.dvh")

    assert bundle.goals
    assert any(item.roi == "PTV_Eval_APBI_2600" for item in bundle.goals)
    assert bundle.goal_status
    assert any(item.roi == "Heart" for item in bundle.goal_status)
    assert "PTV_Eval_APBI_2600" in dvh_map


def test_radonc_rule_engine_suggests_missing_oar_objectives():
    session = radonc_plan_demo_store.get_session_model("radonc-plan-apbi-patient001")
    connector = AirtMockPlanningConnector(
        patient_dir=default_airt_patient_dir(),
        start_iteration=int(session.connector_state.get("current_iteration") or 1),
        current_objectives=[item for item in session.current_objectives if item.roi != "PTV_Eval_APBI_2600"],
        data_source_id=session.data_source_id,
    )
    dvh_map = {item.roi: item for item in asyncio.run(connector.get_dvh())}
    goal_status = asyncio.run(connector.get_goal_status())
    objectives = [item for item in session.current_objectives if item.roi != "PTV_Eval_APBI_2600"]

    resolved_status, suggestions = RuleEngine().analyze(
        goals=session.goals,
        goal_status=goal_status,
        current_objectives=objectives,
        dvh_map=dvh_map,
    )

    assert resolved_status
    assert any(item.objective.roi == "PTV_Eval_APBI_2600" for item in suggestions)


def test_radonc_llm_advisor_interprets_planner_command():
    session = radonc_plan_demo_store.get_session_model("radonc-plan-apbi-patient001")
    suggestions = asyncio.run(LLMAdvisor().interpret_command("Heart is too hot, protect coverage.", session.goals, session.current_objectives))

    assert any(item.objective.roi == "Heart" for item in suggestions)


def test_radonc_chat_command_can_update_goal_and_objective_targets():
    session = radonc_plan_demo_store.get_session_model("radonc-plan-apbi-patient001")

    update = apply_planner_command_update("Set Heart mean dose limit to 8 Gy.", session.goals, session.current_objectives)

    assert update is not None
    goals, objectives, suggestions, response_text = update
    heart_goal = next(item for item in goals if item.roi == "Heart" and item.metric == "Dmean")
    heart_objective = next(item for item in objectives if item.roi == "Heart" and item.objective_type == "Mean Dose")

    assert heart_goal.value == 800.0
    assert heart_objective.dose == 800.0
    assert suggestions[0].objective.roi == "Heart"
    assert "Heart" in response_text


def test_radonc_chat_command_can_update_target_coverage():
    session = radonc_plan_demo_store.get_session_model("radonc-plan-apbi-patient001")

    update = apply_planner_command_update("Increase target coverage to V26Gy >= 98%.", session.goals, session.current_objectives)

    assert update is not None
    goals, objectives, _, _ = update
    target_goal = next(item for item in goals if item.roi == "PTV_Eval_APBI_2600" and item.metric == "V2600cGy")
    target_objective = next(item for item in objectives if item.roi == "PTV_Eval_APBI_2600")

    assert target_goal.operator == ">="
    assert target_goal.value == 98.0
    assert target_objective.objective_type == "Min DVH"
    assert target_objective.dose == 2600.0
    assert target_objective.volume == 98.0


def test_radonc_orchestrator_runs_single_iteration_and_generates_simulated_step():
    radonc_plan_demo_store.reset_session("radonc-plan-apbi-patient001")
    session = radonc_plan_demo_store.get_session_model("radonc-plan-apbi-patient001")
    connector = AirtMockPlanningConnector(
        patient_dir=default_airt_patient_dir(),
        start_iteration=int(session.connector_state.get("current_iteration") or 1),
        current_objectives=session.current_objectives,
        data_source_id=session.data_source_id,
    )
    orchestrator = OptimizationOrchestrator(
        session_id=session.id,
        connector=connector,
        goals=session.goals,
        current_objectives=session.current_objectives,
        current_dvh_data=session.dvh_data,
        start_goal_status=session.start_goal_status,
        start_dvh_data=session.start_dvh_data,
        reference_goal_status=session.reference_goal_status,
        reference_dvh_data=session.reference_dvh_data,
        max_iterations=session.simulation_max_iterations,
        plateau_threshold=session.plateau_threshold,
        start_iteration_number=session.start_iteration_number,
        reference_iteration_number=session.reference_iteration_number,
    )

    iteration = asyncio.run(orchestrator.run_iteration())
    metadata = asyncio.run(connector.get_plan_metadata())

    assert iteration.number == 1
    assert iteration.bundle_kind == "simulated"
    assert iteration.goals_total >= 1
    assert iteration.goal_status
    assert iteration.objectives_snapshot
    assert iteration.reference_gap.overall_percent >= 0
    assert metadata["connector_state"]["current_iteration"] == 1
    assert metadata["connector_state"]["reference_iteration"] == 2


def test_radonc_demo_store_can_reset_patient002_session():
    session = radonc_plan_demo_store.reset_session("radonc-plan-patient002")

    assert session["id"] == "radonc-plan-patient002"
    assert session["data_source_id"] == "Patient002"
    assert session["status"] == "ready"


def test_radonc_patient_endpoints_support_patient_id_queries():
    from clinagent.gateway.server import create_app

    app, _, _ = create_app()
    client = TestClient(app)

    patients_response = client.get("/api/demo/radonc-plan/patients")
    assert patients_response.status_code == 200
    patients_payload = patients_response.json()
    assert "Patient001" in [item["id"] for item in patients_payload["patients"]]
    assert "Patient002" in [item["id"] for item in patients_payload["patients"]]

    session_response = client.get("/api/demo/radonc-plan/session", params={"patient_id": "Patient002"})
    assert session_response.status_code == 200
    session_payload = session_response.json()
    assert session_payload["active_patient_id"] == "Patient002"
    assert session_payload["session"]["data_source_id"] == "Patient002"
    assert session_payload["session"]["id"] == "radonc-plan-patient002"


def test_radonc_patient_endpoint_rejects_unknown_patient():
    from clinagent.gateway.server import create_app

    app, _, _ = create_app()
    client = TestClient(app)

    response = client.get("/api/demo/radonc-plan/session", params={"patient_id": "Patient404"})

    assert response.status_code == 404
    assert response.json() == {"error": "Unknown radonc patient: Patient404"}


def test_radonc_chat_command_can_apply_and_run_single_iteration():
    from clinagent.gateway.server import create_app

    radonc_plan_demo_store.reset_session("radonc-plan-apbi-patient001")
    app, _, _ = create_app()
    client = TestClient(app)

    with client.websocket_connect("/api/demo/radonc-plan/ws/radonc-plan-apbi-patient001") as websocket:
        initial = websocket.receive_json()
        assert initial["type"] == "session_snapshot"

        websocket.send_json(
            {
                "type": "command",
                "text": "Set Heart mean dose limit to 8 Gy.",
                "run_after_apply": True,
            }
        )

        final_snapshot = None
        for _ in range(16):
            payload = websocket.receive_json()
            if payload["type"] == "session_snapshot":
                final_snapshot = payload["session"]
                command = final_snapshot["command_history"][-1]
                if command["status"] == "executed" and final_snapshot["iterations"]:
                    break

    assert final_snapshot is not None
    heart_objective = next(item for item in final_snapshot["current_objectives"] if item["roi"] == "Heart" and item["objective_type"] == "Mean Dose")
    latest_command = final_snapshot["command_history"][-1]

    assert heart_objective["dose"] == 800.0
    assert latest_command["status"] == "executed"
    assert latest_command["applied_in_iteration"] == 1
    assert latest_command["applied_changes"]
    assert final_snapshot["iterations"]


def test_radonc_manual_objective_edit_can_apply_and_run_single_iteration():
    from clinagent.gateway.server import create_app

    radonc_plan_demo_store.reset_session("radonc-plan-apbi-patient001")
    app, _, _ = create_app()
    client = TestClient(app)

    with client.websocket_connect("/api/demo/radonc-plan/ws/radonc-plan-apbi-patient001") as websocket:
        initial = websocket.receive_json()
        assert initial["type"] == "session_snapshot"

        websocket.send_json(
            {
                "type": "update_objectives",
                "updates": [
                    {
                        "roi": "Heart",
                        "objective_type": "Max EUD",
                        "dose": 80.0,
                        "weight": 14.0,
                    }
                ],
                "run_after_apply": True,
            }
        )

        final_snapshot = None
        for _ in range(16):
            payload = websocket.receive_json()
            if payload["type"] == "session_snapshot":
                final_snapshot = payload["session"]
                latest_command = final_snapshot["command_history"][-1]
                if latest_command["status"] == "executed" and final_snapshot["iterations"]:
                    break

    assert final_snapshot is not None
    heart_objective = next(item for item in final_snapshot["current_objectives"] if item["roi"] == "Heart" and item["objective_type"] == "Max EUD")
    latest_command = final_snapshot["command_history"][-1]

    assert heart_objective["dose"] == 80.0
    assert heart_objective["weight"] == 14.0
    assert latest_command["status"] == "executed"
    assert latest_command["applied_in_iteration"] == 1
    assert latest_command["applied_changes"]
