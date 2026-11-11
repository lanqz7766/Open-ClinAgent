from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
import re
from threading import RLock
from typing import Any

from clinagent.families.radonc.airt import discover_airt_iterations, load_airt_iteration_bundle
from clinagent.families.radonc.engine import build_reference_comparison
from clinagent.families.radonc.models import (
    BundleSummary,
    ComparisonSummary,
    DVHSnapshot,
    GoalStatus,
    ObjectiveResult,
    ObjectiveSuggestion,
    OptimizationIteration,
    PlanObjective,
    PlanOptimizationSession,
)
from clinagent.platform.execution_profiles import build_workflow_runtime_bundle
from clinagent.platform.harness import build_workspace_contract
from clinagent.platform.local_data import discover_radonc_demo_patients
from clinagent.platform.mcp_registry import build_context_availability_summary
from clinagent.platform.memory_harness import (
    build_reviewed_memory_context,
    derive_reviewed_memory_defaults,
    save_entity_memory,
    save_reviewed_pattern_memory,
    save_session_memory,
    save_user_memory,
    save_workflow_memory,
)
from clinagent.families.radonc.intake import (
    build_radonc_analysis_plan,
    build_radonc_capability_profile,
    build_radonc_planning_result,
    normalize_radonc_context,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _source_label_for_patient_dir(patient_dir: Path) -> str:
    parent_name = patient_dir.parent.name.lower()
    if parent_name == "anony":
        return "anony"
    if parent_name == "test_data":
        return "test_data"
    return "custom"


def _build_session_id(patient_id: str) -> str:
    if patient_id == "Patient001":
        return "radonc-plan-apbi-patient001"
    slug = re.sub(r"[^a-z0-9]+", "-", patient_id.lower()).strip("-")
    return f"radonc-plan-{slug or 'demo'}"


class RadOncPlanDemoStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._default_patient_id = "Patient001"
        self._default_session_id = ""
        self._patients: dict[str, dict[str, Any]] = {}
        self._patient_to_session: dict[str, str] = {}
        self._session_to_patient: dict[str, str] = {}
        self._sessions: dict[str, PlanOptimizationSession] = {}
        save_reviewed_pattern_memory(
            "radonc",
            "plan_optimization_default_bundle",
            {
                "dashboard_profile": "plan_optimization",
                "review_lane_default_open": False,
                "tool_bundle": [
                    "rt_plan_context_loader",
                    "dvh_constraint_analyzer",
                    "objective_adjustment_engine",
                    "plan_tradeoff_synthesizer",
                ],
            },
        )
        self._reload_patients()

    def _reload_patients(self) -> None:
        discovered = discover_radonc_demo_patients()
        patient_records: dict[str, dict[str, Any]] = {}
        for patient_id, patient_dir in discovered.items():
            available_iterations = discover_airt_iterations(patient_dir)
            if not available_iterations:
                continue
            patient_records[patient_id] = {
                "id": patient_id,
                "path": patient_dir,
                "source": _source_label_for_patient_dir(patient_dir),
                "available_iterations": available_iterations,
            }

        if not patient_records:
            self._patients = {}
            self._sessions = {}
            self._patient_to_session = {}
            self._session_to_patient = {}
            self._default_patient_id = ""
            self._default_session_id = ""
            return

        default_patient_id = "Patient001" if "Patient001" in patient_records else sorted(patient_records)[0]
        sessions: dict[str, PlanOptimizationSession] = {}
        patient_to_session: dict[str, str] = {}
        session_to_patient: dict[str, str] = {}

        self._patients = patient_records
        self._default_patient_id = default_patient_id

        for patient_id in sorted(patient_records):
            session = self._build_session(patient_id)
            sessions[session.id] = session
            patient_to_session[patient_id] = session.id
            session_to_patient[session.id] = patient_id

        self._sessions = sessions
        self._patient_to_session = patient_to_session
        self._session_to_patient = session_to_patient
        self._default_session_id = patient_to_session[default_patient_id]
        self._persist_session(self._sessions[self._default_session_id])

    def _build_session(self, patient_id: str) -> PlanOptimizationSession:
        patient_record = self._patients[patient_id]
        patient_dir = patient_record["path"]
        available_iterations = patient_record["available_iterations"]
        session_id = _build_session_id(patient_id)

        start_bundle = load_airt_iteration_bundle(patient_dir, available_iterations[0])
        reference_bundle = load_airt_iteration_bundle(patient_dir, available_iterations[-1])
        context = normalize_radonc_context(
            request_text="Optimize this partial-breast APBI plan using the current protocol constraints and DVH trade-offs.",
            source_kind="curated_case",
            session_id=session_id,
            patient_id=f"AIRT Mock {patient_id}",
            treatment_site="Partial breast radiotherapy",
            has_rt_plan=True,
            has_structures=True,
            has_dose_or_dvh=True,
            has_protocol=True,
            connector_writable=True,
        )
        profile = build_radonc_capability_profile(context)
        analysis_plan = build_radonc_analysis_plan(context, profile)
        planning_result = build_radonc_planning_result(context, profile, analysis_plan)
        memory_context = build_reviewed_memory_context(
            workflow_family="radonc",
            reviewed_pattern_ids=["plan_optimization_default_bundle"],
            workflow_keys=[("radonc_plan_optimization", "default_snapshot")],
            user_id="default_demo_user",
            session_id=session_id,
        )
        planner_defaults = derive_reviewed_memory_defaults(memory_context)
        runtime_bundle = build_workflow_runtime_bundle(
            "radonc_plan_optimization",
            workflow_family="radonc",
            primary_goal="plan_optimization",
            dashboard_profile="plan_optimization",
            track="optimization",
            context_sources=profile.context_sources,
            policy_mode="planning_controlled_writeback",
        )
        connector_state = {
            "bundle_kind": "observed",
            "current_iteration": available_iterations[0],
            "reference_iteration": available_iterations[-1],
            "current_simulated_iteration": 0,
            "next_iteration_available": True,
            "available_iterations": deepcopy(available_iterations),
            "replay_exhausted": False,
            "can_run_current": True,
        }

        _, comparison_metrics, comparison_summary = build_reference_comparison(
            goals=deepcopy(start_bundle.goals),
            start_goal_status=deepcopy(start_bundle.goal_status),
            current_goal_status=deepcopy(start_bundle.goal_status),
            reference_goal_status=deepcopy(reference_bundle.goal_status),
            current_dvh_data=deepcopy(start_bundle.dvh_data),
            reference_dvh_data=deepcopy(reference_bundle.dvh_data),
            current_label=f"Observed Iteration {available_iterations[0]}",
            reference_label=f"Observed Iteration {available_iterations[-1]}",
        )

        session = PlanOptimizationSession(
            id=session_id,
            title="APBI Plan Optimization",
            subtitle="Observed start/reference bundles with a hybrid simulated optimization loop inside the ClinAgent workspace shell.",
            patient_label=f"{patient_id} · AIRT mock case",
            treatment_site="Breast RadOnc",
            protocol_name=str(start_bundle.plan_metadata.get("protocol_name", "Partial breast protocol")),
            status="ready",
            control_mode="auto",
            connector_type="airt_mock",
            connector_writable=True,
            data_source_type="airt_mock",
            data_source_id=patient_id,
            available_iterations=deepcopy(available_iterations),
            start_iteration_number=available_iterations[0],
            reference_iteration_number=available_iterations[-1],
            simulation_enabled=True,
            simulation_max_iterations=20,
            simulation_reference_mode="iter1_iter2_reference",
            connector_state=connector_state,
            max_iterations=20,
            plateau_threshold=5,
            title_badge="RadOnc flagship",
            goals=deepcopy(start_bundle.goals),
            goal_status=deepcopy(start_bundle.goal_status),
            start_goal_status=deepcopy(start_bundle.goal_status),
            reference_goal_status=deepcopy(reference_bundle.goal_status),
            current_objectives=deepcopy(start_bundle.output_objectives),
            start_objectives=deepcopy(start_bundle.output_objectives),
            reference_objectives=deepcopy(reference_bundle.output_objectives),
            dvh_data=deepcopy(start_bundle.dvh_data),
            start_dvh_data=deepcopy(start_bundle.dvh_data),
            reference_dvh_data=deepcopy(reference_bundle.dvh_data),
            objective_results=deepcopy(start_bundle.objective_results),
            start_objective_results=deepcopy(start_bundle.objective_results),
            reference_objective_results=deepcopy(reference_bundle.objective_results),
            plan_metadata={
                "protocol_name": str(start_bundle.plan_metadata.get("protocol_name", "")),
                "case_label": patient_id,
                "connector_label": "AIRT mock connector",
                "start_iteration": available_iterations[0],
                "reference_iteration": available_iterations[-1],
                "available_iterations": len(available_iterations),
                "patient_id": patient_id,
                "patient_source": patient_record["source"],
            },
            reference_bundle_summary=BundleSummary(
                label="Reference bundle",
                bundle_kind="observed",
                iteration_number=available_iterations[-1],
                goals_fulfilled=sum(1 for item in reference_bundle.goal_status if item.passed),
                goals_total=len(reference_bundle.goal_status),
                description="Observed AIRT optimization result used as the benchmark target.",
            ),
            comparison_summary=comparison_summary,
            comparison_metrics=comparison_metrics,
            messages=[
                {
                    "role": "assistant",
                    "content": (
                        f"Observed Iteration{available_iterations[0]:03d} is loaded as the start state. "
                        f"Run the hybrid simulation loop to generate up to 20 predicted iterations, "
                        f"and compare the final state against observed Iteration{available_iterations[-1]:03d}."
                    ),
                }
            ],
            planning_result=planning_result.to_dict(),
            analysis_plan=analysis_plan.to_dict(),
            capability_profile=profile.to_dict(),
        )
        workspace_contract = build_workspace_contract(
            workflow_id="radonc_plan_optimization",
            workflow_family="radonc",
            analysis_track="optimization",
            dashboard_profile="plan_optimization",
            workspace_url=f"/demo/analysis/radonc-plan?patient_id={patient_id}",
            module="radonc_plan",
            runtime_mode="planning_controlled_writeback",
            viewer_type="workspace",
            can_autorun=True,
            planning_result=planning_result,
            task_traces=runtime_bundle["task_summary"],
            tool_policy=runtime_bundle["tool_policy"],
            context_availability=build_context_availability_summary(
                workflow_id="radonc_plan_optimization",
                workflow_family="radonc",
            ),
            memory_context=memory_context,
            planner_defaults=planner_defaults,
        )
        session.workspace_contract = workspace_contract.to_dict()
        self._refresh_session_summary(session)
        self._persist_session(session)
        return session

    def _persist_session(self, session: PlanOptimizationSession) -> None:
        payload = session.model_dump()
        save_entity_memory("radonc_plan_session", session.id, payload)
        save_session_memory(
            session.id,
            "radonc_plan_optimization",
            {
                "status": session.status,
                "iteration_count": len(session.iterations),
                "risk_tier": session.risk_tier,
                "updated_at": session.updated_at,
            },
        )
        if session.id == self._default_session_id:
            save_workflow_memory(
                "radonc_plan_optimization",
                "default_snapshot",
                {
                    "default_patient_id": self._default_patient_id,
                    "default_session_id": self._default_session_id,
                    "title": session.title,
                    "status": session.status,
                    "risk_tier": session.risk_tier,
                },
            )
        save_user_memory(
            "default_demo_user",
            {
                "preferred_dashboard_profile": "plan_optimization",
                "autorun_examples": True,
                "output_style": "structured_clinical",
            },
        )

    def _refresh_session_summary(self, session: PlanOptimizationSession) -> None:
        total_goals = len(session.goal_status)
        fulfilled = sum(1 for item in session.goal_status if item.passed)
        current_iteration = int(session.connector_state.get("current_iteration") or session.start_iteration_number)
        current_simulation = int(session.connector_state.get("current_simulated_iteration") or 0)
        session.summary_cards = [
            {"label": "Goals met", "value": f"{fulfilled}/{total_goals}" if total_goals else "0/0"},
            {"label": "Simulation", "value": f"{len(session.iterations)}/{session.simulation_max_iterations}"},
            {"label": "Mode", "value": session.control_mode.title()},
            {"label": "Observed start", "value": f"Iteration {current_iteration:03d}"},
            {"label": "Reference", "value": f"Iteration {session.reference_iteration_number:03d}"},
            {"label": "Current sim", "value": f"Step {current_simulation}"},
        ]
        failed = [item for item in session.goal_status if not item.passed]
        if any(item.priority == 1 for item in failed):
            session.risk_tier = "alert"
        elif failed:
            session.risk_tier = "watch"
        else:
            session.risk_tier = "ok"
        if failed:
            top_failure = sorted(failed, key=lambda item: item.priority)[0]
            session.risk_reason = f"{top_failure.roi} {top_failure.metric} remains outside the protocol target."
        else:
            session.risk_reason = "All protocol goals are currently satisfied."
        latest_suggestions = session.latest_suggestions[:3]
        session.recommended_actions = (
            [item.reason for item in latest_suggestions]
            if latest_suggestions
            else [
                "Inspect the baseline DVH and current weighted objectives before advancing to the next iteration.",
                "Use supervised mode if you want to confirm each bundle before moving on.",
            ]
        )
        if session.iterations:
            last_iteration = session.iterations[-1]
            session.report_summary = (
                f"{last_iteration.improvement_summary} "
                f"Reference proximity {session.comparison_summary.reference_proximity_percent:.1f}% against observed Iteration {session.reference_iteration_number:03d}."
            )
        else:
            session.report_summary = (
                f"Observed start bundle loaded from {session.data_source_id}. "
                f"{fulfilled}/{total_goals} protocol goals are currently satisfied before simulated optimization begins."
            )
        session.report_preview = session.report_summary
        session.latest_thinking_log = session.latest_thinking_log or "Thinking output will appear once the hybrid simulation loop starts."
        session.updated_at = _now_iso()

    def _session_list_payload(self) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for patient_id in sorted(self._patient_to_session):
            session_id = self._patient_to_session[patient_id]
            session = self._sessions[session_id]
            payload.append(
                {
                    "id": session.id,
                    "patient_id": patient_id,
                    "title": session.title,
                    "patient_label": session.patient_label,
                    "risk_tier": session.risk_tier,
                    "status": session.status,
                    "iteration_count": len(session.iterations),
                }
            )
        return payload

    def _resolve_patient_id(self, patient_id: str | None = None, session_id: str | None = None) -> str:
        if patient_id:
            if patient_id not in self._patients:
                raise KeyError(patient_id)
            return patient_id
        if session_id:
            resolved = self._session_to_patient.get(session_id)
            if resolved is None:
                raise KeyError(session_id)
            return resolved
        if not self._default_patient_id:
            raise KeyError("no_patients")
        return self._default_patient_id

    def snapshot(self, patient_id: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if not self._sessions:
                return {
                    "default_patient_id": self._default_patient_id,
                    "default_session_id": self._default_session_id,
                    "active_patient_id": "",
                    "patients": [],
                    "sessions": [],
                    "session": {},
                }
            resolved_patient_id = self._resolve_patient_id(patient_id=patient_id, session_id=session_id)
            resolved_session_id = self._patient_to_session[resolved_patient_id]
            session = self._sessions[resolved_session_id]
            return {
                "default_patient_id": self._default_patient_id,
                "default_session_id": self._default_session_id,
                "active_patient_id": resolved_patient_id,
                "patients": self.get_patients()["patients"],
                "sessions": self._session_list_payload(),
                "session": deepcopy(session.model_dump()),
            }

    def get_patients(self) -> dict[str, Any]:
        with self._lock:
            patients: list[dict[str, Any]] = []
            for patient_id in sorted(self._patients):
                session_id = self._patient_to_session.get(patient_id, "")
                session = self._sessions.get(session_id)
                patient_record = self._patients[patient_id]
                patients.append(
                    {
                        "id": patient_id,
                        "label": session.patient_label if session is not None else f"{patient_id} · AIRT mock case",
                        "source": patient_record["source"],
                        "available_iterations": deepcopy(patient_record["available_iterations"]),
                        "default_session_id": session_id,
                        "status": session.status if session is not None else "unavailable",
                        "risk_tier": session.risk_tier if session is not None else "watch",
                    }
                )
            return {
                "default_patient_id": self._default_patient_id,
                "default_session_id": self._default_session_id,
                "patients": patients,
            }

    def get_patient_id_for_session(self, session_id: str) -> str:
        with self._lock:
            patient_id = self._session_to_patient.get(session_id)
            if patient_id is None:
                raise KeyError(session_id)
            return patient_id

    def get_patient_dir(self, patient_id: str) -> Path:
        with self._lock:
            patient_record = self._patients.get(patient_id)
            if patient_record is None:
                raise KeyError(patient_id)
            return patient_record["path"]

    def get_patient_dir_for_session(self, session_id: str) -> Path:
        patient_id = self.get_patient_id_for_session(session_id)
        return self.get_patient_dir(patient_id)

    def get_session_for_patient(self, patient_id: str) -> dict[str, Any]:
        with self._lock:
            resolved_session_id = self._patient_to_session.get(patient_id)
            if resolved_session_id is None:
                raise KeyError(patient_id)
            return deepcopy(self._sessions[resolved_session_id].model_dump())

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            return deepcopy(session.model_dump())

    def get_session_model(self, session_id: str) -> PlanOptimizationSession:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            return session

    def update_session(self, session: PlanOptimizationSession) -> None:
        with self._lock:
            self._refresh_session_summary(session)
            self._sessions[session.id] = session
            self._persist_session(session)

    def append_message(self, session_id: str, role: str, content: str) -> None:
        with self._lock:
            session = self._sessions[session_id]
            session.messages.append({"role": role, "content": content})
            session.updated_at = _now_iso()
            self._persist_session(session)

    def reset_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            patient_id = self._resolve_patient_id(session_id=session_id)
            session = self._build_session(patient_id)
            self._sessions[session.id] = session
            return deepcopy(session.model_dump())

    def apply_iteration(
        self,
        *,
        session_id: str,
        iteration: OptimizationIteration,
        dvh_data: list[DVHSnapshot],
        suggestions: list[ObjectiveSuggestion],
        goal_status: list[GoalStatus],
        objectives: list[PlanObjective],
        objective_results: list[ObjectiveResult],
        connector_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            session = self._sessions[session_id]
            session.iterations.append(iteration)
            session.goal_status = goal_status
            session.latest_suggestions = suggestions
            session.current_objectives = objectives
            session.dvh_data = dvh_data
            session.objective_results = objective_results
            session.latest_thinking_log = iteration.thinking_log
            if connector_state is not None:
                session.connector_state = deepcopy(connector_state)
            session.comparison_metrics = deepcopy(iteration.comparison_metrics)
            session.comparison_summary = ComparisonSummary(
                clinical_completion_percent=round((iteration.goals_fulfilled / iteration.goals_total) * 100.0, 2) if iteration.goals_total else 0.0,
                reference_proximity_percent=round(max(0.0, 100.0 - iteration.reference_gap.overall_percent), 2),
                overall_completion_percent=round(
                    ((iteration.goals_fulfilled / iteration.goals_total) * 100.0 if iteration.goals_total else 0.0) * 0.6
                    + max(0.0, 100.0 - iteration.reference_gap.overall_percent) * 0.25
                    + iteration.reference_gap.goal_agreement_percent * 0.15,
                    2,
                ),
                goal_agreement_percent=iteration.reference_gap.goal_agreement_percent,
                dvh_gap_percent=iteration.reference_gap.dvh_gap_percent,
                metric_gap_percent=iteration.reference_gap.metric_gap_percent,
                current_label=f"Simulated Iteration {iteration.number}",
                reference_label=f"Observed Iteration {session.reference_iteration_number}",
            )
            session.report_summary = (
                f"{iteration.improvement_summary} Latest recommendation focus: "
                f"{suggestions[0].reason if suggestions else 'hold current objective set and compare the current simulated state against the observed reference bundle.'}"
            )
            session.report_preview = session.report_summary
            self._refresh_session_summary(session)
            self._sessions[session.id] = session
            self._persist_session(session)
            return deepcopy(session.model_dump())


radonc_plan_demo_store = RadOncPlanDemoStore()
