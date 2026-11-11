from __future__ import annotations

from pathlib import Path

from clinagent.families.neuro.report_demo import NeuroReportDemoStore, StudyRecord


def _make_record(patient_id: str, study_id: str, study_date: str) -> StudyRecord:
    base = Path("/tmp")
    return StudyRecord(
        patient_id=patient_id,
        study_id=study_id,
        study_date=study_date,
        batch="batch-1",
        age=67,
        sex="F",
        image_dir=base,
        seg_dir=base,
        report_path=base / "report.txt",
        metadata_path=base / "metadata.json",
        report_full_text="Report text",
        report_sections={
            "clinical_information": "Clinical information",
            "technique": "Technique",
            "findings": "Findings",
            "impression": "Impression",
        },
        indication="Memory change",
        diagnosis="Neuro follow-up",
        analysis_image_path=base / "image.nii.gz",
        seg_path=base / "seg.nii.gz",
    )


def _make_store() -> NeuroReportDemoStore:
    store = object.__new__(NeuroReportDemoStore)
    store._records_by_patient = {
        "P1": [
            _make_record("P1", "study-001", "2019-05-22"),
            _make_record("P1", "study-002", "2021-09-03"),
            _make_record("P1", "study-003", "2022-02-17"),
        ]
    }
    store._patient_names = {"P1": "Patient P1"}
    store._response_cases = {
        "proteas-1": {
            "patient": {
                "id": "R1",
                "display_name": "Response Patient R1",
                "age": 54,
                "sex": "F",
                "diagnosis": "Brain metastasis follow-up",
            },
            "timeline": [
                {"study_id": "resp-001", "study_date": "2023-01-04"},
                {"study_id": "resp-002", "study_date": "2023-06-18"},
            ],
        }
    }
    store._build_thumbnail = lambda _record: "thumb"
    store._response_thumbnail = lambda _case, _study_id: "thumb"
    store._response_case = lambda patient_id=None: (
        store._response_cases["proteas-1"] if patient_id == "R1" else None
    )
    store.get_longitudinal_volumetrics = lambda _patient_id: {"highlights": []}
    return store


def test_structural_patient_payload_defaults_to_latest_study() -> None:
    store = _make_store()

    patients = store.get_patients()
    patient_entry = next(item for item in patients["patients"] if item["id"] == "P1")
    patient_data = store.get_patient_data("P1")
    snapshot = store.snapshot()

    assert patient_entry["default_study_id"] == "study-003"
    assert patient_data["default_study_id"] == "study-003"
    assert snapshot["default_case_id"] == "P1:study-003"


def test_response_patient_payload_still_defaults_to_latest_study() -> None:
    store = _make_store()

    patients = store.get_patients()
    patient_entry = next(item for item in patients["patients"] if item["id"] == "R1")
    patient_data = store.get_patient_data("R1")

    assert patient_entry["default_study_id"] == "resp-002"
    assert patient_data["default_study_id"] == "resp-002"
