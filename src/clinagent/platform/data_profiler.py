"""Build a structured profile for an arbitrary local data source.
Input: a file or directory path containing imaging, reports, manifests, or tabular data.
Output: a DataProfile dataclass plus CLI JSON for downstream workflow recommendation.
"""

from __future__ import annotations

import csv
import json
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


MANIFEST_PATTERNS = ("manifest.csv",)
PATIENT_FIELD_CANDIDATES = ("patient_uid", "patient_id", "patient", "subject_id", "patient")
DATE_FIELD_CANDIDATES = ("anon_study_date", "study_date", "date", "studyDate")
IMAGING_FIELD_CANDIDATES = ("mri_relpath", "image_path", "imaging_path", "scan_path")
REPORT_FIELD_CANDIDATES = ("report_relpath", "report_path", "report")
SEGMENTATION_FIELD_CANDIDATES = ("segmentation_path", "mask_path", "seg_path")
TEXT_EXTENSIONS = {".csv", ".xlsx", ".xls", ".tsv", ".txt", ".json"}
ZIP_UID_RE = re.compile(r"\b([A-Z0-9]{8,})\b")
DATE_RE = re.compile(r"(20\d{2}[-_]\d{2}[-_]\d{2})")


@dataclass
class PatientInfo:
    patient_uid: str
    study_dates: list[str]
    timepoints: int
    has_imaging: bool
    has_reports: bool
    has_segmentation: bool
    file_paths: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class DataProfile:
    source_path: str
    detected_type: str
    patients: list[PatientInfo]
    missing_fields: list[str]
    suggested_workflows: list[str]
    raw_inventory: dict[str, int]


def _normalize_key(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def _extension_key(path: Path) -> str:
    lower_name = path.name.lower()
    if lower_name.endswith(".nii.gz"):
        return "nii.gz"
    if path.suffix:
        return path.suffix.lower().lstrip(".")
    return "<no_ext>"


def _find_manifest(paths: list[Path]) -> Path | None:
    for path in paths:
        lower_name = path.name.lower()
        if lower_name in MANIFEST_PATTERNS or "manifest" in lower_name:
            return path
    return None


def _choose_field(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    normalized = {_normalize_key(name): name for name in fieldnames}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    return None


def _safe_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _read_manifest_rows(manifest_path: Path) -> list[dict[str, str]]:
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, str]] = []
        for raw in reader:
            rows.append({key: _safe_str(value) for key, value in raw.items() if key})
    return rows


def _inspect_archive(archive_path: Path, cache: dict[Path, dict[str, bool]]) -> dict[str, bool]:
    if archive_path in cache:
        return cache[archive_path]
    result = {"has_imaging": False, "has_segmentation": False}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.namelist():
                lowered = member.lower()
                if lowered.endswith((".nii.gz", ".nii", ".dcm")) or "/img/" in lowered or "/dicom/" in lowered:
                    result["has_imaging"] = True
                if "/seg/" in lowered or "segmentation" in lowered or "mask" in lowered:
                    result["has_segmentation"] = True
                if result["has_imaging"] and result["has_segmentation"]:
                    break
    except zipfile.BadZipFile:
        pass
    cache[archive_path] = result
    return result


def _profile_from_manifest(source_path: Path, manifest_path: Path, all_files: list[Path]) -> tuple[list[PatientInfo], list[str]]:
    rows = _read_manifest_rows(manifest_path)
    if not rows:
        return [], ["manifest rows"]

    fieldnames = list(rows[0].keys())
    patient_field = _choose_field(fieldnames, PATIENT_FIELD_CANDIDATES)
    date_field = _choose_field(fieldnames, DATE_FIELD_CANDIDATES)
    imaging_field = _choose_field(fieldnames, IMAGING_FIELD_CANDIDATES)
    report_field = _choose_field(fieldnames, REPORT_FIELD_CANDIDATES)
    segmentation_field = _choose_field(fieldnames, SEGMENTATION_FIELD_CANDIDATES)

    missing: list[str] = []
    if patient_field is None:
        missing.append("patient_uid")
    if date_field is None:
        missing.append("study_date")

    if patient_field is None or date_field is None:
        return [], missing

    archive_cache: dict[Path, dict[str, bool]] = {}
    patient_dates: dict[str, set[str]] = defaultdict(set)
    patient_paths: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    imaging_flags: dict[str, bool] = defaultdict(bool)
    report_flags: dict[str, bool] = defaultdict(bool)
    segmentation_flags: dict[str, bool] = defaultdict(bool)

    for row in rows:
        patient_uid = row.get(patient_field, "")
        study_date = row.get(date_field, "")
        if not patient_uid:
            continue
        if study_date:
            patient_dates[patient_uid].add(study_date)

        relpaths = [row.get(imaging_field, "") if imaging_field else ""]
        if report_field:
            relpaths.append(row.get(report_field, ""))
        if segmentation_field:
            relpaths.append(row.get(segmentation_field, ""))

        for relpath in filter(None, relpaths):
            absolute = (source_path / relpath).resolve()
            patient_paths[patient_uid][study_date or "unknown"].append(str(absolute))
            if absolute.suffix.lower() == ".zip":
                archive_features = _inspect_archive(absolute, archive_cache)
                imaging_flags[patient_uid] = imaging_flags[patient_uid] or archive_features["has_imaging"]
                segmentation_flags[patient_uid] = segmentation_flags[patient_uid] or archive_features["has_segmentation"]
            if absolute.exists() and (
                absolute.name.lower().endswith(".nii.gz") or absolute.suffix.lower() in {".nii", ".dcm", ".zip"}
            ):
                imaging_flags[patient_uid] = True
            if "report" in absolute.name.lower() or absolute.suffix.lower() in {".txt", ".csv"}:
                report_flags[patient_uid] = True

        if report_field and row.get(report_field):
            report_flags[patient_uid] = True

    patients = [
        PatientInfo(
            patient_uid=patient_uid,
            study_dates=sorted(study_dates),
            timepoints=len(study_dates) if study_dates else len(patient_paths[patient_uid]),
            has_imaging=imaging_flags[patient_uid],
            has_reports=report_flags[patient_uid],
            has_segmentation=segmentation_flags[patient_uid],
            file_paths={key: value for key, value in sorted(patient_paths[patient_uid].items())},
        )
        for patient_uid, study_dates in sorted(patient_dates.items())
    ]

    if not patients and all_files:
        return [], missing + ["patient rows"]
    return patients, missing


