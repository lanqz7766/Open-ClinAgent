"""Assemble a normalized longitudinal workspace contract from profiled local data.
Input: a DataProfile plus workflow selection and optional patient selection.
Output: a WorkspaceContract with ordered timepoints, report text, and real imaging references.
"""

from __future__ import annotations

import csv
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from clinagent.platform.data_profiler import DataProfile, PatientInfo, profile_data_source
from clinagent.platform.workspace_models.workspace import TimepointData, WorkspaceContract


def _find_manifest(source_root: Path) -> Path | None:
    for candidate in sorted(source_root.rglob("*manifest*.csv")):
        return candidate
    return None


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items() if key} for row in csv.DictReader(handle)]


def _select_patient(profile: DataProfile, patient_uid: str | None) -> PatientInfo:
    if not profile.patients:
        raise ValueError("No patients were found in the profiled data source.")
    if patient_uid:
        for patient in profile.patients:
            if patient.patient_uid == patient_uid:
                return patient
        raise KeyError(f"Unknown patient_uid: {patient_uid}")
    return max(profile.patients, key=lambda item: item.timepoints)


def _timepoint_label(index: int) -> str:
    return "baseline" if index == 0 else f"followup_{index}"


def _zip_member_uri(archive_path: Path, member: str) -> str:
    return f"zip://{archive_path.resolve()}!/{member}"


def _metadata_by_study(metadata_path: Path, cache: dict[Path, dict[str, list[dict[str, str]]]]) -> dict[str, list[dict[str, str]]]:
    if metadata_path in cache:
        return cache[metadata_path]
    rows = _read_csv_rows(metadata_path)
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row.get("study_uid", ""), []).append(row)
    cache[metadata_path] = grouped
    return grouped


def _reports_by_study(report_path: Path, cache: dict[Path, dict[str, dict[str, str]]]) -> dict[str, dict[str, str]]:
    if report_path in cache:
        return cache[report_path]
    rows = _read_csv_rows(report_path)
    grouped = {row.get("study_uid", ""): row for row in rows if row.get("study_uid")}
    cache[report_path] = grouped
    return grouped


def _inspect_archive_members(archive_path: Path) -> tuple[list[str], str | None]:
    imaging_members: list[str] = []
    segmentation_member: str | None = None
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.namelist():
            lowered = member.lower()
            if "/img/" in lowered and lowered.endswith((".nii.gz", ".nii")):
                imaging_members.append(member)
            if "/seg/" in lowered and lowered.endswith((".nii.gz", ".nii")):
                if segmentation_member is None or ("brain-mask" in lowered and "defacing" not in lowered):
                    segmentation_member = member
    return sorted(imaging_members), segmentation_member


def _report_text(report_row: dict[str, str] | None) -> str | None:
    if not report_row:
        return None
    if report_row.get("report"):
        return report_row["report"]
    sections = [report_row.get("clinical_information", ""), report_row.get("findings", ""), report_row.get("impression", "")]
    text = "\n\n".join(part for part in sections if part)
    return text or None


def assemble_workspace(
    profile: DataProfile,
    selected_workflow: str,
    patient_uid: str | None = None,
) -> WorkspaceContract:
    source_root = Path(profile.source_path)
    manifest_path = _find_manifest(source_root)
    if manifest_path is None:
        raise FileNotFoundError(f"Could not find a manifest under {source_root}")

    patient = _select_patient(profile, patient_uid)
    manifest_rows = _read_csv_rows(manifest_path)
    patient_rows = [row for row in manifest_rows if row.get("patient_uid", "").strip() == patient.patient_uid]
    patient_rows.sort(key=lambda row: row.get("anon_study_date", ""))
    if not patient_rows:
        raise ValueError(f"No manifest rows found for patient {patient.patient_uid}")

    metadata_cache: dict[Path, dict[str, list[dict[str, str]]]] = {}
    report_cache: dict[Path, dict[str, dict[str, str]]] = {}
    timepoints: list[TimepointData] = []
    study_uids: list[str] = []

    for index, row in enumerate(patient_rows):
        study_uid = row.get("study_uid", "")
        study_date = row.get("anon_study_date", "")
        archive_path = (source_root / row.get("mri_relpath", "")).resolve()
        report_path = (source_root / row.get("report_relpath", "")).resolve() if row.get("report_relpath") else None
        metadata_path = (source_root / row.get("metadata_relpath", "")).resolve() if row.get("metadata_relpath") else None

        imaging_members, segmentation_member = _inspect_archive_members(archive_path)
        imaging_paths = [_zip_member_uri(archive_path, member) for member in imaging_members]
        segmentation_path = _zip_member_uri(archive_path, segmentation_member) if segmentation_member else None

        report_row = None
        if report_path and report_path.exists():
            report_row = _reports_by_study(report_path, report_cache).get(study_uid)

        metadata_rows = []
        if metadata_path and metadata_path.exists():
            metadata_rows = _metadata_by_study(metadata_path, metadata_cache).get(study_uid, [])

        modalities = sorted({row_.get("classified_modality", "") for row_ in metadata_rows if row_.get("classified_modality")})
        timepoints.append(
            TimepointData(
                date=study_date,
                label=_timepoint_label(index),
                imaging_paths=imaging_paths,
                report_text=_report_text(report_row),
                segmentation_path=segmentation_path,
                extracted_metrics={
                    "study_uid": study_uid,
                    "archive_path": str(archive_path),
                    "image_count": len(imaging_paths),
                    "segmentation_available": segmentation_path is not None,
                    "series_count": len(metadata_rows),
                    "modalities": modalities,
                },
            )
        )
        study_uids.append(study_uid)

    return WorkspaceContract(
        workspace_id=f"{selected_workflow}-{patient.patient_uid.lower()}",
        workflow_type=selected_workflow,
        patient_id=patient.patient_uid,
        timepoints=timepoints,
        metadata={
            "source_path": profile.source_path,
            "detected_type": profile.detected_type,
            "study_uids": study_uids,
            "timepoint_count": len(timepoints),
            "suggested_workflows": list(profile.suggested_workflows),
        },
        created_at=patient_rows[-1].get("anon_study_date", ""),
    )


def assemble_workspace_from_path(
    source_path: str | Path,
    selected_workflow: str,
    patient_uid: str | None = None,
) -> WorkspaceContract:
    return assemble_workspace(
        profile=profile_data_source(source_path),
        selected_workflow=selected_workflow,
        patient_uid=patient_uid,
    )


def workspace_to_dict(workspace: WorkspaceContract) -> dict[str, Any]:
    return asdict(workspace)
