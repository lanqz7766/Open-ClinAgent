from __future__ import annotations

import os
from pathlib import Path

import pytest

from clinagent.platform.data_profiler import profile_data_source


REAL_DATA_ROOT = os.getenv("CLINAGENT_TEST_LONGITUDINAL_DATA_ROOT", "")
requires_real_data = pytest.mark.skipif(
    not REAL_DATA_ROOT or not Path(REAL_DATA_ROOT).exists(),
    reason="Set CLINAGENT_TEST_LONGITUDINAL_DATA_ROOT to run real longitudinal dataset tests.",
)


@requires_real_data
def test_profiles_real_longitudinal_dataset() -> None:
    profile = profile_data_source(Path(REAL_DATA_ROOT))

    assert profile.detected_type == "longitudinal"
    assert profile.missing_fields == []
    assert "longitudinal_neuro_review" in profile.suggested_workflows
    assert [patient.patient_uid for patient in profile.patients] == ["1278", "806"]

    patient_1278 = profile.patients[0]
    assert patient_1278.timepoints == 16
    assert patient_1278.has_imaging is True
    assert patient_1278.has_reports is True
    assert patient_1278.has_segmentation is True
    assert "2022-10-29" in patient_1278.file_paths

    patient_806 = profile.patients[1]
    assert patient_806.timepoints == 28
    assert patient_806.has_imaging is True
    assert patient_806.has_reports is True
    assert patient_806.has_segmentation is True
    assert "2025-05-16" in patient_806.file_paths


def test_profiles_tabular_dataset_without_patients(tmp_path: Path) -> None:
    (tmp_path / "cohort.csv").write_text("col_a,col_b\n1,2\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("summary\n", encoding="utf-8")

    profile = profile_data_source(tmp_path)

    assert profile.detected_type == "cohort_tabular"
    assert profile.patients == []
    assert profile.suggested_workflows == ["cohort_tabular_exploration"]
    assert profile.raw_inventory["csv"] == 1
    assert profile.raw_inventory["txt"] == 1


def test_unknown_layout_reports_missing_fields(tmp_path: Path) -> None:
    study_dir = tmp_path / "uploads"
    study_dir.mkdir()
    (study_dir / "scan_a.zip").write_text("not-a-real-zip", encoding="utf-8")

    profile = profile_data_source(tmp_path)

    assert profile.detected_type == "unknown"
    assert "patient identifier" in profile.missing_fields
    assert "study date" in profile.missing_fields
