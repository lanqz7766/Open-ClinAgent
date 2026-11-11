from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DEFAULT_HARNESS_STAGES = [
    "intake",
    "context_resolution",
    "capability_assessment",
    "goal_selection",
    "tool_plan",
    "execution",
    "synthesis",
    "presentation",
]


@dataclass
class CaseContext:
    workflow_id: str
    workflow_family: str = "general"
    requested_goal: str | None = None
    request_text: str = ""
    source_kind: str = "chat_only"
    patient_id: str | None = None
    study_id: str | None = None
    case_id: str | None = None
    report_id: str | None = None
    nifti_path: str | None = None
    dicom_path: str | None = None
    pacs_reference: str | None = None
    seg_path: str | None = None
    report_text: str | None = None
    template_id: str | None = None
    compliance_profile: str | None = None
    age: int | None = None
    sex: str | None = None
    indication: str | None = None
    available_sequences: list[str] = field(default_factory=list)
    has_prior_study: bool = False
    has_prior_report: bool = False
    has_ehr_context: bool = False
    has_report_context: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityProfile:
    workflow_id: str
    workflow_family: str
    has_demographics: bool
    has_single_study_mri: bool
    imaging_format: str
    has_segmentation: bool
    has_longitudinal_priors: bool
    has_report_context: bool
    has_ehr_context: bool
    has_report_text: bool = False
    has_template_context: bool = False
    available_inputs: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    context_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityProfileSummary:
    detected_inputs: list[str]
    missing_info: list[str]
    blocked_reasons: list[str]
    imaging_format: str
    has_segmentation: bool
    has_demographics: bool
    context_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisPlan:
    workflow_id: str
    workflow_family: str
    analysis_track: str
    primary_goal: str
    dashboard_profile: str
    secondary_lanes: list[str]
    requested_goal: str
    recommended_workflow: str
    recommended_goal: str
    recommended_mode: str | None
    can_execute: bool
    autorun: bool
    allowed_analyses: list[str]
    blocked_analyses: list[str]
    missing_inputs: list[str]
    rationale: list[str]
    safe_fallback_mode: str | None
    workflow_task_id: str | None = None
    stages: list[str] = field(default_factory=lambda: DEFAULT_HARNESS_STAGES.copy())
    handoff_summary: str = ""
    runtime_mode: str = "read_only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisPlanSummary:
    family: str
    track: str
    primary_goal: str
    dashboard_profile: str
    secondary_lanes: list[str]
    detected_inputs: list[str]
    chosen_mode: str | None
    requested_mode: str | None
    recommended_mode: str | None
    missing_info: list[str]
    viewer_type: str
    can_execute: bool
    safety_fallback: str | None
    summary: str
    runtime_mode: str = "read_only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlanningResult:
    workflow_family: str
    workflow_id: str
    intent: str
    family: str
    track: str
    primary_goal: str
    dashboard_profile: str
    secondary_lanes: list[str]
    goal_confidence: float
    entities: dict[str, str | None]
    available_data: list[str]
    recommended_workflow: str
    requested_goal: str
    recommended_goal: str
    reason_for_track_selection: str
    user_override_allowed: bool
    context_sources: list[str]
    can_execute: bool
    missing_inputs: list[str]
    recommended_next_action: str
    viewer_type: str
    blocked_claims: list[str]
    autorun: bool
    analysis_plan_summary: AnalysisPlanSummary
    capability_profile_summary: CapabilityProfileSummary
    context_availability: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["analysis_plan_summary"] = self.analysis_plan_summary.to_dict()
        payload["capability_profile_summary"] = self.capability_profile_summary.to_dict()
        return payload


@dataclass
class StageTrace:
    id: str
    label: str
    status: str
    workflow_family: str | None = None
    track: str | None = None
    primary_goal: str | None = None
    dashboard_profile: str | None = None
    policy_mode: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    blocked_tools: list[str] = field(default_factory=list)
    context_sources: list[str] = field(default_factory=list)
    fallback_reason: str | None = None
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskTrace:
    id: str
    label: str
    status: str
    stage_id: str
    family: str
    track: str
    summary: str
    primary_goal: str | None = None
    dashboard_profile: str | None = None
    policy_mode: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    blocked_tools: list[str] = field(default_factory=list)
    context_sources: list[str] = field(default_factory=list)
    role_id: str | None = None
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkspaceContract:
    workflow_id: str
    workflow_family: str
    analysis_track: str
    primary_goal: str
    dashboard_profile: str
    secondary_lanes: list[str]
    workspace_url: str
    module: str
    runtime_mode: str
    viewer_type: str
    can_autorun: bool
    planning_result: dict[str, Any]
    task_traces: list[dict[str, Any]] = field(default_factory=list)
    tool_policy: dict[str, Any] = field(default_factory=dict)
    context_availability: list[dict[str, Any]] = field(default_factory=list)
    memory_context: dict[str, Any] = field(default_factory=dict)
    planner_defaults: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stage_id_from_label(label: str) -> str:
    return label.strip().lower().replace(" ", "_")


