from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelCapability:
    model_name: str
    api_architecture: str
    max_tokens_field: str
    supports_reasoning_effort: bool
    supports_verbosity: bool
    supports_streaming: bool
    supports_tool_calling: bool
    supports_parallel_tool_calls: bool
    supports_image_input: bool
    supports_strict_tool_schema: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkflowCapability:
    workflow_id: str
    workflow_family: str
    allowed_tracks: list[str]
    blocked_tracks: list[str]
    dashboard_profiles: list[str]
    allowed_modes: list[str]
    blocked_modes: list[str]
    viewer_type: str
    can_execute: bool
    required_inputs: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CHAT_COMPLETIONS_CAPABILITY = ModelCapability(
    model_name="chat_completions_default",
    api_architecture="chat_completions",
    max_tokens_field="max_tokens",
    supports_reasoning_effort=False,
    supports_verbosity=False,
    supports_streaming=True,
    supports_tool_calling=True,
    supports_parallel_tool_calls=True,
    supports_image_input=True,
    supports_strict_tool_schema=False,
)

RESPONSES_API_CAPABILITY = ModelCapability(
    model_name="responses_api_default",
    api_architecture="responses_api",
    max_tokens_field="max_completion_tokens",
    supports_reasoning_effort=True,
    supports_verbosity=True,
    supports_streaming=False,
    supports_tool_calling=True,
    supports_parallel_tool_calls=True,
    supports_image_input=True,
    supports_strict_tool_schema=True,
)


MODEL_CAPABILITY_REGISTRY: dict[str, ModelCapability] = {
    "gpt-5": RESPONSES_API_CAPABILITY,
    "gpt-5-mini": RESPONSES_API_CAPABILITY,
    "gpt-5-nano": RESPONSES_API_CAPABILITY,
    "gpt-5-chat-latest": RESPONSES_API_CAPABILITY,
    "gpt-4o": CHAT_COMPLETIONS_CAPABILITY,
    "gpt-4o-mini": CHAT_COMPLETIONS_CAPABILITY,
    "gpt-4-turbo": CHAT_COMPLETIONS_CAPABILITY,
    "gemini-3-flash-preview": CHAT_COMPLETIONS_CAPABILITY,
    "gemini-2.5-flash": CHAT_COMPLETIONS_CAPABILITY,
    "gemini-2.5-pro": CHAT_COMPLETIONS_CAPABILITY,
    "claude-3-5-sonnet-20241022": CHAT_COMPLETIONS_CAPABILITY,
    "claude-3-5-haiku-20241022": CHAT_COMPLETIONS_CAPABILITY,
}


def infer_model_capability(model_name: str) -> ModelCapability:
    normalized = (model_name or "").strip().lower()
    if normalized in MODEL_CAPABILITY_REGISTRY:
        return MODEL_CAPABILITY_REGISTRY[normalized]
    if "gpt-5" in normalized or normalized.startswith("o1"):
        return RESPONSES_API_CAPABILITY
    if any(token in normalized for token in ("gpt-4", "gemini", "claude")):
        return CHAT_COMPLETIONS_CAPABILITY
    return CHAT_COMPLETIONS_CAPABILITY


def get_model_capability(model_name: str) -> ModelCapability:
    base = infer_model_capability(model_name)
    payload = base.to_dict()
    payload["model_name"] = model_name or base.model_name
    return ModelCapability(**payload)


def evaluate_neuro_workflow_capability(
    *,
    has_single_study_mri: bool,
    imaging_format: str,
    has_segmentation: bool,
    has_demographics: bool,
    has_longitudinal_priors: bool = False,
    lesion_context: bool = False,
) -> WorkflowCapability:
    required_inputs = ["brain_mri"]
    missing_inputs: list[str] = []
    blocked_reasons: list[str] = []
    allowed_modes: list[str] = []
    blocked_modes: list[str] = []

    viewer_type = "png_fallback"
    if imaging_format in {"nifti", "hybrid"}:
        viewer_type = "nifti"
    elif imaging_format == "dicom":
        viewer_type = "dicomweb"

    if not has_single_study_mri:
        missing_inputs.append("brain_mri")
        blocked_reasons.append("No analyzable MRI input is available yet.")
        return WorkflowCapability(
            workflow_id="neuro_report",
            workflow_family="neuro",
            allowed_tracks=[],
            blocked_tracks=["structural", "response", "review"],
            dashboard_profiles=[],
            allowed_modes=[],
            blocked_modes=["vanilla", "seg_overlay", "tool_output", "full_agent", "intake_only"],
            viewer_type=viewer_type,
            can_execute=False,
            required_inputs=required_inputs,
            missing_inputs=missing_inputs,
            blocked_reasons=blocked_reasons,
        )

    if imaging_format == "dicom":
        missing_inputs.append("resolved_primary_series")
        blocked_reasons.append("DICOM/PACS inputs still need primary series resolution before MRI analysis can run.")
        return WorkflowCapability(
            workflow_id="neuro_report",
            workflow_family="neuro",
            allowed_tracks=["review"],
            blocked_tracks=["structural", "response"],
            dashboard_profiles=["report_review"],
            allowed_modes=["intake_only"],
            blocked_modes=["vanilla", "seg_overlay", "tool_output", "full_agent"],
            viewer_type=viewer_type,
            can_execute=False,
            required_inputs=required_inputs + ["resolved_primary_series"],
            missing_inputs=missing_inputs,
            blocked_reasons=blocked_reasons,
        )

    allowed_modes.append("vanilla")
    if has_segmentation:
        allowed_modes.append("seg_overlay")
    else:
        missing_inputs.append("segmentation")
        blocked_reasons.append("Segmentation is missing, so overlay-aware and quantitative modes are unavailable.")
    if has_segmentation and has_demographics:
        allowed_modes.extend(["tool_output", "full_agent"])
    elif has_segmentation:
        missing_inputs.append("age_and_sex")
        blocked_reasons.append("Age and sex are missing, so normative volumetric interpretation must stay disabled.")

    known_modes = ["vanilla", "seg_overlay", "tool_output", "full_agent", "intake_only"]
    blocked_modes = [mode for mode in known_modes if mode not in allowed_modes]
    allowed_tracks = ["structural", "review"]
    dashboard_profiles = ["volumetry", "report_review"]
    blocked_tracks = ["response"]
    if lesion_context or has_longitudinal_priors:
        allowed_tracks.append("response")
        dashboard_profiles.append("longitudinal_response")
        blocked_tracks = []
    return WorkflowCapability(
        workflow_id="neuro_report",
        workflow_family="neuro",
        allowed_tracks=allowed_tracks,
        blocked_tracks=blocked_tracks,
        dashboard_profiles=dashboard_profiles,
        allowed_modes=allowed_modes,
        blocked_modes=blocked_modes,
        viewer_type=viewer_type,
        can_execute=True,
        required_inputs=required_inputs,
        missing_inputs=missing_inputs,
        blocked_reasons=blocked_reasons,
    )


