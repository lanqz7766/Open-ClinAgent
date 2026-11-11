from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class FamilyRegistryEntry:
    family_id: str
    display_name: str
    family_type: str
    summary: str
    supported_workflows: tuple[str, ...]
    default_workspace_shell: str
    default_viewer_policy: str
    allowed_mcp_servers: tuple[str, ...]
    review_lane_enabled: bool
    flagship: bool = False

    def to_summary(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["supported_workflows"] = list(self.supported_workflows)
        payload["allowed_mcp_servers"] = list(self.allowed_mcp_servers)
        return payload


@dataclass(frozen=True)
class WorkflowRegistryEntry:
    workflow_id: str
    runtime_workflow_id: str | None
    workflow_family: str
    display_name: str
    summary: str
    intent_patterns: tuple[str, ...]
    intake_schema: tuple[str, ...]
    capability_evaluator: str
    planner_outputs: tuple[str, ...]
    runtime_stages: tuple[str, ...]
    tool_bundle: tuple[str, ...]
    dashboard_profile: str
    report_contract: dict[str, Any]
    executable: bool = True
    review_lane_role: str = "embedded"
    advisory_skills: tuple[str, ...] = ()

    def to_summary(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["intent_patterns"] = list(self.intent_patterns)
        payload["intake_schema"] = list(self.intake_schema)
        payload["planner_outputs"] = list(self.planner_outputs)
        payload["runtime_stages"] = list(self.runtime_stages)
        payload["tool_bundle"] = list(self.tool_bundle)
        payload["advisory_skills"] = list(self.advisory_skills)
        return payload


FAMILY_REGISTRY: dict[str, FamilyRegistryEntry] = {
    "general": FamilyRegistryEntry(
        family_id="general",
        display_name="General Command",
        family_type="system",
        summary="Top-level routing and orchestration entrypoint for ClinAgent.",
        supported_workflows=("general.general_chat",),
        default_workspace_shell="chat_shell",
        default_viewer_policy="none",
        allowed_mcp_servers=(),
        review_lane_enabled=False,
    ),
    "review": FamilyRegistryEntry(
        family_id="review",
        display_name="Review",
        family_type="cross_cutting",
        summary="Cross-cutting report and evidence critique lane that can stand alone or embed into clinical families.",
        supported_workflows=("review.report_review",),
        default_workspace_shell="review_workspace",
        default_viewer_policy="workspace",
        allowed_mcp_servers=("report_quality_local",),
        review_lane_enabled=True,
    ),
    "findings": FamilyRegistryEntry(
        family_id="findings",
        display_name="Findings Closure",
        family_type="clinical_domain",
        summary="Actionable finding follow-up and closure planning workflows.",
        supported_workflows=("findings.findings_closure",),
        default_workspace_shell="review_workspace",
        default_viewer_policy="workspace",
        allowed_mcp_servers=(),
        review_lane_enabled=True,
    ),
    "queue": FamilyRegistryEntry(
        family_id="queue",
        display_name="Queue Triage",
        family_type="clinical_domain",
        summary="Queue reprioritization and review-first triage workflows.",
        supported_workflows=("queue.queue_triage",),
        default_workspace_shell="review_workspace",
        default_viewer_policy="workspace",
        allowed_mcp_servers=(),
        review_lane_enabled=True,
    ),
    "diagnosis": FamilyRegistryEntry(
        family_id="diagnosis",
        display_name="Missed Diagnosis Review",
        family_type="clinical_domain",
        summary="Diagnosis-gap review workflows for missed findings and workup escalation.",
        supported_workflows=("diagnosis.missed_diagnosis_review",),
        default_workspace_shell="review_workspace",
        default_viewer_policy="workspace",
        allowed_mcp_servers=(),
        review_lane_enabled=True,
    ),
    "screening": FamilyRegistryEntry(
        family_id="screening",
        display_name="Screening Gap Closure",
        family_type="clinical_domain",
        summary="Preventive care and unresolved screening follow-up workflows.",
        supported_workflows=("screening.screening_gap_closure",),
        default_workspace_shell="review_workspace",
        default_viewer_policy="workspace",
        allowed_mcp_servers=(),
        review_lane_enabled=True,
    ),
    "neuro": FamilyRegistryEntry(
        family_id="neuro",
        display_name="Neuro Imaging",
        family_type="clinical_domain",
        summary="Flagship MRI family for structural reporting, response review, and embedded report critique.",
        supported_workflows=(
            "neuro.structural_report",
            "neuro.response_review",
            "neuro.report_review",
            "neuro.legacy_longitudinal_review",
        ),
        default_workspace_shell="neuro_report_shell",
        default_viewer_policy="radiological_hybrid_imaging_workspace",
        allowed_mcp_servers=("neuro_context",),
        review_lane_enabled=True,
        flagship=True,
    ),
    "safety": FamilyRegistryEntry(
        family_id="safety",
        display_name="Radiation Safety",
        family_type="clinical_domain",
        summary="Incident review and mitigation planning workflows for radiation safety monitoring.",
        supported_workflows=("safety.radiation_safety_monitor",),
        default_workspace_shell="review_workspace",
        default_viewer_policy="workspace",
        allowed_mcp_servers=(),
        review_lane_enabled=True,
    ),
    "radonc": FamilyRegistryEntry(
        family_id="radonc",
        display_name="Radiation Oncology Planning",
        family_type="clinical_domain",
        summary="Radiation oncology family for iterative plan optimization, dose prediction, and plan review workflows.",
        supported_workflows=("radonc.plan_optimization", "radonc.dose_prediction", "radonc.plan_review"),
        default_workspace_shell="planning_workspace",
        default_viewer_policy="hybrid_imaging_workspace",
        allowed_mcp_servers=("radonc_context",),
        review_lane_enabled=True,
    ),
}


DEFAULT_PLANNER_OUTPUTS: tuple[str, ...] = (
    "workflow_family",
    "workflow_id",
    "primary_goal",
    "dashboard_profile",
    "secondary_lanes",
    "goal_confidence",
    "context_sources",
    "blocked_claims",
    "recommended_next_action",
)

DEFAULT_RUNTIME_STAGES: tuple[str, ...] = (
    "intake",
    "context_resolution",
    "capability_assessment",
    "goal_selection",
    "tool_plan",
    "execution",
    "synthesis",
    "presentation",
)


WORKFLOW_REGISTRY: dict[str, WorkflowRegistryEntry] = {
    "general.general_chat": WorkflowRegistryEntry(
        workflow_id="general.general_chat",
        runtime_workflow_id="general_chat",
        workflow_family="general",
        display_name="General Clinical Command",
        summary="Route requests into the most relevant ClinAgent workflow and explain the next action.",
        intent_patterns=("route request", "choose workflow", "general clinical command"),
        intake_schema=("message",),
        capability_evaluator="general_router",
        planner_outputs=DEFAULT_PLANNER_OUTPUTS,
        runtime_stages=("route", "clarify", "respond"),
        tool_bundle=("workflow_router", "policy_guard", "tool_selector"),
        dashboard_profile="chat",
        report_contract={"kind": "chat_summary", "sections": ["Routing", "Next Step"]},
        review_lane_role="standalone",
    ),
    "review.report_review": WorkflowRegistryEntry(
        workflow_id="review.report_review",
        runtime_workflow_id="report_quality_review",
        workflow_family="review",
        display_name="Report Review",
        summary="Standalone report QA for privacy, terminology, completeness, and revision support.",
        intent_patterns=("review report", "report quality", "identifier review", "compliance review"),
        intake_schema=("report_text", "template_id", "compliance_profile"),
        capability_evaluator="report_quality_capability_evaluator",
        planner_outputs=DEFAULT_PLANNER_OUTPUTS,
        runtime_stages=("intake", "policy_check", "finalize"),
        tool_bundle=("report_section_parser", "finding_impression_consistency_checker", "report_revision_synthesizer"),
        dashboard_profile="report_review",
        report_contract={"kind": "report_quality_summary", "sections": ["Privacy", "Terminology", "Completeness"]},
        review_lane_role="primary",
        advisory_skills=("report_review_heuristics",),
    ),
    "findings.findings_closure": WorkflowRegistryEntry(
        workflow_id="findings.findings_closure",
        runtime_workflow_id="findings_closure",
        workflow_family="findings",
        display_name="Findings Closure",
        summary="Actionable findings follow-up and closure recommendation workflow.",
        intent_patterns=("critical finding", "follow-up closure", "result escalation"),
        intake_schema=("finding_text", "completion_state"),
        capability_evaluator="findings_closure_evaluator",
        planner_outputs=DEFAULT_PLANNER_OUTPUTS,
        runtime_stages=("route", "evidence_review", "closure_brief"),
        tool_bundle=("finding_parser", "closure_checker", "action_recommender"),
        dashboard_profile="findings_review",
        report_contract={"kind": "findings_brief", "sections": ["Finding Summary", "Closure Check", "Recommended Next Step"]},
    ),
    "queue.queue_triage": WorkflowRegistryEntry(
        workflow_id="queue.queue_triage",
        runtime_workflow_id="queue_triage",
        workflow_family="queue",
        display_name="Queue Triage",
        summary="Review-first queue reprioritization and urgency recommendation workflow.",
        intent_patterns=("queue triage", "referral urgency", "expedite case"),
        intake_schema=("queue_item", "risk_factors"),
        capability_evaluator="queue_triage_evaluator",
        planner_outputs=DEFAULT_PLANNER_OUTPUTS,
        runtime_stages=("route", "priority_review", "queue_recommendation"),
        tool_bundle=("queue_reader", "priority_scorer", "review_router", "action_recommender"),
        dashboard_profile="queue_review",
        report_contract={"kind": "queue_brief", "sections": ["Queue Signal", "Priority Shift", "Recommended Queue Move"]},
    ),
    "diagnosis.missed_diagnosis_review": WorkflowRegistryEntry(
        workflow_id="diagnosis.missed_diagnosis_review",
        runtime_workflow_id="missed_diagnosis_detection",
        workflow_family="diagnosis",
        display_name="Missed Diagnosis Review",
        summary="Diagnosis gap review for likely missed or under-worked-up conditions.",
        intent_patterns=("missed diagnosis", "fracture gap", "undiagnosed condition"),
        intake_schema=("report_text", "followup_context"),
        capability_evaluator="missed_diagnosis_evaluator",
        planner_outputs=DEFAULT_PLANNER_OUTPUTS,
        runtime_stages=("route", "gap_review", "workup_recommendation"),
        tool_bundle=("gap_reader", "evidence_bundle", "workup_recommender"),
        dashboard_profile="diagnosis_review",
        report_contract={"kind": "missed_diagnosis_brief", "sections": ["Gap Signal", "Follow-up Check", "Recommended Workup"]},
    ),
    "screening.screening_gap_closure": WorkflowRegistryEntry(
        workflow_id="screening.screening_gap_closure",
        runtime_workflow_id="screening_gap_closure",
        workflow_family="screening",
        display_name="Screening Gap Closure",
        summary="Screening follow-up closure and care-gap review workflow.",
        intent_patterns=("screening gap", "positive fit", "overdue screening"),
        intake_schema=("screening_result", "followup_status"),
        capability_evaluator="screening_gap_evaluator",
        planner_outputs=DEFAULT_PLANNER_OUTPUTS,
        runtime_stages=("route", "gap_review", "closure_plan"),
        tool_bundle=("screening_reader", "gap_checker", "followup_recommender"),
        dashboard_profile="screening_review",
        report_contract={"kind": "screening_gap_brief", "sections": ["Screening Signal", "Gap Check", "Recommended Next Step"]},
    ),
    "neuro.structural_report": WorkflowRegistryEntry(
        workflow_id="neuro.structural_report",
        runtime_workflow_id="neuro_report",
        workflow_family="neuro",
        display_name="Neuro Structural Report",
        summary="Structural MRI review with volumetry, normative interpretation, and longitudinal change.",
        intent_patterns=("atrophy", "hippocampus", "ventricle", "structural mri", "normative volumetry"),
        intake_schema=("brain_mri", "segmentation", "demographics"),
        capability_evaluator="neuro_capability_evaluator",
        planner_outputs=DEFAULT_PLANNER_OUTPUTS,
        runtime_stages=DEFAULT_RUNTIME_STAGES,
        tool_bundle=("brain_segmentation", "volumetric_analysis", "normative_structural_synthesis"),
        dashboard_profile="volumetry",
        report_contract={"kind": "neuro_report_handoff", "sections": ["Intake", "Capabilities", "Workspace Launch"]},
        advisory_skills=("neuro_response_reasoning",),
    ),
    "neuro.response_review": WorkflowRegistryEntry(
        workflow_id="neuro.response_review",
        runtime_workflow_id="neuro_report",
        workflow_family="neuro",
        display_name="Neuro Response Review",
        summary="Longitudinal lesion and tumor burden review for interval response assessment.",
        intent_patterns=("tumor response", "lesion burden", "brain mets", "longitudinal response"),
        intake_schema=("brain_mri", "segmentation", "prior_study"),
        capability_evaluator="neuro_capability_evaluator",
        planner_outputs=DEFAULT_PLANNER_OUTPUTS,
        runtime_stages=DEFAULT_RUNTIME_STAGES,
        tool_bundle=("lesion_segmentation_ingestion", "lesion_volume_calculator", "response_delta_calculator", "longitudinal_response_synthesizer"),
        dashboard_profile="longitudinal_response",
        report_contract={"kind": "neuro_report_handoff", "sections": ["Intake", "Capabilities", "Workspace Launch"]},
        advisory_skills=("neuro_response_reasoning",),
    ),
    "neuro.report_review": WorkflowRegistryEntry(
        workflow_id="neuro.report_review",
        runtime_workflow_id="neuro_report",
        workflow_family="neuro",
        display_name="Neuro Report Review",
        summary="Case-scoped report critique embedded inside the Neuro Report family.",
        intent_patterns=("review this neuro report", "neuro report omission", "neuro report inconsistency"),
        intake_schema=("case_context", "report_text"),
        capability_evaluator="neuro_capability_evaluator",
        planner_outputs=DEFAULT_PLANNER_OUTPUTS,
        runtime_stages=DEFAULT_RUNTIME_STAGES,
        tool_bundle=("report_section_parser", "finding_impression_consistency_checker", "report_revision_synthesizer"),
        dashboard_profile="report_review",
        report_contract={"kind": "neuro_report_handoff", "sections": ["Intake", "Capabilities", "Workspace Launch"]},
        review_lane_role="primary",
        advisory_skills=("report_review_heuristics",),
    ),
    "neuro.legacy_longitudinal_review": WorkflowRegistryEntry(
        workflow_id="neuro.legacy_longitudinal_review",
        runtime_workflow_id="neuro_longitudinal",
        workflow_family="neuro",
        display_name="Legacy Neuro Longitudinal Review",
        summary="Compatibility workflow retained while the Neuro Report family absorbs flagship response use cases.",
        intent_patterns=("legacy neuro longitudinal", "brain metastasis review"),
        intake_schema=("brain_mri", "longitudinal_series"),
        capability_evaluator="legacy_neuro_response_evaluator",
        planner_outputs=DEFAULT_PLANNER_OUTPUTS,
        runtime_stages=("route", "intake", "evidence_review", "report_synthesis"),
        tool_bundle=("brain_met_response_tracker", "lesion_trend_plotter", "longitudinal_comparison_panel_builder"),
        dashboard_profile="longitudinal_response",
        report_contract={"kind": "neuro_longitudinal_brief", "sections": ["MRI Trend Analysis", "Draft Physician Summary", "Recommendations"]},
    ),
    "safety.radiation_safety_monitor": WorkflowRegistryEntry(
        workflow_id="safety.radiation_safety_monitor",
        runtime_workflow_id="radiation_safety_monitor",
        workflow_family="safety",
        display_name="Radiation Safety Monitor",
        summary="Incident pattern matching and mitigation planning for radiation safety review.",
        intent_patterns=("radiation incident", "dosimetry alert", "physics qa issue"),
        intake_schema=("incident_text",),
        capability_evaluator="radiation_safety_evaluator",
        planner_outputs=DEFAULT_PLANNER_OUTPUTS,
        runtime_stages=("route", "safety_review", "mitigation_brief"),
        tool_bundle=("case_parser", "failure_pattern_matcher", "risk_tier_engine"),
        dashboard_profile="safety_review",
        report_contract={"kind": "safety_brief", "sections": ["Risk Summary", "Matched Failure Patterns", "Escalation"]},
    ),
    "radonc.dose_prediction": WorkflowRegistryEntry(
        workflow_id="radonc.dose_prediction",
        runtime_workflow_id=None,
        workflow_family="radonc",
        display_name="Dose Prediction",
        summary="Planned radiation oncology workflow for dose estimation and planning context review.",
        intent_patterns=("dose prediction", "predicted dose", "planning dose estimate"),
        intake_schema=("ct_sim", "structures", "planning_context"),
        capability_evaluator="radonc_capability_evaluator",
        planner_outputs=DEFAULT_PLANNER_OUTPUTS,
        runtime_stages=DEFAULT_RUNTIME_STAGES,
        tool_bundle=("dose_context_resolver", "dose_metric_estimator", "dose_summary_synthesizer"),
        dashboard_profile="dose_prediction",
        report_contract={"kind": "radonc_plan_summary", "sections": ["Inputs", "Dose Drivers", "Predicted Coverage"]},
        executable=False,
        advisory_skills=("radonc_plan_summary_style",),
    ),
    "radonc.plan_optimization": WorkflowRegistryEntry(
        workflow_id="radonc.plan_optimization",
        runtime_workflow_id="radonc_plan_optimization",
        workflow_family="radonc",
        display_name="Plan Optimization",
        summary="Flagship radonc workflow for iterative DVH optimization, objective adjustment, and auto-loop planning support.",
        intent_patterns=("plan optimization", "dvh optimization", "auto optimize plan", "oar tradeoff", "coverage tradeoff"),
        intake_schema=("rt_plan", "rt_structures", "dvh_metrics", "protocol_template"),
        capability_evaluator="radonc_capability_evaluator",
        planner_outputs=DEFAULT_PLANNER_OUTPUTS,
        runtime_stages=DEFAULT_RUNTIME_STAGES,
        tool_bundle=("rt_plan_context_loader", "dvh_constraint_analyzer", "objective_adjustment_engine", "plan_tradeoff_synthesizer"),
        dashboard_profile="plan_optimization",
        report_contract={"kind": "radonc_plan_optimization", "sections": ["Inputs", "Constraint Review", "Iteration Summary", "Suggested Next Step"]},
        executable=True,
        advisory_skills=("radonc_plan_summary_style",),
    ),
    "radonc.plan_review": WorkflowRegistryEntry(
        workflow_id="radonc.plan_review",
        runtime_workflow_id=None,
        workflow_family="radonc",
        display_name="Plan Review",
        summary="Planned radiation oncology review workflow for plan quality, tradeoffs, and revision support.",
        intent_patterns=("plan review", "rt plan qa", "coverage critique"),
        intake_schema=("rt_plan", "dose_metrics", "constraints"),
        capability_evaluator="radonc_capability_evaluator",
        planner_outputs=DEFAULT_PLANNER_OUTPUTS,
        runtime_stages=DEFAULT_RUNTIME_STAGES,
        tool_bundle=("plan_metric_parser", "constraint_checker", "plan_review_synthesizer"),
        dashboard_profile="plan_review",
        report_contract={"kind": "radonc_plan_summary", "sections": ["Plan Summary", "Constraint Review", "Suggested Revisions"]},
        executable=False,
        review_lane_role="primary",
        advisory_skills=("radonc_plan_summary_style",),
    ),
}


def list_family_registry() -> list[dict[str, Any]]:
    return [entry.to_summary() for entry in FAMILY_REGISTRY.values()]


def get_family_registry_entry(family_id: str) -> dict[str, Any] | None:
    entry = FAMILY_REGISTRY.get(family_id)
    return entry.to_summary() if entry else None


def list_workflow_registry(*, family_id: str | None = None, executable_only: bool = False) -> list[dict[str, Any]]:
    entries = list(WORKFLOW_REGISTRY.values())
    if family_id is not None:
        entries = [entry for entry in entries if entry.workflow_family == family_id]
    if executable_only:
        entries = [entry for entry in entries if entry.executable]
    return [entry.to_summary() for entry in entries]


def get_workflow_registry_entry(workflow_id: str) -> dict[str, Any] | None:
    entry = WORKFLOW_REGISTRY.get(workflow_id)
    return entry.to_summary() if entry else None


def get_workflow_registry_entry_for_runtime(
    *,
    runtime_workflow_id: str,
    workflow_family: str | None = None,
    primary_goal: str | None = None,
) -> dict[str, Any] | None:
    resolved_id = resolve_workflow_registry_id(
        runtime_workflow_id=runtime_workflow_id,
        workflow_family=workflow_family,
        primary_goal=primary_goal,
    )
    return get_workflow_registry_entry(resolved_id)


def resolve_workflow_registry_id(
    *,
    runtime_workflow_id: str,
    workflow_family: str | None = None,
    primary_goal: str | None = None,
) -> str:
    if runtime_workflow_id == "neuro_report":
        if primary_goal == "response_review":
            return "neuro.response_review"
        if primary_goal == "report_review":
            return "neuro.report_review"
        return "neuro.structural_report"
    if runtime_workflow_id == "report_quality_review":
        return "review.report_review"
    if runtime_workflow_id == "neuro_longitudinal":
        return "neuro.legacy_longitudinal_review"
    explicit_map = {
        "general_chat": "general.general_chat",
        "findings_closure": "findings.findings_closure",
        "queue_triage": "queue.queue_triage",
        "missed_diagnosis_detection": "diagnosis.missed_diagnosis_review",
        "screening_gap_closure": "screening.screening_gap_closure",
        "radiation_safety_monitor": "safety.radiation_safety_monitor",
        "radonc_plan_optimization": "radonc.plan_optimization",
    }
    if runtime_workflow_id in explicit_map:
        return explicit_map[runtime_workflow_id]
    family = (workflow_family or "general").strip() or "general"
    return f"{family}.{runtime_workflow_id}"
