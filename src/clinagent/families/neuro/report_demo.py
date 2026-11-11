from __future__ import annotations

import base64
import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from clinagent.platform.config import load_settings
from clinagent.families.neuro.config import NeuroAgentConfig
from clinagent.families.neuro.intake import (
    AnalysisPlan,
    CapabilityProfile,
    CaseIntakeContext,
    build_capability_profile,
    build_analysis_plan,
    build_planning_result,
    normalize_case_intake,
    summarize_analysis_plan,
    summarize_capability_profile,
)
from clinagent.families.neuro.longitudinal import ProteasDataset, neuro_longitudinal_store
from clinagent.families.neuro.preprocessing import SequenceRouter
from clinagent.families.neuro.preprocessing.slice_selector import SliceSelector
from clinagent.families.neuro.reasoning.reasoning_chain import ReasoningResult
from clinagent.families.neuro.resources import VISTA_LABEL_MAPPING_PATH
from clinagent.families.neuro.run_single import run_single_case
from clinagent.families.neuro.tools import NNUNetBrainSegmentationTool, StructuralSegmentationAdapter, VolumetricAnalysisTool
from clinagent.platform.harness import build_workspace_contract
from clinagent.platform.execution_profiles import build_workflow_runtime_bundle
from clinagent.platform.memory_harness import (
    build_reviewed_memory_context,
    derive_reviewed_memory_defaults,
    get_harness_memory_store,
    get_session_memory,
    save_session_memory,
    save_entity_memory,
    save_reviewed_pattern_memory,
    save_user_memory,
    save_workflow_memory,
)
from clinagent.platform.mcp_registry import build_context_availability_summary
from clinagent.families.shared.report_quality import evaluate_report_quality
from clinagent.platform.local_data import neuro_report_data_root_candidates


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATA_ROOT = REPO_ROOT / ".clinagent" / "local" / "longitudinal_patient"
DEFAULT_VISTA_LABEL_MAPPING_PATH = VISTA_LABEL_MAPPING_PATH
DEFAULT_REGION_ORDER = [
    "total_brain_volume",
    "left_hippocampus",
    "right_hippocampus",
    "hippocampus",
    "left_lateral_ventricle",
    "right_lateral_ventricle",
    "ventricles",
    "left_cerebral_cortex",
    "right_cerebral_cortex",
    "left_cerebral_white_matter",
    "right_cerebral_white_matter",
]
STRUCTURAL_SERIES_PRIORITY = [
    "left_hippocampus",
    "right_hippocampus",
    "left_lateral_ventricle",
    "right_lateral_ventricle",
    "hippocampus",
    "ventricles",
    "left_cerebral_cortex",
    "right_cerebral_cortex",
    "left_cerebral_white_matter",
    "right_cerebral_white_matter",
    "total_brain_volume",
]
SUPPORTED_ANALYSIS_MODES = ["vanilla", "seg_overlay", "tool_output", "full_agent"]
DATE_PLACEHOLDER_RE = re.compile(r"\[date_[^\]]+\]", flags=re.IGNORECASE)


@dataclass(frozen=True)
class StudyRecord:
    patient_id: str
    study_id: str
    study_date: str
    batch: str
    age: int
    sex: str
    image_dir: Path
    seg_dir: Path
    report_path: Path
    metadata_path: Path
    report_full_text: str
    report_sections: dict[str, str]
    indication: str
    diagnosis: str
    analysis_image_path: Path
    seg_path: Path | None
    seg_label_source: str | None = None
    seg_label_mapping_path: Path | None = None
    seg_label_schema_path: Path | None = None

    @property
    def case_id(self) -> str:
        return f"{self.patient_id}:{self.study_id}"


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items() if key} for row in csv.DictReader(handle)]


def _encode_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _encode_label_map(mask: Any) -> tuple[str, list[int]]:
    array = mask.astype("<u2", copy=False)
    return base64.b64encode(array.tobytes(order="C")).decode("ascii"), [int(array.shape[0]), int(array.shape[1])]


def _parse_age(value: str | None) -> int:
    text = (value or "").strip().upper()
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 65


def _parse_sex(value: str | None) -> str:
    sex = (value or "").strip().upper()
    return sex if sex in {"M", "F"} else "M"


def _clean_section_text(value: str | None) -> str:
    text = (value or "").replace("\r\n", "\n").strip()
    if not text:
        return ""

    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue
        if line.lower().startswith("comparison") and DATE_PLACEHOLDER_RE.search(line):
            cleaned_lines.append("Comparison: Prior MR exam available.")
            continue
        cleaned_lines.append(line)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines)).strip()


def _parse_report_sections(row: dict[str, str]) -> dict[str, str]:
    sections = {
        "clinical_information": _clean_section_text(row.get("clinical_information")),
        "technique": _clean_section_text(row.get("technique")),
        "findings": _clean_section_text(row.get("findings")),
        "impression": _clean_section_text(row.get("impression")),
    }
    full_text = _clean_section_text(row.get("report"))
    if all(sections.values()) or not full_text:
        return sections

    lowered = full_text.lower()
    markers = [
        ("clinical information", "clinical_information"),
        ("technique", "technique"),
        ("findings", "findings"),
        ("impression", "impression"),
    ]
    spans: list[tuple[str, int, int]] = []
    for label, key in markers:
        idx = lowered.find(label)
        if idx >= 0:
            spans.append((key, idx, idx + len(label)))
    spans.sort(key=lambda item: item[1])
    for index, (key, start, end) in enumerate(spans):
        next_start = spans[index + 1][1] if index + 1 < len(spans) else len(full_text)
        snippet = full_text[end:next_start].lstrip(" :\n").strip()
        if snippet and not sections[key]:
            sections[key] = snippet
    return sections


def _compose_report_text(sections: dict[str, str], fallback_text: str) -> str:
    ordered = [
        ("CLINICAL INFORMATION", sections.get("clinical_information", "")),
        ("TECHNIQUE", sections.get("technique", "")),
        ("FINDINGS", sections.get("findings", "")),
        ("IMPRESSION", sections.get("impression", "")),
    ]
    if not any(value for _, value in ordered):
        return fallback_text.strip()
    return "\n\n".join(f"{label}:\n{value or 'Not provided.'}" for label, value in ordered)


def _candidate_image_paths(image_dir: Path) -> list[Path]:
    return sorted(path for path in image_dir.glob("*.nii.gz") if path.is_file())


def _nifti_stem(path: str | Path) -> str:
    name = Path(path).name
    if name.endswith(".nii.gz"):
        return name[:-7]
    if name.endswith(".nii"):
        return name[:-4]
    return Path(path).stem


def _select_default_image(image_dir: Path, seg_path: Path | None) -> Path:
    image_paths = _candidate_image_paths(image_dir)
    if not image_paths:
        raise FileNotFoundError(f"No NIfTI files were found under {image_dir}")

    if seg_path is not None:
        prefix = seg_path.name
        for suffix in ("_vista-seg.nii.gz", "_server-seg.nii.gz", "_generated-seg.nii.gz"):
            prefix = prefix.replace(suffix, "")
        for path in image_paths:
            if path.name.startswith(prefix):
                return path

    preferred_tokens = ["t1w-raw-sag", "t1w-raw-cor", "t1w-raw-axi", "t1w"]
    for token in preferred_tokens:
        for path in image_paths:
            if token in path.name:
                return path
    return image_paths[0]


def _study_label(study: StudyRecord) -> str:
    return f"{study.study_date} · {study.study_id}"


def _baseline_study(studies: list[StudyRecord]) -> StudyRecord:
    if not studies:
        raise KeyError("No studies are available for this patient.")
    return studies[0]


def _safe_case_slug(*parts: str | None) -> str:
    tokens = [str(part).strip().replace(":", "-") for part in parts if str(part or "").strip()]
    return "-".join(tokens) or uuid.uuid4().hex


def _display_name_from_series(series_name: str) -> str:
    return series_name.replace("_", " ").title()


def _structural_data_root_candidates(explicit_root: str | Path | None) -> list[Path]:
    candidates = neuro_report_data_root_candidates(explicit_root)
    if DEFAULT_DATA_ROOT not in candidates:
        candidates.append(DEFAULT_DATA_ROOT)
    return candidates