def _infer_from_filenames(source_path: Path, all_files: list[Path]) -> tuple[list[PatientInfo], list[str]]:
    grouped_dates: dict[str, set[str]] = defaultdict(set)
    grouped_paths: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    imaging_flags: dict[str, bool] = defaultdict(bool)
    report_flags: dict[str, bool] = defaultdict(bool)
    segmentation_flags: dict[str, bool] = defaultdict(bool)

    for path in all_files:
        relative = path.relative_to(source_path) if source_path.is_dir() else path.name
        candidate = str(relative)
        patient_match = ZIP_UID_RE.search(path.stem.upper()) or ZIP_UID_RE.search(candidate.upper())
        date_match = DATE_RE.search(candidate)
        patient_uid = patient_match.group(1) if patient_match else "unknown"
        study_date = date_match.group(1).replace("_", "-") if date_match else "unknown"

        grouped_dates[patient_uid].add(study_date)
        grouped_paths[patient_uid][study_date].append(str(path.resolve()))
        ext_key = _extension_key(path)
        if ext_key in {"nii.gz", "nii", "dcm", "zip"}:
            imaging_flags[patient_uid] = True
        if "report" in path.name.lower() or path.suffix.lower() in {".txt", ".csv"}:
            report_flags[patient_uid] = True
        if "seg" in path.name.lower() or "mask" in path.name.lower():
            segmentation_flags[patient_uid] = True

    missing = []
    if "unknown" in grouped_dates:
        missing.append("patient identifier")
    if any("unknown" in dates for dates in grouped_dates.values()):
        missing.append("study date")

    patients = [
        PatientInfo(
            patient_uid=patient_uid,
            study_dates=sorted(date for date in study_dates if date != "unknown"),
            timepoints=len(study_dates),
            has_imaging=imaging_flags[patient_uid],
            has_reports=report_flags[patient_uid],
            has_segmentation=segmentation_flags[patient_uid],
            file_paths={key: value for key, value in sorted(grouped_paths[patient_uid].items())},
        )
        for patient_uid, study_dates in sorted(grouped_dates.items())
    ]
    return patients, missing


def _detected_type_from_profile(patients: list[PatientInfo], raw_inventory: dict[str, int], missing_fields: list[str]) -> str:
    if not patients and set(raw_inventory).issubset({"csv", "xlsx", "xls", "tsv", "txt", "json"}):
        return "cohort_tabular"
    if missing_fields:
        return "unknown"
    if patients and any(patient.has_imaging for patient in patients) and any(patient.timepoints > 1 for patient in patients):
        return "longitudinal"
    if len(patients) == 1 and patients[0].has_imaging and patients[0].timepoints <= 1:
        return "single_study"
    if patients and any(patient.has_imaging for patient in patients) and any(patient.has_reports for patient in patients):
        return "imaging_with_reports"
    return "unknown"


def _suggested_workflows(detected_type: str, patients: list[PatientInfo]) -> list[str]:
    if detected_type == "longitudinal":
        suggestions = ["longitudinal_neuro_review", "longitudinal_report_summarization"]
        if any(patient.has_reports for patient in patients):
            suggestions.append("report_aware_longitudinal_review")
        return suggestions
    if detected_type == "single_study":
        return ["single_study_neuro_review"]
    if detected_type == "imaging_with_reports":
        return ["imaging_report_reconciliation", "report_quality_review"]
    if detected_type == "cohort_tabular":
        return ["cohort_tabular_exploration"]
    return []


def profile_data_source(source_path: str | Path) -> DataProfile:
    root = Path(source_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Data source does not exist: {root}")

    all_files = sorted(path for path in root.rglob("*") if path.is_file()) if root.is_dir() else [root]
    raw_inventory = dict(sorted(Counter(_extension_key(path) for path in all_files).items()))

    manifest_path = _find_manifest(all_files)
    if manifest_path is not None:
        patients, missing_fields = _profile_from_manifest(root, manifest_path, all_files)
    elif set(raw_inventory).issubset({"csv", "xlsx", "xls", "tsv", "txt", "json"}):
        patients, missing_fields = [], []
    else:
        patients, missing_fields = _infer_from_filenames(root if root.is_dir() else root.parent, all_files)

    detected_type = _detected_type_from_profile(patients, raw_inventory, missing_fields)
    suggestions = _suggested_workflows(detected_type, patients)

    return DataProfile(
        source_path=str(root),
        detected_type=detected_type,
        patients=patients,
        missing_fields=sorted(dict.fromkeys(filter(None, missing_fields))),
        suggested_workflows=suggestions,
        raw_inventory=raw_inventory,
    )


def data_profile_to_json(profile: DataProfile) -> str:
    return json.dumps(asdict(profile), indent=2, sort_keys=False)


def main(argv: list[str] | None = None) -> int:
    args = argv or []
    if not args:
        raise SystemExit("Usage: python src/data_profiler.py <source_path>")
    profile = profile_data_source(args[0])
    print(data_profile_to_json(profile))
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