def evaluate_report_quality_workflow_capability(
    *,
    has_report_text: bool,
    has_template_context: bool,
) -> WorkflowCapability:
    missing_inputs: list[str] = []
    blocked_reasons: list[str] = []
    if not has_report_text:
        missing_inputs.append("report_text")
        blocked_reasons.append("No report text or selected report-quality case is available yet.")
    if not has_template_context:
        missing_inputs.append("template_context")
        blocked_reasons.append("Template or compliance profile metadata is missing.")

    can_execute = has_report_text and has_template_context
    return WorkflowCapability(
        workflow_id="report_quality_review",
        workflow_family="review",
        allowed_tracks=["review"],
        blocked_tracks=[],
        dashboard_profiles=["report_review"],
        allowed_modes=["policy_check"] if can_execute else [],
        blocked_modes=[] if can_execute else ["policy_check"],
        viewer_type="workspace",
        can_execute=can_execute,
        required_inputs=["report_text", "template_context"],
        missing_inputs=missing_inputs,
        blocked_reasons=blocked_reasons,
    )


def evaluate_radonc_workflow_capability(
    *,
    has_rt_plan: bool,
    has_rt_structures: bool,
    has_dose_or_dvh: bool,
    has_protocol: bool,
    connector_writable: bool,
) -> WorkflowCapability:
    missing_inputs: list[str] = []
    blocked_reasons: list[str] = []

    if not has_rt_plan:
        missing_inputs.append("rt_plan")
        blocked_reasons.append("RT plan metadata is missing.")
    if not has_rt_structures:
        missing_inputs.append("rt_structures")
        blocked_reasons.append("Structure context is missing.")
    if not has_dose_or_dvh:
        missing_inputs.append("dvh_metrics")
        blocked_reasons.append("Dose or DVH context is missing.")
    if not has_protocol:
        missing_inputs.append("protocol_template")
        blocked_reasons.append("Protocol goals are missing.")

    base_allowed_modes = ["manual_review"]
    if has_rt_plan and has_rt_structures and has_dose_or_dvh and has_protocol:
        base_allowed_modes.append("supervised")
        if connector_writable:
            base_allowed_modes.append("auto_loop")
        else:
            blocked_reasons.append("Write-back connector is unavailable, so auto optimization must stay disabled.")

    return WorkflowCapability(
        workflow_id="radonc_plan_optimization",
        workflow_family="radonc",
        allowed_tracks=["optimization", "review"] if not missing_inputs else ["review"],
        blocked_tracks=[] if not missing_inputs else ["optimization"],
        dashboard_profiles=["plan_optimization", "plan_review"] if not missing_inputs else ["plan_review"],
        allowed_modes=base_allowed_modes if not missing_inputs else [],
        blocked_modes=["auto_loop", "supervised"] if missing_inputs else ([] if connector_writable else ["auto_loop"]),
        viewer_type="workspace",
        can_execute=has_rt_plan and has_rt_structures and has_dose_or_dvh and has_protocol,
        required_inputs=["rt_plan", "rt_structures", "dvh_metrics", "protocol_template"],
        missing_inputs=missing_inputs,
        blocked_reasons=blocked_reasons,
    )


WORKFLOW_CAPABILITY_REGISTRY: dict[str, str] = {
    "neuro_report": "evaluate_neuro_workflow_capability",
    "report_quality_review": "evaluate_report_quality_workflow_capability",
    "radonc_plan_optimization": "evaluate_radonc_workflow_capability",
}
