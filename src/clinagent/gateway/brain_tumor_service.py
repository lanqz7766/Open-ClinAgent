#!/usr/bin/env python3
"""Lightweight HTTP service for GlioMODA brain tumor segmentation.

This script is intentionally dependency-light: it uses the Python standard
library for HTTP serving and expects GlioMODA plus common imaging libraries to
already be installed in the runtime environment.
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from PIL import Image

HOST = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_HOST", "127.0.0.1")
PORT = int(os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_PORT", "18200"))
DEVICE = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_DEVICE", "cuda")
GPU_ID = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_GPU_ID", "0")
ENGINE = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_ENGINE", "nnunetv2").strip().lower()
OUTPUT_ROOT = Path(
    os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_OUTPUT_ROOT", "tumor_segmentation_outputs")
).expanduser()
API_KEY = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_API_KEY", "").strip()
MODEL_ID = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_MODEL_ID", "dataset802-unified-4class")
QC_PROFILE = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_QC_PROFILE", "fast").strip().lower()
WEIGHTS_ROOT = Path(os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_WEIGHTS_ROOT", "")).expanduser()
FAST_NNUNET_SRC = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_FAST_NNUNET_SRC", "").strip()
FAST_HELPER_PATH = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_FAST_HELPER_PATH", "").strip()
NNUNET_BIN = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_NNUNET_BIN", "nnUNetv2_predict").strip()
NNUNET_DATASET = os.environ.get(
    "CLINAGENT_TUMOR_SEGMENTATION_NNUNET_DATASET",
    "Dataset802_GliomaMixedV1_MemorialLabels",
).strip()
NNUNET_CONFIGURATION = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_NNUNET_CONFIGURATION", "3d_fullres").strip()
NNUNET_TRAINER = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_NNUNET_TRAINER", "nnUNetTrainer").strip()
NNUNET_PLANS = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_NNUNET_PLANS", "nnUNetResEncUNetMPlans").strip()
NNUNET_FOLD = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_NNUNET_FOLD", "0").strip()
NNUNET_CHECKPOINT = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_NNUNET_CHECKPOINT", "checkpoint_best.pth").strip()
NNUNET_RAW = os.environ.get("nnUNet_raw") or os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_NNUNET_RAW", "")
NNUNET_PREPROCESSED = os.environ.get("nnUNet_preprocessed") or os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_NNUNET_PREPROCESSED", "")
NNUNET_RESULTS = os.environ.get("nnUNet_results") or os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_NNUNET_RESULTS", "")
NNUNET_MODEL_DIR = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_NNUNET_MODEL_DIR", "").strip()
NNUNET_RUNTIME = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_NNUNET_RUNTIME", "cli").strip().lower()
FAST_MODE_DEFAULT = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_FAST_MODE", "1").strip().lower() not in {"0", "false", "no"}
WARMUP_ON_START = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_WARMUP", "1").strip().lower() not in {"0", "false", "no"}
WARMUP_MODALITIES_JSON = os.environ.get("CLINAGENT_TUMOR_SEGMENTATION_WARMUP_MODALITIES_JSON", "").strip()
SERVICE_VERSION = "clinagent-glioma-unified-service-2026-08-16"

MODALITIES = ("t1n", "t1c", "t2w", "t2f")
NNUNET_CHANNEL_ORDER = ("t1n", "t1c", "t2w", "t2f")
GLIOMODA_CHANNEL_ORDER = ("t1c", "t2f", "t1n", "t2w")
MODE_MAP = {
    ("t1c", "t2f", "t1n", "t2w"): "t1c-t2f-t1n-t2w",
    ("t1c",): "t1c",
    ("t2f",): "t2f",
    ("t1n",): "t1n",
    ("t2w",): "t2w",
    ("t1c", "t2f"): "t1c-t2f",
    ("t1c", "t1n"): "t1c-t1n",
    ("t1c", "t1n", "t2w"): "t1c-t1n-t2w",
    ("t1c", "t2w"): "t1c-t2w",
    ("t2f", "t1n"): "t2f-t1n",
    ("t2f", "t1n", "t2w"): "t2f-t1n-t2w",
    ("t2f", "t2w"): "t2f-t2w",
}
LABELS = {
    1: "non_enhancing_core_candidate",
    2: "flair_edema_abnormality",
    3: "enhancing_tumor",
    4: "cavity_or_post_surgical_change",
}
DERIVED_REGIONS = {
    "whole_tumor": (1, 2, 3),
    "tumor_core": (1, 3),
    "enhancing_tumor": (3,),
    "flair_abnormality": (2,),
    "non_enhancing_core_candidate": (1,),
    "active_tumor_for_rano_primary": (3,),
    "cavity_or_post_surgical_change": (4,),
    "cavity_exclusion": (4,),
}

_inferer: Any | None = None
_fast_predictors: dict[tuple[str, bool, str], Any] = {}
_nnunet_fast_predictors: dict[tuple[str, str, str], Any] = {}
_fast_runtime: dict[str, Any] | None = None
_infer_lock = threading.Lock()
_readiness_lock = threading.Lock()
_readiness: dict[str, Any] = {
    "status": "starting",
    "service_ready": False,
    "model_loaded": False,
    "warmup_level": "pending",
    "warmup_started_at": None,
    "warmup_completed_at": None,
    "warmup_duration_s": None,
    "warmup_error": None,
}


def _set_readiness(**updates: Any) -> None:
    with _readiness_lock:
        _readiness.update(updates)


def _readiness_snapshot() -> dict[str, Any]:
    with _readiness_lock:
        snapshot = dict(_readiness)
    snapshot.update(
        {
            "fast_predictors_loaded": len(_fast_predictors),
            "nnunet_fast_predictors_loaded": len(_nnunet_fast_predictors),
        }
    )
    return snapshot


def _persistent_model_loaded() -> bool:
    if ENGINE == "nnunetv2":
        return NNUNET_RUNTIME == "fast" and bool(_nnunet_fast_predictors)
    if ENGINE == "fast":
        return bool(_fast_predictors)
    if ENGINE == "gliomoda":
        return _inferer is not None
    return False


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, indent=2, default=_json_default).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _require_auth(handler: BaseHTTPRequestHandler) -> bool:
    if not API_KEY:
        return True
    if handler.headers.get("Authorization", "") == f"Bearer {API_KEY}":
        return True
    _send_json(handler, 401, {"ok": False, "error": "unauthorized"})
    return False


def _get_inferer() -> Inferer:
    global _inferer
    if _inferer is None:
        from gliomoda import Inferer

        _inferer = Inferer(device=DEVICE, cuda_visible_devices=GPU_ID)
    return _inferer


def _resolve_mode(modalities: dict[str, str]) -> tuple[str, list[str]]:
    ordered = tuple(key for key in GLIOMODA_CHANNEL_ORDER if key in modalities)
    mode = MODE_MAP.get(ordered)
    if mode is None:
        raise NotImplementedError(
            "No GlioMODA model is available for modality combination: " + ",".join(ordered)
        )
    return mode, list(ordered)


def _load_fast_runtime() -> dict[str, Any]:
    global _fast_runtime
    if _fast_runtime is not None:
        return _fast_runtime
    if FAST_NNUNET_SRC:
        sys.path.insert(0, FAST_NNUNET_SRC)
    if FAST_HELPER_PATH:
        sys.path.insert(0, FAST_HELPER_PATH)
    if not WEIGHTS_ROOT:
        raise RuntimeError("Fast tumor engine requires CLINAGENT_TUMOR_SEGMENTATION_WEIGHTS_ROOT")

    import SimpleITK as sitk
    import torch
    from app.predictor import FastNnUNetPredictor
    from nnunetv2.imageio.simpleitk_reader_writer import SimpleITKIO

    _fast_runtime = {
        "FastNnUNetPredictor": FastNnUNetPredictor,
        "SimpleITKIO": SimpleITKIO,
        "sitk": sitk,
        "torch": torch,
    }
    return _fast_runtime


def _get_fast_predictor(mode: str, use_resencl: bool) -> Any:
    runtime = _load_fast_runtime()
    torch = runtime["torch"]
    key = (mode, use_resencl, GPU_ID)
    predictor = _fast_predictors.get(key)
    if predictor is not None:
        return predictor

    model_dir = WEIGHTS_ROOT / f"{mode}{'_ResEncL' if use_resencl else ''}"
    if not model_dir.exists():
        raise FileNotFoundError(f"GlioMODA model folder not found for mode {mode}")
    predictor_cls = runtime["FastNnUNetPredictor"]
    predictor = predictor_cls(
        tile_step_size=0.5,
        use_gaussian=True,
        use_mirroring=False,
        perform_everything_on_device=DEVICE == "cuda",
        device=torch.device("cuda", int(GPU_ID)) if DEVICE == "cuda" else torch.device("cpu"),
        verbose=False,
        verbose_preprocessing=False,
        allow_tqdm=False,
    )
    predictor.initialize_from_trained_model_folder(
        str(model_dir),
        use_folds=("all",),
        checkpoint_name="checkpoint_final.pth",
    )
    _fast_predictors[key] = predictor
    return predictor


def _nnunet_model_dir() -> Path:
    if NNUNET_MODEL_DIR:
        return Path(NNUNET_MODEL_DIR).expanduser()
    if not NNUNET_RESULTS:
        raise RuntimeError(
            "Fast Dataset802 runtime requires nnUNet_results or "
            "CLINAGENT_TUMOR_SEGMENTATION_NNUNET_MODEL_DIR"
        )
    return (
        Path(NNUNET_RESULTS).expanduser()
        / NNUNET_DATASET
        / f"{NNUNET_TRAINER}__{NNUNET_PLANS}__{NNUNET_CONFIGURATION}"
    )


def _maybe_nnunet_model_dir() -> str | None:
    if NNUNET_MODEL_DIR:
        return str(Path(NNUNET_MODEL_DIR).expanduser())
    if NNUNET_RESULTS:
        return str(
            Path(NNUNET_RESULTS).expanduser()
            / NNUNET_DATASET
            / f"{NNUNET_TRAINER}__{NNUNET_PLANS}__{NNUNET_CONFIGURATION}"
        )
    return None


def _parse_nnunet_folds() -> tuple[str, ...]:
    if not NNUNET_FOLD:
        return ("0",)
    return tuple(part.strip() for part in NNUNET_FOLD.split(",") if part.strip()) or ("0",)


def _get_nnunet_fast_predictor(mode: str) -> Any:
    runtime = _load_fast_runtime()
    torch = runtime["torch"]
    key = (mode, NNUNET_CHECKPOINT, GPU_ID)
    predictor = _nnunet_fast_predictors.get(key)
    if predictor is not None:
        return predictor

    model_dir = _nnunet_model_dir()
    if not model_dir.exists():
        raise FileNotFoundError(f"Dataset802 nnU-Net model folder not found: {model_dir}")
    predictor_cls = runtime["FastNnUNetPredictor"]
    predictor = predictor_cls(
        tile_step_size=0.5,
        use_gaussian=True,
        use_mirroring=mode == "full",
        perform_everything_on_device=DEVICE == "cuda",
        device=torch.device("cuda", int(GPU_ID)) if DEVICE == "cuda" else torch.device("cpu"),
        verbose=False,
        verbose_preprocessing=False,
        allow_tqdm=False,
    )
    predictor.initialize_from_trained_model_folder(
        str(model_dir),
        use_folds=_parse_nnunet_folds(),
        checkpoint_name=NNUNET_CHECKPOINT,
    )
    _nnunet_fast_predictors[key] = predictor
    return predictor


def _safe_case_id(modalities: dict[str, str]) -> str:
    first = Path(next(iter(modalities.values()))).name
    for suffix in (".nii.gz", ".nii"):
        if first.endswith(suffix):
            first = first[: -len(suffix)]
            break
    first = re.sub(r"_(t1n|t1c|t2w|t2f|T1|T1c|T1GD|FLAIR|T2)$", "", first)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", first)[:80] or "case"


def _validate_payload(payload: dict[str, Any]) -> tuple[dict[str, str], Path, list[str]]:
    raw_modalities = payload.get("modalities")
    if not isinstance(raw_modalities, dict):
        raise ValueError("payload.modalities must be an object")
    modalities = {key: str(raw_modalities[key]) for key in MODALITIES if raw_modalities.get(key)}
    if not modalities:
        raise ValueError("At least one of t1n/t1c/t2w/t2f must be provided")

    warnings: list[str] = []
    for key, value in modalities.items():
        path = Path(value)
        if not path.exists():
            raise ValueError(f"{key} path does not exist on the service host")
        if not path.is_file():
            raise ValueError(f"{key} path is not a file on the service host")
    for key in MODALITIES:
        if key not in modalities:
            warnings.append(f"Missing modality: {key}")
    if "t1c" not in modalities:
        warnings.append("Missing contrast-enhanced T1; enhancing tumor reliability may be reduced")
    if "t2f" not in modalities:
        warnings.append("Missing FLAIR/T2-FLAIR; whole tumor reliability may be reduced")

    requested_output = payload.get("output_dir")
    if requested_output:
        output_dir = Path(str(requested_output))
    else:
        output_dir = (
            OUTPUT_ROOT
            / f"{_safe_case_id(modalities)}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    return modalities, output_dir, warnings


def _qc_modalities(modalities: dict[str, str], warnings: list[str]) -> dict[str, Any]:
    if QC_PROFILE not in {"fast", "strict"}:
        raise ValueError("CLINAGENT_TUMOR_SEGMENTATION_QC_PROFILE must be fast or strict")

    reference_key = "t1c" if "t1c" in modalities else next(iter(modalities))
    reference = nib.load(modalities[reference_key])
    reference_shape = tuple(int(v) for v in reference.shape[:3])
    reference_affine = reference.affine
    details: dict[str, Any] = {}

    for key, path in modalities.items():
        image = nib.load(path)
        image_shape = tuple(int(v) for v in image.shape)
        data_shape = image_shape
        finite_fraction: float | None = None
        nonzero_voxels: int | None = None

        if len(data_shape) == 4 and data_shape[-1] == 1:
            data_shape = data_shape[:3]
        if len(data_shape) != 3:
            raise ValueError(f"{key} must be a single 3D volume")
        if tuple(int(v) for v in data_shape[:3]) != reference_shape:
            warnings.append(f"{key} shape does not match {reference_key}")
        if not np.allclose(image.affine, reference_affine, atol=1e-3):
            warnings.append(f"{key} affine does not match {reference_key}")

        if QC_PROFILE == "strict":
            data = np.asanyarray(image.dataobj)
            if data.ndim == 4 and data.shape[-1] == 1:
                data = np.squeeze(data, axis=-1)
            finite_fraction = float(np.mean(np.isfinite(data)))
            if finite_fraction < 0.999:
                warnings.append(f"{key} contains non-finite voxels")
            nonzero_voxels = int(np.count_nonzero(data))
            if nonzero_voxels == 0:
                raise ValueError(f"{key} appears empty or all-zero")

        details[key] = {
            "shape": [int(v) for v in data_shape[:3]],
            "spacing_mm": [float(v) for v in image.header.get_zooms()[:3]],
            "dtype": str(image.get_data_dtype()),
            "finite_fraction": finite_fraction,
            "nonzero_voxels": nonzero_voxels,
        }

    return {
        "reference_modality": reference_key,
        "modalities": details,
        "warnings": warnings,
        "qc_profile": QC_PROFILE,
        "intended_use": "research_demo_segmentation_not_diagnosis",
    }


def _region_stats(seg_path: Path) -> dict[str, Any]:
    image = nib.load(str(seg_path))
    data = np.asanyarray(image.dataobj)
    if data.ndim == 4 and data.shape[-1] == 1:
        data = np.squeeze(data, axis=-1)

    voxel_volume_ml = float(np.prod(image.header.get_zooms()[:3])) / 1000.0
    label_regions = []
    for label_id, name in LABELS.items():
        voxels = int(np.count_nonzero(data == label_id))
        label_regions.append(
            {
                "label_id": label_id,
                "region": name,
                "voxel_count": voxels,
                "volume_ml": voxels * voxel_volume_ml,
            }
        )

    derived_regions = []
    for region, labels in DERIVED_REGIONS.items():
        voxels = int(np.count_nonzero(np.isin(data, labels)))
        derived_regions.append(
            {
                "region": region,
                "label_ids": list(labels),
                "voxel_count": voxels,
                "volume_ml": voxels * voxel_volume_ml,
            }
        )

    return {
        "label_schema": LABELS,
        "derived_region_schema": {key: list(value) for key, value in DERIVED_REGIONS.items()},
        "voxel_volume_ml": voxel_volume_ml,
        "label_regions": label_regions,
        "derived_regions": derived_regions,
    }


def _write_volumes_csv(path: Path, stats: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["kind", "region", "label_ids", "voxel_count", "volume_ml"])
        writer.writeheader()
        for row in stats["label_regions"]:
            writer.writerow(
                {
                    "kind": "label",
                    "region": row["region"],
                    "label_ids": row["label_id"],
                    "voxel_count": row["voxel_count"],
                    "volume_ml": f"{row['volume_ml']:.6f}",
                }
            )
        for row in stats["derived_regions"]:
            writer.writerow(
                {
                    "kind": "derived",
                    "region": row["region"],
                    "label_ids": ",".join(str(v) for v in row["label_ids"]),
                    "voxel_count": row["voxel_count"],
                    "volume_ml": f"{row['volume_ml']:.6f}",
                }
            )


def _normalize_uint8(data: np.ndarray) -> np.ndarray:
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return np.zeros(data.shape, dtype=np.uint8)
    low, high = np.percentile(finite, [1, 99])
    if high <= low:
        return np.zeros(data.shape, dtype=np.uint8)
    return ((np.clip(data, low, high) - low) / (high - low) * 255.0).astype(np.uint8)


def _write_preview(image_path: Path, seg_path: Path, output_path: Path) -> None:
    image = nib.load(str(image_path))
    seg = nib.load(str(seg_path))
    image_data = np.asanyarray(image.dataobj)
    seg_data = np.asanyarray(seg.dataobj)
    if image_data.ndim == 4 and image_data.shape[-1] == 1:
        image_data = np.squeeze(image_data, axis=-1)
    if seg_data.ndim == 4 and seg_data.shape[-1] == 1:
        seg_data = np.squeeze(seg_data, axis=-1)
    if image_data.shape[:3] != seg_data.shape[:3]:
        return

    mask = seg_data > 0
    slice_index = int(np.round(np.mean(np.argwhere(mask)[:, 2]))) if mask.any() else int(image_data.shape[2] // 2)
    base = _normalize_uint8(np.asarray(image_data[:, :, slice_index], dtype=np.float32))
    rgb = np.stack([base, base, base], axis=-1)
    colors = {
        1: np.array([255, 120, 80], dtype=np.uint8),
        2: np.array([80, 180, 255], dtype=np.uint8),
        3: np.array([255, 80, 160], dtype=np.uint8),
        4: np.array([170, 120, 255], dtype=np.uint8),
    }
    seg_slice = np.asarray(seg_data[:, :, slice_index])
    for label_id, color in colors.items():
        region_mask = seg_slice == label_id
        rgb[region_mask] = (0.45 * rgb[region_mask] + 0.55 * color).astype(np.uint8)
    Image.fromarray(np.rot90(rgb), mode="RGB").save(output_path)


def _resolve_runtime_engine(requested: str) -> str:
    engine = requested.strip().lower()
    aliases = {
        "dataset802": "nnunetv2",
        "unified": "nnunetv2",
        "nnunet": "nnunetv2",
    }
    return aliases.get(engine, engine)


def _run_nnunetv2_prediction(
    *,
    modalities: dict[str, str],
    output_dir: Path,
    overwrite: bool,
    requested_mode: str,
) -> tuple[Path, dict[str, float], dict[str, Any]]:
    missing = [key for key in NNUNET_CHANNEL_ORDER if key not in modalities]
    if missing:
        raise ValueError(
            "Dataset802 unified prediction requires t1n, t1c, t2w, and t2f inputs; "
            f"missing: {', '.join(missing)}"
        )
    missing_env = [
        name
        for name, value in {
            "nnUNet_raw": NNUNET_RAW,
            "nnUNet_preprocessed": NNUNET_PREPROCESSED,
            "nnUNet_results": NNUNET_RESULTS,
        }.items()
        if not value
    ]
    if missing_env:
        raise RuntimeError("nnU-Net prediction environment is incomplete; missing " + ", ".join(missing_env))

    case_id = _safe_case_id(modalities)
    input_dir = output_dir / "nnunet_imagesTs"
    prediction_dir = output_dir / "nnunet_predictions"
    input_dir.mkdir(parents=True, exist_ok=True)
    prediction_dir.mkdir(parents=True, exist_ok=True)

    for channel_index, key in enumerate(NNUNET_CHANNEL_ORDER):
        target = input_dir / f"{case_id}_{channel_index:04d}.nii.gz"
        if target.exists() and not overwrite:
            raise FileExistsError(f"nnU-Net input already exists and overwrite=false: {target.name}")
        shutil.copy2(modalities[key], target)

    mode = requested_mode if requested_mode in {"fast", "full"} else ("fast" if FAST_MODE_DEFAULT else "full")
    command = [
        NNUNET_BIN,
        "-i",
        str(input_dir),
        "-o",
        str(prediction_dir),
        "-d",
        NNUNET_DATASET,
        "-c",
        NNUNET_CONFIGURATION,
        "-f",
        NNUNET_FOLD,
        "-tr",
        NNUNET_TRAINER,
        "-p",
        NNUNET_PLANS,
        "-chk",
        NNUNET_CHECKPOINT,
        "-device",
        DEVICE,
    ]
    if mode == "fast":
        command.append("--disable_tta")

    env = dict(os.environ)
    env.update(
        {
            "nnUNet_raw": NNUNET_RAW,
            "nnUNet_preprocessed": NNUNET_PREPROCESSED,
            "nnUNet_results": NNUNET_RESULTS,
        }
    )
    timing: dict[str, float] = {}
    t0 = time.time()
    completed = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
    timing["nnunetv2_predict_s"] = time.time() - t0
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "no nnU-Net output"
        raise RuntimeError(f"nnUNetv2_predict failed: {details}")

    predicted = prediction_dir / f"{case_id}.nii.gz"
    if not predicted.exists():
        candidates = sorted(prediction_dir.glob("*.nii.gz"))
        if len(candidates) == 1:
            predicted = candidates[0]
        else:
            raise RuntimeError("nnUNetv2_predict did not create a unique prediction NIfTI")

    seg_path = output_dir / "seg.nii.gz"
    if seg_path.exists() and not overwrite:
        raise FileExistsError("seg.nii.gz already exists and overwrite=false")
    shutil.copy2(predicted, seg_path)

    metadata = {
        "inference_mode": mode,
        "channel_order": list(NNUNET_CHANNEL_ORDER),
        "nnunet": {
            "dataset": NNUNET_DATASET,
            "configuration": NNUNET_CONFIGURATION,
            "trainer": NNUNET_TRAINER,
            "plans": NNUNET_PLANS,
            "fold": NNUNET_FOLD,
            "checkpoint": NNUNET_CHECKPOINT,
            "disable_tta": mode == "fast",
        },
    }
    return seg_path, timing, metadata


def _run_nnunetv2_fast_prediction(
    *,
    modalities: dict[str, str],
    output_dir: Path,
    overwrite: bool,
    requested_mode: str,
) -> tuple[Path, dict[str, float], dict[str, Any]]:
    missing = [key for key in NNUNET_CHANNEL_ORDER if key not in modalities]
    if missing:
        raise ValueError(
            "Dataset802 unified prediction requires t1n, t1c, t2w, and t2f inputs; "
            f"missing: {', '.join(missing)}"
        )

    mode = requested_mode if requested_mode in {"fast", "full"} else ("fast" if FAST_MODE_DEFAULT else "full")
    runtime = _load_fast_runtime()
    predictor = _get_nnunet_fast_predictor(mode)
    reader = runtime["SimpleITKIO"]()
    sitk = runtime["sitk"]

    timing: dict[str, float] = {}
    t0 = time.time()
    t_read = time.time()
    image, props = reader.read_images([modalities[key] for key in NNUNET_CHANNEL_ORDER])
    timing["read_images_s"] = time.time() - t_read

    t_infer = time.time()
    segmentation, crop_s, norm_s, pre_resample_s, network_s, logit_s, post_resample_s = predictor.inference(
        image,
        props,
        use_softmax=True,
    )
    timing.update(
        {
            "crop_s": float(crop_s),
            "normalize_s": float(norm_s),
            "preprocess_resample_s": float(pre_resample_s),
            "network_s": float(network_s),
            "logit_to_seg_s": float(logit_s),
            "postprocess_resample_s": float(post_resample_s),
            "fast_inference_s": time.time() - t_infer,
        }
    )

    seg_path = output_dir / "seg.nii.gz"
    if seg_path.exists() and not overwrite:
        raise FileExistsError("seg.nii.gz already exists and overwrite=false")
    t_write = time.time()
    seg_img = sitk.GetImageFromArray(segmentation.numpy())
    seg_img.SetSpacing(props["sitk_stuff"]["spacing"])
    seg_img.SetOrigin(props["sitk_stuff"]["origin"])
    seg_img.SetDirection(props["sitk_stuff"]["direction"])
    sitk.WriteImage(seg_img, str(seg_path))
    timing["write_seg_s"] = time.time() - t_write
    timing["nnunetv2_fast_pipeline_s"] = time.time() - t0

    metadata = {
        "inference_mode": mode,
        "channel_order": list(NNUNET_CHANNEL_ORDER),
        "nnunet_runtime": "fast",
        "nnunet": {
            "dataset": NNUNET_DATASET,
            "configuration": NNUNET_CONFIGURATION,
            "trainer": NNUNET_TRAINER,
            "plans": NNUNET_PLANS,
            "fold": NNUNET_FOLD,
            "checkpoint": NNUNET_CHECKPOINT,
            "model_dir_configured": _maybe_nnunet_model_dir() is not None,
            "use_mirroring": mode == "full",
            "perform_everything_on_device": DEVICE == "cuda",
        },
    }
    return seg_path, timing, metadata


def _predict(payload: dict[str, Any]) -> dict[str, Any]:
    modalities, output_dir, warnings = _validate_payload(payload)
    overwrite = bool(payload.get("overwrite", True))
    model_id = str(payload.get("model_id") or MODEL_ID)
    engine = _resolve_runtime_engine(str(payload.get("engine") or ENGINE or "nnunetv2"))
    requested_mode = str(payload.get("mode") or ("fast" if FAST_MODE_DEFAULT else "full")).lower()
    use_resencl = "resenc" in model_id.lower()
    seg_path = output_dir / "seg.nii.gz"
    if seg_path.exists() and not overwrite:
        raise FileExistsError("seg.nii.gz already exists and overwrite=false")

    qc = _qc_modalities(modalities, warnings)
    timing: dict[str, float] = {}
    prediction_metadata: dict[str, Any]
    with _infer_lock:
        if engine == "nnunetv2":
            if NNUNET_RUNTIME == "fast":
                seg_path, timing, prediction_metadata = _run_nnunetv2_fast_prediction(
                    modalities=modalities,
                    output_dir=output_dir,
                    overwrite=overwrite,
                    requested_mode=requested_mode,
                )
            elif NNUNET_RUNTIME == "cli":
                seg_path, timing, prediction_metadata = _run_nnunetv2_prediction(
                    modalities=modalities,
                    output_dir=output_dir,
                    overwrite=overwrite,
                    requested_mode=requested_mode,
                )
                prediction_metadata["nnunet_runtime"] = "cli"
            else:
                raise ValueError("CLINAGENT_TUMOR_SEGMENTATION_NNUNET_RUNTIME must be fast or cli")
        elif engine == "gliomoda":
            mode, channel_order = _resolve_mode(modalities)
            t0 = time.time()
            inferer = _get_inferer()
            inferer.infer(
                t1c=modalities.get("t1c"),
                t2f=modalities.get("t2f"),
                t1n=modalities.get("t1n"),
                t2w=modalities.get("t2w"),
                segmentation_file=seg_path,
                use_ResEncL=use_resencl,
            )
            timing["gliomoda_pipeline_s"] = time.time() - t0
            prediction_metadata = {"inference_mode": mode, "channel_order": channel_order}
        elif engine == "fast":
            mode, channel_order = _resolve_mode(modalities)
            t0 = time.time()
            runtime = _load_fast_runtime()
            predictor = _get_fast_predictor(mode, use_resencl)
            reader = runtime["SimpleITKIO"]()
            sitk = runtime["sitk"]
            t_read = time.time()
            image, props = reader.read_images([modalities[key] for key in channel_order])
            timing["read_images_s"] = time.time() - t_read
            t_infer = time.time()
            segmentation, crop_s, norm_s, pre_resample_s, network_s, logit_s, post_resample_s = predictor.inference(
                image,
                props,
                use_softmax=True,
            )
            timing.update(
                {
                    "crop_s": float(crop_s),
                    "normalize_s": float(norm_s),
                    "preprocess_resample_s": float(pre_resample_s),
                    "network_s": float(network_s),
                    "logit_to_seg_s": float(logit_s),
                    "postprocess_resample_s": float(post_resample_s),
                    "fast_inference_s": time.time() - t_infer,
                }
            )
            t_write = time.time()
            seg_img = sitk.GetImageFromArray(segmentation.numpy())
            seg_img.SetSpacing(props["sitk_stuff"]["spacing"])
            seg_img.SetOrigin(props["sitk_stuff"]["origin"])
            seg_img.SetDirection(props["sitk_stuff"]["direction"])
            sitk.WriteImage(seg_img, str(seg_path))
            timing["write_seg_s"] = time.time() - t_write
            timing["fast_pipeline_s"] = time.time() - t0
            prediction_metadata = {"inference_mode": mode, "channel_order": channel_order}
        else:
            raise ValueError("engine must be nnunetv2, fast, or gliomoda")

    if not seg_path.exists():
        raise RuntimeError("Tumor segmentation engine did not create seg.nii.gz")

    stats = _region_stats(seg_path)
    tumor_regions_path = output_dir / "tumor_regions.json"
    volumes_csv_path = output_dir / "volumes.csv"
    preview_path = output_dir / "overlay_preview.png"
    qc_summary_path = output_dir / "qc_summary.json"
    reference_path = Path(modalities.get("t1c") or modalities.get("t2f") or next(iter(modalities.values())))

    tumor_regions = {**stats, "qc": qc, "model_id": model_id}
    tumor_regions_path.write_text(json.dumps(tumor_regions, indent=2, default=_json_default), encoding="utf-8")
    qc_summary_path.write_text(json.dumps(qc, indent=2, default=_json_default), encoding="utf-8")
    _write_volumes_csv(volumes_csv_path, stats)
    _write_preview(reference_path, seg_path, preview_path)

    return {
        "ok": True,
        "status": "success",
        "model_id": model_id,
        "model_family": "Dataset802 unified glioma nnU-Net v2" if engine == "nnunetv2" else "GlioMODA nnU-Net v2",
        "engine": engine,
        "nnunet_runtime": prediction_metadata.get("nnunet_runtime"),
        "service_version": SERVICE_VERSION,
        **prediction_metadata,
        "seg_path": str(seg_path),
        "segmentation_path": str(seg_path),
        "tumor_regions_path": str(tumor_regions_path),
        "volumes_csv_path": str(volumes_csv_path),
        "overlay_preview_path": str(preview_path),
        "qc_summary_path": str(qc_summary_path),
        "warnings": qc["warnings"],
        "timing": {key: round(value, 4) for key, value in timing.items()},
        "derived_regions": stats["derived_regions"],
        "intended_use": "research_demo_segmentation_not_diagnosis",
    }


def _configured_warmup_modalities() -> dict[str, str] | None:
    if not WARMUP_MODALITIES_JSON:
        return None
    path = Path(WARMUP_MODALITIES_JSON).expanduser()
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_modalities = payload.get("modalities") if isinstance(payload, dict) and isinstance(payload.get("modalities"), dict) else payload
    if not isinstance(raw_modalities, dict):
        raise ValueError("Warmup modalities configuration must be a JSON object")
    modalities = {key: str(raw_modalities.get(key) or "") for key in MODALITIES}
    if any(not modalities[key] for key in MODALITIES):
        raise ValueError("Warmup modalities configuration requires t1n, t1c, t2w, and t2f")
    if any(not Path(value).expanduser().is_file() for value in modalities.values()):
        raise ValueError("One or more configured warmup modality files are unavailable")
    return modalities


def _warmup_model() -> None:
    started = time.time()
    _set_readiness(
        status="loading",
        service_ready=False,
        warmup_started_at=started,
        warmup_error=None,
    )
    if not WARMUP_ON_START:
        _set_readiness(
            status="ready",
            service_ready=True,
            model_loaded=_persistent_model_loaded(),
            warmup_level="disabled",
            warmup_completed_at=time.time(),
            warmup_duration_s=0.0,
        )
        return
    try:
        if ENGINE == "nnunetv2":
            if NNUNET_RUNTIME == "fast":
                _get_nnunet_fast_predictor("fast" if FAST_MODE_DEFAULT else "full")
            elif NNUNET_RUNTIME != "cli":
                raise ValueError("CLINAGENT_TUMOR_SEGMENTATION_NNUNET_RUNTIME must be fast or cli")
        elif ENGINE == "fast":
            _get_fast_predictor("t1c-t2f-t1n-t2w", "resenc" in MODEL_ID.lower())
        elif ENGINE == "gliomoda":
            _get_inferer()
        else:
            raise ValueError("engine must be nnunetv2, fast, or gliomoda")

        warmup_level = "model_loaded" if _persistent_model_loaded() else "runtime_checked"
        modalities = _configured_warmup_modalities()
        if modalities:
            with tempfile.TemporaryDirectory(prefix="clinagent-warmup-", dir=OUTPUT_ROOT) as output_dir:
                _predict(
                    {
                        "modalities": modalities,
                        "output_dir": output_dir,
                        "model_id": MODEL_ID,
                        "engine": ENGINE,
                        "mode": "fast",
                        "overwrite": True,
                    }
                )
            warmup_level = "full_inference"

        completed = time.time()
        _set_readiness(
            status="ready",
            service_ready=True,
            model_loaded=_persistent_model_loaded(),
            warmup_level=warmup_level,
            warmup_completed_at=completed,
            warmup_duration_s=round(completed - started, 3),
        )
        print(
            f"Warmup complete: level={warmup_level} model_loaded={_persistent_model_loaded()} "
            f"duration_s={completed - started:.3f}",
            flush=True,
        )
    except Exception:
        traceback.print_exc()
        completed = time.time()
        _set_readiness(
            status="failed",
            service_ready=False,
            model_loaded=_persistent_model_loaded(),
            warmup_level="failed",
            warmup_completed_at=completed,
            warmup_duration_s=round(completed - started, 3),
            warmup_error="Model warmup failed; review service logs.",
        )


def _health_payload() -> dict[str, Any]:
    readiness = _readiness_snapshot()
    return {
        "ok": bool(readiness["service_ready"]),
        **readiness,
        "engine": ENGINE,
        "nnunet_runtime": NNUNET_RUNTIME,
        "model_id": MODEL_ID,
        "device": DEVICE,
        "gpu_id": GPU_ID,
        "service_version": SERVICE_VERSION,
        "qc_profile": QC_PROFILE,
        "fast_mode_default": FAST_MODE_DEFAULT,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "ClinAgentGlioMODA/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} {fmt % args}", flush=True)

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/live":
            _send_json(self, 200, {"ok": True, "status": "alive", "service_version": SERVICE_VERSION})
            return
        if not _require_auth(self):
            return
        if self.path.rstrip("/") == "/health":
            _send_json(self, 200, _health_payload())
            return
        if self.path.rstrip("/") == "/ready":
            payload = _health_payload()
            _send_json(self, 200 if payload["service_ready"] else 503, payload)
            return
        if self.path.rstrip("/") == "/model-info":
            _send_json(
                self,
                200,
                {
                    "ok": True,
                    "model_id": MODEL_ID,
                    "model_family": "Dataset802 unified glioma nnU-Net v2" if ENGINE == "nnunetv2" else "GlioMODA nnU-Net v2",
                    "default_engine": ENGINE,
                    "nnunet_runtime": NNUNET_RUNTIME,
                    "architecture": "nnU-Net v2 ResEncUNet" if ENGINE == "nnunetv2" else "nnU-Net v2 PlainConvUNet default; optional ResEncL via model_id containing resenc",
                    "nnunet": {
                        "dataset": NNUNET_DATASET,
                        "configuration": NNUNET_CONFIGURATION,
                        "trainer": NNUNET_TRAINER,
                        "plans": NNUNET_PLANS,
                        "fold": NNUNET_FOLD,
                        "checkpoint": NNUNET_CHECKPOINT,
                        "model_dir_configured": _maybe_nnunet_model_dir() is not None,
                    },
                    "input_modalities": list(MODALITIES),
                    "minimum_supported_modalities": list(MODALITIES) if ENGINE == "nnunetv2" else ["t1c", "t2f"],
                    "labels": LABELS,
                    "derived_regions": DERIVED_REGIONS,
                    "intended_use": "research_demo_segmentation_not_diagnosis",
                    "service_version": SERVICE_VERSION,
                    "readiness": _readiness_snapshot(),
                },
            )
            return
        _send_json(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not _require_auth(self):
            return
        if self.path.rstrip("/") != "/predict":
            _send_json(self, 404, {"ok": False, "error": "not found"})
            return
        if not _readiness_snapshot()["service_ready"]:
            _send_json(
                self,
                503,
                {
                    "ok": False,
                    "error": "Segmentation model is not ready yet.",
                    "status": _readiness_snapshot()["status"],
                    "intended_use": "research_demo_segmentation_not_diagnosis",
                },
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            response = _predict(payload)
            _send_json(self, 200, response)
        except Exception as exc:
            traceback.print_exc()
            _send_json(
                self,
                500,
                {
                    "ok": False,
                    "error": str(exc),
                    "intended_use": "research_demo_segmentation_not_diagnosis",
                },
            )


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Starting {SERVICE_VERSION} on http://{HOST}:{PORT}", flush=True)
    threading.Thread(target=_warmup_model, name="clinagent-tumor-model-warmup", daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
