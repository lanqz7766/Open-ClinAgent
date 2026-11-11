from clinagent.platform.capabilities import (
    evaluate_neuro_workflow_capability,
    evaluate_radonc_workflow_capability,
    evaluate_report_quality_workflow_capability,
    get_model_capability,
)


def test_get_model_capability_marks_gpt5_as_responses_api():
    capability = get_model_capability("gpt-5-mini")

    assert capability.api_architecture == "responses_api"
    assert capability.supports_reasoning_effort is True
    assert capability.supports_strict_tool_schema is True


def test_evaluate_neuro_workflow_capability_requires_series_resolution_for_dicom():
    capability = evaluate_neuro_workflow_capability(
        has_single_study_mri=True,
        imaging_format="dicom",
        has_segmentation=False,
        has_demographics=False,
    )

    assert capability.can_execute is False
    assert capability.workflow_family == "neuro"
    assert capability.viewer_type == "dicomweb"
    assert capability.allowed_tracks == ["review"]
    assert capability.dashboard_profiles == ["report_review"]
    assert capability.allowed_modes == ["intake_only"]
    assert "resolved_primary_series" in capability.missing_inputs


def test_evaluate_neuro_workflow_capability_allows_full_agent_for_complete_nifti_case():
    capability = evaluate_neuro_workflow_capability(
        has_single_study_mri=True,
        imaging_format="nifti",
        has_segmentation=True,
        has_demographics=True,
    )

    assert capability.can_execute is True
    assert capability.workflow_family == "neuro"
    assert capability.viewer_type == "nifti"
    assert "structural" in capability.allowed_tracks
    assert "review" in capability.allowed_tracks
    assert "volumetry" in capability.dashboard_profiles
    assert "full_agent" in capability.allowed_modes
    assert "tool_output" in capability.allowed_modes


def test_evaluate_neuro_workflow_capability_enables_response_track_for_lesion_context():
    capability = evaluate_neuro_workflow_capability(
        has_single_study_mri=True,
        imaging_format="nifti",
        has_segmentation=True,
        has_demographics=False,
        has_longitudinal_priors=True,
        lesion_context=True,
    )

    assert capability.can_execute is True
    assert "response" in capability.allowed_tracks
    assert "longitudinal_response" in capability.dashboard_profiles


def test_evaluate_report_quality_workflow_capability_requires_report_text_and_template():
    capability = evaluate_report_quality_workflow_capability(
        has_report_text=False,
        has_template_context=True,
    )

    assert capability.workflow_id == "report_quality_review"
    assert capability.workflow_family == "review"
    assert capability.can_execute is False
    assert "report_text" in capability.missing_inputs


def test_evaluate_report_quality_workflow_capability_allows_policy_check_for_complete_case():
    capability = evaluate_report_quality_workflow_capability(
        has_report_text=True,
        has_template_context=True,
    )

    assert capability.can_execute is True
    assert capability.workflow_family == "review"
    assert capability.viewer_type == "workspace"
    assert capability.allowed_tracks == ["review"]
    assert capability.dashboard_profiles == ["report_review"]
    assert capability.allowed_modes == ["policy_check"]


def test_evaluate_radonc_workflow_capability_requires_complete_planning_context():
    capability = evaluate_radonc_workflow_capability(
        has_rt_plan=True,
        has_rt_structures=False,
        has_dose_or_dvh=True,
        has_protocol=False,
        connector_writable=False,
    )

    assert capability.workflow_id == "radonc_plan_optimization"
    assert capability.workflow_family == "radonc"
    assert capability.can_execute is False
    assert capability.viewer_type == "workspace"
    assert "rt_structures" in capability.missing_inputs
    assert "protocol_template" in capability.missing_inputs


def test_evaluate_radonc_workflow_capability_allows_auto_loop_when_connector_is_writable():
    capability = evaluate_radonc_workflow_capability(
        has_rt_plan=True,
        has_rt_structures=True,
        has_dose_or_dvh=True,
        has_protocol=True,
        connector_writable=True,
    )

    assert capability.can_execute is True
    assert capability.allowed_tracks == ["optimization", "review"]
    assert "plan_optimization" in capability.dashboard_profiles
    assert "auto_loop" in capability.allowed_modes
