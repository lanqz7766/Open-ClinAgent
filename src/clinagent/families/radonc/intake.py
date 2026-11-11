from __future__ import annotations

from clinagent.platform.capabilities import evaluate_radonc_workflow_capability
from clinagent.platform.family_registry import resolve_workflow_registry_id
from clinagent.platform.harness import (
    AnalysisPlan,
    CapabilityProfile,
    CaseContext,
    PlanningResult,
    build_planning_result,
)


def normalize_radonc_context(
    *,
    request_text: str = "",
    source_kind: str = "planning_workspace",
    session_id: str | None = None,
    patient_id: str | None = None,
    treatment_site: str | None = None,
    has_rt_plan: bool = True,
    has_structures: bool = True,
    has_dose_or_dvh: bool = True,
    has_protocol: bool = True,
    connector_writable: bool = True,
) -> CaseContext:
    return CaseContext(
        workflow_id="radonc_plan_optimization",
        workflow_family="radonc",
        requested_goal="Iteratively optimize a radiotherapy treatment plan using DVH feedback and planning objectives.",
        request_text=request_text.strip(),
        source_kind=source_kind,
        patient_id=patient_id,
        case_id=session_id,
        indication=treatment_site,
        has_report_context=True,
        metadata={
            "treatment_site": treatment_site,
            "has_rt_plan": has_rt_plan,
            "has_structures": has_structures,
            "has_dose_or_dvh": has_dose_or_dvh,
            "has_protocol": has_protocol,
            "connector_writable": connector_writable,
        },
    )


def infer_radonc_context(message: str) -> CaseContext:
    lowered = message.lower()
    return normalize_radonc_context(
        request_text=message,
        source_kind="chat_only",
        treatment_site="Thoracic SBRT" if any(token in lowered for token in ("lung", "thoracic", "sbrt")) else "Radiation planning",
        has_rt_plan=True,
        has_structures=True,
        has_dose_or_dvh=True,
        has_protocol=True,
        connector_writable=True,
    )


def build_radonc_capability_profile(context: CaseContext) -> CapabilityProfile:
    metadata = context.metadata or {}
    has_rt_plan = bool(metadata.get("has_rt_plan"))
    has_structures = bool(metadata.get("has_structures"))
    has_dose_or_dvh = bool(metadata.get("has_dose_or_dvh"))
    has_protocol = bool(metadata.get("has_protocol"))

    available_inputs: list[str] = []
    missing_inputs: list[str] = []
    blocked_reasons: list[str] = []
    context_sources = ["radonc_context", "mock_tps_connector"]

    if has_rt_plan:
        available_inputs.append("rt_plan")
    else:
        missing_inputs.append("rt_plan")
        blocked_reasons.append("RT plan metadata is missing.")
    if has_structures:
        available_inputs.append("rt_structures")
    else:
        missing_inputs.append("rt_structures")
        blocked_reasons.append("Structure set is missing.")
    if has_dose_or_dvh:
        available_inputs.append("dvh_metrics")
    else:
        missing_inputs.append("dvh_metrics")
        blocked_reasons.append("Dose or DVH context is missing.")
    if has_protocol:
        available_inputs.append("protocol_template")
    else:
        missing_inputs.append("protocol_template")
        blocked_reasons.append("Protocol goals are missing.")

    return CapabilityProfile(
        workflow_id="radonc_plan_optimization",
        workflow_family="radonc",
        has_demographics=False,
        has_single_study_mri=has_rt_plan,
        imaging_format="rtplan",
        has_segmentation=has_structures,
        has_longitudinal_priors=False,
        has_report_context=True,
        has_ehr_context=False,
        has_report_text=False,
        has_template_context=has_protocol,
        available_inputs=available_inputs,
        missing_inputs=missing_inputs,
        blocked_reasons=blocked_reasons,
        context_sources=context_sources,
    )


def build_radonc_analysis_plan(context: CaseContext, profile: CapabilityProfile) -> AnalysisPlan:
    metadata = context.metadata or {}
    connector_writable = bool(metadata.get("connector_writable", False))
    capability = evaluate_radonc_workflow_capability(
        has_rt_plan=profile.has_single_study_mri,
        has_rt_structures=profile.has_segmentation,
        has_dose_or_dvh="dvh_metrics" in profile.available_inputs,
        has_protocol=profile.has_template_context,
        connector_writable=connector_writable,
    )
    can_execute = capability.can_execute and connector_writable
    rationale = [
        "RadOnc optimization needs a plan, structures, dose feedback, and protocol goals before the loop can run.",
        "The optimization workspace should stay inside the family-specific planning shell rather than falling back to report-style routing.",
    ]
    if can_execute:
        rationale.append("Mock TPS write-back is enabled, so the full optimization loop can auto-run.")
    elif capability.can_execute:
        rationale.append("The planning context is readable, but write-back is unavailable, so the workflow should stay in review mode.")
    else:
        rationale.append("The planning loop should stay blocked until the missing planning inputs are resolved.")

    return AnalysisPlan(
        workflow_id="radonc_plan_optimization",
        workflow_family="radonc",
        analysis_track="optimization",
        primary_goal="plan_optimization",
        dashboard_profile="plan_optimization",
        secondary_lanes=["plan_review"],
        requested_goal="Optimize plan objectives iteratively using current DVH feedback.",
        recommended_workflow="radonc_plan_optimization",
        recommended_goal="Auto-optimize the active treatment plan and summarize trade-offs.",
        recommended_mode="auto_loop" if can_execute else "manual_review",
        can_execute=capability.can_execute,
        autorun=can_execute,
        allowed_analyses=["dvh_review", "constraint_optimization", "tradeoff_summary"] if capability.can_execute else [],
        blocked_analyses=[] if capability.can_execute else ["dvh_review", "constraint_optimization", "tradeoff_summary"],
        missing_inputs=profile.missing_inputs,
        rationale=rationale,
        safe_fallback_mode="plan_review",
        workflow_task_id=resolve_workflow_registry_id(
            runtime_workflow_id="radonc_plan_optimization",
            workflow_family="radonc",
            primary_goal="plan_optimization",
        ),
        stages=[
            "intake",
            "context_resolution",
            "capability_assessment",
            "goal_selection",
            "tool_plan",
            "execution",
            "synthesis",
            "presentation",
        ],
        handoff_summary="I identified a radiation oncology planning optimization request and prepared the plan-optimization workspace with DVH, objectives, and control-state context.",
        runtime_mode="planning_controlled_writeback" if connector_writable else "external_data",
    )


def build_radonc_planning_result(
    context: CaseContext,
    profile: CapabilityProfile,
    plan: AnalysisPlan,
) -> PlanningResult:
    return build_planning_result(
        context,
        profile,
        plan,
        requested_mode=plan.recommended_mode,
        executed_mode=plan.recommended_mode if plan.autorun else None,
        viewer_type="workspace",
    )


def intake_plan_from_radonc_message(message: str) -> tuple[CaseContext, CapabilityProfile, AnalysisPlan]:
    context = infer_radonc_context(message)
    profile = build_radonc_capability_profile(context)
    plan = build_radonc_analysis_plan(context, profile)
    return context, profile, plan
