from __future__ import annotations

from clinagent.platform.harness import (
    AnalysisPlan,
    CapabilityProfile,
    CaseContext,
    PlanningResult,
    build_planning_result,
)
from clinagent.platform.family_registry import resolve_workflow_registry_id


def normalize_report_quality_context(
    *,
    request_text: str = "",
    source_kind: str = "chat_only",
    case_id: str | None = None,
    report_text: str | None = None,
    template_id: str | None = None,
    compliance_profile: str | None = None,
) -> CaseContext:
    return CaseContext(
        workflow_id="report_quality_review",
        workflow_family="review",
        requested_goal="Review a clinical report draft for policy, terminology, and completeness.",
        request_text=request_text.strip(),
        source_kind=source_kind,
        case_id=case_id,
        report_text=report_text.strip() if report_text else None,
        template_id=template_id,
        compliance_profile=compliance_profile,
        has_report_context=bool(report_text or case_id),
        metadata={
            "template_id": template_id,
            "compliance_profile": compliance_profile,
        },
    )


def infer_report_quality_context(message: str) -> CaseContext:
    lowered = message.lower()
    wants_demo = any(token in lowered for token in ("demo", "example", "sample", "show me"))
    template_id = "radiology" if any(token in lowered for token in ("radiology", "mri", "ct", "x-ray", "xray")) else "radiology"
    return normalize_report_quality_context(
        request_text=message,
        source_kind="curated_case" if wants_demo else "chat_only",
        template_id=template_id,
        compliance_profile="radiology",
    )


def build_report_quality_capability_profile(context: CaseContext) -> CapabilityProfile:
    has_report_text = bool(context.report_text or context.case_id or context.source_kind == "curated_case")
    has_template_context = bool(context.template_id or context.compliance_profile)
    available_inputs: list[str] = []
    missing_inputs: list[str] = []
    blocked_reasons: list[str] = []
    context_sources = ["report_quality_demo_store"]

    if has_report_text:
        available_inputs.append("report_text")
    else:
        missing_inputs.append("report_text")
        blocked_reasons.append("No report text or selected report-quality case is available yet.")

    if has_template_context:
        available_inputs.append("template_registry")
    else:
        missing_inputs.append("template_context")
        blocked_reasons.append("A template or compliance profile is missing, so the review contract is incomplete.")

    if context.compliance_profile:
        available_inputs.append("compliance_profile")

    return CapabilityProfile(
        workflow_id="report_quality_review",
        workflow_family="review",
        has_demographics=False,
        has_single_study_mri=False,
        imaging_format="none",
        has_segmentation=False,
        has_longitudinal_priors=False,
        has_report_context=has_report_text,
        has_ehr_context=False,
        has_report_text=has_report_text,
        has_template_context=has_template_context,
        available_inputs=available_inputs,
        missing_inputs=missing_inputs,
        blocked_reasons=blocked_reasons,
        context_sources=context_sources,
    )


def build_report_quality_analysis_plan(context: CaseContext, profile: CapabilityProfile) -> AnalysisPlan:
    can_execute = profile.has_report_text and profile.has_template_context
    if context.source_kind == "curated_case" and can_execute:
        handoff_summary = "I found a report-quality example and can open the review workspace with the policy checks ready."
    elif can_execute:
        handoff_summary = "I found enough report context to run privacy, terminology, and completeness review."
    else:
        handoff_summary = "I can explain the report-quality workflow, but I still need report text or a selected sample before running review."

    rationale = [
        "Report quality review works best when there is text to inspect and a template/compliance profile to score against."
    ]
    if can_execute:
        rationale.append("The current context supports privacy, terminology, and completeness checks.")
    else:
        rationale.append("The workflow should stay in intake mode until report text or a selected demo case is available.")

    return AnalysisPlan(
        workflow_id="report_quality_review",
        workflow_family="review",
        analysis_track="review",
        primary_goal="report_review",
        dashboard_profile="report_review",
        secondary_lanes=[],
        requested_goal="Review a clinical report draft for privacy, terminology, and completeness issues.",
        recommended_workflow="report_quality_review",
        recommended_goal="Review report quality and suggest revisions.",
        recommended_mode="policy_check" if can_execute else None,
        can_execute=can_execute,
        autorun=can_execute and context.source_kind == "curated_case",
        allowed_analyses=["privacy_review", "terminology_review", "template_compliance_review"] if can_execute else [],
        blocked_analyses=[] if can_execute else ["privacy_review", "terminology_review", "template_compliance_review"],
        missing_inputs=profile.missing_inputs,
        rationale=rationale,
        safe_fallback_mode=None,
        workflow_task_id=resolve_workflow_registry_id(
            runtime_workflow_id="report_quality_review",
            workflow_family="review",
            primary_goal="report_review",
        ),
        stages=["intake", "policy_check", "finalize"],
        handoff_summary=handoff_summary,
        runtime_mode="read_only" if not can_execute else "clinical_safe",
    )


def build_report_quality_planning_result(
    context: CaseContext,
    profile: CapabilityProfile,
    plan: AnalysisPlan,
) -> PlanningResult:
    return build_planning_result(
        context,
        profile,
        plan,
        requested_mode=plan.recommended_mode,
        executed_mode=plan.recommended_mode,
        viewer_type="workspace",
        context_availability=[
            {
                "server_id": "report_quality_local",
                "label": "Local report-quality context",
                "available": True,
                "source": "demo_store",
            }
        ],
    )


def intake_plan_from_report_quality_message(message: str) -> tuple[CaseContext, CapabilityProfile, AnalysisPlan]:
    context = infer_report_quality_context(message)
    profile = build_report_quality_capability_profile(context)
    plan = build_report_quality_analysis_plan(context, profile)
    return context, profile, plan