def build_stage_trace(
    *,
    label: str,
    workflow_family: str,
    track: str | None = None,
    primary_goal: str | None = None,
    dashboard_profile: str | None = None,
    policy_mode: str | None = None,
    allowed_tools: list[str] | None = None,
    blocked_tools: list[str] | None = None,
    context_sources: list[str] | None = None,
    fallback_reason: str | None = None,
    status: str = "pending",
    summary: str | None = None,
) -> StageTrace:
    return StageTrace(
        id=_stage_id_from_label(label),
        label=label,
        status=status,
        workflow_family=workflow_family,
        track=track,
        primary_goal=primary_goal,
        dashboard_profile=dashboard_profile,
        policy_mode=policy_mode,
        allowed_tools=list(allowed_tools or []),
        blocked_tools=list(blocked_tools or []),
        context_sources=list(context_sources or []),
        fallback_reason=fallback_reason,
        summary=summary,
    )


def build_task_trace(
    *,
    task_id: str,
    label: str,
    stage_id: str,
    workflow_family: str,
    track: str,
    summary: str,
    primary_goal: str | None = None,
    dashboard_profile: str | None = None,
    policy_mode: str | None = None,
    allowed_tools: list[str] | None = None,
    blocked_tools: list[str] | None = None,
    context_sources: list[str] | None = None,
    role_id: str | None = None,
    fallback_reason: str | None = None,
    status: str = "pending",
) -> TaskTrace:
    return TaskTrace(
        id=task_id,
        label=label,
        status=status,
        stage_id=stage_id,
        family=workflow_family,
        track=track,
        summary=summary,
        primary_goal=primary_goal,
        dashboard_profile=dashboard_profile,
        policy_mode=policy_mode,
        allowed_tools=list(allowed_tools or []),
        blocked_tools=list(blocked_tools or []),
        context_sources=list(context_sources or []),
        role_id=role_id,
        fallback_reason=fallback_reason,
    )


def build_stage_trace_set(
    *,
    labels: list[str] | tuple[str, ...],
    workflow_family: str,
    track: str | None = None,
    primary_goal: str | None = None,
    dashboard_profile: str | None = None,
    policy_mode: str | None = None,
    allowed_tools: list[str] | None = None,
    blocked_tools: list[str] | None = None,
    context_sources: list[str] | None = None,
    fallback_reason: str | None = None,
) -> list[dict[str, Any]]:
    return [
        build_stage_trace(
            label=label,
            workflow_family=workflow_family,
            track=track,
            primary_goal=primary_goal,
            dashboard_profile=dashboard_profile,
            policy_mode=policy_mode,
            allowed_tools=allowed_tools,
            blocked_tools=blocked_tools,
            context_sources=context_sources,
            fallback_reason=fallback_reason,
        ).to_dict()
        for label in labels
    ]


def build_task_trace_set(
    *,
    task_templates: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    workflow_family: str,
    track: str,
    primary_goal: str | None = None,
    dashboard_profile: str | None = None,
    policy_mode: str | None = None,
    allowed_tools: list[str] | None = None,
    blocked_tools: list[str] | None = None,
    context_sources: list[str] | None = None,
    fallback_reason: str | None = None,
) -> list[dict[str, Any]]:
    return [
        build_task_trace(
            task_id=str(task["id"]),
            label=str(task["label"]),
            stage_id=str(task["stage_id"]),
            workflow_family=workflow_family,
            track=track,
            summary=str(task["summary"]),
            primary_goal=primary_goal,
            dashboard_profile=dashboard_profile,
            policy_mode=policy_mode,
            allowed_tools=allowed_tools,
            blocked_tools=blocked_tools,
            context_sources=context_sources,
            role_id=task.get("role_id"),
            fallback_reason=fallback_reason,
        ).to_dict()
        for task in task_templates
    ]


def summarize_capability_profile(profile: CapabilityProfile) -> CapabilityProfileSummary:
    return CapabilityProfileSummary(
        detected_inputs=profile.available_inputs,
        missing_info=profile.missing_inputs,
        blocked_reasons=profile.blocked_reasons,
        imaging_format=profile.imaging_format,
        has_segmentation=profile.has_segmentation,
        has_demographics=profile.has_demographics,
        context_sources=profile.context_sources,
    )


