from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from clinagent.platform.family_registry import (
    get_family_registry_entry,
    get_workflow_registry_entry_for_runtime,
    resolve_workflow_registry_id,
)
from clinagent.platform.harness import build_stage_trace_set, build_task_trace_set
from clinagent.platform.mcp_registry import build_mcp_registry_snapshot


@dataclass(frozen=True)
class ClinicalSubAgentRole:
    role_id: str
    title: str
    summary: str
    activation_condition: str
    output_contract: str
    allowed_tools: tuple[str, ...]

    def to_summary(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkflowExecutionProfile:
    workflow_id: str
    title: str
    workflow_family: str
    allowed_tools: tuple[str, ...]
    blocked_tools: tuple[str, ...]
    default_lane: str
    subagents: tuple[str, ...]
    requires_confirmation: bool
    policy_mode: str
    output_contract: dict[str, Any]
    ui_capabilities: dict[str, Any]
    stage_labels: tuple[str, ...]
    task_templates: tuple[dict[str, str], ...]

    def to_summary(self) -> dict[str, Any]:
        data = asdict(self)
        data["allowed_tools"] = list(self.allowed_tools)
        data["blocked_tools"] = list(self.blocked_tools)
        data["subagents"] = list(self.subagents)
        data["stage_labels"] = list(self.stage_labels)
        return data


BASE_AGENT_TOOLS: tuple[str, ...] = (
    "think",
    "write_todos",
    "update_todo",
    "list_skills",
    "use_skill",
    "workflow_catalog",
    "render_clinical_report",
)

BLOCKED_TOOL_CATEGORIES: tuple[str, ...] = (
    "shell_exec",
    "file_edit",
    "external_network_write",
    "unscoped_filesystem_access",
)

SUBAGENT_ROLES: dict[str, ClinicalSubAgentRole] = {
    "intake_agent": ClinicalSubAgentRole(
        role_id="intake_agent",
        title="Intake Agent",
        summary="Converts the request into a workflow-specific handoff with safe next steps.",
        activation_condition="Activated when a request first enters a workflow or needs route clarification.",
        output_contract="Structured intake summary with workflow, request goal, and missing inputs.",
        allowed_tools=("workflow_catalog",),
    ),
    "evidence_agent": ClinicalSubAgentRole(
        role_id="evidence_agent",
        title="Evidence Agent",
        summary="Collects workspace facts, case evidence, and workflow-specific artifacts before synthesis.",
        activation_condition="Activated when the selected workflow has evidence-bearing tools or review surfaces.",
        output_contract="Structured evidence bundle with source workspace facts and open questions.",
        allowed_tools=(
            "get_findings_workspace",
            "get_queue_workspace",
            "get_diagnosis_workspace",
            "get_screening_workspace",
            "get_neuro_workspace",
            "get_neuro_knowledge_cohort",
            "search_neuro_knowledge",
            "get_neuro_knowledge_case",
            "get_neuro_knowledge_case_assets",
            "get_neuro_knowledge_study",
            "get_neuro_longitudinal_workspace",
            "get_neuro_longitudinal_visuals",
            "get_neuro_longitudinal_viewer_manifest",
            "coregister_neuro_sequences",
            "apply_neuro_transform",
            "coregister_neuro_longitudinal",
            "check_deepprep_tool_health",
            "run_deepprep_preprocessing",
            "get_safety_queue",
            "get_safety_case",
            "get_radonc_plan_session",
            "get_radonc_plan_dvh",
        ),
    ),
    "report_agent": ClinicalSubAgentRole(
        role_id="report_agent",
        title="Report Agent",
        summary="Shapes the gathered evidence into a polished clinical response or workspace handoff.",
        activation_condition="Activated when a workflow needs a reusable summary, report, or presentation artifact.",
        output_contract="Structured report summary with final recommendation, review status, and artifact metadata.",
        allowed_tools=("render_clinical_report", "use_skill"),
    ),
}

WORKFLOW_TOOL_MAP: dict[str, tuple[str, ...]] = {
    "general_chat": (
        "get_findings_workspace",
        "get_queue_workspace",
        "get_diagnosis_workspace",
        "get_screening_workspace",
        "get_neuro_workspace",
        "get_neuro_knowledge_cohort",
        "search_neuro_knowledge",
        "get_neuro_knowledge_case",
        "get_neuro_knowledge_case_assets",
        "get_neuro_knowledge_study",
        "get_neuro_longitudinal_workspace",
        "get_neuro_longitudinal_visuals",
        "get_neuro_longitudinal_viewer_manifest",
        "build_neuro_visualization_bundle",
        "get_neuro_longitudinal_report",
        "get_neuro_longitudinal_series_catalog",
        "dicom_series_selector",
        "check_brain_seg_service_health",
        "get_brain_structure_model_info",
        "run_brain_structure_segmentation",
        "coregister_neuro_sequences",
        "apply_neuro_transform",
        "coregister_neuro_longitudinal",
        "check_deepprep_tool_health",
        "run_deepprep_preprocessing",
        "brain_met_response_tracker",
        "rt_timeline_aligner",
        "slice_preview_renderer",
        "lesion_trend_plotter",
        "treatment_event_timeline_renderer",
        "key_slice_selector",
        "overlay_composer",
        "longitudinal_comparison_panel_builder",
        "risk_signal_renderer",
        "get_safety_queue",
        "get_safety_case",
        "search_safety_knowledge",
    ),
    "report_quality_review": (),
    "findings_closure": ("get_findings_workspace",),
    "queue_triage": ("get_queue_workspace",),
    "missed_diagnosis_detection": ("get_diagnosis_workspace",),
    "screening_gap_closure": ("get_screening_workspace",),
    "neuro_longitudinal": (
        "get_neuro_longitudinal_workspace",
        "get_neuro_knowledge_cohort",
        "search_neuro_knowledge",
        "get_neuro_knowledge_case",
        "get_neuro_knowledge_case_assets",
        "get_neuro_knowledge_study",
        "get_neuro_longitudinal_visuals",
        "get_neuro_longitudinal_viewer_manifest",
        "build_neuro_visualization_bundle",
        "get_neuro_longitudinal_report",
        "get_neuro_longitudinal_series_catalog",
        "dicom_series_selector",
        "check_brain_seg_service_health",
        "get_brain_structure_model_info",
        "run_brain_structure_segmentation",
        "coregister_neuro_sequences",
        "apply_neuro_transform",
        "coregister_neuro_longitudinal",
        "check_deepprep_tool_health",
        "run_deepprep_preprocessing",
        "brain_met_response_tracker",
        "rt_timeline_aligner",
        "slice_preview_renderer",
        "lesion_trend_plotter",
        "treatment_event_timeline_renderer",
        "key_slice_selector",
        "overlay_composer",
        "longitudinal_comparison_panel_builder",
        "risk_signal_renderer",
    ),
    "neuro_report": (
        "get_neuro_longitudinal_workspace",
        "get_neuro_knowledge_cohort",
        "search_neuro_knowledge",
        "get_neuro_knowledge_case",
        "get_neuro_knowledge_case_assets",
        "get_neuro_knowledge_study",
        "get_neuro_longitudinal_visuals",
        "get_neuro_longitudinal_viewer_manifest",
        "build_neuro_visualization_bundle",
        "get_neuro_longitudinal_report",
        "get_neuro_longitudinal_series_catalog",
        "check_brain_seg_service_health",
        "get_brain_structure_model_info",
        "run_brain_structure_segmentation",
        "coregister_neuro_sequences",
        "apply_neuro_transform",
        "coregister_neuro_longitudinal",
        "check_deepprep_tool_health",
        "run_deepprep_preprocessing",
        "brain_met_response_tracker",
        "slice_preview_renderer",
        "lesion_trend_plotter",
        "longitudinal_comparison_panel_builder",
        "risk_signal_renderer",
    ),
    "radiation_safety_monitor": ("get_safety_queue", "get_safety_case", "search_safety_knowledge"),
    "radonc_plan_optimization": (
        "get_radonc_plan_session",
        "get_radonc_plan_dvh",
        "run_radonc_plan_iteration",
        "submit_radonc_objectives",
        "render_clinical_report",
    ),
}

WORKFLOW_SUBAGENT_MAP: dict[str, tuple[str, ...]] = {
    "general_chat": ("intake_agent",),
    "report_quality_review": ("intake_agent", "report_agent"),
    "findings_closure": ("intake_agent", "evidence_agent", "report_agent"),
    "queue_triage": ("intake_agent", "evidence_agent", "report_agent"),
    "missed_diagnosis_detection": ("intake_agent", "evidence_agent", "report_agent"),
    "screening_gap_closure": ("intake_agent", "evidence_agent", "report_agent"),
    "neuro_longitudinal": ("intake_agent", "evidence_agent", "report_agent"),
    "neuro_report": ("intake_agent", "evidence_agent"),
    "radiation_safety_monitor": ("intake_agent", "evidence_agent", "report_agent"),
    "radonc_plan_optimization": ("intake_agent", "evidence_agent", "report_agent"),
}

WORKFLOW_STAGE_MAP: dict[str, tuple[str, ...]] = {
    "general_chat": ("Route", "Clarify", "Respond"),
    "report_quality_review": ("Route", "Policy Check", "Finalize"),
    "findings_closure": ("Route", "Evidence Review", "Closure Brief"),
    "queue_triage": ("Route", "Priority Review", "Queue Recommendation"),
    "missed_diagnosis_detection": ("Route", "Gap Review", "Workup Recommendation"),
    "screening_gap_closure": ("Route", "Gap Review", "Closure Plan"),
    "neuro_longitudinal": ("Route", "Intake", "Evidence Review", "Report Synthesis"),
    "neuro_report": (
        "Intake",
        "Context Resolution",
        "Capability Assessment",
        "Goal Selection",
        "Tool Plan",
        "Execution",
        "Synthesis",
        "Presentation",
    ),
    "radiation_safety_monitor": ("Route", "Safety Review", "Mitigation Brief"),
    "radonc_plan_optimization": (
        "Intake",
        "Context Resolution",
        "Capability Assessment",
        "Goal Selection",
        "Tool Plan",
        "Execution",
        "Synthesis",
        "Presentation",
    ),
}

WORKFLOW_POLICY_MODE_MAP: dict[str, str] = {
    "general_chat": "read_only",
    "report_quality_review": "clinical_safe",
    "findings_closure": "clinical_safe",
    "queue_triage": "clinical_safe",
    "missed_diagnosis_detection": "clinical_safe",
    "screening_gap_closure": "clinical_safe",
    "neuro_longitudinal": "demo",
    "neuro_report": "demo",
    "radiation_safety_monitor": "clinical_safe",
    "radonc_plan_optimization": "planning_controlled_writeback",
}

WORKFLOW_TASK_MAP: dict[str, tuple[dict[str, str], ...]] = {
    "general_chat": (
        {"id": "route_request", "label": "Route request", "stage_id": "route", "role_id": "intake_agent", "summary": "Classify the request and decide whether to stay in chat or hand off."},
        {"id": "prepare_response", "label": "Prepare response", "stage_id": "respond", "role_id": "report_agent", "summary": "Prepare the user-facing answer or workspace handoff."},
    ),
    "report_quality_review": (
        {"id": "intake_report", "label": "Intake report", "stage_id": "route", "role_id": "intake_agent", "summary": "Normalize the report-quality request and inputs."},
        {"id": "policy_check", "label": "Policy check", "stage_id": "policy_check", "role_id": "report_agent", "summary": "Run privacy, terminology, and completeness review."},
        {"id": "finalize_review", "label": "Finalize review", "stage_id": "finalize", "role_id": "report_agent", "summary": "Prepare the review workspace handoff."},
    ),
    "neuro_report": (
        {"id": "intake_request", "label": "Intake request", "stage_id": "intake", "role_id": "intake_agent", "summary": "Normalize the neuro request, source type, and requested goal."},
        {"id": "resolve_context", "label": "Resolve context", "stage_id": "context_resolution", "role_id": "evidence_agent", "summary": "Resolve study context, priors, and external data availability."},
        {"id": "assess_capability", "label": "Assess capability", "stage_id": "capability_assessment", "role_id": "evidence_agent", "summary": "Decide what analysis modes, viewer backend, and claims are allowed."},
        {"id": "select_goal", "label": "Select goal", "stage_id": "goal_selection", "role_id": "intake_agent", "summary": "Choose the primary goal, dashboard profile, and secondary lanes."},
        {"id": "plan_tools", "label": "Plan tools", "stage_id": "tool_plan", "role_id": "evidence_agent", "summary": "Prepare the track-specific tool bundle and fallback policy."},
        {"id": "execute_track", "label": "Execute track", "stage_id": "execution", "role_id": "evidence_agent", "summary": "Run the chosen structural, response, or review execution path."},
        {"id": "synthesize_result", "label": "Synthesize result", "stage_id": "synthesis", "role_id": "report_agent", "summary": "Combine evidence, measurements, and track-specific findings."},
        {"id": "present_workspace", "label": "Present workspace", "stage_id": "presentation", "role_id": "report_agent", "summary": "Prepare the dashboard-aware handoff and workspace contract."},
    ),
    "radonc_plan_optimization": (
        {"id": "intake_request", "label": "Intake request", "stage_id": "intake", "role_id": "intake_agent", "summary": "Normalize the radonc optimization request, protocol, and connector state."},
        {"id": "resolve_context", "label": "Resolve context", "stage_id": "context_resolution", "role_id": "evidence_agent", "summary": "Resolve RT plan, structures, DVH, and protocol availability."},
        {"id": "assess_capability", "label": "Assess capability", "stage_id": "capability_assessment", "role_id": "evidence_agent", "summary": "Decide whether auto optimization, supervised review, or intake-only mode is allowed."},
        {"id": "select_goal", "label": "Select goal", "stage_id": "goal_selection", "role_id": "intake_agent", "summary": "Choose the optimization goal, dashboard profile, and review lane defaults."},
        {"id": "plan_tools", "label": "Plan tools", "stage_id": "tool_plan", "role_id": "evidence_agent", "summary": "Prepare DVH analysis, objective adjustment, and controlled write-back steps."},
        {"id": "execute_loop", "label": "Execute loop", "stage_id": "execution", "role_id": "evidence_agent", "summary": "Run iterative plan optimization until goals are met, plateau, or stop is requested."},
        {"id": "synthesize_summary", "label": "Synthesize summary", "stage_id": "synthesis", "role_id": "report_agent", "summary": "Summarize goal fulfillment, trade-offs, and the latest objective state."},
        {"id": "present_workspace", "label": "Present workspace", "stage_id": "presentation", "role_id": "report_agent", "summary": "Prepare the radonc workspace handoff with DVH, timeline, and report surfaces."},
    ),
}

WORKFLOW_FAMILY_MAP: dict[str, str] = {
    "general_chat": "general",
    "report_quality_review": "review",
    "findings_closure": "findings",
    "queue_triage": "queue",
    "missed_diagnosis_detection": "diagnosis",
    "screening_gap_closure": "screening",
    "neuro_longitudinal": "neuro",
    "neuro_report": "neuro",
    "radiation_safety_monitor": "safety",
    "radonc_plan_optimization": "radonc",
}

WORKFLOW_OUTPUT_CONTRACTS: dict[str, dict[str, Any]] = {
    "general_chat": {"kind": "chat_summary", "sections": ["Routing", "Next Step"]},
    "report_quality_review": {"kind": "report_quality_summary", "sections": ["Privacy", "Terminology", "Completeness"]},
    "findings_closure": {"kind": "findings_brief", "sections": ["Finding Summary", "Closure Check", "Recommended Next Step"]},
    "queue_triage": {"kind": "queue_brief", "sections": ["Queue Signal", "Priority Shift", "Recommended Queue Move"]},
    "missed_diagnosis_detection": {"kind": "missed_diagnosis_brief", "sections": ["Gap Signal", "Follow-up Check", "Recommended Workup"]},
    "screening_gap_closure": {"kind": "screening_gap_brief", "sections": ["Screening Signal", "Gap Check", "Recommended Next Step"]},
    "neuro_longitudinal": {"kind": "neuro_longitudinal_brief", "sections": ["MRI Trend Analysis", "Draft Physician Summary", "Recommendations"]},
    "neuro_report": {"kind": "neuro_report_handoff", "sections": ["Intake", "Capabilities", "Workspace Launch"]},
    "radiation_safety_monitor": {"kind": "safety_brief", "sections": ["Risk Summary", "Matched Failure Patterns", "Escalation"]},
    "radonc_plan_optimization": {"kind": "radonc_plan_optimization", "sections": ["Inputs", "Constraint Review", "Iteration Summary", "Suggested Next Step"]},
}

PRIMARY_GOAL_TOOL_BUNDLES: dict[str, dict[str, tuple[str, ...]]] = {
    "neuro_report": {
        "structural_report": (
            "brain_segmentation",
            "volumetric_analysis",
            "normative_structural_synthesis",
        ),
        "response_review": (
            "lesion_segmentation_ingestion",
            "lesion_volume_calculator",
            "response_delta_calculator",
            "longitudinal_response_synthesizer",
        ),
        "report_review": (
            "report_section_parser",
            "finding_impression_consistency_checker",
            "report_revision_synthesizer",
        ),
    },
    "report_quality_review": {
        "report_review": (
            "report_section_parser",
            "finding_impression_consistency_checker",
            "report_revision_synthesizer",
        ),
    },
    "radonc_plan_optimization": {
        "plan_optimization": (
            "rt_plan_context_loader",
            "dvh_constraint_analyzer",
            "objective_adjustment_engine",
            "plan_tradeoff_synthesizer",
        ),
    },
}


def _workflow_title(workflow_id: str) -> str:
    return workflow_id.replace("_", " ").title()


def _profile_for(workflow_id: str) -> WorkflowExecutionProfile:
    allowed_tools = tuple(dict.fromkeys(BASE_AGENT_TOOLS + WORKFLOW_TOOL_MAP.get(workflow_id, ())))
    return WorkflowExecutionProfile(
        workflow_id=workflow_id,
        title=_workflow_title(workflow_id),
        workflow_family=WORKFLOW_FAMILY_MAP.get(workflow_id, "general"),
        allowed_tools=allowed_tools,
        blocked_tools=BLOCKED_TOOL_CATEGORIES,
        default_lane="main",
        subagents=WORKFLOW_SUBAGENT_MAP.get(workflow_id, ("intake_agent",)),
        requires_confirmation=workflow_id in {"neuro_report", "report_quality_review"},
        policy_mode=WORKFLOW_POLICY_MODE_MAP.get(workflow_id, "read_only"),
        output_contract=WORKFLOW_OUTPUT_CONTRACTS.get(workflow_id, {"kind": "workflow_summary", "sections": ["Summary"]}),
        ui_capabilities={
            "show_tool_policy": True,
            "show_subagents": True,
            "show_stage_labels": True,
            "user_safe_summary": True,
        },
        stage_labels=WORKFLOW_STAGE_MAP.get(workflow_id, ("Route", "Respond")),
        task_templates=WORKFLOW_TASK_MAP.get(workflow_id, ()),
    )


WORKFLOW_PROFILES: dict[str, WorkflowExecutionProfile] = {
    workflow_id: _profile_for(workflow_id)
    for workflow_id in (
        "general_chat",
        "report_quality_review",
        "findings_closure",
        "queue_triage",
        "missed_diagnosis_detection",
        "screening_gap_closure",
        "neuro_longitudinal",
        "neuro_report",
        "radiation_safety_monitor",
        "radonc_plan_optimization",
    )
}


def get_execution_profile(workflow_id: str) -> WorkflowExecutionProfile:
    return WORKFLOW_PROFILES.get(workflow_id, WORKFLOW_PROFILES["general_chat"])


def list_execution_profiles() -> list[dict[str, Any]]:
    return [profile.to_summary() for profile in WORKFLOW_PROFILES.values()]


def list_subagent_roles() -> list[dict[str, Any]]:
    return [role.to_summary() for role in SUBAGENT_ROLES.values()]


def list_developer_actions() -> list[dict[str, str]]:
    return [
        {
            "id": "inspect_profile",
            "label": "Inspect workflow profile",
            "description": "Show the selected workflow policy, allowed tools, and subagent roles.",
        },
        {
            "id": "route_only",
            "label": "Route only",
            "description": "Classify the request without entering the full workflow execution path.",
        },
        {
            "id": "dry_run",
            "label": "Dry-run workflow",
            "description": "Preview the workflow handoff and trace skeleton without mutating workspaces.",
        },
        {
            "id": "inspect_handoff",
            "label": "Inspect handoff",
            "description": "Review the structured handoff that would be sent into the workflow agent path.",
        },
    ]


def resolve_tool_policy(
    workflow_id: str,
    *,
    workflow_family: str | None = None,
    primary_goal: str | None = None,
    policy_mode: str | None = None,
) -> dict[str, Any]:
    profile = get_execution_profile(workflow_id)
    family = workflow_family or profile.workflow_family
    mode = policy_mode or profile.policy_mode
    declared_tools = list(profile.allowed_tools)
    goal_bundles = PRIMARY_GOAL_TOOL_BUNDLES.get(workflow_id, {})
    allowed_tools = list(goal_bundles.get(primary_goal or "", ())) or declared_tools
    blocked_goal_tools = sorted(
        {
            tool
            for goal, bundle in goal_bundles.items()
            if primary_goal is None or goal != primary_goal
            for tool in bundle
        }
        - set(allowed_tools)
    )
    return {
        "mode": mode,
        "workflow_family": family,
        "primary_goal": primary_goal,
        "allowed_tools": allowed_tools,
        "blocked_tools": blocked_goal_tools,
        "blocked_tool_classes": list(profile.blocked_tools),
        "bundle_source": "goal_bundle" if primary_goal and goal_bundles.get(primary_goal) else "workflow_profile",
    }


def build_workflow_runtime_bundle(
    workflow_id: str,
    *,
    workflow_family: str | None = None,
    primary_goal: str | None = None,
    dashboard_profile: str | None = None,
    track: str | None = None,
    context_sources: list[str] | None = None,
    fallback_reason: str | None = None,
    policy_mode: str | None = None,
) -> dict[str, Any]:
    profile = get_execution_profile(workflow_id)
    family = workflow_family or profile.workflow_family
    workflow_registry_id = resolve_workflow_registry_id(
        runtime_workflow_id=workflow_id,
        workflow_family=family,
        primary_goal=primary_goal,
    )
    tool_policy = resolve_tool_policy(
        workflow_id,
        workflow_family=family,
        primary_goal=primary_goal,
        policy_mode=policy_mode or profile.policy_mode,
    )
    stage_summary = build_stage_trace_set(
        labels=profile.stage_labels,
        workflow_family=family,
        track=track,
        primary_goal=primary_goal,
        dashboard_profile=dashboard_profile,
        policy_mode=tool_policy["mode"],
        allowed_tools=tool_policy["allowed_tools"],
        blocked_tools=tool_policy["blocked_tools"],
        context_sources=context_sources,
        fallback_reason=fallback_reason,
    )
    task_summary = build_task_trace_set(
        task_templates=profile.task_templates,
        workflow_family=family,
        track=track or "default",
        primary_goal=primary_goal,
        dashboard_profile=dashboard_profile,
        policy_mode=tool_policy["mode"],
        allowed_tools=tool_policy["allowed_tools"],
        blocked_tools=tool_policy["blocked_tools"],
        context_sources=context_sources,
        fallback_reason=fallback_reason,
    )
    mcp_snapshot = build_mcp_registry_snapshot(workflow_id=workflow_id, workflow_family=family)
    return {
        "workflow_registry_id": workflow_registry_id,
        "family_registry": get_family_registry_entry(family),
        "workflow_registry": get_workflow_registry_entry_for_runtime(
            runtime_workflow_id=workflow_id,
            workflow_family=family,
            primary_goal=primary_goal,
        ),
        "stage_summary": stage_summary,
        "task_summary": task_summary,
        "tool_policy": tool_policy,
        "mcp_snapshot": mcp_snapshot,
        "mcp_servers": list(mcp_snapshot.get("servers", [])),
        "subagent_activity": [
            {
                "role_id": role_id,
                "title": SUBAGENT_ROLES[role_id].title,
                "status": "available",
                "summary": SUBAGENT_ROLES[role_id].summary,
            }
            for role_id in profile.subagents
            if role_id in SUBAGENT_ROLES
        ],
    }


def build_route_runtime(route: dict[str, Any]) -> dict[str, Any]:
    profile = get_execution_profile(str(route.get("workflow_id") or "general_chat"))
    workflow = route.get("workflow") or {}
    workflow_family = str(route.get("workflow_family") or profile.workflow_family)
    primary_goal = route.get("primary_goal")
    dashboard_profile = route.get("dashboard_profile")
    track = route.get("track")
    context_sources = list(route.get("context_sources") or [])
    fallback_reason = route.get("fallback_reason")
    memory_context = route.get("memory_context") or {}
    planner_defaults = route.get("planner_defaults") or {}
    runtime_bundle = build_workflow_runtime_bundle(
        profile.workflow_id,
        workflow_family=workflow_family,
        primary_goal=str(primary_goal) if primary_goal else None,
        dashboard_profile=str(dashboard_profile) if dashboard_profile else None,
        track=str(track) if track else None,
        context_sources=context_sources,
        fallback_reason=str(fallback_reason) if fallback_reason else None,
        policy_mode=str(route.get("policy_mode") or profile.policy_mode),
    )
    route_summary = {
        "workflow_id": profile.workflow_id,
        "workflow_task_id": runtime_bundle["workflow_registry_id"],
        "workflow_family": workflow_family,
        "workflow_title": workflow.get("title") or profile.title,
        "target_module": route.get("target_module"),
        "suggested_module": route.get("suggested_module"),
        "confidence": route.get("confidence"),
        "fallback": route.get("fallback", False),
        "reason": route.get("reason"),
        "next_action": route.get("next_action"),
        "alternatives": route.get("alternatives", []),
        "primary_goal": primary_goal,
        "dashboard_profile": dashboard_profile,
        "context_sources": context_sources,
    }
    user_explanation = (
        f"Routed to {workflow.get('title') or profile.title}. "
        f"Next step: {route.get('next_action') or 'Open the selected workflow.'}"
    )
    developer_explanation = (
        f"Router selected {workflow.get('title') or profile.title} "
        f"for module {route.get('target_module') or 'home'} on lane {profile.default_lane}. "
        f"Enabled {len(profile.allowed_tools)} allowed tools and {len(profile.subagents)} declared subagent roles."
    )
    handoff = {
        "workflow_id": profile.workflow_id,
        "workflow_task_id": runtime_bundle["workflow_registry_id"],
        "workflow_family": workflow_family,
        "workflow_title": workflow.get("title") or profile.title,
        "target_module": route.get("target_module"),
        "default_lane": profile.default_lane,
        "requires_confirmation": profile.requires_confirmation,
        "policy_mode": runtime_bundle["tool_policy"]["mode"],
        "primary_goal": primary_goal,
        "dashboard_profile": dashboard_profile,
        "family_registry": runtime_bundle["family_registry"],
        "workflow_registry": runtime_bundle["workflow_registry"],
        "subagents": list(profile.subagents),
        "output_contract": profile.output_contract,
    }
    return {
        "route": route_summary,
        "profile": profile.to_summary(),
        "user_explanation": user_explanation,
        "developer_explanation": developer_explanation,
        "handoff": handoff,
        "stage_summary": runtime_bundle["stage_summary"],
        "task_summary": runtime_bundle["task_summary"],
        "tool_policy": runtime_bundle["tool_policy"],
        "mcp_servers": runtime_bundle["mcp_servers"],
        "mcp_snapshot": runtime_bundle["mcp_snapshot"],
        "family_registry": runtime_bundle["family_registry"],
        "workflow_registry": runtime_bundle["workflow_registry"],
        "memory_context": memory_context,
        "planner_defaults": planner_defaults,
        "subagent_activity": runtime_bundle["subagent_activity"],
    }