class NeuroReportDemoStore:
    def __init__(self, data_root: str | Path | None = None) -> None:
        self.data_root = self._resolve_data_root(data_root)
        self._settings = load_settings()
        self._proteas_dataset = ProteasDataset.discover()
        self._asset_root = REPO_ROOT / ".clinagent" / "derived" / "neuro_longitudinal" / "neuro-report"
        self._asset_root.mkdir(parents=True, exist_ok=True)
        self._records_by_patient: dict[str, list[StudyRecord]] = {}
        self._records_by_case_id: dict[str, StudyRecord] = {}
        self._records_by_study_key: dict[tuple[str, str], StudyRecord] = {}
        self._response_cases: dict[str, dict[str, Any]] = {}
        self._response_case_by_patient: dict[str, str] = {}
        self._patient_names: dict[str, str] = {}
        self._study_detail_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._thumbnail_cache: dict[str, str] = {}
        self._response_thumbnail_cache: dict[str, str] = {}
        self._volumetrics_cache: dict[str, dict[str, Any]] = {}
        self._longitudinal_cache: dict[str, dict[str, Any]] = {}
        self._heatmap_cache: dict[str, dict[str, Any]] = {}
        self._slice_manifest_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._slice_payload_cache: dict[tuple[str, str, str, int, bool], dict[str, Any]] = {}
        self._examples_cache: list[dict[str, Any]] | None = None
        self._session_store: dict[str, dict[str, Any]] = {}
        self._sequence_router = SequenceRouter()
        self._structural_segmenter = NNUNetBrainSegmentationTool()
        self._structural_segmentation_adapter = StructuralSegmentationAdapter()
        self._volumetrics_tool = VolumetricAnalysisTool(NeuroAgentConfig().normative_table_path)
        self._selector_thumbnail = SliceSelector(num_slices=1, output_size=(320, 320))
        self._selector_detail = SliceSelector(num_slices=7, output_size=(420, 420))
        self._selector_structural_dense = SliceSelector(num_slices=7, output_size=(256, 256))
        self._load_records()
        self._load_response_cases()

    @staticmethod
    def _asset_url(path: Path) -> str:
        repo_root = REPO_ROOT / ".clinagent" / "derived" / "neuro_longitudinal"
        return f"/neuro-assets/{path.relative_to(repo_root).as_posix()}"

    @staticmethod
    def _default_plane_for_name(filename: str) -> str:
        lowered = filename.lower()
        if "sag" in lowered:
            return "sagittal"
        if "cor" in lowered:
            return "coronal"
        return "axial"

    def _materialize_viewer_assets(
        self,
        *,
        image_path: str | Path,
        seg_path: str | Path | None,
        asset_slug: str,
        viewer_type: str = "nifti",
        study_uid: str | None = None,
        series_uid: str | None = None,
    ) -> dict[str, Any]:
        asset_dir = self._asset_root / asset_slug / "viewer"
        asset_dir.mkdir(parents=True, exist_ok=True)

        source_image = Path(image_path).expanduser().resolve()
        target_image = asset_dir / "image.nii.gz"
        if target_image.exists() or target_image.is_symlink():
            target_image.unlink()
        shutil.copy2(source_image, target_image)

        target_seg: Path | None = None
        if seg_path:
            source_seg = Path(seg_path).expanduser().resolve()
            target_seg = asset_dir / "segmentation.nii.gz"
            if target_seg.exists() or target_seg.is_symlink():
                target_seg.unlink()
            shutil.copy2(source_seg, target_seg)

        ohif_base_url = (self._settings.ohif_base_url or "").rstrip("/")
        ohif_url = None
        if viewer_type == "dicomweb" and ohif_base_url and study_uid:
            ohif_url = f"{ohif_base_url}/viewer?StudyInstanceUIDs={study_uid}"
            if series_uid:
                ohif_url = f"{ohif_url}&SeriesInstanceUIDs={series_uid}"

        return {
            "viewer_type": viewer_type,
            "has_segmentation": target_seg is not None,
            "default_plane": self._default_plane_for_name(source_image.name),
            "orientation_policy": "radiological",
            "image_asset_url": self._asset_url(target_image),
            "segmentation_asset_url": self._asset_url(target_seg) if target_seg else None,
            "study_uid": study_uid,
            "series_uid": series_uid,
            "dicomweb_base_url": self._settings.dicomweb_base_url or None,
            "ohif_url": ohif_url,
        }

    @staticmethod
    def _resolve_data_root(explicit_root: str | Path | None) -> Path:
        candidates = _structural_data_root_candidates(explicit_root)
        for candidate in candidates:
            if (candidate / "metadata" / "longitudinal_manifest.csv").exists():
                return candidate
        return candidates[0]

    def _generated_structural_seg_paths(self, *, patient_id: str, study_id: str, image_path: str | Path) -> dict[str, Path]:
        export_dir = self._asset_root / "generated-seg" / _safe_case_slug(patient_id) / _safe_case_slug(study_id)
        stem = _nifti_stem(image_path)
        seg_path = export_dir / f"{stem}_server-seg.nii.gz"
        label_schema_path = export_dir / f"{stem}_server-seg_labels.json"
        metadata_path = export_dir / f"{stem}_server-seg.meta.json"
        return {
            "dir": export_dir,
            "seg_path": seg_path,
            "label_schema_path": label_schema_path,
            "metadata_path": metadata_path,
        }

    def _resolved_structural_segmentation(
        self,
        *,
        patient_id: str,
        study_id: str,
        image_path: Path,
        legacy_seg_path: Path | None,
    ) -> tuple[Path | None, str | None, Path | None, Path | None]:
        generated = self._generated_structural_seg_paths(
            patient_id=patient_id,
            study_id=study_id,
            image_path=image_path,
        )
        generated_seg_path = generated["seg_path"]
        generated_label_schema_path = generated["label_schema_path"]
        if generated_seg_path.exists() and generated_label_schema_path.exists():
            return (
                generated_seg_path,
                "remote_schema",
                generated_label_schema_path,
                generated_label_schema_path,
            )
        if legacy_seg_path is None:
            return None, None, None, None
        return (
            legacy_seg_path,
            "vista_tsv",
            Path(DEFAULT_VISTA_LABEL_MAPPING_PATH),
            None,
        )

    def _replace_record(self, original: StudyRecord, updated: StudyRecord) -> None:
        patient_records = self._records_by_patient.get(original.patient_id, [])
        for index, record in enumerate(patient_records):
            if record.study_id == original.study_id:
                patient_records[index] = updated
                break
        self._records_by_case_id[original.case_id] = updated
        self._records_by_study_key[(original.patient_id, original.study_id)] = updated

    def _invalidate_structural_caches(self, *, patient_id: str, study_id: str, case_id: str) -> None:
        self._examples_cache = None
        self._study_detail_cache.pop((patient_id, study_id), None)
        self._volumetrics_cache.pop(case_id, None)
        self._thumbnail_cache.pop(case_id, None)
        self._longitudinal_cache.pop(patient_id, None)
        self._heatmap_cache.pop(patient_id, None)
        self._slice_manifest_cache.clear()
        self._slice_payload_cache.clear()

    def _load_records(self) -> None:
        manifest_path = self.data_root / "metadata" / "longitudinal_manifest.csv"
        if not manifest_path.exists():
            return

        manifest_rows = _read_csv_rows(manifest_path)
        report_cache: dict[Path, dict[str, dict[str, str]]] = {}
        metadata_cache: dict[Path, dict[str, list[dict[str, str]]]] = {}

        for row in manifest_rows:
            patient_id = row["patient_uid"]
            study_id = row["study_uid"]
            report_path = self.data_root / row["report_relpath"]
            metadata_path = self.data_root / row["metadata_relpath"]
            batch = row["batch"]

            report_rows = report_cache.setdefault(
                report_path,
                {item["study_uid"]: item for item in _read_csv_rows(report_path)},
            )
            metadata_rows = metadata_cache.setdefault(metadata_path, {})
            if not metadata_rows:
                grouped: dict[str, list[dict[str, str]]] = {}
                for item in _read_csv_rows(metadata_path):
                    grouped.setdefault(item.get("study_uid", ""), []).append(item)
                metadata_rows.update(grouped)

            study_report = report_rows.get(study_id, {})
            study_metadata = metadata_rows.get(study_id, [])
            if not study_metadata:
                continue

            age = _parse_age(study_metadata[0].get("Patient'sAge"))
            sex = _parse_sex(study_metadata[0].get("Patient'sSex"))
            sections = _parse_report_sections(study_report)
            report_full = _compose_report_text(sections, _clean_section_text(study_report.get("report")))
            image_dir = self.data_root / "mri" / batch / study_id / "img"
            seg_dir = self.data_root / "mri_seg" / batch / study_id / "seg"
            seg_candidates = sorted(seg_dir.glob("*_vista-seg.nii.gz"))
            legacy_seg_path = seg_candidates[0] if seg_candidates else None
            analysis_image_path = _select_default_image(image_dir, legacy_seg_path)
            seg_path, seg_label_source, seg_label_mapping_path, seg_label_schema_path = self._resolved_structural_segmentation(
                patient_id=patient_id,
                study_id=study_id,
                image_path=analysis_image_path,
                legacy_seg_path=legacy_seg_path,
            )

            diagnosis = sections.get("clinical_information") or "Brain MRI follow-up"
            self._patient_names.setdefault(patient_id, f"Patient {patient_id}")

            record = StudyRecord(
                patient_id=patient_id,
                study_id=study_id,
                study_date=row["anon_study_date"],
                batch=batch,
                age=age,
                sex=sex,
                image_dir=image_dir,
                seg_dir=seg_dir,
                report_path=report_path,
                metadata_path=metadata_path,
                report_full_text=report_full,
                report_sections=sections,
                indication=sections.get("clinical_information") or "Brain MRI for clinical evaluation",
                diagnosis=diagnosis,
                analysis_image_path=analysis_image_path,
                seg_path=seg_path,
                seg_label_source=seg_label_source,
                seg_label_mapping_path=seg_label_mapping_path,
                seg_label_schema_path=seg_label_schema_path,
            )
            self._records_by_patient.setdefault(patient_id, []).append(record)
            self._records_by_case_id[record.case_id] = record
            self._records_by_study_key[(patient_id, study_id)] = record

        for patient_id, studies in self._records_by_patient.items():
            studies.sort(key=lambda item: item.study_date)
            self._patient_names[patient_id] = f"Patient {patient_id}"

    def snapshot(self) -> dict[str, Any]:
        patients = self.get_patients()["patients"]
        default_patient = patients[0] if patients else None
        default_study = None
        if default_patient:
            default_study = self._records_by_patient[default_patient["id"]][-1]
        return {
            "default_case_id": default_study.case_id if default_study else None,
            "workspace": {
                "title": "Neuro MRI Report Workspace",
                "patient": {
                    "display_name": default_patient["name"] if default_patient else "Neuro MRI",
                    "summary": "Curated MR-RATE studies with real segmentation, volumetrics, and reporting.",
                },
                "review": {"status": "ready"},
                "analysis": {"risk_level": "review"},
            },
        }

    def _record_for_case(self, case_id: str) -> StudyRecord:
        if case_id not in self._records_by_case_id:
            raise KeyError(f"Unknown case: {case_id}")
        return self._records_by_case_id[case_id]

    def _record_for_study(self, patient_id: str, study_id: str) -> StudyRecord:
        key = (patient_id, study_id)
        if key not in self._records_by_study_key:
            raise KeyError(f"Unknown study: {patient_id}/{study_id}")
        return self._records_by_study_key[key]

    def _build_thumbnail(self, record: StudyRecord) -> str:
        cached = self._thumbnail_cache.get(record.case_id)
        if cached:
            return cached
        selected = self._selector_thumbnail.select_slices(record.analysis_image_path)
        png_bytes = self._selector_thumbnail.render_to_png_bytes(selected[0])
        encoded = _encode_base64(png_bytes)
        self._thumbnail_cache[record.case_id] = encoded
        return encoded

    def _compute_volumetrics(self, record: StudyRecord) -> dict[str, Any] | None:
        cached = self._volumetrics_cache.get(record.case_id)
        if cached is not None:
            return cached
        if record.seg_path is None:
            self._volumetrics_cache[record.case_id] = None
            return None
        adapter_kwargs: dict[str, Any] = {
            "seg_nifti_path": str(record.seg_path),
        }
        if record.seg_label_source == "remote_schema":
            if record.seg_label_schema_path is None:
                raise ValueError(f"Remote-schema segmentation is missing a label schema for {record.case_id}")
            adapter_kwargs["label_schema_path"] = str(record.seg_label_schema_path)
            adapter_kwargs["label_source"] = "remote_schema"
        else:
            adapter_kwargs["label_mapping_path"] = str(record.seg_label_mapping_path or DEFAULT_VISTA_LABEL_MAPPING_PATH)
            adapter_kwargs["label_source"] = "vista_tsv"
        segmentation_result = self._structural_segmentation_adapter.run(**adapter_kwargs)
        volumetrics = self._volumetrics_tool.run(
            segmentation_result=segmentation_result,
            patient_age=record.age,
            patient_sex=record.sex,
        )
        payload = {
            "segmentation": segmentation_result,
            "volumetrics": volumetrics,
        }
        self._volumetrics_cache[record.case_id] = payload
        return payload

    def _infer_sequences(self, image_path: Path) -> list[str]:
        inferred = self._sequence_router.identify_from_filename(image_path.name).value
        return [inferred if inferred != "unknown" else "T1w"]

    def _plan_for_record(self, record: StudyRecord, request_text: str = "") -> tuple[CaseIntakeContext, CapabilityProfile, AnalysisPlan]:
        has_prior_study = len(self._records_by_patient.get(record.patient_id, [])) > 1
        context = normalize_case_intake(
            request_text=request_text,
            source_kind="curated_case",
            patient_id=record.patient_id,
            study_id=record.study_id,
            case_id=record.case_id,
            nifti_path=str(record.analysis_image_path),
            seg_path=str(record.seg_path) if record.seg_path else None,
            age=record.age,
            sex=record.sex,
            indication=record.indication,
            available_sequences=self._infer_sequences(record.analysis_image_path),
            has_prior_study=has_prior_study,
            has_prior_report=has_prior_study,
            has_ehr_context=True,
            has_report_context=True,
        )
        profile = build_capability_profile(context)
        return context, profile, build_analysis_plan(context, profile)

    def _load_response_cases(self) -> None:
        snapshot = neuro_longitudinal_store.snapshot()
        preferred_patient_id = os.getenv("CLINAGENT_NEURO_DEMO_CASE", "P28").strip() or "P28"
        case_stubs = list(snapshot.get("cases", []))
        case_stubs.sort(
            key=lambda case_stub: (
                str(case_stub.get("patient", {}).get("id", "")).strip() != preferred_patient_id,
                str(case_stub.get("id", "")),
            )
        )
        for case_stub in case_stubs:
            case_id = str(case_stub.get("id", "")).strip()
            if not case_id:
                continue
            try:
                workspace = neuro_longitudinal_store.get_case(case_id)
            except KeyError:
                continue
            patient_id = str(workspace.get("patient", {}).get("id", "")).strip()
            if not patient_id:
                continue
            if self._response_timepoint_assets(workspace) is None:
                continue
            self._response_cases[case_id] = workspace
            self._response_case_by_patient[patient_id] = case_id

    def _is_response_patient(self, patient_id: str | None) -> bool:
        return bool(patient_id and patient_id in self._response_case_by_patient)

    def _response_case(self, *, case_id: str | None = None, patient_id: str | None = None) -> dict[str, Any] | None:
        if case_id and case_id in self._response_cases:
            return self._response_cases[case_id]
        if patient_id and patient_id in self._response_case_by_patient:
            return self._response_cases[self._response_case_by_patient[patient_id]]
        return None

    def _response_case_root(self, case: dict[str, Any]) -> Path | None:
        if self._proteas_dataset is None:
            return None
        patient_id = str(case.get("patient", {}).get("id", "")).strip()
        if not patient_id:
            return None
        root = self._proteas_dataset.root / patient_id
        return root if root.exists() else None

    @staticmethod
    def _response_latest_timeline_point(case: dict[str, Any]) -> dict[str, Any]:
        timeline = case.get("timeline") or []
        if not timeline:
            raise KeyError("No response timeline is available for this case.")
        return timeline[-1]

    def _response_study_point(self, case: dict[str, Any], study_id: str | None) -> dict[str, Any]:
        timeline = case.get("timeline") or []
        if study_id:
            for point in timeline:
                if str(point.get("study_id")) == study_id:
                    return point
        return self._response_latest_timeline_point(case)

    def _response_timepoint_assets(self, case: dict[str, Any], study_id: str | None = None) -> dict[str, Any] | None:
        case_root = self._response_case_root(case)
        if case_root is None:
            return None
        patient_id = str(case.get("patient", {}).get("id", "")).strip()
        point = self._response_study_point(case, study_id)
        timepoint = str(point.get("timepoint", "baseline"))
        mask_suffix = "baseline" if timepoint == "baseline" else timepoint
        image_path = case_root / "BraTS" / timepoint / "t1c.nii.gz"
        seg_path = case_root / "tumor_segmentation" / f"{patient_id}_tumor_mask_{mask_suffix}.nii.gz"
        dicom_series = sorted((case_root / "DICOM").glob(f"T1C_HR_*{str(point.get('study_date', '')).strip()}"))
        if not dicom_series:
            dicom_series = sorted((case_root / "DICOM").glob(f"T1C_*{str(point.get('study_date', '')).strip()}"))
        if not image_path.exists():
            return None
        return {
            "patient_id": patient_id,
            "study_id": str(point.get("study_id", "")),
            "timepoint": timepoint,
            "study_date": str(point.get("study_date", "")),
            "image_path": image_path,
            "seg_path": seg_path if seg_path.exists() else None,
            "dicom_dir": dicom_series[0] if dicom_series else None,
        }

    def _response_report_sections(self, case: dict[str, Any]) -> dict[str, str]:
        report = case.get("report") or {}
        sections = report.get("sections") or []
        mapped = {
            "clinical_information": "",
            "technique": "Serial post-treatment MRI review with longitudinal lesion burden assessment.",
            "findings": "",
            "impression": report.get("summary", ""),
        }
        for section in sections:
            title = str(section.get("title", "")).strip().lower()
            body = str(section.get("body", "")).strip()
            if "context" in title:
                mapped["clinical_information"] = body
            elif "burden" in title or "interpretation" in title:
                mapped["findings"] = "\n\n".join(filter(None, [mapped["findings"], body])).strip()
            elif "attention" in title:
                mapped["impression"] = "\n\n".join(filter(None, [mapped["impression"], body])).strip()
        return mapped

    def _response_report_text(self, case: dict[str, Any]) -> str:
        report = case.get("report") or {}
        sections = self._response_report_sections(case)
        return _compose_report_text(sections, str(report.get("summary", "")).strip())

    def _response_viewer_assets(self, case: dict[str, Any], study_id: str | None = None) -> dict[str, Any]:
        assets = self._response_timepoint_assets(case, study_id)
        if assets is None:
            return {
                "viewer_type": "png_fallback",
                "has_segmentation": False,
                "default_plane": "axial",
                "orientation_policy": "radiological",
                "image_asset_url": None,
                "segmentation_asset_url": None,
                "dicomweb_base_url": self._settings.dicomweb_base_url or None,
                "ohif_url": None,
            }
        viewer_assets = self._materialize_viewer_assets(
            image_path=assets["image_path"],
            seg_path=assets["seg_path"],
            asset_slug=_safe_case_slug(str(case.get("id")), assets["study_id"], assets["timepoint"]),
            viewer_type="nifti",
        )
        viewer_assets["dicom_series_label"] = assets["dicom_dir"].name if assets["dicom_dir"] else None
        viewer_assets["source_kind"] = "hybrid_dicom_mask_case"
        return viewer_assets

    def _response_slices(self, case: dict[str, Any], study_id: str | None = None) -> tuple[dict[str, list[dict[str, Any]]] | None, dict[str, list[dict[str, Any]]] | None]:
        assets = self._response_timepoint_assets(case, study_id)
        if assets is None:
            return None, None
        return self._build_slice_payloads(
            selector=self._selector_detail,
            image_path=assets["image_path"],
            seg_path=assets["seg_path"],
        )

    def _response_thumbnail(self, case: dict[str, Any], study_id: str | None = None) -> str:
        point = self._response_study_point(case, study_id)
        cache_key = f"{case['id']}:{point.get('study_id')}"
        cached = self._response_thumbnail_cache.get(cache_key)
        if cached:
            return cached
        assets = self._response_timepoint_assets(case, study_id)
        if assets is None:
            preview = str(case.get("imaging_preview", {}).get("image_url", "")).strip()
            if preview.startswith("data:image/"):
                encoded = preview.split(",", 1)[1]
                self._response_thumbnail_cache[cache_key] = encoded
                return encoded
            raise FileNotFoundError(f"No imaging assets are available for response case {case['id']}")
        selected = self._selector_thumbnail.select_slices(assets["image_path"])
        png_bytes = self._selector_thumbnail.render_to_png_bytes(selected[0])
        encoded = _encode_base64(png_bytes)
        self._response_thumbnail_cache[cache_key] = encoded
        return encoded

    def _build_slice_payloads(
        self,
        *,
        selector: SliceSelector,
        image_path: str | Path,
        seg_path: str | Path | None,
        dense: bool = False,
        dense_stride: int = 1,
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]] | None]:
        slices = selector.select_dense_slices(image_path, stride=dense_stride) if dense else selector.select_slices(image_path)
        raw_by_plane: dict[str, list[dict[str, Any]]] = {"axial": [], "coronal": [], "sagittal": []}
        overlay_by_plane: dict[str, list[dict[str, Any]]] = {"axial": [], "coronal": [], "sagittal": []}

        for item in slices:
            raw_png = selector.render_to_png_bytes(item)
            render_metadata = selector.get_render_metadata(item)
            raw_entry = {
                "image_base64": _encode_base64(raw_png),
                "overlay_base64": None,
                "label_map_base64": None,
                "label_shape": None,
                "original_shape": render_metadata["original_shape"],
                "render_shape": render_metadata["render_shape"],
                "content_bbox": render_metadata["content_bbox"],
                "padding": render_metadata["padding"],
                "slice_index": item["slice_index"],
                "slice_fraction": item["slice_fraction"],
                "description": item["description"],
                "orientation_labels": item.get("orientation_labels"),
                "orientation_policy": item.get("orientation_policy", "radiological"),
            }
            raw_by_plane[item["plane"]].append(raw_entry)
            if seg_path is not None:
                try:
                    overlay_png = selector.render_with_overlay(item, seg_path)
                    label_map = selector.extract_segmentation_slice(item, seg_path)
                    label_map_base64, label_shape = _encode_label_map(label_map)
                    overlay_by_plane[item["plane"]].append(
                        {
                            **raw_entry,
                            "overlay_base64": _encode_base64(overlay_png),
                            "label_map_base64": label_map_base64,
                            "label_shape": label_shape,
                        }
                    )
                except Exception:
                    overlay_by_plane[item["plane"]].append(raw_entry)

        return raw_by_plane, overlay_by_plane if seg_path is not None else None

    def _structural_slice_manifest(self, *, image_path: str | Path, seg_path: str | Path | None) -> dict[str, Any]:
        cache_key = (str(Path(image_path).resolve()), str(Path(seg_path).resolve()) if seg_path else "")
        cached = self._slice_manifest_cache.get(cache_key)
        if cached is not None:
            return cached
        manifest = self._selector_structural_dense.get_slice_manifest(
            image_path,
            has_overlay=seg_path is not None,
            seg_nifti_path=seg_path,
        )
        self._slice_manifest_cache[cache_key] = manifest
        return manifest

    def _structural_slice_payload(
        self,
        *,
        image_path: str | Path,
        seg_path: str | Path | None,
        plane: str,
        index: int,
        overlay: bool,
    ) -> dict[str, Any]:
        normalized_plane = plane.strip().lower()
        if normalized_plane not in {"axial", "coronal", "sagittal"}:
            raise KeyError(f"Unsupported plane: {plane}")
        manifest = self._structural_slice_manifest(image_path=image_path, seg_path=seg_path)
        plane_meta = manifest["planes"][normalized_plane]
        clamped_index = max(0, min(int(index), int(plane_meta["slice_count"]) - 1))
        cache_key = (
            str(Path(image_path).resolve()),
            str(Path(seg_path).resolve()) if seg_path else "",
            normalized_plane,
            clamped_index,
            bool(overlay and seg_path is not None),
        )
        cached = self._slice_payload_cache.get(cache_key)
        if cached is not None:
            return cached

        slice_data = self._selector_structural_dense.select_slice(
            image_path,
            plane=normalized_plane,
            index=clamped_index,
            description="",
        )
        raw_png = self._selector_structural_dense.render_to_png_bytes(slice_data)
        render_metadata = self._selector_structural_dense.get_render_metadata(slice_data)
        payload: dict[str, Any] = {
            "image_base64": _encode_base64(raw_png),
            "overlay_base64": None,
            "label_map_base64": None,
            "label_shape": None,
            "original_shape": render_metadata["original_shape"],
            "render_shape": render_metadata["render_shape"],
            "content_bbox": render_metadata["content_bbox"],
            "padding": render_metadata["padding"],
            "slice_index": slice_data["slice_index"],
            "slice_fraction": slice_data["slice_fraction"],
            "description": "",
            "orientation_labels": slice_data.get("orientation_labels"),
            "orientation_policy": slice_data.get("orientation_policy", "radiological"),
        }
        if overlay and seg_path is not None:
            try:
                overlay_png = self._selector_structural_dense.render_with_overlay(slice_data, seg_path)
                label_map = self._selector_structural_dense.extract_segmentation_slice(slice_data, seg_path)
                label_map_base64, label_shape = _encode_label_map(label_map)
                payload = {
                    **payload,
                    "overlay_base64": _encode_base64(overlay_png),
                    "label_map_base64": label_map_base64,
                    "label_shape": label_shape,
                }
            except Exception:
                pass
        self._slice_payload_cache[cache_key] = payload
        return payload

    def _response_planning_bundle(
        self,
        case: dict[str, Any],
        *,
        study_id: str | None = None,
        request_text: str = "Review this tumor follow-up brain MRI and estimate longitudinal response burden.",
        requested_mode: str = "seg_overlay",
        executed_mode: str | None = None,
    ) -> tuple[CaseIntakeContext, CapabilityProfile, AnalysisPlan, dict[str, Any], dict[str, Any]]:
        assets = self._response_timepoint_assets(case, study_id)
        if assets is None:
            raise FileNotFoundError(f"Response imaging assets are unavailable for case {case['id']}")
        patient = case.get("patient") or {}
        intake_context = normalize_case_intake(
            request_text=request_text,
            source_kind="curated_case",
            patient_id=str(patient.get("id", "")).strip() or None,
            study_id=str(assets["study_id"]),
            case_id=str(case.get("id", "")).strip() or None,
            nifti_path=str(assets["image_path"]),
            dicom_path=str(assets["dicom_dir"]) if assets["dicom_dir"] else None,
            seg_path=str(assets["seg_path"]) if assets["seg_path"] is not None else None,
            age=int(patient.get("age") or 0) or None,
            sex=str(patient.get("sex", "")).strip()[:1].upper() or None,
            indication=str(patient.get("diagnosis") or "Brain metastasis follow-up"),
            available_sequences=["T1c", "FLAIR"],
            has_prior_study=True,
            has_prior_report=True,
            has_ehr_context=True,
            has_report_context=True,
        )
        capability_profile = build_capability_profile(intake_context)
        analysis_plan = build_analysis_plan(intake_context, capability_profile)
        viewer_assets = self._response_viewer_assets(case, study_id)
        planning_result = build_planning_result(
            intake_context,
            capability_profile,
            analysis_plan,
            requested_mode=requested_mode,
            executed_mode=executed_mode or analysis_plan.recommended_mode or requested_mode,
            viewer_type=viewer_assets["viewer_type"],
        ).to_dict()
        return intake_context, capability_profile, analysis_plan, viewer_assets, planning_result

    def _response_dashboard_payloads(
        self,
        case: dict[str, Any],
        *,
        planning_result: dict[str, Any],
        study_id: str | None = None,
    ) -> dict[str, Any]:
        report_text = self._response_report_text(case)
        review = self._build_review_dashboard_payload(
            record=StudyRecord(
                patient_id=str(case.get("patient", {}).get("id", "")),
                study_id=str(self._response_latest_timeline_point(case).get("study_id", "")),
                study_date=str(self._response_latest_timeline_point(case).get("study_date", "")),
                batch="response",
                age=int(case.get("patient", {}).get("age") or 0),
                sex=str(case.get("patient", {}).get("sex") or "U")[:1].upper(),
                image_dir=Path("."),
                seg_dir=Path("."),
                report_path=Path("."),
                metadata_path=Path("."),
                report_full_text=report_text,
                report_sections=self._response_report_sections(case),
                indication=str(case.get("patient", {}).get("diagnosis") or "Brain metastasis follow-up"),
                diagnosis=str(case.get("patient", {}).get("diagnosis") or "Brain metastasis follow-up"),
                analysis_image_path=Path("."),
                seg_path=None,
            ),
            report_text=report_text,
        )
        analysis = case.get("analysis") or {}
        report = case.get("report") or {}
        volumetrics = self._response_volumetrics(case, study_id)
        return {
            "active_profile": "longitudinal_response",
            "structural": {
                "dashboard_profile": "volumetry",
                "summary": "Structural context remains available as a secondary lane when the planner prioritizes tumor-response review.",
                "volumetrics_summary": None,
            },
            "response": {
                "dashboard_profile": "longitudinal_response",
                "status": "ready",
                "summary": str(report.get("summary") or "Longitudinal lesion-response review is ready."),
                "requirements": ["lesion_or_tumor_segmentation", "prior_study"],
                "available_inputs": planning_result.get("available_data", []),
                "recommended_tools": [
                    "lesion_segmentation_ingestion",
                    "lesion_volume_calculator",
                    "response_delta_calculator",
                    "longitudinal_response_synthesizer",
                ],
                "source_label": "case_backed_response",
                "baseline_total_ml": analysis.get("baseline_total_ml"),
                "latest_total_ml": analysis.get("latest_total_ml"),
                "previous_total_ml": analysis.get("previous_total_ml"),
                "delta_pct": analysis.get("delta_pct"),
                "recent_segment_pct": analysis.get("recent_segment_pct"),
                "annual_change_pct": analysis.get("annual_change_pct"),
                "lesion_count": analysis.get("lesion_count"),
                "risk_level": analysis.get("risk_level"),
                "risk_reason": analysis.get("risk_reason"),
                "response_category": "progressive" if analysis.get("accelerated_progression") else "stable_or_mixed",
                "confidence_note": "This dashboard is backed by a real longitudinal lesion case with follow-up masks and treatment-aligned imaging history.",
                "coverage_note": "Viewer overlays use the case-specific tumor mask while longitudinal metrics are derived from the curated response dataset.",
                "next_checks": analysis.get("next_checks", []),
                "timeline": case.get("timeline", []),
                "key_slice_compare": case.get("imaging_preview"),
                "report_summary": report.get("summary", ""),
                "report_sections": report.get("sections", []),
                "available_series": volumetrics.get("available_series", []),
                "default_series": volumetrics.get("default_series", []),
            },
            "review": review,
        }

    def _plan_for_upload(
        self,
        *,
        nifti_path: str,
        seg_path: str | None,
        age: int | None,
        sex: str | None,
        indication: str,
        request_text: str = "",
    ) -> tuple[CaseIntakeContext, CapabilityProfile, AnalysisPlan]:
        context = normalize_case_intake(
            request_text=request_text,
            source_kind="upload",
            nifti_path=nifti_path,
            seg_path=seg_path,
            age=age,
            sex=sex,
            indication=indication,
            available_sequences=self._infer_sequences(Path(nifti_path)),
            has_prior_study=False,
            has_prior_report=False,
            has_ehr_context=age is not None or bool(sex),
            has_report_context=bool(indication),
        )
        profile = build_capability_profile(context)
        return context, profile, build_analysis_plan(context, profile)

    @staticmethod
    def _context_availability(workflow_family: str) -> list[dict[str, Any]]:
        return build_context_availability_summary(workflow_id="neuro_report", workflow_family=workflow_family)

    @staticmethod
    def _reviewed_pattern_ids_for_goal(primary_goal: str) -> list[str]:
        if primary_goal == "response_review":
            return ["response_default_bundle"]
        if primary_goal == "report_review":
            return ["review_default_bundle"]
        return ["structural_default_bundle"]

    def _planner_memory_bundle(
        self,
        *,
        workflow_family: str,
        primary_goal: str,
        patient_id: str | None = None,
        study_id: str | None = None,
        session_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        entity_keys = [("neuro_study", f"{patient_id}:{study_id}")] if patient_id and study_id else []
        workflow_keys = [("neuro_report", "examples")]
        memory_context = build_reviewed_memory_context(
            workflow_family=workflow_family,
            reviewed_pattern_ids=self._reviewed_pattern_ids_for_goal(primary_goal),
            entity_keys=entity_keys,
            workflow_keys=workflow_keys,
            user_id="default_demo_user",
            session_id=session_id,
        )
        planner_defaults = derive_reviewed_memory_defaults(memory_context)
        preferred = planner_defaults.get("preferred_dashboard_profile")
        compatible = {
            "structural_report": "volumetry",
            "response_review": "longitudinal_response",
            "report_review": "report_review",
        }.get(primary_goal)
        if preferred and preferred != compatible:
            planner_defaults["preferred_dashboard_profile"] = compatible
        return memory_context, planner_defaults

    def _runtime_bundle(
        self,
        *,
        analysis_plan: AnalysisPlan,
        capability_profile: CapabilityProfile,
    ) -> dict[str, Any]:
        return build_workflow_runtime_bundle(
            "neuro_report",
            workflow_family=analysis_plan.workflow_family,
            primary_goal=analysis_plan.primary_goal,
            dashboard_profile=analysis_plan.dashboard_profile,
            track=analysis_plan.analysis_track,
            context_sources=capability_profile.context_sources,
            fallback_reason=capability_profile.blocked_reasons[0] if capability_profile.blocked_reasons else None,
            policy_mode=analysis_plan.runtime_mode,
        )

    def _dashboard_payloads(
        self,
        *,
        record: StudyRecord,
        analysis_plan: AnalysisPlan,
        planning_result: dict[str, Any],
        volumetrics_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._build_response_dashboard_payload(
            record=record,
            analysis_plan=analysis_plan,
            planning_result=planning_result,
        )
        review = self._build_review_dashboard_payload(
            record=record,
            report_text=record.report_full_text,
        )
        structural = {
            "dashboard_profile": "volumetry",
            "summary": "Structural dashboard highlights normalized brain-region volumetrics and change-over-time trends.",
            "volumetrics_summary": volumetrics_payload["volumetrics"]["summary"] if volumetrics_payload else None,
        }
        return {
            "active_profile": analysis_plan.dashboard_profile,
            "structural": structural,
            "response": response,
            "review": review,
        }

    def _build_response_dashboard_payload(
        self,
        *,
        record: StudyRecord,
        analysis_plan: AnalysisPlan,
        planning_result: dict[str, Any],
    ) -> dict[str, Any]:
        workspace = neuro_longitudinal_store.snapshot().get("workspace") or {}
        analysis = workspace.get("analysis") or {}
        report = workspace.get("report") or {}
        timeline = workspace.get("timeline") or []
        response_ready = bool(record.seg_path) and len(self._records_by_patient.get(record.patient_id, [])) > 1

        compact_timeline = [
            {
                "study_id": str(point.get("study_id", "")),
                "study_date": str(point.get("study_date", "")),
                "timepoint": str(point.get("timepoint", "")),
                "lesion_volume_ml": float(point.get("lesion_volume_ml", 0.0) or 0.0),
                "percent_change_from_baseline": point.get("percent_change_from_baseline"),
                "percent_change_from_prior": point.get("percent_change_from_prior"),
            }
            for point in timeline[:6]
        ]
        return {
            "dashboard_profile": "longitudinal_response",
            "status": "ready" if response_ready else "intake_only",
            "summary": (
                "Response dashboard reframes the workspace around lesion burden, interval change, and treatment-aligned follow-up."
            ),
            "requirements": ["lesion_or_tumor_segmentation", "prior_study"],
            "available_inputs": planning_result.get("available_data", []),
            "recommended_tools": [
                "lesion_segmentation_ingestion",
                "lesion_volume_calculator",
                "response_delta_calculator",
                "longitudinal_response_synthesizer",
            ],
            "source_label": "compatibility_preview" if not response_ready else "case_ready_preview",
            "baseline_total_ml": analysis.get("baseline_total_ml"),
            "latest_total_ml": analysis.get("latest_total_ml"),
            "previous_total_ml": analysis.get("previous_total_ml"),
            "delta_pct": analysis.get("delta_pct"),
            "recent_segment_pct": analysis.get("recent_segment_pct"),
            "annual_change_pct": analysis.get("annual_change_pct"),
            "lesion_count": analysis.get("lesion_count"),
            "risk_level": analysis.get("risk_level"),
            "risk_reason": analysis.get("risk_reason"),
            "response_category": "progression_signal" if analysis.get("accelerated_progression") else "stable_or_mixed",
            "confidence_note": (
                "Uses longitudinal lesion-response compatibility data until case-level lesion segmentation and prior alignment are available."
                if not response_ready
                else "Case has enough local inputs to present a lesion-response style dashboard."
            ),
            "coverage_note": (
                "Current case is not yet wired to lesion-specific measurements; viewer/report remain structural while the response track demonstrates the intended review surface."
                if not response_ready
                else "Timeline is ready for lesion-aware longitudinal review."
            ),
            "next_checks": analysis.get("next_checks", []),
            "timeline": compact_timeline,
            "key_slice_compare": {
                "title": workspace.get("imaging_preview", {}).get("title", "Representative lesion comparison"),
                "caption": workspace.get("imaging_preview", {}).get("caption", ""),
                "image_url": workspace.get("imaging_preview", {}).get("image_url"),
            },
            "report_summary": report.get("summary", analysis_plan.handoff_summary),
            "report_sections": report.get("sections", []),
        }

    def _build_review_dashboard_payload(
        self,
        *,
        record: StudyRecord,
        report_text: str,
    ) -> dict[str, Any]:
        quality = evaluate_report_quality(report_text, compliance_profile="radiology")
        finding_groups = []
        if quality.deidentification.findings:
            finding_groups.append(
                {
                    "label": "Privacy",
                    "status": quality.deidentification.status,
                    "items": [
                        {
                            "label": item.label,
                            "severity": item.severity,
                            "count": item.count,
                            "recommendation": item.recommendation,
                        }
                        for item in quality.deidentification.findings[:4]
                    ],
                }
            )
        terminology_items = [*quality.terminology.do_not_use[:3], *quality.terminology.ambiguous[:3]]
        if terminology_items:
            finding_groups.append(
                {
                    "label": "Terminology",
                    "status": quality.terminology.status,
                    "items": [
                        {
                            "label": item.label,
                            "severity": item.severity,
                            "count": item.count,
                            "recommendation": item.recommendation,
                        }
                        for item in terminology_items
                    ],
                }
            )
        if quality.compliance.missing:
            finding_groups.append(
                {
                    "label": "Completeness",
                    "status": "needs_completion",
                    "items": [
                        {
                            "label": item.label,
                            "severity": "medium",
                            "count": 1,
                            "recommendation": item.recommendation,
                        }
                        for item in quality.compliance.missing[:4]
                    ],
                }
            )
        revision_suggestions = [
            item["recommendation"]
            for group in finding_groups
            for item in group["items"]
            if item.get("recommendation")
        ][:6]
        if not revision_suggestions:
            revision_suggestions.append("The current report draft is ready for review with no major language or completeness issues detected.")
        return {
            "dashboard_profile": "report_review",
            "summary": "Review dashboard compares report sections against tool evidence and highlights omissions, language risks, and revision opportunities.",
            "recommended_tools": [
                "report_section_parser",
                "finding_impression_consistency_checker",
                "report_revision_synthesizer",
            ],
            "status": quality.status,
            "finding_groups": finding_groups,
            "revision_suggestions": revision_suggestions,
            "source_report_sections": record.report_sections,
        }

    @staticmethod
    def _key_findings(volumetrics_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not volumetrics_payload:
            return []
        region_lookup = {
            region["name"]: region
            for region in (
                volumetrics_payload["volumetrics"].get("interpreted_regions")
                or volumetrics_payload["volumetrics"].get("regions", [])
            )
        }
        findings: list[dict[str, Any]] = []
        for name in DEFAULT_REGION_ORDER:
            region = region_lookup.get(name)
            if not region:
                continue
            z_score = region.get("z_score")
            if z_score is None:
                continue
            findings.append(
                {
                    "name": region["name"],
                    "display_name": region["display_name"],
                    "z_score": z_score,
                    "percentile": region["percentile"],
                    "volume_mm3": region["volume_mm3"],
                    "direction": region["direction"],
                    "interpretation": region["interpretation"],
                }
            )
        findings.sort(key=lambda item: abs(float(item["z_score"])), reverse=True)
        return findings[:8]

    @staticmethod
    def _series_meta(
        *,
        name: str,
        display_name: str | None = None,
        unit: str = "mm3",
        series_type: str,
        priority: int = 0,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "display_name": display_name or _display_name_from_series(name),
            "unit": unit,
            "series_type": series_type,
            "priority": priority,
        }

    def _default_structural_series(self, available_names: list[str]) -> list[str]:
        defaults = [name for name in STRUCTURAL_SERIES_PRIORITY if name in available_names][:4]
        return defaults or available_names[: min(4, len(available_names))]

    @staticmethod
    def _merged_structural_regions(volumetrics_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not volumetrics_payload:
            return []
        volumetrics = volumetrics_payload.get("volumetrics") or {}
        regions = [dict(region) for region in volumetrics.get("regions", []) if isinstance(region, dict)]
        interpreted_lookup = {
            str(region.get("name")): dict(region)
            for region in volumetrics.get("interpreted_regions", [])
            if isinstance(region, dict) and region.get("name")
        }
        merged_regions: list[dict[str, Any]] = []
        for region in regions:
            interpreted = interpreted_lookup.get(str(region.get("name")))
            if interpreted:
                merged_regions.append({**region, **interpreted})
            else:
                merged_regions.append(region)
        for name, interpreted in interpreted_lookup.items():
            if not any(str(region.get("name")) == name for region in merged_regions):
                merged_regions.append(interpreted)
        return merged_regions

    def _structural_series_registry(self, volumetrics_payload: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[str]]:
        if not volumetrics_payload:
            return [], []
        regions = self._merged_structural_regions(volumetrics_payload)
        available_names = [str(region.get("name", "")) for region in regions if region.get("name")]
        available_series = [
            self._series_meta(
                name=str(region.get("name")),
                display_name=str(region.get("display_name") or _display_name_from_series(str(region.get("name")))),
                unit="mm3",
                series_type="anatomical_region",
                priority=STRUCTURAL_SERIES_PRIORITY.index(str(region.get("name")))
                if str(region.get("name")) in STRUCTURAL_SERIES_PRIORITY
                else 100,
            )
            for region in regions
            if region.get("name")
        ]
        available_series.sort(key=lambda item: (item["priority"], item["display_name"]))
        return available_series, self._default_structural_series(available_names)

    def _structural_volumetrics_response(self, volumetrics_payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not volumetrics_payload:
            return None
        available_series, default_series = self._structural_series_registry(volumetrics_payload)
        payload = dict(volumetrics_payload["volumetrics"])
        payload.update(self._segmentation_metadata(volumetrics_payload.get("segmentation"), volumetrics_payload.get("volumetrics")))
        payload["regions"] = self._merged_structural_regions(volumetrics_payload)
        payload["series_type"] = "anatomical_region"
        payload["kind"] = "anatomical_region"
        payload["available_series"] = available_series
        payload["default_series"] = default_series
        return payload

    @staticmethod
    def _segmentation_metadata(*sources: dict[str, Any] | None) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in (
                "label_source",
                "label_mapping_path",
                "label_mapping_label_count",
                "label_schema_path",
                "label_schema_version",
            ):
                value = source.get(key)
                if value not in (None, ""):
                    metadata[key] = value
        return metadata

    def _structural_label_payload(
        self,
        *,
        volumetrics: dict[str, Any] | None,
        segmentation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "segmentation_regions": self._normalized_segmentation_regions(volumetrics, segmentation),
            **self._segmentation_metadata(volumetrics, segmentation),
        }

    @staticmethod
    def _normalized_segmentation_regions(
        volumetrics: dict[str, Any] | None,
        segmentation: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        for source in (volumetrics, segmentation):
            if not isinstance(source, dict):
                continue
            regions = source.get("regions")
            if isinstance(regions, list):
                return [dict(region) for region in regions]
        return None

    @staticmethod
    def _is_local_tunnel_service_url(service_url: str | None) -> bool:
        parsed = urlparse((service_url or "").strip())
        return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == 18000

    def _segmentation_tunnel_diagnostics(self) -> dict[str, Any] | None:
        script_path = REPO_ROOT / "scripts" / "segmentation_tunnel.sh"
        if not script_path.exists():
            return None
        try:
            result = subprocess.run(
                [str(script_path), "status"],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=12,
            )
        except Exception as exc:
            return {
                "ok": False,
                "message": str(exc),
            }

        combined = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip()).strip()
        return {
            "ok": result.returncode == 0,
            "message": combined or None,
        }

    def structural_segmentation_service_status(self) -> dict[str, Any]:
        service_url = (self._structural_segmenter.service_url or "").strip() or None
        try:
            health = self._structural_segmenter.check_health()
            model_info = self._structural_segmenter.get_model_info()
            return {
                "ok": bool(health.get("ok", True)),
                "service_ready": True,
                "status": "ready",
                "service_url": service_url,
                "health": health,
                "model": {
                    "model_id": model_info.get("model_id"),
                    "label_schema_path": model_info.get("label_schema_path"),
                    "label_schema_version": model_info.get("label_schema_version"),
                    "label_count": model_info.get("label_count"),
                    "input_modalities": model_info.get("input_modalities"),
                    "requires_skullstripped": model_info.get("requires_skullstripped"),
                },
            }
        except Exception as exc:
            message = str(exc)
            lowered = message.lower()
            status = "service_unavailable"
            tunnel = None
            if "not configured" in lowered:
                message = "Segmentation tool service is not configured."
                status = "not_configured"
            elif self._is_local_tunnel_service_url(service_url):
                tunnel = self._segmentation_tunnel_diagnostics()
                if tunnel and not tunnel.get("ok"):
                    message = "Segmentation tunnel is not established. Start the local tunnel to reach the remote nnUNet service."
                    status = "tunnel_down"
                else:
                    message = "Segmentation tunnel is connected, but the remote segmentation service is not healthy."
                    status = "remote_unhealthy"
            elif "connection refused" in lowered or "connect" in lowered or "timed out" in lowered:
                message = "Segmentation tool service is unavailable."
            return {
                "ok": False,
                "service_ready": False,
                "status": status,
                "service_url": service_url,
                "error": message,
                "health": None,
                "model": None,
                "tunnel": tunnel,
            }

    def _run_structural_segmentation(
        self,
        *,
        nifti_path: str,
        age: int | None,
        sex: str | None,
        indication: str,
        patient_id: str | None,
        study_id: str | None,
        case_id: str | None,
    ) -> dict[str, Any]:
        segmenter_result = self._structural_segmenter.run(
            input_nifti_path=nifti_path,
            sequence_hint="T1w",
        )
        label_schema_path = segmenter_result.get("label_schema_path")
        output_seg_path = str(segmenter_result.get("output_seg_path") or "")
        if not label_schema_path or not output_seg_path:
            raise ValueError("Structural segmentation service did not return a label schema and output segmentation path.")
        segmentation_result = self._structural_segmentation_adapter.run(
            seg_nifti_path=output_seg_path,
            label_schema_path=str(label_schema_path),
            label_source="remote_schema",
        )
        volumetrics_result = self._volumetrics_tool.run(
            segmentation_result=segmentation_result,
            patient_age=age or 65,
            patient_sex=(sex or "M").upper()[:1] if sex else "M",
        )
        return {
            "segmentation_service": segmenter_result,
            "segmentation_result": segmentation_result,
            "volumetrics": volumetrics_result,
            "seg_path": output_seg_path,
            "label_source": segmentation_result.get("label_source"),
            "label_mapping_path": segmentation_result.get("label_mapping_path"),
            "label_mapping_label_count": segmentation_result.get("label_mapping_label_count"),
            "label_schema_path": str(label_schema_path),
            "label_schema_version": segmentation_result.get("label_schema_version"),
            "preprocessing_profile": "lia_basic_qc",
            "segmentation_backend": "structural_segmenter",
            "patient_id": patient_id,
            "study_id": study_id,
            "case_id": case_id,
            "indication": indication,
        }

    def regenerate_structural_demo_segmentation(
        self,
        *,
        patient_id: str,
        study_id: str,
        overwrite: bool = True,
        device: str = "auto",
        engine: str = "auto",
    ) -> dict[str, Any]:
        record = self._record_for_study(patient_id, study_id)
        generated = self._generated_structural_seg_paths(
            patient_id=patient_id,
            study_id=study_id,
            image_path=record.analysis_image_path,
        )
        generated["dir"].mkdir(parents=True, exist_ok=True)

        if (
            not overwrite
            and generated["seg_path"].exists()
            and generated["label_schema_path"].exists()
        ):
            updated = replace(
                record,
                seg_path=generated["seg_path"],
                seg_label_source="remote_schema",
                seg_label_mapping_path=generated["label_schema_path"],
                seg_label_schema_path=generated["label_schema_path"],
            )
            self._replace_record(record, updated)
            self._invalidate_structural_caches(
                patient_id=patient_id,
                study_id=study_id,
                case_id=record.case_id,
            )
            return {
                "patient_id": patient_id,
                "study_id": study_id,
                "case_id": record.case_id,
                "status": "skipped",
                "image_path": str(record.analysis_image_path),
                "seg_path": str(generated["seg_path"]),
                "label_schema_path": str(generated["label_schema_path"]),
            }

        segmentation_service = self._structural_segmenter.run(
            input_nifti_path=str(record.analysis_image_path),
            output_seg_path=str(generated["seg_path"]),
            sequence_hint="T1w",
            device=device,
            engine=engine,
            overwrite=overwrite,
        )
        output_seg_path = Path(str(segmentation_service.get("output_seg_path") or generated["seg_path"])).expanduser().resolve()
        label_schema_path = Path(str(segmentation_service.get("label_schema_path") or generated["label_schema_path"])).expanduser().resolve()

        if output_seg_path != generated["seg_path"]:
            shutil.copy2(output_seg_path, generated["seg_path"])
        if label_schema_path != generated["label_schema_path"]:
            shutil.copy2(label_schema_path, generated["label_schema_path"])

        metadata = {
            "patient_id": patient_id,
            "study_id": study_id,
            "case_id": record.case_id,
            "input_image_path": str(record.analysis_image_path),
            "generated_seg_path": str(generated["seg_path"]),
            "label_schema_path": str(generated["label_schema_path"]),
            "label_source": "remote_schema",
            "segmentation_backend": "structural_segmenter",
            "preprocessing_profile": "lia_basic_qc",
            "service_url": segmentation_service.get("service_url"),
            "remote_staging": segmentation_service.get("remote_staging"),
            "model_info": segmentation_service.get("model_info"),
            "prediction": segmentation_service.get("prediction"),
        }
        generated["metadata_path"].write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        updated = replace(
            record,
            seg_path=generated["seg_path"],
            seg_label_source="remote_schema",
            seg_label_mapping_path=generated["label_schema_path"],
            seg_label_schema_path=generated["label_schema_path"],
        )
        self._replace_record(record, updated)
        self._invalidate_structural_caches(
            patient_id=patient_id,
            study_id=study_id,
            case_id=record.case_id,
        )

        return {
            "patient_id": patient_id,
            "study_id": study_id,
            "case_id": record.case_id,
            "status": "generated",
            "image_path": str(record.analysis_image_path),
            "seg_path": str(generated["seg_path"]),
            "label_schema_path": str(generated["label_schema_path"]),
            "metadata_path": str(generated["metadata_path"]),
        }

    def _structural_csv_export_path(self, session_id: str) -> Path:
        export_dir = self._asset_root / "sessions" / session_id
        export_dir.mkdir(parents=True, exist_ok=True)
        return export_dir / "structural-regions.csv"

    def _structural_study_csv_export_path(self, patient_id: str, study_id: str) -> Path:
        export_dir = self._asset_root / "studies" / _safe_case_slug(patient_id) / _safe_case_slug(study_id)
        export_dir.mkdir(parents=True, exist_ok=True)
        return export_dir / "structural-regions.csv"

    def _response_series_registry(self, case: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        timeline = case.get("timeline") or []
        has_enhancing = any(point.get("enhancing_volume_ml") is not None for point in timeline)
        available_series = [
            self._series_meta(
                name="total_lesion_volume_mm3",
                display_name="Total lesion volume",
                unit="mm3",
                series_type="lesion_burden",
                priority=0,
            ),
            self._series_meta(
                name="lesion_count",
                display_name="Lesion count",
                unit="count",
                series_type="lesion_burden",
                priority=1,
            ),
        ]
        if has_enhancing:
            available_series.append(
                self._series_meta(
                    name="enhancing_burden_mm3",
                    display_name="Enhancing burden",
                    unit="mm3",
                    series_type="lesion_burden",
                    priority=2,
                )
            )
        default_series = [
            meta["name"]
            for meta in available_series
            if meta["name"] in {"total_lesion_volume_mm3", "enhancing_burden_mm3"}
        ]
        if not default_series:
            default_series = [available_series[0]["name"]]
        return available_series, default_series

    def _response_volumetrics(self, case: dict[str, Any], study_id: str | None = None) -> dict[str, Any]:
        point = self._response_study_point(case, study_id)
        analysis = case.get("analysis") or {}
        available_series, default_series = self._response_series_registry(case)
        lesion_count = analysis.get("lesion_count")
        try:
            lesion_count_value = int(float(lesion_count)) if lesion_count is not None else None
        except (TypeError, ValueError):
            lesion_count_value = None
        total_lesion_volume_mm3 = float(point.get("lesion_volume_ml", 0.0) or 0.0) * 1000.0
        enhancing_burden_ml = point.get("enhancing_volume_ml")
        enhancing_burden_mm3 = (
            float(enhancing_burden_ml) * 1000.0
            if enhancing_burden_ml is not None
            else None
        )
        delta_vs_baseline = point.get("percent_change_from_baseline")
        delta_vs_prior = point.get("percent_change_from_prior")
        response_category = "progressive" if analysis.get("accelerated_progression") else "stable_or_mixed"
        return {
            "series_type": "lesion_burden",
            "kind": "lesion_burden",
            "regions": [],
            "summary": str(case.get("report", {}).get("summary") or "Longitudinal lesion burden review is ready."),
            "total_brain_volume_mm3": None,
            "lesion_count": lesion_count_value,
            "total_lesion_volume_mm3": total_lesion_volume_mm3,
            "enhancing_burden_mm3": enhancing_burden_mm3,
            "delta_vs_baseline": delta_vs_baseline,
            "delta_vs_prior": delta_vs_prior,
            "confidence_or_coverage_note": (
                "Derived from the current curated response case using local lesion masks and longitudinal follow-up measurements."
            ),
            "response_category": response_category,
            "available_series": available_series,
            "default_series": default_series,
            "active_study_id": str(point.get("study_id", "")),
            "baseline_study_id": str((case.get("timeline") or [{}])[0].get("study_id", "")),
            "prior_study_id": str((case.get("timeline") or [{}])[-2].get("study_id", ""))
            if len(case.get("timeline") or []) > 1
            else None,
        }

    def get_examples(self) -> list[dict[str, Any]]:
        if self._examples_cache is not None:
            return self._examples_cache

        examples: list[StudyRecord] = []
        for patient_id, studies in sorted(self._records_by_patient.items()):
            if studies:
                examples.extend(reversed(studies))

        payloads: list[dict[str, Any]] = []
        for record in examples:
            intake_context, capability_profile, analysis_plan = self._plan_for_record(record)
            default_mode = "full_agent" if record.seg_path else "vanilla"
            viewer_assets = self._materialize_viewer_assets(
                image_path=record.analysis_image_path,
                seg_path=record.seg_path,
                asset_slug=_safe_case_slug(record.patient_id, record.study_id),
            )
            planning_result = build_planning_result(
                intake_context,
                capability_profile,
                analysis_plan,
                requested_mode=default_mode,
                executed_mode=default_mode,
                viewer_type=viewer_assets["viewer_type"],
            )
            memory_context, planner_defaults = self._planner_memory_bundle(
                workflow_family=analysis_plan.workflow_family,
                primary_goal=analysis_plan.primary_goal,
                patient_id=record.patient_id,
                study_id=record.study_id,
            )
            runtime_bundle = self._runtime_bundle(
                analysis_plan=analysis_plan,
                capability_profile=capability_profile,
            )
            payloads.append(
                {
                    "case_id": record.case_id,
                    "patient_id": record.patient_id,
                    "study_id": record.study_id,
                    "study_date": record.study_date,
                    "title": f"{self._patient_names[record.patient_id]} · {_study_label(record)}",
                    "description": record.indication,
                    "thumbnail_base64": self._build_thumbnail(record),
                    "age": record.age,
                    "sex": record.sex,
                    "default_mode": default_mode,
                    "supported_modes": [
                        mode
                        for mode in SUPPORTED_ANALYSIS_MODES
                        if mode == "vanilla" or record.seg_path is not None
                    ],
                    "analysis_plan": analysis_plan.to_dict(),
                    "capability_profile": capability_profile.to_dict(),
                    "analysis_plan_summary": planning_result.analysis_plan_summary.to_dict(),
                    "capability_profile_summary": planning_result.capability_profile_summary.to_dict(),
                    "planning_result": planning_result.to_dict(),
                    "viewer_assets": viewer_assets,
                    "report": {
                        "full_text": record.report_full_text,
                        "sections": record.report_sections,
                    },
                    "dashboard_payloads": self._dashboard_payloads(
                        record=record,
                        analysis_plan=analysis_plan,
                        planning_result=planning_result.to_dict(),
                        volumetrics_payload=self._compute_volumetrics(record),
                    ),
                    "workspace_contract": build_workspace_contract(
                        workflow_id="neuro_report",
                        workflow_family=analysis_plan.workflow_family,
                        analysis_track=analysis_plan.analysis_track,
                        dashboard_profile=analysis_plan.dashboard_profile,
                        workspace_url=f"/demo/analysis/neuro-report?patient_id={record.patient_id}&study_id={record.study_id}&mode={default_mode}",
                        module="neuro_report",
                        runtime_mode=analysis_plan.runtime_mode,
                        viewer_type=viewer_assets["viewer_type"],
                        can_autorun=planning_result.autorun,
                        planning_result=planning_result,
                        task_traces=runtime_bundle["task_summary"],
                        tool_policy=runtime_bundle["tool_policy"],
                        context_availability=runtime_bundle["mcp_snapshot"]["servers"],
                        memory_context=memory_context,
                        planner_defaults=planner_defaults,
                    ).to_dict(),
                    "case_type": "structural",
                }
            )
        for case in self._response_cases.values():
            point = self._response_latest_timeline_point(case)
            intake_context, capability_profile, analysis_plan, viewer_assets, planning_result = self._response_planning_bundle(case)
            patient = case.get("patient") or {}
            memory_context, planner_defaults = self._planner_memory_bundle(
                workflow_family=analysis_plan.workflow_family,
                primary_goal=analysis_plan.primary_goal,
                patient_id=str(patient.get("id", "")),
                study_id=str(point.get("study_id", "")),
            )
            runtime_bundle = self._runtime_bundle(
                analysis_plan=analysis_plan,
                capability_profile=capability_profile,
            )
            report_sections = self._response_report_sections(case)
            payloads.append(
                {
                    "case_id": case["id"],
                    "patient_id": str(patient.get("id", "")),
                    "study_id": str(point.get("study_id", "")),
                    "study_date": str(point.get("study_date", "")),
                    "title": f"{patient.get('display_name', patient.get('id', 'Response case'))} · {point.get('study_date', '')}",
                    "description": str(case.get("report", {}).get("summary") or patient.get("summary") or "Longitudinal lesion-response review"),
                    "thumbnail_base64": self._response_thumbnail(case),
                    "age": int(patient.get("age") or 0),
                    "sex": str(patient.get("sex") or "U")[:1].upper(),
                    "default_mode": "seg_overlay",
                    "supported_modes": ["vanilla", "seg_overlay"],
                    "analysis_plan": analysis_plan.to_dict(),
                    "capability_profile": capability_profile.to_dict(),
                    "analysis_plan_summary": planning_result["analysis_plan_summary"],
                    "capability_profile_summary": planning_result["capability_profile_summary"],
                    "planning_result": planning_result,
                    "viewer_assets": viewer_assets,
                    "report": {
                        "full_text": self._response_report_text(case),
                        "sections": report_sections,
                    },
                    "dashboard_payloads": self._response_dashboard_payloads(
                        case,
                        planning_result=planning_result,
                        study_id=str(point.get("study_id", "")),
                    ),
                    "workspace_contract": build_workspace_contract(
                        workflow_id="neuro_report",
                        workflow_family=analysis_plan.workflow_family,
                        analysis_track=analysis_plan.analysis_track,
                        dashboard_profile=analysis_plan.dashboard_profile,
                        workspace_url=f"/demo/analysis/neuro-report?case_id={case['id']}&goal={planning_result['primary_goal']}",
                        module="neuro_report",
                        runtime_mode=analysis_plan.runtime_mode,
                        viewer_type=viewer_assets["viewer_type"],
                        can_autorun=bool(planning_result.get("autorun")),
                        planning_result=build_planning_result(
                            intake_context,
                            capability_profile,
                            analysis_plan,
                            requested_mode="seg_overlay",
                            executed_mode="seg_overlay",
                            viewer_type=viewer_assets["viewer_type"],
                        ),
                        task_traces=runtime_bundle["task_summary"],
                        tool_policy=runtime_bundle["tool_policy"],
                        context_availability=runtime_bundle["mcp_snapshot"]["servers"],
                        memory_context=memory_context,
                        planner_defaults=planner_defaults,
                    ).to_dict(),
                    "case_type": "response",
                }
            )
        self._examples_cache = payloads
        save_user_memory(
            "default_demo_user",
            {
                "preferred_workflow_family": "neuro",
                "preferred_dashboard_profile": "volumetry",
                "autorun_examples": True,
                "output_style": "structured_radiology",
            },
        )
        save_workflow_memory(
            "neuro_report",
            "examples",
            {
                "case_ids": [item["case_id"] for item in payloads],
                "default_case_id": payloads[0]["case_id"] if payloads else None,
            },
        )
        save_reviewed_pattern_memory(
            "neuro",
            "structural_default_bundle",
            {
                "track": "structural",
                "dashboard_profile": "volumetry",
                "tool_bundle": ["slice_selector", "brain_segmentation", "volumetric_analysis", "vlm_report_generator"],
            },
        )
        save_reviewed_pattern_memory(
            "neuro",
            "response_default_bundle",
            {
                "track": "response",
                "dashboard_profile": "longitudinal_response",
                "tool_bundle": [
                    "lesion_segmentation_ingestion",
                    "lesion_volume_calculator",
                    "response_delta_calculator",
                    "longitudinal_response_synthesizer",
                ],
            },
        )
        save_reviewed_pattern_memory(
            "neuro",
            "review_default_bundle",
            {
                "track": "review",
                "dashboard_profile": "report_review",
                "tool_bundle": [
                    "report_section_parser",
                    "finding_impression_consistency_checker",
                    "report_revision_synthesizer",
                ],
                "review_lane_default_open": True,
            },
        )
        return self._examples_cache

    def get_preload_status(self) -> dict[str, Any]:
        structural_manifest = self.data_root / "metadata" / "longitudinal_manifest.csv"
        structural_ready = structural_manifest.exists() and bool(self._records_by_patient)
        response_ready = self._proteas_dataset is not None and bool(self._response_cases)
        example_count = (
            len(self._examples_cache)
            if self._examples_cache is not None
            else len(self._records_by_case_id) + len(self._response_cases)
        )
        warnings: list[str] = []
        if not structural_manifest.exists():
            warnings.append("structural preload unavailable")
        elif not self._records_by_patient:
            warnings.append("structural preload empty")
        if self._proteas_dataset is None:
            warnings.append("response preload unavailable")
        elif not self._response_cases:
            warnings.append("response preload empty")
        return {
            "structural_ready": structural_ready,
            "response_ready": response_ready,
            "structural_patient_count": len(self._records_by_patient),
            "response_case_count": len(self._response_cases),
            "example_count": example_count,
            "warnings": warnings,
        }

    def get_patients(self) -> dict[str, Any]:
        patients = []
        for patient_id, studies in sorted(self._records_by_patient.items()):
            latest = studies[-1]
            patients.append(
                {
                    "id": patient_id,
                    "name": self._patient_names[patient_id],
                    "age": latest.age,
                    "sex": latest.sex,
                    "study_count": len(studies),
                    "date_range": {
                        "start": studies[0].study_date,
                        "end": studies[-1].study_date,
                    },
                    "default_study_id": latest.study_id,
                    "diagnosis": latest.diagnosis,
                }
            )
        for case in self._response_cases.values():
            patient = case.get("patient") or {}
            timeline = case.get("timeline") or []
            latest_point = timeline[-1] if timeline else {}
            patient_id = str(patient.get("id", "")).strip()
            if not patient_id:
                continue
            patients.append(
                {
                    "id": patient_id,
                    "name": patient.get("display_name", patient_id),
                    "age": int(patient.get("age") or 0),
                    "sex": str(patient.get("sex") or "U")[:1].upper(),
                    "study_count": len(timeline),
                    "date_range": {
                        "start": str(timeline[0].get("study_date", "N/A")) if timeline else "N/A",
                        "end": str(latest_point.get("study_date", "N/A")) if latest_point else "N/A",
                    },
                    "default_study_id": str(latest_point.get("study_id", patient_id)),
                    "diagnosis": patient.get("diagnosis", "Brain metastasis follow-up"),
                }
            )
        return {
            "default_patient_id": patients[0]["id"] if patients else None,
            "patients": patients,
        }

    def get_patient_data(self, patient_id: str) -> dict[str, Any]:
        response_case = self._response_case(patient_id=patient_id)
        if response_case is not None:
            patient = response_case.get("patient") or {}
            timeline = response_case.get("timeline") or []
            studies = []
            highlights = []
            for point in timeline:
                studies.append(
                    {
                        "study_id": str(point.get("study_id", "")),
                        "study_date": str(point.get("study_date", "")),
                        "age_at_study": int(patient.get("age") or 0),
                        "thumbnail_base64": self._response_thumbnail(response_case, str(point.get("study_id", ""))),
                        "indication": patient.get("diagnosis", "Brain metastasis follow-up"),
                        "has_segmentation": True,
                        "supported_modes": ["vanilla", "seg_overlay"],
                    }
                )
                delta = point.get("percent_change_from_prior")
                if delta is not None:
                    highlights.append(
                        {
                            "study_id": str(point.get("study_id", "")),
                            "study_date": str(point.get("study_date", "")),
                            "display_name": "Lesion burden",
                            "z_score": float(delta) / 10.0,
                            "interpretation": f"Interval lesion-volume change {float(delta):+.1f}% versus prior.",
                        }
                    )
            latest = timeline[-1] if timeline else {}
            return {
                "patient": {
                    "id": patient_id,
                    "name": patient.get("display_name", patient_id),
                    "age": int(patient.get("age") or 0),
                    "sex": str(patient.get("sex") or "U")[:1].upper(),
                    "study_count": len(studies),
                    "diagnosis": patient.get("diagnosis", "Brain metastasis follow-up"),
                    "date_range": {
                        "start": str(timeline[0].get("study_date", "N/A")) if timeline else "N/A",
                        "end": str(latest.get("study_date", "N/A")) if latest else "N/A",
                    },
                },
                "default_study_id": str(latest.get("study_id", patient_id)),
                "studies": studies,
                "highlights": highlights[:10],
            }
        if patient_id not in self._records_by_patient:
            raise KeyError(patient_id)
        studies = self._records_by_patient[patient_id]
        latest = studies[-1]
        longitudinal = self.get_longitudinal_volumetrics(patient_id)
        return {
            "patient": {
                "id": patient_id,
                "name": self._patient_names[patient_id],
                "age": latest.age,
                "sex": latest.sex,
                "study_count": len(studies),
                "diagnosis": latest.diagnosis,
                "date_range": {
                    "start": studies[0].study_date,
                    "end": studies[-1].study_date,
                },
            },
            "default_study_id": latest.study_id,
            "studies": [
                {
                    "study_id": record.study_id,
                    "study_date": record.study_date,
                    "age_at_study": record.age,
                    "thumbnail_base64": self._build_thumbnail(record),
                    "indication": record.indication,
                    "has_segmentation": record.seg_path is not None,
                    "supported_modes": [
                        mode
                        for mode in SUPPORTED_ANALYSIS_MODES
                        if mode == "vanilla" or record.seg_path is not None
                    ],
                }
                for record in studies
            ],
            "highlights": longitudinal.get("highlights", []),
        }

    def get_study_detail(self, patient_id: str, study_id: str) -> dict[str, Any]:
        key = (patient_id, study_id)
        cached = self._study_detail_cache.get(key)
        if cached is not None:
            return cached

        response_case = self._response_case(patient_id=patient_id)
        if response_case is not None:
            response_volumetrics = self._response_volumetrics(response_case, study_id)
            intake_context, capability_profile, analysis_plan, viewer_assets, planning_result = self._response_planning_bundle(
                response_case,
                study_id=study_id,
            )
            memory_context, planner_defaults = self._planner_memory_bundle(
                workflow_family=analysis_plan.workflow_family,
                primary_goal=analysis_plan.primary_goal,
                patient_id=patient_id,
                study_id=study_id,
            )
            runtime_bundle = self._runtime_bundle(
                analysis_plan=analysis_plan,
                capability_profile=capability_profile,
            )
            raw_slices, overlay_slices = self._response_slices(response_case, study_id)
            detail = {
                "patient_id": patient_id,
                "study_id": study_id,
                "study_date": str(self._response_study_point(response_case, study_id).get("study_date", "N/A")),
                "age_at_study": int(response_case.get("patient", {}).get("age") or 0),
                "sex": str(response_case.get("patient", {}).get("sex") or "U")[:1].upper(),
                "indication": response_case.get("patient", {}).get("diagnosis", "Brain metastasis follow-up"),
                "image_name": Path(viewer_assets.get("image_asset_url") or "").name or "t1c.nii.gz",
                "segmentation_name": "tumor_mask",
                "thumbnail_base64": self._response_thumbnail(response_case, study_id),
                "viewer_assets": viewer_assets,
                "slices": overlay_slices or raw_slices,
                "raw_slices": raw_slices,
                "overlay_slices": overlay_slices,
                "report": {
                    "full_text": self._response_report_text(response_case),
                    "sections": self._response_report_sections(response_case),
                },
                "volumetrics": response_volumetrics,
                "segmentation_regions": self._normalized_segmentation_regions(response_volumetrics),
                "key_findings": [],
                "supported_modes": ["vanilla", "seg_overlay"],
                "capability_profile": capability_profile.to_dict(),
                "analysis_plan": analysis_plan.to_dict(),
                "analysis_plan_summary": planning_result["analysis_plan_summary"],
                "capability_profile_summary": planning_result["capability_profile_summary"],
                "planning_result": planning_result,
                "dashboard_payloads": self._response_dashboard_payloads(
                    response_case,
                    planning_result=planning_result,
                    study_id=study_id,
                ),
                "workspace_contract": build_workspace_contract(
                    workflow_id="neuro_report",
                    workflow_family=analysis_plan.workflow_family,
                    analysis_track=analysis_plan.analysis_track,
                    dashboard_profile=analysis_plan.dashboard_profile,
                    workspace_url=f"/demo/analysis/neuro-report?patient_id={patient_id}&study_id={study_id}&mode=seg_overlay&goal={planning_result['primary_goal']}",
                    module="neuro_report",
                    runtime_mode=analysis_plan.runtime_mode,
                    viewer_type=viewer_assets["viewer_type"],
                    can_autorun=bool(planning_result.get("autorun")),
                    planning_result=build_planning_result(
                        intake_context,
                        capability_profile,
                        analysis_plan,
                        requested_mode="seg_overlay",
                        executed_mode="seg_overlay",
                        viewer_type=viewer_assets["viewer_type"],
                    ),
                    task_traces=runtime_bundle["task_summary"],
                    tool_policy=runtime_bundle["tool_policy"],
                    context_availability=runtime_bundle["mcp_snapshot"]["servers"],
                    memory_context=memory_context,
                    planner_defaults=planner_defaults,
                ).to_dict(),
            }
            save_entity_memory("neuro_study", f"{patient_id}:{study_id}", detail)
            self._study_detail_cache[key] = detail
            return detail

        record = self._record_for_study(patient_id, study_id)
        intake_context, capability_profile, analysis_plan = self._plan_for_record(record)
        viewer_assets = self._materialize_viewer_assets(
            image_path=record.analysis_image_path,
            seg_path=record.seg_path,
            asset_slug=_safe_case_slug(record.patient_id, record.study_id),
        )
        planning_result = build_planning_result(
            intake_context,
            capability_profile,
            analysis_plan,
            requested_mode=analysis_plan.recommended_mode,
            executed_mode=analysis_plan.recommended_mode,
            viewer_type=viewer_assets["viewer_type"],
        )
        memory_context, planner_defaults = self._planner_memory_bundle(
            workflow_family=analysis_plan.workflow_family,
            primary_goal=analysis_plan.primary_goal,
            patient_id=record.patient_id,
            study_id=record.study_id,
        )
        runtime_bundle = self._runtime_bundle(
            analysis_plan=analysis_plan,
            capability_profile=capability_profile,
        )
        slice_manifest = self._structural_slice_manifest(
            image_path=record.analysis_image_path,
            seg_path=record.seg_path,
        )

        volumetrics_payload = self._compute_volumetrics(record)
        normalized_volumetrics = self._structural_volumetrics_response(volumetrics_payload)
        segmentation_payload = self._structural_label_payload(
            volumetrics=normalized_volumetrics,
            segmentation=volumetrics_payload.get("segmentation") if volumetrics_payload else None,
        )
        if normalized_volumetrics:
            normalized_volumetrics.update(
                {key: value for key, value in segmentation_payload.items() if key != "segmentation_regions" and value not in (None, "")}
            )
            export_path = self._structural_study_csv_export_path(record.patient_id, record.study_id)
            csv_export_path = self._structural_segmentation_adapter.export_regions_csv(
                destination_path=export_path,
                regions=normalized_volumetrics.get("regions", []),
                case_id=record.case_id,
                patient_id=record.patient_id,
                study_id=record.study_id,
            )
            normalized_volumetrics["csv_export_path"] = str(csv_export_path)
            normalized_volumetrics["csv_export_url"] = (
                f"/api/demo/neuro-report/patients/{record.patient_id}/studies/{record.study_id}/structural-regions.csv"
            )
        detail = {
            "patient_id": record.patient_id,
            "study_id": record.study_id,
            "study_date": record.study_date,
            "age_at_study": record.age,
            "sex": record.sex,
            "indication": record.indication,
            "image_name": record.analysis_image_path.name,
            "segmentation_name": record.seg_path.name if record.seg_path else None,
            "thumbnail_base64": self._build_thumbnail(record),
            "viewer_assets": viewer_assets,
            "slices": None,
            "raw_slices": None,
            "overlay_slices": None,
            "slice_manifest": slice_manifest,
            "slice_source": "on_demand",
            "report": {
                "full_text": record.report_full_text,
                "sections": record.report_sections,
            },
            "volumetrics": normalized_volumetrics,
            **segmentation_payload,
            "key_findings": self._key_findings(volumetrics_payload),
            "supported_modes": [
                mode
                for mode in SUPPORTED_ANALYSIS_MODES
                if mode == "vanilla" or record.seg_path is not None
            ],
            "capability_profile": capability_profile.to_dict(),
            "analysis_plan": analysis_plan.to_dict(),
            "analysis_plan_summary": planning_result.analysis_plan_summary.to_dict(),
            "capability_profile_summary": planning_result.capability_profile_summary.to_dict(),
            "planning_result": planning_result.to_dict(),
            "dashboard_payloads": self._dashboard_payloads(
                record=record,
                analysis_plan=analysis_plan,
                planning_result=planning_result.to_dict(),
                volumetrics_payload=volumetrics_payload,
            ),
            "workspace_contract": build_workspace_contract(
                workflow_id="neuro_report",
                workflow_family=analysis_plan.workflow_family,
                analysis_track=analysis_plan.analysis_track,
                dashboard_profile=analysis_plan.dashboard_profile,
                workspace_url=f"/demo/analysis/neuro-report?patient_id={record.patient_id}&study_id={record.study_id}&mode={analysis_plan.recommended_mode or 'vanilla'}",
                module="neuro_report",
                runtime_mode=analysis_plan.runtime_mode,
                viewer_type=viewer_assets["viewer_type"],
                can_autorun=planning_result.autorun,
                planning_result=planning_result,
                task_traces=runtime_bundle["task_summary"],
                tool_policy=runtime_bundle["tool_policy"],
                context_availability=runtime_bundle["mcp_snapshot"]["servers"],
                memory_context=memory_context,
                planner_defaults=planner_defaults,
            ).to_dict(),
        }
        save_entity_memory("neuro_study", record.case_id, detail)
        self._study_detail_cache[key] = detail
        return detail

    def get_longitudinal_volumetrics(self, patient_id: str, region_names: list[str] | None = None) -> dict[str, Any]:
        cached = self._longitudinal_cache.get(patient_id)
        if cached is not None and not region_names:
            return cached
        response_case = self._response_case(patient_id=patient_id)
        if response_case is not None:
            available_series, default_series = self._response_series_registry(response_case)
            requested_series = region_names or default_series
            series = [
                {
                    "study_id": point["study_id"],
                    "study_date": point["study_date"],
                    "age_at_study": int(response_case.get("patient", {}).get("age") or 0),
                    "total_lesion_volume_mm3": (point.get("lesion_volume_ml") or 0.0) * 1000.0,
                    "total_lesion_volume_mm3_delta": point.get("percent_change_from_baseline"),
                    "lesion_count": int(float(response_case.get("analysis", {}).get("lesion_count") or 0) or 0),
                    "lesion_count_delta": point.get("percent_change_from_prior"),
                    "enhancing_burden_mm3": (
                        float(point.get("enhancing_volume_ml") or 0.0) * 1000.0
                        if point.get("enhancing_volume_ml") is not None
                        else None
                    ),
                    "enhancing_burden_mm3_delta": point.get("percent_change_from_baseline"),
                }
                for point in response_case.get("timeline", [])
            ]
            highlights = [
                {
                    "study_id": point["study_id"],
                    "study_date": point["study_date"],
                    "display_name": "Lesion burden",
                    "z_score": float(point.get("percent_change_from_prior") or 0.0) / 10.0,
                    "interpretation": f"Lesion burden changed {float(point.get('percent_change_from_prior') or 0.0):+.1f}% versus prior.",
                }
                for point in response_case.get("timeline", [])
                if point.get("percent_change_from_prior") is not None
            ]
            payload = {
                "patient_id": patient_id,
                "patient_name": response_case.get("patient", {}).get("display_name", patient_id),
                "region_names": requested_series,
                "available_series": available_series,
                "default_series": default_series,
                "series": series,
                "highlights": highlights[:10],
            }
            if not region_names:
                self._longitudinal_cache[patient_id] = payload
            return payload
        if patient_id not in self._records_by_patient:
            raise KeyError(patient_id)

        studies = self._records_by_patient[patient_id]
        reference_payload = None
        for record in studies:
            reference_payload = self._compute_volumetrics(record)
            if reference_payload:
                break
        available_series, default_series = self._structural_series_registry(reference_payload)
        selected_region_names = region_names or default_series or DEFAULT_REGION_ORDER[:4]
        series = []
        highlights = []

        for record in studies:
            volumetrics_payload = self._compute_volumetrics(record)
            regions_by_name = {
                str(region["name"]): region
                for region in self._merged_structural_regions(volumetrics_payload)
                if region.get("name")
            }
            data_point = {
                "study_id": record.study_id,
                "study_date": record.study_date,
                "age_at_study": record.age,
            }
            for region_name in selected_region_names:
                region = regions_by_name.get(region_name)
                data_point[f"{region_name}_volume_mm3"] = region.get("volume_mm3") if region else None
                data_point[f"{region_name}_z_score"] = region.get("z_score") if region else None
            series.append(data_point)

            for region in self._key_findings(volumetrics_payload):
                z_score = region.get("z_score")
                if z_score is not None and abs(float(z_score)) >= 1.0:
                    highlights.append(
                        {
                            "study_id": record.study_id,
                            "study_date": record.study_date,
                            "display_name": region["display_name"],
                            "z_score": z_score,
                            "interpretation": region["interpretation"],
                        }
                    )

        payload = {
            "patient_id": patient_id,
            "patient_name": self._patient_names[patient_id],
            "region_names": selected_region_names,
            "available_series": available_series,
            "default_series": default_series,
            "series": series,
            "highlights": highlights[:10],
        }
        if not region_names:
            self._longitudinal_cache[patient_id] = payload
        return payload

    def get_heatmap_data(self, patient_id: str, region_names: list[str] | None = None) -> dict[str, Any]:
        requested_region_names = list(region_names) if region_names else None
        cached = self._heatmap_cache.get(patient_id)
        if cached is not None and not requested_region_names:
            return cached
        response_case = self._response_case(patient_id=patient_id)
        if response_case is not None:
            available_series, default_series = self._response_series_registry(response_case)
            requested_region_names = requested_region_names or default_series
            requested_set = set(requested_region_names)
            payload = {
                "patient_id": patient_id,
                "region_names": requested_region_names,
                "available_series": available_series,
                "default_series": default_series,
                "dates": [str(point.get("study_date", "")) for point in response_case.get("timeline", [])],
                "matrix": {},
            }
            if "total_lesion_volume_mm3" in requested_set:
                payload["matrix"]["total_lesion_volume_mm3"] = [
                    {
                        "z_score": point.get("percent_change_from_baseline"),
                        "volume_mm3": (point.get("lesion_volume_ml") or 0.0) * 1000.0,
                    }
                    for point in response_case.get("timeline", [])
                ]
            if "lesion_count" in requested_set:
                payload["matrix"]["lesion_count"] = [
                    {
                        "z_score": point.get("percent_change_from_prior"),
                        "volume_mm3": float(response_case.get("analysis", {}).get("lesion_count") or 0.0),
                    }
                    for point in response_case.get("timeline", [])
                ]
            if "enhancing_burden_mm3" in requested_set and any(meta["name"] == "enhancing_burden_mm3" for meta in available_series):
                payload["matrix"]["enhancing_burden_mm3"] = [
                    {
                        "z_score": point.get("percent_change_from_baseline"),
                        "volume_mm3": float(point.get("enhancing_volume_ml") or 0.0) * 1000.0
                        if point.get("enhancing_volume_ml") is not None
                        else None,
                    }
                    for point in response_case.get("timeline", [])
                ]
            if region_names is None:
                self._heatmap_cache[patient_id] = payload
            return payload
        longitudinal = self.get_longitudinal_volumetrics(patient_id, requested_region_names)
        region_names = list(longitudinal.get("region_names") or [])
        matrix: dict[str, list[dict[str, Any]]] = {name: [] for name in region_names}
        dates: list[str] = []
        for point in longitudinal["series"]:
            dates.append(point["study_date"])
            for region_name in region_names:
                matrix[region_name].append(
                    {
                        "z_score": point.get(f"{region_name}_z_score"),
                        "volume_mm3": point.get(f"{region_name}_volume_mm3"),
                    }
                )
        payload = {
            "patient_id": patient_id,
            "region_names": region_names,
            "available_series": longitudinal.get("available_series", []),
            "default_series": longitudinal.get("default_series", []),
            "dates": dates,
            "matrix": matrix,
        }
        if region_names is None:
            self._heatmap_cache[patient_id] = payload
        return payload

    async def analyze(
        self,
        *,
        nifti_path: str,
        seg_path: str | None,
        age: int | None,
        sex: str | None,
        indication: str,
        mode: str,
        patient_id: str | None = None,
        study_id: str | None = None,
        case_id: str | None = None,
        source: str = "example",
        request_text: str = "",
        auto_segment: bool = False,
        segmentation_backend: str | None = None,
    ) -> dict[str, Any]:
        response_case = self._response_case(case_id=case_id, patient_id=patient_id) if source == "example" else None
        if response_case is not None:
            return await self._analyze_response_case(
                case=response_case,
                patient_id=patient_id or str(response_case.get("patient", {}).get("id", "")),
                study_id=study_id,
                case_id=case_id or str(response_case.get("id", "")),
                mode=mode,
                request_text=request_text,
            )
        structural_generated: dict[str, Any] | None = None
        if source in {"upload", "knowledge", "example"} and seg_path is None and auto_segment and segmentation_backend == "structural_segmenter":
            service_status = self.structural_segmentation_service_status()
            if service_status.get("service_ready"):
                structural_generated = self._run_structural_segmentation(
                    nifti_path=nifti_path,
                    age=age,
                    sex=sex,
                    indication=indication,
                    patient_id=patient_id,
                    study_id=study_id,
                    case_id=case_id,
                )
                seg_path = structural_generated["seg_path"]

        example_record: StudyRecord | None = None
        existing_structural_payload: dict[str, Any] | None = None
        if source == "example" and patient_id and study_id:
            example_record = self._record_for_study(patient_id, study_id)

        if source == "example" and patient_id and study_id and structural_generated is None:
            record = example_record
            assert record is not None
            intake_context, capability_profile, analysis_plan = self._plan_for_record(record, request_text=request_text)
        elif source == "example" and patient_id and study_id:
            record = example_record
            assert record is not None
            has_prior_study = len(self._records_by_patient.get(record.patient_id, [])) > 1
            intake_context = normalize_case_intake(
                request_text=request_text,
                source_kind="curated_case",
                patient_id=record.patient_id,
                study_id=record.study_id,
                case_id=record.case_id,
                nifti_path=str(record.analysis_image_path),
                seg_path=seg_path,
                age=record.age,
                sex=record.sex,
                indication=record.indication,
                available_sequences=self._infer_sequences(record.analysis_image_path),
                has_prior_study=has_prior_study,
                has_prior_report=has_prior_study,
                has_ehr_context=True,
                has_report_context=True,
            )
            capability_profile = build_capability_profile(intake_context)
            analysis_plan = build_analysis_plan(intake_context, capability_profile)
        else:
            intake_context, capability_profile, analysis_plan = self._plan_for_upload(
                nifti_path=nifti_path,
                seg_path=seg_path,
                age=age,
                sex=sex,
                indication=indication,
                request_text=request_text,
            )
        if not analysis_plan.can_execute:
            raise ValueError(analysis_plan.handoff_summary)

        chosen_mode = mode if mode in SUPPORTED_ANALYSIS_MODES else (analysis_plan.recommended_mode or "vanilla")
        if chosen_mode in {"seg_overlay", "tool_output", "full_agent"} and not capability_profile.has_segmentation:
            chosen_mode = "vanilla"
        if chosen_mode in {"tool_output", "full_agent"} and not capability_profile.has_demographics:
            chosen_mode = "seg_overlay" if capability_profile.has_segmentation else "vanilla"
        viewer_assets = self._materialize_viewer_assets(
            image_path=nifti_path,
            seg_path=seg_path,
            asset_slug=f"analysis-{uuid.uuid4().hex}",
        )
        planning_result = build_planning_result(
            intake_context,
            capability_profile,
            analysis_plan,
            requested_mode=mode,
            executed_mode=chosen_mode,
            viewer_type=viewer_assets["viewer_type"],
        )
        memory_context, planner_defaults = self._planner_memory_bundle(
            workflow_family=analysis_plan.workflow_family,
            primary_goal=analysis_plan.primary_goal,
            patient_id=patient_id,
            study_id=study_id,
        )
        runtime_bundle = self._runtime_bundle(
            analysis_plan=analysis_plan,
            capability_profile=capability_profile,
        )

        slice_manifest = self._structural_slice_manifest(
            image_path=nifti_path,
            seg_path=seg_path,
        )

        if structural_generated is None and example_record is not None and example_record.seg_path is not None:
            existing_structural_payload = self._compute_volumetrics(example_record)

        reasoning_result: ReasoningResult = await run_single_case(
            nifti_path=nifti_path,
            seg_path=seg_path,
            age=age,
            sex=sex,
            indication=indication,
            mode=chosen_mode,
            segmentation_result_override=(
                structural_generated["segmentation_result"]
                if structural_generated
                else (existing_structural_payload or {}).get("segmentation")
            ),
            volumetrics_result_override=(
                structural_generated["volumetrics"]
                if structural_generated
                else (existing_structural_payload or {}).get("volumetrics")
            ),
        )
        tool_outputs = reasoning_result.tool_outputs or {}
        structural_volumetrics_payload = (
            {"volumetrics": structural_generated["volumetrics"]}
            if structural_generated and structural_generated.get("volumetrics")
            else (
                existing_structural_payload
                if existing_structural_payload and existing_structural_payload.get("volumetrics")
                else (
                    {"volumetrics": tool_outputs.get("volumetrics", {})}
                    if tool_outputs.get("volumetrics")
                    else None
                )
            )
        )
        report_sections = self._report_to_sections(reasoning_result.final_report)
        dashboard_payloads = self._dashboard_payloads(
            record=example_record if example_record is not None else StudyRecord(
                patient_id=patient_id or "uploaded",
                study_id=study_id or "uploaded",
                study_date="N/A",
                batch="upload",
                age=age or 0,
                sex=sex or "U",
                image_dir=Path(nifti_path).parent,
                seg_dir=Path(seg_path).parent if seg_path else Path(nifti_path).parent,
                report_path=Path(nifti_path),
                metadata_path=Path(nifti_path),
                report_full_text=reasoning_result.final_report,
                report_sections=report_sections,
                indication=indication,
                diagnosis=indication or "Uploaded neuro MRI",
                analysis_image_path=Path(nifti_path),
                seg_path=Path(seg_path) if seg_path else None,
            ),
            analysis_plan=analysis_plan,
            planning_result=planning_result.to_dict(),
            volumetrics_payload=structural_volumetrics_payload,
        )
        normalized_volumetrics = self._structural_volumetrics_response(structural_volumetrics_payload)
        segmentation_payload = self._structural_label_payload(
            volumetrics=normalized_volumetrics,
            segmentation=structural_generated.get("segmentation_result") if structural_generated else None,
        )
        session_id = uuid.uuid4().hex
        csv_export_path = None
        csv_export_url = None
        if structural_generated and normalized_volumetrics:
            export_path = self._structural_csv_export_path(session_id)
            csv_export_path = self._structural_segmentation_adapter.export_regions_csv(
                destination_path=export_path,
                regions=normalized_volumetrics.get("regions", []),
                case_id=case_id,
                patient_id=patient_id,
                study_id=study_id,
            )
            csv_export_url = f"/api/demo/neuro-report/sessions/{session_id}/structural-regions.csv"
            normalized_volumetrics["csv_export_path"] = csv_export_path
            normalized_volumetrics["csv_export_url"] = csv_export_url
            normalized_volumetrics["label_schema_path"] = structural_generated.get("label_schema_path")
            normalized_volumetrics["label_source"] = structural_generated.get("label_source")
            normalized_volumetrics["label_mapping_path"] = structural_generated.get("label_mapping_path")
            normalized_volumetrics["label_mapping_label_count"] = structural_generated.get("label_mapping_label_count")
            normalized_volumetrics["label_schema_version"] = structural_generated.get("label_schema_version")
            normalized_volumetrics["segmentation_backend"] = "structural_segmenter"
            normalized_volumetrics["preprocessing_profile"] = "lia_basic_qc"
        session_payload = {
                "patient_id": patient_id,
                "study_id": study_id,
                "case_id": case_id,
                "mode": chosen_mode,
                "requested_mode": mode,
                "source": source,
                "age": age,
                "sex": sex,
                "indication": indication,
                "image_name": Path(nifti_path).name,
                "segmentation_name": Path(seg_path).name if seg_path else None,
                "report": reasoning_result.final_report,
                "report_sections": report_sections,
                "tool_outputs": reasoning_result.tool_outputs,
                "volumetrics": normalized_volumetrics,
                **segmentation_payload,
                "analysis_plan": analysis_plan.to_dict(),
                "analysis_plan_summary": planning_result.analysis_plan_summary.to_dict(),
                "capability_profile": capability_profile.to_dict(),
                "capability_profile_summary": planning_result.capability_profile_summary.to_dict(),
                "planning_result": planning_result.to_dict(),
                "intake_context": intake_context.__dict__,
                "viewer_assets": viewer_assets,
                "_slice_image_path": nifti_path,
                "_slice_seg_path": seg_path,
                "slice_manifest": slice_manifest,
                "slice_source": "on_demand",
                "dashboard_payloads": dashboard_payloads,
                "segmentation_run": structural_generated,
                "segmentation_backend": "structural_segmenter" if structural_generated else None,
                "preprocessing_profile": "lia_basic_qc" if structural_generated else None,
                "label_source": segmentation_payload.get("label_source"),
                "label_mapping_path": segmentation_payload.get("label_mapping_path"),
                "label_mapping_label_count": segmentation_payload.get("label_mapping_label_count"),
                "label_schema_path": structural_generated.get("label_schema_path") if structural_generated else None,
                "label_schema_version": structural_generated.get("label_schema_version") if structural_generated else None,
                "csv_export_path": csv_export_path,
                "csv_export_url": csv_export_url,
                "workspace_contract": build_workspace_contract(
                    workflow_id="neuro_report",
                    workflow_family=analysis_plan.workflow_family,
                    analysis_track=analysis_plan.analysis_track,
                    dashboard_profile=analysis_plan.dashboard_profile,
                    workspace_url=f"/demo/analysis/neuro-report?session_id={session_id}",
                    module="neuro_report",
                    runtime_mode=analysis_plan.runtime_mode,
                    viewer_type=viewer_assets["viewer_type"],
                    can_autorun=planning_result.autorun,
                    planning_result=planning_result,
                    task_traces=runtime_bundle["task_summary"],
                    tool_policy=runtime_bundle["tool_policy"],
                    context_availability=runtime_bundle["mcp_snapshot"]["servers"],
                    memory_context=memory_context,
                    planner_defaults=planner_defaults,
                ).to_dict(),
            }
        self.create_session(session_payload, session_id=session_id)
        return {
            "session_id": session_id,
            "mode": chosen_mode,
            "requested_mode": mode,
            "patient_id": patient_id,
            "study_id": study_id,
            "case_id": case_id,
            "report": reasoning_result.final_report,
            "report_sections": report_sections,
            "tool_outputs": reasoning_result.tool_outputs,
            "volumetrics": normalized_volumetrics,
            **segmentation_payload,
            "slices": None,
            "raw_slices": None,
            "overlay_slices": None,
            "slice_manifest": slice_manifest,
            "slice_source": "on_demand",
            "viewer_assets": viewer_assets,
            "analysis_plan": analysis_plan.to_dict(),
            "analysis_plan_summary": planning_result.analysis_plan_summary.to_dict(),
            "capability_profile": capability_profile.to_dict(),
            "capability_profile_summary": planning_result.capability_profile_summary.to_dict(),
            "planning_result": planning_result.to_dict(),
            "dashboard_payloads": dashboard_payloads,
            "segmentation_run": structural_generated,
            "segmentation_backend": "structural_segmenter" if structural_generated else None,
            "preprocessing_profile": "lia_basic_qc" if structural_generated else None,
            "label_source": segmentation_payload.get("label_source"),
            "label_mapping_path": segmentation_payload.get("label_mapping_path"),
            "label_mapping_label_count": segmentation_payload.get("label_mapping_label_count"),
            "label_schema_path": structural_generated.get("label_schema_path") if structural_generated else None,
            "label_schema_version": structural_generated.get("label_schema_version") if structural_generated else None,
            "csv_export_path": csv_export_path,
            "csv_export_url": csv_export_url,
            "workspace_contract": build_workspace_contract(
                workflow_id="neuro_report",
                workflow_family=analysis_plan.workflow_family,
                analysis_track=analysis_plan.analysis_track,
                dashboard_profile=analysis_plan.dashboard_profile,
                workspace_url=f"/demo/analysis/neuro-report?session_id={session_id}",
                module="neuro_report",
                runtime_mode=analysis_plan.runtime_mode,
                viewer_type=viewer_assets["viewer_type"],
                can_autorun=planning_result.autorun,
                planning_result=planning_result,
                task_traces=runtime_bundle["task_summary"],
                tool_policy=runtime_bundle["tool_policy"],
                context_availability=runtime_bundle["mcp_snapshot"]["servers"],
                memory_context=memory_context,
                planner_defaults=planner_defaults,
            ).to_dict(),
        }

    async def _analyze_response_case(
        self,
        *,
        case: dict[str, Any],
        patient_id: str,
        study_id: str | None,
        case_id: str,
        mode: str,
        request_text: str,
    ) -> dict[str, Any]:
        point = self._response_study_point(case, study_id)
        intake_context, capability_profile, analysis_plan, viewer_assets, planning_result = self._response_planning_bundle(
            case,
            study_id=str(point.get("study_id", "")),
            request_text=request_text or "Review this tumor follow-up brain MRI and estimate longitudinal response burden.",
            requested_mode=mode or "seg_overlay",
            executed_mode="seg_overlay",
        )
        raw_slices, overlay_slices = self._response_slices(case, str(point.get("study_id", "")))
        report_text = self._response_report_text(case)
        report_sections = self._response_report_sections(case)
        response_volumetrics = self._response_volumetrics(case, str(point.get("study_id", "")))
        segmentation_regions = self._normalized_segmentation_regions(response_volumetrics)
        dashboard_payloads = self._response_dashboard_payloads(
            case,
            planning_result=planning_result,
            study_id=str(point.get("study_id", "")),
        )
        memory_context, planner_defaults = self._planner_memory_bundle(
            workflow_family=analysis_plan.workflow_family,
            primary_goal=analysis_plan.primary_goal,
            patient_id=patient_id,
            study_id=str(point.get("study_id", "")),
        )
        runtime_bundle = self._runtime_bundle(
            analysis_plan=analysis_plan,
            capability_profile=capability_profile,
        )
        tool_outputs = {
            "response_analysis": case.get("analysis"),
            "timeline": case.get("timeline"),
        }
        session_id = self.create_session(
            {
                "patient_id": patient_id,
                "study_id": str(point.get("study_id", "")),
                "case_id": case_id,
                "mode": "seg_overlay",
                "source": "example",
                "age": int(case.get("patient", {}).get("age") or 0),
                "sex": str(case.get("patient", {}).get("sex") or "U")[:1].upper(),
                "indication": case.get("patient", {}).get("diagnosis", "Brain metastasis follow-up"),
                "image_name": "t1c.nii.gz",
                "segmentation_name": "tumor_mask",
                "report": report_text,
                "report_sections": report_sections,
                "tool_outputs": tool_outputs,
                "segmentation_regions": segmentation_regions,
                "analysis_plan": analysis_plan.to_dict(),
                "analysis_plan_summary": planning_result["analysis_plan_summary"],
                "capability_profile": capability_profile.to_dict(),
                "capability_profile_summary": planning_result["capability_profile_summary"],
                "planning_result": planning_result,
                "viewer_assets": viewer_assets,
                "dashboard_payloads": dashboard_payloads,
                "workspace_contract": build_workspace_contract(
                    workflow_id="neuro_report",
                    workflow_family=analysis_plan.workflow_family,
                    analysis_track=analysis_plan.analysis_track,
                    dashboard_profile=analysis_plan.dashboard_profile,
                    workspace_url="/demo/analysis/neuro-report",
                    module="neuro_report",
                    runtime_mode=analysis_plan.runtime_mode,
                    viewer_type=viewer_assets["viewer_type"],
                    can_autorun=bool(planning_result.get("autorun")),
                    planning_result=build_planning_result(
                        intake_context,
                        capability_profile,
                        analysis_plan,
                        requested_mode=mode or "seg_overlay",
                        executed_mode="seg_overlay",
                        viewer_type=viewer_assets["viewer_type"],
                    ),
                    task_traces=runtime_bundle["task_summary"],
                    tool_policy=runtime_bundle["tool_policy"],
                    context_availability=runtime_bundle["mcp_snapshot"]["servers"],
                    memory_context=memory_context,
                    planner_defaults=planner_defaults,
                ).to_dict(),
            }
        )
        return {
            "session_id": session_id,
            "mode": "seg_overlay",
            "requested_mode": mode or "seg_overlay",
            "patient_id": patient_id,
            "study_id": str(point.get("study_id", "")),
            "case_id": case_id,
            "report": report_text,
            "report_sections": report_sections,
            "tool_outputs": tool_outputs,
            "volumetrics": response_volumetrics,
            "segmentation_regions": segmentation_regions,
            "slices": overlay_slices or raw_slices,
            "raw_slices": raw_slices,
            "overlay_slices": overlay_slices,
            "viewer_assets": viewer_assets,
            "analysis_plan": analysis_plan.to_dict(),
            "analysis_plan_summary": planning_result["analysis_plan_summary"],
            "capability_profile": capability_profile.to_dict(),
            "capability_profile_summary": planning_result["capability_profile_summary"],
            "planning_result": planning_result,
            "dashboard_payloads": dashboard_payloads,
            "workspace_contract": build_workspace_contract(
                workflow_id="neuro_report",
                workflow_family=analysis_plan.workflow_family,
                analysis_track=analysis_plan.analysis_track,
                dashboard_profile=analysis_plan.dashboard_profile,
                workspace_url=f"/demo/analysis/neuro-report?case_id={case_id}&study_id={point.get('study_id', '')}&goal={planning_result['primary_goal']}",
                module="neuro_report",
                runtime_mode=analysis_plan.runtime_mode,
                viewer_type=viewer_assets["viewer_type"],
                can_autorun=bool(planning_result.get("autorun")),
                planning_result=build_planning_result(
                    intake_context,
                    capability_profile,
                    analysis_plan,
                    requested_mode=mode or "seg_overlay",
                    executed_mode="seg_overlay",
                    viewer_type=viewer_assets["viewer_type"],
                ),
                task_traces=runtime_bundle["task_summary"],
                tool_policy=runtime_bundle["tool_policy"],
                context_availability=runtime_bundle["mcp_snapshot"]["servers"],
                memory_context=memory_context,
                planner_defaults=planner_defaults,
                ).to_dict(),
            }

    def prepare_workspace_preview(
        self,
        *,
        nifti_path: str,
        seg_path: str | None,
        age: int | None,
        sex: str | None,
        indication: str,
        patient_id: str | None = None,
        study_id: str | None = None,
        source: str = "upload",
        request_text: str = "",
        report_text: str = "",
        report_sections: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        intake_context, capability_profile, analysis_plan = self._plan_for_upload(
            nifti_path=nifti_path,
            seg_path=seg_path,
            age=age,
            sex=sex,
            indication=indication,
            request_text=request_text,
        )
        if not analysis_plan.can_execute:
            raise ValueError(analysis_plan.handoff_summary)

        preview_mode = analysis_plan.recommended_mode or ("seg_overlay" if seg_path else "vanilla")
        if preview_mode not in SUPPORTED_ANALYSIS_MODES:
            preview_mode = "vanilla"
        if preview_mode in {"seg_overlay", "tool_output", "full_agent"} and not capability_profile.has_segmentation:
            preview_mode = "vanilla"
        if preview_mode in {"tool_output", "full_agent"} and not capability_profile.has_demographics:
            preview_mode = "seg_overlay" if capability_profile.has_segmentation else "vanilla"

        viewer_assets = self._materialize_viewer_assets(
            image_path=nifti_path,
            seg_path=seg_path,
            asset_slug=_safe_case_slug(patient_id, study_id, None, source, Path(nifti_path).stem),
        )
        planning_result = build_planning_result(
            intake_context,
            capability_profile,
            analysis_plan,
            requested_mode=preview_mode,
            executed_mode=preview_mode,
            viewer_type=viewer_assets["viewer_type"],
        )
        memory_context, planner_defaults = self._planner_memory_bundle(
            workflow_family=analysis_plan.workflow_family,
            primary_goal=analysis_plan.primary_goal,
            patient_id=patient_id,
            study_id=study_id,
        )
        runtime_bundle = self._runtime_bundle(
            analysis_plan=analysis_plan,
            capability_profile=capability_profile,
        )
        slice_manifest = self._structural_slice_manifest(
            image_path=nifti_path,
            seg_path=seg_path,
        )

        resolved_report_sections = report_sections or (self._report_to_sections(report_text) if report_text else None)
        session_id = uuid.uuid4().hex
        session_payload = {
            "patient_id": patient_id,
            "study_id": study_id,
            "case_id": None,
            "mode": preview_mode,
            "requested_mode": preview_mode,
            "source": source,
            "age": age,
            "sex": sex,
            "indication": indication,
            "image_name": Path(nifti_path).name,
            "segmentation_name": Path(seg_path).name if seg_path else None,
            "report": report_text,
            "report_sections": resolved_report_sections,
            "volumetrics": None,
            "segmentation_regions": None,
            "analysis_plan": analysis_plan.to_dict(),
            "analysis_plan_summary": planning_result.analysis_plan_summary.to_dict(),
            "capability_profile": capability_profile.to_dict(),
            "capability_profile_summary": planning_result.capability_profile_summary.to_dict(),
            "planning_result": planning_result.to_dict(),
            "viewer_assets": viewer_assets,
            "_slice_image_path": nifti_path,
            "_slice_seg_path": seg_path,
            "slice_manifest": slice_manifest,
            "slice_source": "on_demand",
            "dashboard_payloads": None,
            "segmentation_backend": None,
            "preprocessing_profile": None,
            "label_source": None,
            "label_mapping_path": None,
            "label_mapping_label_count": None,
            "label_schema_version": None,
            "csv_export_path": None,
            "csv_export_url": None,
            "workspace_contract": build_workspace_contract(
                workflow_id="neuro_report",
                workflow_family=analysis_plan.workflow_family,
                analysis_track=analysis_plan.analysis_track,
                dashboard_profile=analysis_plan.dashboard_profile,
                workspace_url=f"/demo/analysis/neuro-report?source={source}&session_id={session_id}",
                module="neuro_report",
                runtime_mode=analysis_plan.runtime_mode,
                viewer_type=viewer_assets["viewer_type"],
                can_autorun=False,
                planning_result=planning_result,
                task_traces=runtime_bundle["task_summary"],
                tool_policy=runtime_bundle["tool_policy"],
                context_availability=runtime_bundle["mcp_snapshot"]["servers"],
                memory_context=memory_context,
                planner_defaults=planner_defaults,
            ).to_dict(),
        }
        self.create_session(session_payload, session_id=session_id)
        return {
            "session_id": session_id,
            "patient_id": patient_id,
            "study_id": study_id,
            "case_id": None,
            "source": source,
            "mode": preview_mode,
            "requested_mode": preview_mode,
            "age": age,
            "sex": sex,
            "indication": indication,
            "image_name": Path(nifti_path).name,
            "segmentation_name": Path(seg_path).name if seg_path else None,
            "report": report_text,
            "report_sections": resolved_report_sections,
            "viewer_assets": viewer_assets,
            "slice_manifest": slice_manifest,
            "slice_source": "on_demand",
            "volumetrics": None,
            "segmentation_regions": None,
            "analysis_plan": analysis_plan.to_dict(),
            "analysis_plan_summary": planning_result.analysis_plan_summary.to_dict(),
            "capability_profile": capability_profile.to_dict(),
            "capability_profile_summary": planning_result.capability_profile_summary.to_dict(),
            "planning_result": planning_result.to_dict(),
            "workspace_contract": session_payload["workspace_contract"],
            "dashboard_payloads": None,
            "segmentation_backend": None,
            "preprocessing_profile": None,
            "csv_export_url": None,
            "label_source": None,
            "label_mapping_path": None,
            "label_mapping_label_count": None,
            "label_schema_version": None,
        }

    def create_session(self, payload: dict[str, Any], session_id: str | None = None) -> str:
        session_id = session_id or uuid.uuid4().hex
        self._session_store[session_id] = payload
        save_session_memory(session_id, "neuro_report", payload)
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any]:
        if session_id in self._session_store:
            return self._session_store[session_id]
        persisted = get_session_memory(session_id)
        if not isinstance(persisted, dict) or persisted.get("workflow_id") != "neuro_report":
            raise KeyError(f"Unknown session: {session_id}")
        payload = persisted.get("payload") if isinstance(persisted, dict) else None
        if not isinstance(payload, dict):
            raise KeyError(f"Unknown session: {session_id}")
        self._session_store[session_id] = payload
        return payload

    def find_session(
        self,
        *,
        source: str | None = None,
        patient_id: str | None = None,
        study_id: str | None = None,
    ) -> tuple[str, dict[str, Any]] | None:
        def _matches(payload: dict[str, Any]) -> bool:
            if not isinstance(payload, dict):
                return False
            if source is not None and str(payload.get("source") or "").strip() != source:
                return False
            if patient_id is not None and str(payload.get("patient_id") or "").strip() != patient_id:
                return False
            if study_id is not None and str(payload.get("study_id") or "").strip() != study_id:
                return False
            if not str(payload.get("_slice_image_path") or "").strip():
                return False
            return True

        for existing_session_id, payload in reversed(list(self._session_store.items())):
            if _matches(payload):
                return existing_session_id, payload

        persisted_sessions = get_harness_memory_store().session_memories
        for existing_session_id, stored in reversed(list(persisted_sessions.items())):
            payload = stored.get("payload") if isinstance(stored, dict) else None
            if not isinstance(payload, dict) or not _matches(payload):
                continue
            self._session_store[existing_session_id] = payload
            return existing_session_id, payload
        return None

    def get_structural_study_slice(
        self,
        patient_id: str,
        study_id: str,
        *,
        plane: str,
        index: int,
        overlay: bool,
    ) -> dict[str, Any]:
        record = self._record_for_study(patient_id, study_id)
        return self._structural_slice_payload(
            image_path=record.analysis_image_path,
            seg_path=record.seg_path,
            plane=plane,
            index=index,
            overlay=overlay,
        )

    def get_structural_session_slice(
        self,
        session_id: str,
        *,
        plane: str,
        index: int,
        overlay: bool,
    ) -> dict[str, Any]:
        session = self.get_session(session_id)
        image_path = str(session.get("_slice_image_path") or "").strip()
        if not image_path:
            raise KeyError(f"Session {session_id} does not expose structural slice data.")
        seg_path_value = str(session.get("_slice_seg_path") or "").strip()
        seg_path = seg_path_value or None
        return self._structural_slice_payload(
            image_path=image_path,
            seg_path=seg_path,
            plane=plane,
            index=index,
            overlay=overlay,
        )

    @staticmethod
    def _report_to_sections(report_text: str) -> dict[str, str]:
        sections = {
            "clinical_information": "",
            "technique": "",
            "findings": "",
            "impression": "",
        }
        current: str | None = None
        for raw_line in report_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            upper = line.upper().rstrip(":")
            if upper == "CLINICAL INFORMATION":
                current = "clinical_information"
                continue
            if upper == "TECHNIQUE":
                current = "technique"
                continue
            if upper == "FINDINGS":
                current = "findings"
                continue
            if upper == "IMPRESSION":
                current = "impression"
                continue
            if current:
                sections[current] = (sections[current] + "\n" + line).strip()
        return sections

    def resolve_analysis_request(
        self,
        *,
        case_id: str | None = None,
        patient_id: str | None = None,
        study_id: str | None = None,
    ) -> StudyRecord | dict[str, Any]:
        response_case = self._response_case(case_id=case_id, patient_id=patient_id)
        if response_case is not None:
            assets = self._response_timepoint_assets(response_case, study_id)
            if assets is None:
                raise KeyError(f"Response case assets are unavailable for {case_id or patient_id}")
            return {
                "kind": "response",
                "patient_id": patient_id or str(response_case.get("patient", {}).get("id", "")),
                "study_id": str(assets["study_id"]),
                "case_id": case_id or str(response_case.get("id", "")),
                "analysis_image_path": assets["image_path"],
                "seg_path": assets["seg_path"],
                "age": int(response_case.get("patient", {}).get("age") or 0),
                "sex": str(response_case.get("patient", {}).get("sex") or "U")[:1].upper(),
                "indication": response_case.get("patient", {}).get("diagnosis", "Brain metastasis follow-up"),
            }
        if case_id:
            return self._record_for_case(case_id)
        if patient_id and study_id:
            return self._record_for_study(patient_id, study_id)
        raise KeyError("Either case_id or patient_id/study_id must be provided")

    def create_uploaded_source(
        self,
        *,
        nifti_bytes: bytes,
        nifti_filename: str,
        seg_bytes: bytes | None,
        seg_filename: str | None,
    ) -> tuple[str, str | None]:
        temp_root = Path(tempfile.gettempdir()) / "clinagent-neuro-report"
        temp_root.mkdir(parents=True, exist_ok=True)
        request_id = uuid.uuid4().hex
        request_dir = temp_root / request_id
        request_dir.mkdir(parents=True, exist_ok=True)
        nifti_path = request_dir / (Path(nifti_filename).name or "uploaded.nii.gz")
        nifti_path.write_bytes(nifti_bytes)
        seg_path = None
        if seg_bytes is not None:
            seg_path = request_dir / (Path(seg_filename or "uploaded_seg.nii.gz").name or "uploaded_seg.nii.gz")
            seg_path.write_bytes(seg_bytes)
        return str(nifti_path), str(seg_path) if seg_path else None


neuro_report_demo_store = NeuroReportDemoStore()
