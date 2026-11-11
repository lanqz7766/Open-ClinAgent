from clinagent.families.neuro.intake import (
    build_analysis_plan,
    build_capability_profile,
    build_planning_result,
    intake_plan_from_message,
    normalize_case_intake,
    summarize_analysis_plan,
)


def test_capability_profile_allows_full_agent_when_segmentation_and_demographics_exist():
    context = normalize_case_intake(
        source_kind="nifti",
        nifti_path="/tmp/example_t1w.nii.gz",
        seg_path="/tmp/example_seg.nii.gz",
        age=72,
        sex="F",
        indication="Memory decline",
        has_prior_study=True,
        has_prior_report=True,
    )

    profile = build_capability_profile(context)
    plan = build_analysis_plan(context, profile)

    assert profile.has_demographics is True
    assert profile.has_segmentation is True
    assert profile.workflow_family == "neuro"
    assert plan.can_execute is True
    assert plan.workflow_family == "neuro"
    assert plan.analysis_track == "structural"
    assert plan.dashboard_profile == "volumetry"
    assert plan.recommended_mode == "full_agent"
    assert "normative_volumetric_analysis" in plan.allowed_analyses


def test_capability_profile_falls_back_when_segmentation_lacks_demographics():
    context = normalize_case_intake(
        source_kind="upload",
        nifti_path="/tmp/example_t1w.nii.gz",
        seg_path="/tmp/example_seg.nii.gz",
        age=None,
        sex=None,
        indication="Brain MRI review",
    )

    profile = build_capability_profile(context)
    plan = build_analysis_plan(context, profile)

    assert profile.has_segmentation is True
    assert profile.has_demographics is False
    assert "age_and_sex" in profile.missing_inputs
    assert plan.recommended_mode == "seg_overlay"
    assert "normative_volumetric_analysis" in plan.blocked_analyses


def test_intake_plan_from_message_keeps_dicom_requests_in_safe_pre_execution_mode():
    _, profile, plan = intake_plan_from_message("Review this brain MRI from PACS DICOM only and tell me what to do next.")

    assert profile.imaging_format == "dicom"
    assert plan.can_execute is False
    assert plan.analysis_track in {"structural", "review"}
    assert plan.dashboard_profile in {"volumetry", "report_review"}
    assert plan.recommended_mode is None
    assert "series resolution" in plan.handoff_summary.lower()


def test_tumor_followup_request_routes_to_response_track():
    context, profile, plan = intake_plan_from_message(
        "Review this tumor follow-up brain MRI and estimate longitudinal response burden."
    )

    assert context.workflow_family == "neuro"
    assert profile.workflow_family == "neuro"
    assert plan.analysis_track == "response"
    assert plan.dashboard_profile == "longitudinal_response"
    assert "longitudinal response" in plan.recommended_goal.lower()


def test_planning_result_exposes_next_action_and_viewer_contract():
    context = normalize_case_intake(
        source_kind="curated_case",
        patient_id="1278",
        study_id="EXAMPLE",
        case_id="1278:EXAMPLE",
        nifti_path="/tmp/example_t1w.nii.gz",
        seg_path="/tmp/example_seg.nii.gz",
        age=71,
        sex="F",
        indication="Memory decline",
        has_prior_study=True,
        has_prior_report=True,
    )
    profile = build_capability_profile(context)
    plan = build_analysis_plan(context, profile)
    summary = summarize_analysis_plan(plan, profile, requested_mode="full_agent", executed_mode="full_agent", viewer_type="nifti")
    planning_result = build_planning_result(
        context,
        profile,
        plan,
        requested_mode="full_agent",
        executed_mode="full_agent",
        viewer_type="nifti",
    )

    assert summary.viewer_type == "nifti"
    assert summary.family == "neuro"
    assert summary.track == "structural"
    assert summary.dashboard_profile == "volumetry"
    assert planning_result.can_execute is True
    assert planning_result.autorun is True
    assert planning_result.workflow_family == "neuro"
    assert planning_result.workflow_id == "neuro.structural_report"
    assert planning_result.family == "neuro"
    assert planning_result.track == "structural"
    assert planning_result.dashboard_profile == "volumetry"
    assert planning_result.recommended_workflow == "neuro_report"
    assert "start the recommended analysis automatically" in planning_result.recommended_next_action.lower()
