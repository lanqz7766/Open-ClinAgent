"""Deterministic alignment workflow shared by the workstation and neuro tools."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import nibabel as nib
import numpy as np

from .core import apply_neuro_transform, coregister_longitudinal, coregister_sequences
from .rigid import _to_sitk, correct_bias_field


ALIGNMENT_STEPS = (
    ("inputs", "Check inputs", "validate_neuro_images"),
    ("intensity", "Intensity correction", "n4_bias_field_correction"),
    ("within_visit", "Within-visit alignment", "coregister_neuro_sequences"),
    ("longitudinal", "Between-visit alignment", "coregister_neuro_longitudinal"),
    ("outputs", "Resample and check", "apply_neuro_transform"),
)
MODALITY_LABELS = {"t1n": "T1", "t1c": "T1c", "t2w": "T2", "t2f": "FLAIR"}


def pending_steps():
    return [{"id": key, "label": label, "tool": tool, "status": "pending"}
            for key, label, tool in ALIGNMENT_STEPS]


def align_visit(*, reference_t1c: str, modalities: dict[str, str], masks: dict[str, str],
                output_dir: Path, bias_correction: bool = False,
                on_step: Callable[[dict], None] | None = None) -> dict:
    started = time.monotonic()
    steps = pending_steps()
    step_started: dict[str, float] = {}

    def emit(key, status, detail):
        step = next(item for item in steps if item["id"] == key)
        if status == "running":
            step_started.setdefault(key, time.monotonic())
        step.update(status=status, detail=detail)
        if status in {"complete", "failed"} and key in step_started:
            step["duration_sec"] = round(time.monotonic() - step_started[key], 2)
        if on_step:
            on_step(dict(step))

    try:
        emit("inputs", "running", "Checking T1c, MRI geometry and readable volumes")
        if not modalities.get("t1c"):
            raise ValueError("A T1c image is required for alignment.")
        if set(modalities) - {"t1c", "t1n", "t2w", "t2f"} or set(masks) - {"seg", "ground_truth_seg"}:
            raise ValueError("Unsupported MRI channel or mask name.")
        for path in [reference_t1c, *modalities.values()]:
            _to_sitk(nib.load(path))
        emit("inputs", "complete", f"T1c reference; {len(modalities)} moving MRI channels verified")

        prepared = dict(modalities)
        fixed = reference_t1c
        if bias_correction:
            emit("intensity", "running", "N4 on the reference T1c")
            fixed = correct_bias_field(reference_t1c, output_dir / "n4/reference.nii.gz")
            for key, path in modalities.items():
                emit("intensity", "running", f"N4 on {MODALITY_LABELS[key]}")
                prepared[key] = correct_bias_field(path, output_dir / f"n4/{key}.nii.gz")
            emit("intensity", "complete", "N4 applied to derived images; source images retained")
        else:
            emit("intensity", "skipped", "N4 not selected; source intensities retained")

        intra = {"t1c": np.eye(4)}
        within_qc = {}
        for key, path in prepared.items():
            if key == "t1c":
                continue
            emit("within_visit", "running", f"Rigid {MODALITY_LABELS[key]} to this visit's T1c")
            result = coregister_sequences(
                fixed_image_path=prepared["t1c"], moving_image_path=path,
                output_dir=output_dir / "within" / key, method="rigid",
                fixed_label="T1c", moving_label=key,
            )
            intra[key] = np.asarray(result["transform"]["moving_to_fixed_world_affine"])
            within_qc[key] = {name: result["qc"].get(name) for name in
                              ("rotation_angle_deg", "translation_norm_mm", "similarity_metric")}
        emit("within_visit", "complete" if within_qc else "skipped",
             f"{len(within_qc)} channels rigidly aligned to T1c" if within_qc else "Only T1c supplied; no cross-modality step")

        emit("longitudinal", "running", "Rigid T1c to reference T1c; 6 degrees of freedom")
        result = coregister_longitudinal(
            baseline_image_path=fixed, followup_image_path=prepared["t1c"],
            output_dir=output_dir / "between", method="rigid",
            progress=lambda detail: emit("longitudinal", "running", f"T1c to reference T1c: {detail}"),
        )
        forward = np.asarray(result["transform"]["moving_to_fixed_world_affine"])
        emit("longitudinal", "complete", "Rotation and translation estimated; no scaling or deformation")

        emit("outputs", "running", "Applying transform chains to MRI and masks")
        artifacts = {}
        for key, path in prepared.items():
            transform = output_dir / f"transform_{key}.json"
            transform.write_text(json.dumps({"matrix_convention": "moving_world_to_fixed_world",
                                             "moving_to_fixed_world_affine": (forward @ intra[key]).tolist()}))
            output = output_dir / f"image_{key}.nii.gz"
            apply_neuro_transform(source_image_path=path, reference_image_path=reference_t1c,
                                  transform_path=transform, output_image_path=output)
            artifacts[f"image_{key}"] = str(output)
        for name, path in masks.items():
            output = output_dir / f"{name}.nii.gz"
            apply_neuro_transform(source_image_path=path, reference_image_path=reference_t1c,
                                  transform_path=output_dir / "transform_t1c.json",
                                  output_image_path=output, interpolation="nearest")
            artifacts[name] = str(output)
        emit("outputs", "complete", "Aligned MRI and available masks saved; native measurements unchanged")
        qc = result["qc"]
        return {
            "registration": {
                **{key: qc.get(key) for key in ("backend", "deformation_model", "translation_mm", "translation_norm_mm",
                                               "rotation_angle_deg", "ncc_before", "ncc_after", "ncc_delta", "warnings", "similarity_metric")},
                "status": "ok", "nonlinear_deformation_allowed": False,
                "reference_modality": "t1c", "bias_correction": bias_correction,
                "workflow": "brain_tumor_alignment_v1", "steps": steps, "within_visit_qc": within_qc,
                "registration_runtime_sec": round(time.monotonic() - started, 2),
                "measurement_space": "native_segmentation",
            },
            "artifacts": artifacts,
        }
    except Exception:
        running = next((step for step in steps if step["status"] == "running"), None)
        if running:
            emit(running["id"], "failed", "This step failed; original images and measurements are unchanged")
        raise
