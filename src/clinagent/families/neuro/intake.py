"""Structured intake, capability assessment, and safe planning for neuro MRI analysis."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from clinagent.platform.capabilities import evaluate_neuro_workflow_capability
from clinagent.platform.family_registry import resolve_workflow_registry_id
from clinagent.platform.harness import (
    AnalysisPlan,
    AnalysisPlanSummary,
    CapabilityProfile,
    CapabilityProfileSummary,
    CaseContext,
    PlanningResult,
    build_planning_result,
    summarize_analysis_plan,
    summarize_capability_profile,
)


AnalysisMode = Literal["vanilla", "seg_overlay", "tool_output", "full_agent"]
SourceKind = Literal["curated_case", "upload", "nifti", "dicom", "pacs", "chat_only"]
AnalysisTrack = Literal["structural", "response", "review"]
PrimaryGoal = Literal["structural_report", "response_review", "report_review"]

DEFAULT_STAGES = [
    "intake",
    "context_resolution",
    "capability_assessment",
    "goal_selection",
    "tool_plan",
    "execution",
    "synthesis",
    "presentation",
]


CaseIntakeContext = CaseContext


def normalize_case_intake(
    *,
    request_text: str = "",
    source_kind: SourceKind = "chat_only",
    patient_id: str | None = None,
    study_id: str | None = None,
    case_id: str | None = None,
    nifti_path: str | None = None,
    dicom_path: str | None = None,
    pacs_reference: str | None = None,
    seg_path: str | None = None,
    age: int | None = None,
    sex: str | None = None,
    indication: str | None = None,
    available_sequences: list[str] | None = None,
    has_prior_study: bool = False,
    has_prior_report: bool = False,
    has_ehr_context: bool = False,
    has_report_context: bool = False,
) -> CaseIntakeContext:
    text = request_text.strip()
    sequences = [item for item in (available_sequences or []) if item]

    normalized_source = source_kind
    if nifti_path and normalized_source == "chat_only":
        normalized_source = "nifti"
    elif dicom_path and normalized_source == "chat_only":
        normalized_source = "dicom"
    elif pacs_reference and normalized_source == "chat_only":
        normalized_source = "pacs"

    return CaseIntakeContext(
        workflow_id="neuro_report",
        workflow_family="neuro",
        request_text=text,
        source_kind=normalized_source,
        patient_id=patient_id,
        study_id=study_id,
        case_id=case_id,
        nifti_path=nifti_path,
        dicom_path=dicom_path,
        pacs_reference=pacs_reference,
        seg_path=seg_path,
        age=age,
        sex=(sex or "").upper() or None,
        indication=indication,
        available_sequences=sequences,
        has_prior_study=has_prior_study,
        has_prior_report=has_prior_report,
        has_ehr_context=has_ehr_context or age is not None or bool(sex),
        has_report_context=has_report_context or has_prior_report or bool(indication),
    )


def _normalize_ingest_context(ingest_context: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(ingest_context, dict):
        return {}
    raw_inventory = ingest_context.get("raw_inventory")
    suggested_workflows = ingest_context.get("suggested_workflows")
    return {
        "detected_type": str(ingest_context.get("detected_type") or "").strip().lower(),
        "has_imaging": bool(ingest_context.get("has_imaging")),
        "has_longitudinal_data": bool(ingest_context.get("has_longitudinal_data")),
        "has_segmentation": bool(ingest_context.get("has_segmentation")),
        "patient_count": int(ingest_context.get("patient_count") or 0),
        "raw_inventory": raw_inventory if isinstance(raw_inventory, dict) else {},
        "source_path": str(ingest_context.get("source_path") or "").strip(),
        "suggested_workflows": suggested_workflows if isinstance(suggested_workflows, list) else [],
    }


def infer_chat_intake(message: str, ingest_context: dict[str, object] | None = None) -> CaseIntakeContext:
    lowered = message.lower()
    normalized_ingest = _normalize_ingest_context(ingest_context)
    raw_inventory = normalized_ingest.get("raw_inventory", {})
    has_nifti_upload = any(bool(raw_inventory.get(ext, 0)) for ext in ("nii", "nii.gz"))
    has_dicom_upload = any(bool(raw_inventory.get(ext, 0)) for ext in ("dcm", "dicom"))
    has_uploaded_imaging = bool(normalized_ingest.get("has_imaging")) or has_nifti_upload or has_dicom_upload
    has_uploaded_segmentation = bool(normalized_ingest.get("has_segmentation"))
    source_path = str(normalized_ingest.get("source_path") or "").strip() or None
    mentions_curated = any(token in lowered for token in ("curated", "example", "demo case", "show me a case", "show me an example"))
    mentions_nifti = any(token in lowered for token in ("nifti", ".nii", ".nii.gz"))
    mentions_dicom = "dicom" in lowered
    mentions_pacs = "pacs" in lowered or "dicomweb" in lowered
    mentions_seg = any(token in lowered for token in ("segmentation", "mask", "overlay"))
    mentions_volume = any(token in lowered for token in ("volume", "volumetric", "z-score", "percentile"))
    mentions_prior = any(token in lowered for token in ("longitudinal", "follow-up", "follow up", "prior", "trend"))
    mentions_ehr = any(token in lowered for token in ("ehr", "sqlite", "age", "sex", "demographic"))

    source_kind: SourceKind = "chat_only"
    if mentions_curated:
        source_kind = "curated_case"
    elif mentions_nifti:
        source_kind = "nifti"
    elif mentions_dicom:
        source_kind = "dicom"
    elif mentions_pacs:
        source_kind = "pacs"
    elif has_uploaded_imaging:
        source_kind = "upload"

    indication = "Brain MRI review requested from Home chat" if "brain" in lowered or "mri" in lowered or has_uploaded_imaging else None
    return normalize_case_intake(
        request_text=message,
        source_kind=source_kind,
        nifti_path=source_path if (mentions_nifti or has_nifti_upload) else None,
        dicom_path=source_path if (mentions_dicom or has_dicom_upload) else None,
        seg_path=source_path if has_uploaded_segmentation else ("requested" if mentions_seg else None),
        has_prior_study=mentions_prior or bool(normalized_ingest.get("has_longitudinal_data")),
        has_prior_report=mentions_prior or bool(normalized_ingest.get("has_longitudinal_data")),
        has_ehr_context=mentions_ehr,
        has_report_context=mentions_prior or bool(normalized_ingest.get("has_longitudinal_data")),
        indication=indication,
    )


def build_capability_profile(context: CaseIntakeContext) -> CapabilityProfile:
    has_nifti = bool(context.nifti_path) or context.source_kind in {"curated_case", "nifti", "upload"}
    has_dicom = bool(context.dicom_path) or context.source_kind in {"dicom", "pacs"}
    imaging_format = "hybrid" if has_nifti and has_dicom else "nifti" if has_nifti else "dicom" if has_dicom else "none"
    has_demographics = context.age is not None and context.sex in {"M", "F"}
    has_single_study_mri = has_nifti or has_dicom
    has_segmentation = bool(context.seg_path)
    has_priors = bool(context.has_prior_study or context.has_prior_report)

    available_inputs: list[str] = []
    context_sources: list[str] = []
    if has_nifti:
        available_inputs.append("nifti_mri")
        context_sources.append("local_nifti")
    if has_dicom:
        available_inputs.append("dicom_reference")
        context_sources.append("local_dicom_series")
    if has_segmentation:
        available_inputs.append("segmentation")
        context_sources.append("local_segmentation")
    if has_demographics:
        available_inputs.append("demographics")
    if context.has_ehr_context:
        available_inputs.append("ehr_context")
        context_sources.append("ehr_context")
    if context.has_report_context or context.indication:
        available_inputs.append("report_context")
        context_sources.append("report_context")
    if has_priors:
        available_inputs.append("longitudinal_priors")
        context_sources.append("longitudinal_history")

    missing_inputs: list[str] = []
    blocked_reasons: list[str] = []
    if not has_single_study_mri:
        missing_inputs.append("brain_mri")
        blocked_reasons.append("No analyzable brain MRI input is available yet.")
    if has_dicom and not has_nifti:
        missing_inputs.append("resolved_primary_series")
        blocked_reasons.append("DICOM/PACS inputs still need series resolution before MRI analysis can run.")
    if not has_demographics:
        missing_inputs.append("age_and_sex")
        blocked_reasons.append("Age and sex are missing, so normative volumetric interpretation must stay disabled.")
    if not has_segmentation:
        missing_inputs.append("segmentation")
        blocked_reasons.append("Segmentation is missing, so overlay and quantitative volumetrics must fall back.")

    return CapabilityProfile(
        workflow_id="neuro_report",
        workflow_family="neuro",
        has_demographics=has_demographics,
        has_single_study_mri=has_single_study_mri,
        imaging_format=imaging_format,
        has_segmentation=has_segmentation,
        has_longitudinal_priors=has_priors,
        has_report_context=bool(context.has_report_context or context.indication),
        has_ehr_context=context.has_ehr_context,
        has_report_text=bool(context.indication),
        has_template_context=False,
        available_inputs=available_inputs,
        missing_inputs=missing_inputs,
        blocked_reasons=blocked_reasons,
        context_sources=context_sources,
    )


def choose_analysis_track(context: CaseIntakeContext, profile: CapabilityProfile) -> AnalysisTrack:
    lowered = context.request_text.lower()
    review_tokens = ("review this report", "quality check", "draft critique", "omission", "inconsistency", "report quality")
    response_tokens = (
        "tumor",
        "lesion",
        "mets",
        "metastasis",
        "response",
        "progression",
        "rano",
        "follow-up burden",
        "follow up burden",
        "brain metastasis",
    )
    structural_tokens = ("atrophy", "ventricle", "hippocampus", "normative", "volume", "volumetric", "structure")

    if any(token in lowered for token in review_tokens):
        return "review"
    if any(token in lowered for token in response_tokens):
        return "response"
    if any(token in lowered for token in structural_tokens):
        return "structural"
    if profile.has_longitudinal_priors and profile.has_segmentation and any(token in lowered for token in ("follow-up", "follow up", "longitudinal", "prior", "trend")):
        return "response"
    return "structural"


def dashboard_for_track(track: AnalysisTrack) -> str:
    if track == "response":
        return "longitudinal_response"
    if track == "review":
        return "report_review"
    return "volumetry"


def primary_goal_for_track(track: AnalysisTrack) -> PrimaryGoal:
    if track == "response":
        return "response_review"
    if track == "review":
        return "report_review"
    return "structural_report"


def secondary_lanes_for_track(track: AnalysisTrack) -> list[str]:
    if track == "response":
        return ["review", "structural_context"]
    if track == "review":
        return ["structural_context", "response_context"]
    return ["review", "response_context"]


def choose_analysis_mode(context: CaseIntakeContext, profile: CapabilityProfile) -> AnalysisMode | None:
    lowered = context.request_text.lower()
    wants_overlay = any(token in lowered for token in ("overlay", "segmentation", "mask"))
    wants_quant = any(token in lowered for token in ("volume", "volumetric", "z-score", "percentile", "atrophy"))
    capability = evaluate_neuro_workflow_capability(
        has_single_study_mri=profile.has_single_study_mri,
        imaging_format=profile.imaging_format,
        has_segmentation=profile.has_segmentation,
        has_demographics=profile.has_demographics,
        has_longitudinal_priors=profile.has_longitudinal_priors,
        lesion_context=choose_analysis_track(context, profile) == "response",
    )
    if not capability.can_execute or profile.imaging_format == "dicom":
        return None
    if "full_agent" in capability.allowed_modes:
        if wants_overlay and not wants_quant:
            return "seg_overlay"
        return "full_agent"
    if "seg_overlay" in capability.allowed_modes and "full_agent" not in capability.allowed_modes:
        return "seg_overlay" if wants_overlay or wants_quant else "seg_overlay"
    return "vanilla"


def build_analysis_plan(context: CaseIntakeContext, profile: CapabilityProfile) -> AnalysisPlan:
    analysis_track = choose_analysis_track(context, profile)
    primary_goal = primary_goal_for_track(analysis_track)
    dashboard_profile = dashboard_for_track(analysis_track)
    secondary_lanes = secondary_lanes_for_track(analysis_track)
    recommended_mode = choose_analysis_mode(context, profile)
    workflow_capability = evaluate_neuro_workflow_capability(
        has_single_study_mri=profile.has_single_study_mri,
        imaging_format=profile.imaging_format,
        has_segmentation=profile.has_segmentation,
        has_demographics=profile.has_demographics,
        has_longitudinal_priors=profile.has_longitudinal_priors,
        lesion_context=analysis_track == "response",
    )
    allowed: list[str] = []
    blocked: list[str] = []
    rationale: list[str] = []

    if profile.has_single_study_mri and profile.imaging_format in {"nifti", "hybrid"}:
        allowed.append("structured_report_generation")
        rationale.append("A single-study MRI input is available for image-based review.")
    else:
        blocked.append("structured_report_generation")

    if profile.has_segmentation and profile.imaging_format in {"nifti", "hybrid"}:
        allowed.extend(["segmentation_overlay_review", "regional_volume_extraction"])
        rationale.append("Segmentation is available, so overlay and structure-level measurements are allowed.")
    else:
        blocked.extend(["segmentation_overlay_review", "regional_volume_extraction"])

    if profile.has_segmentation and profile.has_demographics and profile.imaging_format in {"nifti", "hybrid"}:
        allowed.append("normative_volumetric_analysis")
        rationale.append("Demographics and segmentation are both present, so normative volumetrics are allowed.")
    else:
        blocked.append("normative_volumetric_analysis")

    if profile.has_longitudinal_priors:
        allowed.append("longitudinal_storytelling")
        rationale.append("Prior studies or prior report context are available for change-over-time interpretation.")
    else:
        blocked.append("longitudinal_storytelling")

    if analysis_track == "response":
        if profile.has_segmentation:
            allowed.extend(["lesion_volume_tracking", "response_delta_calculation"])
            rationale.append("The request is lesion/response oriented, so lesion burden and interval change tools are relevant.")
        else:
            blocked.extend(["lesion_volume_tracking", "response_delta_calculation"])
            rationale.append("The request is lesion/response oriented, but segmentation is missing, so response quantification must stay limited.")
        if profile.has_longitudinal_priors:
            allowed.append("response_category_suggestion")
        else:
            blocked.append("response_category_suggestion")
    elif analysis_track == "review":
        allowed.extend(["report_draft_review", "finding_impression_consistency_review"])
        rationale.append("The request is report-review oriented, so the workspace should prioritize critique and revision support.")

    if context.source_kind == "curated_case":
        requested_goal = "Launch a curated neuro MRI example and run the safest complete analysis."
    elif context.source_kind in {"dicom", "pacs"}:
        requested_goal = "Resolve DICOM/PACS inputs into an analyzable MRI study."
    elif profile.has_single_study_mri:
        requested_goal = "Analyze the provided MRI input using the safest available workflow."
    else:
        requested_goal = "Clarify available neuro inputs and recommend the next best action."

    can_execute = workflow_capability.can_execute and profile.imaging_format in {"nifti", "hybrid"}
    autorun = can_execute and context.source_kind == "curated_case"

    recommended_goal = (
        "Review lesion burden, interval change, and longitudinal response."
        if analysis_track == "response"
        else "Review and improve a radiology report draft."
        if analysis_track == "review"
        else "Review structural MRI findings, volumetrics, and longitudinal change."
    )

    if not can_execute and profile.imaging_format == "dicom":
        rationale.append("The system should stay in chat or intake mode until a primary MRI series is resolved.")
    elif not can_execute:
        rationale.append("The system should stay in chat mode until imaging is supplied.")

    if recommended_mode == "vanilla":
        rationale.append("The safe fallback is image-only reporting because segmentation or demographics are incomplete.")
    elif recommended_mode == "seg_overlay":
        rationale.append("The safe fallback keeps segmentation as visual support and avoids unsupported quantitative claims.")
    elif recommended_mode == "full_agent":
        rationale.append("All required inputs are present, so the full segmentation-aware workflow can run.")

    if context.source_kind == "chat_only" and not can_execute:
        handoff_summary = "I can explain the neuro workflow and suggest next steps, but I still need MRI input before I can run analysis."
    elif context.source_kind in {"dicom", "pacs"}:
        handoff_summary = "I found DICOM/PACS-style inputs. The next safe step is series resolution before MRI analysis starts."
    elif autorun:
        handoff_summary = "I found a curated MRI case with enough data to start the recommended analysis automatically."
    else:
        handoff_summary = "I found a runnable MRI input and selected the safest analysis mode based on the available data."

    return AnalysisPlan(
        workflow_id="neuro_report",
        workflow_family="neuro",
        analysis_track=analysis_track,
        primary_goal=primary_goal,
        dashboard_profile=dashboard_profile,
        secondary_lanes=secondary_lanes,
        requested_goal=requested_goal,
        recommended_workflow="neuro_report",
        recommended_goal=recommended_goal,
        recommended_mode=recommended_mode,
        can_execute=can_execute,
        autorun=autorun,
        allowed_analyses=allowed,
        blocked_analyses=blocked,
        missing_inputs=profile.missing_inputs,
        rationale=rationale,
        safe_fallback_mode="vanilla" if can_execute else None,
        workflow_task_id=resolve_workflow_registry_id(
            runtime_workflow_id="neuro_report",
            workflow_family="neuro",
            primary_goal=primary_goal,
        ),
        runtime_mode="demo" if can_execute else "read_only",
        stages=DEFAULT_STAGES.copy(),
        handoff_summary=handoff_summary,
    )


def intake_plan_from_message(message: str, ingest_context: dict[str, object] | None = None) -> tuple[CaseIntakeContext, CapabilityProfile, AnalysisPlan]:
    context = infer_chat_intake(message, ingest_context=ingest_context)
    profile = build_capability_profile(context)
    plan = build_analysis_plan(context, profile)
    return context, profile, plan


def record_intake_for_case(
    *,
    patient_id: str,
    study_id: str,
    case_id: str,
    nifti_path: str,
    seg_path: str | None,
    age: int | None,
    sex: str | None,
    indication: str,
    has_prior_study: bool,
    has_prior_report: bool,
    request_text: str = "",
    source_kind: SourceKind = "curated_case",
    available_sequences: list[str] | None = None,
) -> tuple[CaseIntakeContext, CapabilityProfile, AnalysisPlan]:
    context = normalize_case_intake(
        request_text=request_text,
        source_kind=source_kind,
        patient_id=patient_id,
        study_id=study_id,
        case_id=case_id,
        nifti_path=nifti_path,
        seg_path=seg_path,
        age=age,
        sex=sex,
        indication=indication,
        available_sequences=available_sequences,
        has_prior_study=has_prior_study,
        has_prior_report=has_prior_report,
        has_ehr_context=age is not None or bool(sex),
        has_report_context=True,
    )
    profile = build_capability_profile(context)
    plan = build_analysis_plan(context, profile)
    return context, profile, plan


def path_looks_like_dicom(path: str | None) -> bool:
    if not path:
        return False
    suffixes = Path(path).suffixes
    return any(suffix.lower() in {".dcm", ".dicom"} for suffix in suffixes)
