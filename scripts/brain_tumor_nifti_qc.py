#!/usr/bin/env python3
"""Run lightweight QC on normalized BraTS-style glioma NIfTI cases."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

MODALITIES = ("t1n", "t1c", "t2w", "t2f")
REQUIRED_FILES = (*MODALITIES, "seg")
VALID_LABELS = {0, 1, 2, 3, 4}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normalized-root", required=True, help="Root containing normalized case directories.")
    parser.add_argument("--output-csv", required=True, help="QC CSV path to write.")
    parser.add_argument("--quarantine-json", required=True, help="JSON path for failed/ambiguous cases.")
    args = parser.parse_args()

    normalized_root = Path(args.normalized_root).expanduser().resolve()
    rows: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    for case_dir in sorted(path for path in normalized_root.iterdir() if path.is_dir()):
        result = _qc_case(case_dir)
        rows.append(result)
        if result["status"] != "ok":
            quarantine.append(result)

    output_csv = Path(args.output_csv).expanduser().resolve()
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "case_id",
            "status",
            "warnings",
            "shape",
            "spacing_mm",
            "labels",
            "whole_tumor_voxels",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})

    quarantine_path = Path(args.quarantine_json).expanduser().resolve()
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    quarantine_path.write_text(json.dumps(quarantine, indent=2), encoding="utf-8")
    print(f"QC cases: {len(rows)}")
    print(f"Quarantined: {len(quarantine)}")


def _qc_case(case_dir: Path) -> dict[str, Any]:
    warnings: list[str] = []
    missing = [name for name in REQUIRED_FILES if not (case_dir / f"{name}.nii.gz").exists()]
    if missing:
        warnings.append(f"missing files: {', '.join(missing)}")

    images: dict[str, nib.spatialimages.SpatialImage] = {}
    for name in REQUIRED_FILES:
        path = case_dir / f"{name}.nii.gz"
        if not path.exists():
            continue
        try:
            images[name] = nib.load(str(path))
        except Exception as exc:
            warnings.append(f"{name} unreadable: {exc}")

    reference = images.get("t1c") or next(iter(images.values()), None)
    reference_shape: tuple[int, int, int] | None = None
    reference_affine: np.ndarray | None = None
    if reference is not None:
        reference_shape = tuple(int(v) for v in reference.shape[:3])
        reference_affine = reference.affine

    for name, image in images.items():
        data = np.asanyarray(image.dataobj)
        if data.ndim == 4 and data.shape[-1] == 1:
            data = np.squeeze(data, axis=-1)
        if data.ndim != 3:
            warnings.append(f"{name} is not 3D: {tuple(image.shape)}")
        if reference_shape and tuple(int(v) for v in data.shape[:3]) != reference_shape:
            warnings.append(f"{name} shape mismatch")
        if reference_affine is not None and not np.allclose(image.affine, reference_affine, atol=1e-3):
            warnings.append(f"{name} affine mismatch")
        if float(np.mean(np.isfinite(data))) < 0.999:
            warnings.append(f"{name} non-finite voxels")
        if int(np.count_nonzero(data)) == 0 and name != "seg":
            warnings.append(f"{name} all-zero image")

    labels: list[int] = []
    whole_tumor_voxels = 0
    if "seg" in images:
        seg_data = np.asanyarray(images["seg"].dataobj)
        labels = sorted(int(v) for v in np.unique(seg_data))
        unknown = sorted(set(labels) - VALID_LABELS)
        if unknown:
            warnings.append(f"unknown labels: {unknown}")
        whole_tumor_voxels = int(np.count_nonzero(seg_data))
        if whole_tumor_voxels == 0:
            warnings.append("empty segmentation")

    return {
        "case_id": case_dir.name,
        "status": "ok" if not warnings else "quarantine",
        "warnings": warnings,
        "shape": list(reference_shape) if reference_shape else [],
        "spacing_mm": [float(v) for v in reference.header.get_zooms()[:3]] if reference is not None else [],
        "labels": labels,
        "whole_tumor_voxels": whole_tumor_voxels,
    }


def _csv_value(value: Any) -> str:
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value)
    return str(value if value is not None else "")


if __name__ == "__main__":
    main()
