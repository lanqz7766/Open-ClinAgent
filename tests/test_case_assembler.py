from __future__ import annotations

import os

import pytest

from clinagent.platform.case_assembler import assemble_workspace_from_path


REAL_DATA_ROOT = os.getenv("CLINAGENT_TEST_LONGITUDINAL_DATA_ROOT", "")
requires_real_data = pytest.mark.skipif(
    not REAL_DATA_ROOT,
    reason="Set CLINAGENT_TEST_LONGITUDINAL_DATA_ROOT to run real longitudinal assembler tests.",
)


@requires_real_data
def test_assembles_real_longitudinal_workspace_for_patient_806() -> None:
    workspace = assemble_workspace_from_path(
        source_path=REAL_DATA_ROOT,
        selected_workflow="longitudinal_neuro_review",
        patient_uid="806",
    )

    assert workspace.workflow_type == "longitudinal_neuro_review"
    assert workspace.patient_id == "806"
    assert workspace.workspace_id == "longitudinal_neuro_review-806"
    assert len(workspace.timepoints) == 28

    first = workspace.timepoints[0]
    second = workspace.timepoints[1]
    last = workspace.timepoints[-1]

    assert first.label == "baseline"
    assert second.label == "followup_1"
    assert last.label == "followup_27"
    assert first.date == "2020-10-20"
    assert last.date == "2025-05-16"
    assert first.imaging_paths
    assert first.imaging_paths[0].startswith("zip:///")
    assert first.report_text is not None
    assert "Findings" in first.report_text or "Clinical information" in first.report_text
    assert first.segmentation_path is not None
    assert first.extracted_metrics["study_uid"] == "PIMJJU2LNM"
    assert "modalities" in first.extracted_metrics


@requires_real_data
def test_assembles_real_longitudinal_workspace_for_patient_1278() -> None:
    workspace = assemble_workspace_from_path(
        source_path=REAL_DATA_ROOT,
        selected_workflow="longitudinal_neuro_review",
        patient_uid="1278",
    )

    assert workspace.patient_id == "1278"
    assert len(workspace.timepoints) == 16
    assert workspace.timepoints[0].label == "baseline"
    assert workspace.timepoints[-1].label == "followup_15"
    assert workspace.metadata["timepoint_count"] == 16
    assert workspace.metadata["detected_type"] == "longitudinal"
