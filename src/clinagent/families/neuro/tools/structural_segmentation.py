"""Schema-driven structural segmentation adapter for external brain structure services."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

from clinagent.families.neuro.resources import VISTA_LABEL_MAPPING_PATH
from clinagent.families.neuro.tools.segmentation import _normalize_region_name, _region_groups

EXCLUDED_LABEL_NAMES = {
    "ctx-lh-bankssts",
    "ctx-lh-inferiortemporal",
    "ctx-lh-middletemporal",
    "ctx-lh-postcentral",
    "ctx-lh-precentral",
    "ctx-lh-rostralanteriorcingulate",
    "ctx-lh-rostralmiddlefrontal",
    "ctx-lh-superiorfrontal",
    "ctx-lh-superiorparietal",
    "ctx-lh-superiortemporal",
    "ctx-lh-supramarginal",
    "ctx-lh-frontalpole",
    "ctx-lh-temporalpole",
    "ctx-lh-transversetemporal",
    "ctx-rh-entorhinal",
    "ctx-rh-precentral",
}

DEFAULT_VISTA_LABEL_MAPPING_PATH = VISTA_LABEL_MAPPING_PATH


def _display_name(value: str) -> str:
    cleaned = value.replace("ctx-lh-", "Left ").replace("ctx-rh-", "Right ")
    cleaned = cleaned.replace("-", " ").replace("_", " ")
    return " ".join(part.capitalize() for part in cleaned.split())


def _group_display_name(group: str | None) -> str:
    if not group:
        return "Ungrouped"
    return _display_name(group)


def _is_csf_like(label_name: str, group: str | None) -> bool:
    lowered = label_name.lower()
    if "ventricle" in lowered:
        return True
    if group and "ventricle" in group.lower():
        return True
    return False


def _normalize_group(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _infer_hemisphere(label_name: str) -> str | None:
    lowered = label_name.lower()
    if lowered.startswith(("left-", "left_", "ctx-lh-")):
        return "left"
    if lowered.startswith(("right-", "right_", "ctx-rh-")):
        return "right"
    return None


def _humanize_label_name(value: str) -> str:
    return " ".join(part for part in value.replace("_", " ").replace("-", " ").split())


def _read_label_schema(label_schema_path: str | Path) -> tuple[list[dict[str, Any]], str | None]:
    payload = json.loads(Path(label_schema_path).read_text())
    if isinstance(payload, list):
        return [dict(item) for item in payload], None
    if isinstance(payload, dict):
        if isinstance(payload.get("labels"), list):
            version = payload.get("label_schema_version") or payload.get("version")
            return [dict(item) for item in payload["labels"]], str(version) if version else None
        if all(isinstance(value, dict) for value in payload.values()):
            labels: list[dict[str, Any]] = []
            for key, value in payload.items():
                item = dict(value)
                item.setdefault("label_id", int(key))
                labels.append(item)
            return labels, None
    raise ValueError(f"Unsupported label schema format: {label_schema_path}")


def _read_vista_label_mapping(label_mapping_path: str | Path) -> list[dict[str, Any]]:
    path = Path(label_mapping_path)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            label_id = str(row.get("label_id") or "").strip()
            label_name = str(row.get("label_name") or "").strip()
            if not label_id or not label_name:
                continue
            rows.append(
                {
                    "label_id": int(label_id),
                    "label_name": label_name,
                    "display_name": _humanize_label_name(label_name),
                }
            )
    return rows


class StructuralSegmentationAdapter:
    """Read a segmentation volume using an external label schema."""

    def __init__(self, excluded_label_names: set[str] | None = None) -> None:
        self.excluded_label_names = set(excluded_label_names or EXCLUDED_LABEL_NAMES)

    def run(
        self,
        *,
        seg_nifti_path: str,
        label_schema_path: str | None = None,
        label_mapping_path: str | None = None,
        label_source: str | None = None,
    ) -> dict[str, Any]:
        seg_path = Path(seg_nifti_path)
        image = nib.load(str(seg_path))
        image = nib.as_closest_canonical(image)
        data = np.asarray(image.get_fdata(), dtype=np.int32)
        voxel_size_mm = tuple(float(value) for value in image.header.get_zooms()[:3])
        voxel_volume_mm3 = float(np.prod(voxel_size_mm))

        mapping_mode = (label_source or "").strip() or ("vista_tsv" if label_mapping_path else "remote_schema")
        schema_version: str | None = None
        resolved_label_mapping_path: str | None = None
        resolved_label_schema_path: str | None = None
        if mapping_mode == "vista_tsv":
            mapping_path = Path(label_mapping_path or DEFAULT_VISTA_LABEL_MAPPING_PATH).expanduser().resolve()
            label_rows = _read_vista_label_mapping(mapping_path)
            resolved_label_mapping_path = str(mapping_path)
        else:
            if not label_schema_path:
                raise ValueError("label_schema_path is required for remote structural segmentation metadata.")
            schema_path = Path(label_schema_path).expanduser().resolve()
            label_rows, schema_version = _read_label_schema(schema_path)
            resolved_label_mapping_path = str(schema_path)
            resolved_label_schema_path = str(schema_path)

        label_by_id: dict[int, dict[str, Any]] = {}
        for row in label_rows:
            label_id = int(row.get("label_id", 0))
            label_name = str(row.get("label_name") or row.get("name") or "").strip()
            if not label_name:
                continue
            analysis_name = str(row.get("name") or "").strip()
            if not analysis_name:
                analysis_name = _normalize_region_name(label_name) if mapping_mode == "vista_tsv" else label_name
            groups = _region_groups(label_id, analysis_name) if mapping_mode == "vista_tsv" else []
            group = _normalize_group(str(row.get("group") or "").strip()) or (groups[0] if groups else None)
            label_by_id[label_id] = {
                "label_id": label_id,
                "label_name": label_name,
                "analysis_name": analysis_name,
                "display_name": str(row.get("display_name") or _display_name(label_name)),
                "group": group,
                "hemisphere": str(row.get("hemisphere") or "").strip() or _infer_hemisphere(label_name),
            }

        labels, counts = np.unique(data, return_counts=True)
        regions: list[dict[str, Any]] = []
        grouped_regions: dict[str, dict[str, Any]] = {}
        total_brain_voxels = 0
        total_brain_volume_mm3 = 0.0

        for label_id, voxel_count in zip(labels.tolist(), counts.tolist(), strict=True):
            label_id = int(label_id)
            voxel_count = int(voxel_count)
            if label_id == 0:
                continue
            label_meta = label_by_id.get(label_id)
            label_name = str(label_meta["label_name"] if label_meta else f"unknown_label_{label_id}")
            if label_name in self.excluded_label_names:
                continue
            group = label_meta.get("group") if label_meta else None
            region = {
                "label_id": label_id,
                "name": label_meta.get("analysis_name") if label_meta else f"unknown_label_{label_id}",
                "label_name": label_name,
                "display_name": label_meta.get("display_name") if label_meta else _display_name(label_name),
                "group": group,
                "hemisphere": label_meta.get("hemisphere") if label_meta else None,
                "voxel_count": voxel_count,
                "volume_mm3": float(voxel_count * voxel_volume_mm3),
            }
            regions.append(region)
            if group:
                grouped = grouped_regions.setdefault(
                    group,
                    {
                        "name": group,
                        "display_name": _group_display_name(group),
                        "group": group,
                        "voxel_count": 0,
                        "volume_mm3": 0.0,
                        "member_regions": [],
                    },
                )
                grouped["voxel_count"] += voxel_count
                grouped["volume_mm3"] += region["volume_mm3"]
                grouped["member_regions"].append(label_name)
            if not _is_csf_like(label_name, group):
                total_brain_voxels += voxel_count
                total_brain_volume_mm3 += region["volume_mm3"]

        regions.sort(key=lambda item: item["label_id"])
        grouped_region_list = sorted(grouped_regions.values(), key=lambda item: item["name"])
        for item in grouped_region_list:
            item["member_regions"] = sorted(set(item["member_regions"]))

        return {
            "regions": regions,
            "grouped_regions": grouped_region_list,
            "voxel_size_mm": [float(value) for value in voxel_size_mm],
            "voxel_volume_mm3": voxel_volume_mm3,
            "total_brain_voxels": total_brain_voxels,
            "total_brain_volume_mm3": total_brain_volume_mm3,
            "segmentation_path": str(seg_path),
            "label_source": mapping_mode,
            "label_mapping_path": resolved_label_mapping_path,
            "label_mapping_label_count": len(label_by_id),
            "label_schema_path": resolved_label_schema_path,
            "label_schema_version": schema_version,
            "segmentation_backend": "structural_segmenter",
        }

    @staticmethod
    def export_regions_csv(
        *,
        destination_path: str | Path,
        regions: list[dict[str, Any]],
        case_id: str | None,
        patient_id: str | None,
        study_id: str | None,
    ) -> str:
        path = Path(destination_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "case_id",
            "patient_id",
            "study_id",
            "label_id",
            "label_name",
            "display_name",
            "group",
            "hemisphere",
            "voxel_count",
            "volume_mm3",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for region in regions:
                writer.writerow(
                    {
                        "case_id": case_id or "",
                        "patient_id": patient_id or "",
                        "study_id": study_id or "",
                        "label_id": region.get("label_id"),
                        "label_name": region.get("label_name") or region.get("name"),
                        "display_name": region.get("display_name"),
                        "group": region.get("group") or "",
                        "hemisphere": region.get("hemisphere") or "",
                        "voxel_count": region.get("voxel_count"),
                        "volume_mm3": region.get("volume_mm3"),
                    }
                )
        return str(path.resolve())