def summarize_analysis_plan(
    plan: AnalysisPlan,
    profile: CapabilityProfile,
    *,
    requested_mode: str | None = None,
    executed_mode: str | None = None,
    viewer_type: str = "png_fallback",
) -> AnalysisPlanSummary:
    chosen_mode = executed_mode or plan.recommended_mode
    fallback_reason = None
    if requested_mode and chosen_mode and requested_mode != chosen_mode:
        fallback_reason = "Requested mode was safely downgraded to match the available inputs."
    return AnalysisPlanSummary(
        family=plan.workflow_family,
        track=plan.analysis_track,
        primary_goal=plan.primary_goal,
        dashboard_profile=plan.dashboard_profile,
        secondary_lanes=list(plan.secondary_lanes),
        detected_inputs=profile.available_inputs,
        chosen_mode=chosen_mode,
        requested_mode=requested_mode,
        recommended_mode=plan.recommended_mode,
        missing_info=plan.missing_inputs,
        viewer_type=viewer_type,
        can_execute=plan.can_execute,
        safety_fallback=fallback_reason,
        summary=plan.handoff_summary,
        runtime_mode=plan.runtime_mode,
    )


def build_planning_result(
    context: CaseContext,
    profile: CapabilityProfile,
    plan: AnalysisPlan,
    *,
    requested_mode: str | None = None,
    executed_mode: str | None = None,
    viewer_type: str = "png_fallback",
    context_availability: list[dict[str, Any]] | None = None,
) -> PlanningResult:
    if plan.can_execute and plan.autorun:
        next_action = f"Open the {plan.recommended_workflow.replace('_', ' ')} workspace and start the recommended analysis automatically."
    elif plan.can_execute:
        next_action = f"Open the {plan.recommended_workflow.replace('_', ' ')} workspace and review the selected case."
    else:
        next_action = "Stay in Home chat, clarify the available inputs, and request the missing data before execution."

    entities = {
        "patient_id": context.patient_id,
        "study_id": context.study_id,
        "case_id": context.case_id,
        "report_id": context.report_id,
        "source_kind": context.source_kind,
        "workflow_id": context.workflow_id,
        "imaging_format": profile.imaging_format,
    }
    return PlanningResult(
        workflow_family=plan.workflow_family,
        workflow_id=plan.workflow_task_id or plan.workflow_id,
        intent=plan.requested_goal,
        family=plan.workflow_family,
        track=plan.analysis_track,
        primary_goal=plan.primary_goal,
        dashboard_profile=plan.dashboard_profile,
        secondary_lanes=list(plan.secondary_lanes),
        goal_confidence=0.9 if plan.can_execute else 0.72,
        entities=entities,
        available_data=profile.available_inputs,
        recommended_workflow=plan.recommended_workflow,
        requested_goal=plan.requested_goal,
        recommended_goal=plan.recommended_goal,
        reason_for_track_selection=" ".join(plan.rationale[:2]).strip() or plan.handoff_summary,
        user_override_allowed=True,
        context_sources=profile.context_sources,
        can_execute=plan.can_execute,
        missing_inputs=plan.missing_inputs,
        recommended_next_action=next_action,
        viewer_type=viewer_type,
        blocked_claims=list(profile.blocked_reasons),
        autorun=plan.autorun,
        analysis_plan_summary=summarize_analysis_plan(
            plan,
            profile,
            requested_mode=requested_mode,
            executed_mode=executed_mode,
            viewer_type=viewer_type,
        ),
        capability_profile_summary=summarize_capability_profile(profile),
        context_availability=context_availability or [],
    )


def build_workspace_contract(
    *,
    workflow_id: str,
    workflow_family: str,
    analysis_track: str,
    dashboard_profile: str,
    workspace_url: str,
    module: str,
    runtime_mode: str,
    viewer_type: str,
    can_autorun: bool,
    planning_result: PlanningResult,
    primary_goal: str | None = None,
    secondary_lanes: list[str] | None = None,
    task_traces: list[dict[str, Any]] | None = None,
    tool_policy: dict[str, Any] | None = None,
    context_availability: list[dict[str, Any]] | None = None,
    memory_context: dict[str, Any] | None = None,
    planner_defaults: dict[str, Any] | None = None,
) -> WorkspaceContract:
    return WorkspaceContract(
        workflow_id=workflow_id,
        workflow_family=workflow_family,
        analysis_track=analysis_track,
        primary_goal=primary_goal or planning_result.primary_goal,
        dashboard_profile=dashboard_profile,
        secondary_lanes=list(secondary_lanes or planning_result.secondary_lanes),
        workspace_url=workspace_url,
        module=module,
        runtime_mode=runtime_mode,
        viewer_type=viewer_type,
        can_autorun=can_autorun,
        planning_result=planning_result.to_dict(),
        task_traces=task_traces or [],
        tool_policy=tool_policy or {},
        context_availability=context_availability or planning_result.context_availability,
        memory_context=memory_context or {},
        planner_defaults=planner_defaults or {},
    )
