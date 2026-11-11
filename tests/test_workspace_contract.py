from __future__ import annotations

from dataclasses import asdict

from clinagent.platform.workspace_models.workspace import TimepointData, WorkspaceContract


def test_timepoint_data_serializes_cleanly() -> None:
    timepoint = TimepointData(
        date="2024-01-02",
        label="baseline",
        imaging_paths=["/tmp/a.nii.gz", "/tmp/b.nii.gz"],
        report_text="Stable treated lesion.",
        segmentation_path="/tmp/mask.nii.gz",
        extracted_metrics={"lesion_count": 2, "total_volume_ml": 12.3},
    )

    assert asdict(timepoint) == {
        "date": "2024-01-02",
        "label": "baseline",
        "imaging_paths": ["/tmp/a.nii.gz", "/tmp/b.nii.gz"],
        "report_text": "Stable treated lesion.",
        "segmentation_path": "/tmp/mask.nii.gz",
        "extracted_metrics": {"lesion_count": 2, "total_volume_ml": 12.3},
    }


def test_workspace_contract_minimal_instance() -> None:
    contract = WorkspaceContract(
        workspace_id="workspace-123",
        workflow_type="longitudinal_neuro_review",
        patient_id="806",
        created_at="2026-03-29T00:00:00Z",
    )

    payload = asdict(contract)
    assert payload["workspace_id"] == "workspace-123"
    assert payload["workflow_type"] == "longitudinal_neuro_review"
    assert payload["patient_id"] == "806"
    assert payload["timepoints"] == []
    assert payload["metadata"] == {}
    assert payload["created_at"] == "2026-03-29T00:00:00Z"


def test_workspace_contract_stays_normalized() -> None:
    contract = WorkspaceContract(
        workspace_id="workspace-abc",
        workflow_type="longitudinal_neuro_review",
        patient_id="1278",
        timepoints=[TimepointData(date="2023-01-21", label="followup_1")],
        metadata={"source_path": "/tmp/input"},
        created_at="2026-03-29T12:00:00Z",
    )

    payload = asdict(contract)
    assert sorted(payload.keys()) == ["created_at", "metadata", "patient_id", "timepoints", "workflow_type", "workspace_id"]
    assert "analysis" not in payload
    assert "visualizations" not in payload
    assert "viewer" not in payload
