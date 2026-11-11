"""Brain tumor segmentation service tool and postprocessing helpers."""
from __future__ import annotations

import csv
import json
import os
import shlex
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import nibabel as nib
import numpy as np
from nibabel.processing import resample_from_to
from PIL import Image

from clinagent.families.neuro.tools.base_tool import BaseTool
from clinagent.platform.config import load_settings

MODALITY_KEYS = ("t1n", "t1c", "t2w", "t2f")
MINIMUM_MODALITIES = MODALITY_KEYS

TUMOR_LABELS: dict[int, str] = {
    1: "non_enhancing_core_candidate",
    2: "flair_edema_abnormality",
    3: "enhancing_tumor",
    4: "cavity_or_post_surgical_change",
}

DERIVED_REGIONS: dict[str, tuple[int, ...]] = {
    "whole_tumor": (1, 2, 3),
    "tumor_core": (1, 3),
    "enhancing_tumor": (3,),
    "flair_abnormality": (2,),
    "non_enhancing_core_candidate": (1,),
    "active_tumor_for_rano_primary": (3,),
    "cavity_or_post_surgical_change": (4,),
    "cavity_exclusion": (4,),
}


@dataclass(frozen=True)
class TumorSegmentationInput:
    modalities: dict[str, str]
    output_dir: Path


@dataclass(frozen=True)
class RemoteTumorSegmentationRun:
    remote_host: str
    remote_dir: str
    remote_output_dir: str
    remote_modalities: dict[str, str]


class BrainTumorSegmentationServiceClient:
    """HTTP client for a standalone research/demo glioma segmentation service."""

    def __init__(
        self,
        *,
        service_url: str,
        api_key: str | None = None,
        timeout_s: float = 900.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        normalized = (service_url or "").strip().rstrip("/")
        if not normalized:
            raise ValueError("Tumor segmentation service is not configured")
        self.service_url = normalized
        self.api_key = (api_key or "").strip()
        self.timeout_s = timeout_s
        self.transport = transport

    def check_health(self) -> dict[str, Any]:
        return self._get_json("/health")

    def get_model_info(self) -> dict[str, Any]:
        return self._get_json("/model-info")

    def predict(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("/predict", payload)

    def _get_json(self, path: str) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout_s, transport=self.transport, headers=self._headers()) as client:
            response = client.get(f"{self.service_url}{path}")
            response.raise_for_status()
            return dict(response.json())

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout_s, transport=self.transport, headers=self._headers()) as client:
            response = client.post(f"{self.service_url}{path}", json=payload)
            response.raise_for_status()
            return dict(response.json())

    def _headers(self) -> dict[str, str] | None:
        if not self.api_key:
            return None
        return {"Authorization": f"Bearer {self.api_key}"}


class BrainTumorSegmentationTool(BaseTool):
    """Run an agent-callable research/demo glioma segmentation workflow."""

    def __init__(
        self,
        *,
        service_url: str | None = None,
        timeout_s: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = load_settings()
        self.service_url = (service_url or settings.tumor_segmentation_service_url or "").strip()
        self.timeout_s = float(
            timeout_s if timeout_s is not None else settings.tumor_segmentation_timeout_s
        )
        self.model_id_hint = settings.tumor_segmentation_model_id
        self.api_key = (settings.tumor_segmentation_api_key or os.getenv("BRAIN_TUMOR_SEG_API_KEY", "")).strip()
        self.transport = transport
        self._remote_host = (settings.segmentation_tool_remote_host or "").strip()
        self._remote_root = (settings.segmentation_tool_remote_root or "/tmp/clinagent-segmentation").strip()

    @property
    def name(self) -> str:
        return "brain_tumor_segmentation"

    @property
    def description(self) -> str:
        return (
            "Run research/demo glioma MRI segmentation from multimodal NIfTI inputs and return tumor volumes, "
            "QC warnings, and preview artifacts"
        )

    @property
    def parameters_schema(self) -> dict:
        modality_properties = {
            f"{key}_nifti_path": {
                "type": "string",
                "description": f"Optional absolute path to the {key} NIfTI modality",
            }
            for key in MODALITY_KEYS
        }
        return {
            "type": "object",
            "properties": {
                **modality_properties,
                "output_dir": {
                    "type": "string",
                    "description": "Optional directory for segmentation artifacts",
                },
                "device": {
                    "type": "string",
                    "enum": ["auto", "cuda", "cpu"],
                    "description": "Preferred inference device",
                },
                "model_id": {
                    "type": "string",
                    "description": "Optional service-side model id",
                },
                "mode": {
                    "type": "string",
                    "enum": ["fast", "full"],
                    "description": "Inference mode. fast may disable TTA; full keeps the service default quality settings.",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Whether existing output artifacts may be overwritten",
                },
                "qc_profile": {
                    "type": "string",
                    "enum": ["fast", "strict"],
                    "description": "Input QC depth. fast checks headers/affines; strict also scans voxel arrays.",
                },
                "precomputed_seg_path": {
                    "type": "string",
                    "description": "Optional existing segmentation NIfTI for postprocessing/testing without service inference",
                },
            },
            "additionalProperties": False,
        }

    def check_health(self) -> dict[str, Any]:
        return self._client().check_health()

    def get_model_info(self) -> dict[str, Any]:
        return self._client().get_model_info()

    def run(
        self,
        *,
        t1n_nifti_path: str | None = None,
        t1c_nifti_path: str | None = None,
        t2w_nifti_path: str | None = None,
        t2f_nifti_path: str | None = None,
        output_dir: str | None = None,
        device: str = "auto",
        model_id: str | None = None,
        mode: str | None = None,
        overwrite: bool = True,
        qc_profile: str = "fast",
        precomputed_seg_path: str | None = None,
    ) -> dict[str, Any]:
        prepared = _prepare_inputs(
            {
                "t1n": t1n_nifti_path,
                "t1c": t1c_nifti_path,
                "t2w": t2w_nifti_path,
                "t2f": t2f_nifti_path,
            },
            output_dir=output_dir,
        )
        qc = _run_multimodal_qc(prepared.modalities, profile=qc_profile)
        service_modalities = _harmonize_modalities_to_reference(
            prepared.modalities,
            output_dir=prepared.output_dir,
            reference_key="t1c",
        )
        if service_modalities != prepared.modalities:
            qc.setdefault("warnings", []).append("Input modalities were resampled to the T1c grid before service inference")
            qc["service_modalities"] = {
                key: str(Path(value).name)
                for key, value in service_modalities.items()
            }
        prediction: dict[str, Any]
        health: dict[str, Any] | None = None
        model_info: dict[str, Any] | None = None
        remote_run: RemoteTumorSegmentationRun | None = None

        if precomputed_seg_path:
            prediction = {"seg_path": str(Path(precomputed_seg_path).expanduser().resolve())}
        else:
            client = self._client()
            health = client.check_health()
            model_info = client.get_model_info()
            try:
                remote_run = self._create_remote_run(service_modalities)
                payload = {
                    "modalities": remote_run.remote_modalities if remote_run else service_modalities,
                    "output_dir": remote_run.remote_output_dir if remote_run else str(prepared.output_dir),
                    "device": device,
                    "model_id": (model_id or self.model_id_hint or "default"),
                    "mode": mode or "fast",
                    "overwrite": bool(overwrite),
                }
                prediction = client.predict(payload)
                if remote_run:
                    prediction = self._materialize_remote_prediction(
                        prediction=prediction,
                        remote_run=remote_run,
                        output_dir=prepared.output_dir,
                    )
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(f"Tumor segmentation service prediction failed: {exc}") from exc
            finally:
                if remote_run:
                    self._cleanup_remote_run(remote_run)

        seg_path = _resolve_prediction_segmentation(prediction)
        postprocessed = _postprocess_segmentation(
            seg_path=seg_path,
            reference_image_path=service_modalities.get("t1c") or next(iter(service_modalities.values())),
            output_dir=prepared.output_dir,
            qc=qc,
            overwrite=overwrite,
        )

        return {
            "service_url": self.service_url or None,
            "model_id_hint": model_id or self.model_id_hint or None,
            "mode": "precomputed" if precomputed_seg_path else "service",
            "input_modalities": prepared.modalities,
            "service_modalities": service_modalities,
            "health": health,
            "model_info": model_info,
            "prediction": prediction,
            "remote_staging": {"enabled": remote_run is not None},
            **postprocessed,
        }

    def _client(self) -> BrainTumorSegmentationServiceClient:
        return BrainTumorSegmentationServiceClient(
            service_url=self.service_url,
            api_key=self.api_key,
            timeout_s=self.timeout_s,
            transport=self.transport,
        )

    def _create_remote_run(self, modalities: dict[str, str]) -> RemoteTumorSegmentationRun | None:
        if not self._remote_host:
            return None

        run_id = uuid.uuid4().hex
        remote_dir = f"{self._remote_root.rstrip('/')}/tumor/{run_id}"
        remote_output_dir = f"{remote_dir}/outputs"
        self._run_subprocess(
            ["ssh", self._remote_host, f"mkdir -p {shlex.quote(remote_output_dir)}"],
            "create remote tumor segmentation staging directory",
        )

        remote_modalities: dict[str, str] = {}
        for key, local_path in modalities.items():
            remote_path = f"{remote_dir}/{key}.nii.gz"
            self._run_subprocess(
                ["scp", str(Path(local_path).expanduser().resolve()), f"{self._remote_host}:{remote_path}"],
                f"copy {key} NIfTI to remote tumor segmentation service",
            )
            remote_modalities[key] = remote_path

        return RemoteTumorSegmentationRun(
            remote_host=self._remote_host,
            remote_dir=remote_dir,
            remote_output_dir=remote_output_dir,
            remote_modalities=remote_modalities,
        )

    def _materialize_remote_prediction(
        self,
        *,
        prediction: dict[str, Any],
        remote_run: RemoteTumorSegmentationRun,
        output_dir: Path,
    ) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        materialized = dict(prediction)
        artifact_map = {
            "seg_path": ("seg_path", "seg.nii.gz"),
            "output_seg": ("seg_path", "seg.nii.gz"),
            "segmentation_path": ("seg_path", "seg.nii.gz"),
            "tumor_regions_path": ("service_tumor_regions_path", "service_tumor_regions.json"),
            "volumes_csv_path": ("service_volumes_csv_path", "service_volumes.csv"),
            "overlay_preview_path": ("service_overlay_preview_path", "service_overlay_preview.png"),
            "qc_summary_path": ("service_qc_summary_path", "service_qc_summary.json"),
        }

        remote_seg = (
            prediction.get("seg_path")
            or prediction.get("output_seg")
            or prediction.get("segmentation_path")
            or f"{remote_run.remote_output_dir}/seg.nii.gz"
        )
        materialized["seg_path"] = self._copy_remote_file(
            remote_host=remote_run.remote_host,
            remote_path=str(remote_seg),
            local_path=output_dir / "seg.nii.gz",
            required=True,
        )

        for response_key, (materialized_key, local_name) in artifact_map.items():
            if response_key in {"seg_path", "output_seg", "segmentation_path"}:
                continue
            remote_path = prediction.get(response_key)
            if not remote_path:
                continue
            local_path = self._copy_remote_file(
                remote_host=remote_run.remote_host,
                remote_path=str(remote_path),
                local_path=output_dir / local_name,
                required=False,
            )
            if local_path:
                materialized[materialized_key] = local_path

        return materialized

    def _copy_remote_file(
        self,
        *,
        remote_host: str,
        remote_path: str,
        local_path: Path,
        required: bool,
    ) -> str | None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        exists = subprocess.run(
            ["ssh", remote_host, f"test -f {shlex.quote(remote_path)}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if exists.returncode != 0:
            if required:
                raise RuntimeError(f"Remote tumor segmentation artifact was not created: {Path(remote_path).name}")
            return None
        self._run_subprocess(
            ["scp", f"{remote_host}:{remote_path}", str(local_path)],
            f"copy remote tumor segmentation artifact {Path(remote_path).name}",
        )
        return str(local_path)

    def _cleanup_remote_run(self, remote_run: RemoteTumorSegmentationRun) -> None:
        subprocess.run(
            ["ssh", remote_run.remote_host, f"rm -rf -- {shlex.quote(remote_run.remote_dir)}"],
            check=False,
            capture_output=True,
            text=True,
        )

    @staticmethod
    def _run_subprocess(command: list[str], action: str) -> None:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            details = completed.stderr.strip() or completed.stdout.strip() or "no process output"
            raise RuntimeError(f"Failed to {action}: {details}")


def _prepare_inputs(modality_paths: dict[str, str | None], *, output_dir: str | None) -> TumorSegmentationInput:
    modalities: dict[str, str] = {}
    for key, value in modality_paths.items():
        if not value:
            continue
        path = Path(value).expanduser().resolve()
        if not path.exists():
            raise ValueError(f"{key} NIfTI does not exist: {path}")
        modalities[key] = str(path)

    missing_minimum = [key for key in MINIMUM_MODALITIES if key not in modalities]
    if missing_minimum:
        raise ValueError(
            "Unified glioma segmentation requires t1n, t1c, t2w, and t2f NIfTI inputs; "
            f"missing: {', '.join(missing_minimum)}"
        )

    if output_dir:
        target_dir = Path(output_dir).expanduser().resolve()
    else:
        target_dir = Path(next(iter(modalities.values()))).parent / f"tumor_segmentation_{uuid.uuid4().hex[:8]}"
    target_dir.mkdir(parents=True, exist_ok=True)
    return TumorSegmentationInput(modalities=modalities, output_dir=target_dir)


def _run_multimodal_qc(modalities: dict[str, str], *, profile: str = "fast") -> dict[str, Any]:
    if profile not in {"fast", "strict"}:
        raise ValueError("qc_profile must be 'fast' or 'strict'")

    warnings: list[str] = []
    missing_modalities = [key for key in MODALITY_KEYS if key not in modalities]
    for key in missing_modalities:
        warnings.append(f"Missing optional modality: {key}")

    reference_key = "t1c" if "t1c" in modalities else next(iter(modalities))
    reference_img = nib.load(modalities[reference_key])
    reference_shape = tuple(int(v) for v in reference_img.shape[:3])
    reference_affine = reference_img.affine
    modality_qc: dict[str, Any] = {}

    for key, path in modalities.items():
        image = nib.load(path)
        image_shape = tuple(int(v) for v in image.shape)
        data_shape = image_shape
        finite_fraction: float | None = None
        nonzero_voxels: int | None = None

        if len(data_shape) == 4 and data_shape[-1] == 1:
            data_shape = data_shape[:3]
        if len(data_shape) != 3:
            raise ValueError(f"{key} must be a single 3D NIfTI volume, got shape {tuple(image.shape)}")
        if tuple(int(v) for v in data_shape[:3]) != reference_shape:
            warnings.append(f"{key} shape does not match {reference_key}")
        if not np.allclose(image.affine, reference_affine, atol=1e-3):
            warnings.append(f"{key} affine does not match {reference_key}")

        if profile == "strict":
            data = np.asanyarray(image.dataobj)
            if data.ndim == 4 and data.shape[-1] == 1:
                data = np.squeeze(data, axis=-1)
            finite_fraction = float(np.mean(np.isfinite(data)))
            if finite_fraction < 0.999:
                warnings.append(f"{key} contains non-finite voxels")
            nonzero_voxels = int(np.count_nonzero(data))
            if nonzero_voxels == 0:
                raise ValueError(f"{key} appears empty or all-zero")

        modality_qc[key] = {
            "path": str(Path(path).name),
            "shape": [int(v) for v in data_shape[:3]],
            "spacing_mm": [float(v) for v in image.header.get_zooms()[:3]],
            "dtype": str(image.get_data_dtype()),
            "finite_fraction": finite_fraction,
            "nonzero_voxels": nonzero_voxels,
        }

    return {
        "reference_modality": reference_key,
        "missing_modalities": missing_modalities,
        "warnings": warnings,
        "modalities": modality_qc,
        "qc_profile": profile,
        "intended_use": "research_demo_segmentation_not_diagnosis",
    }


def _harmonize_modalities_to_reference(
    modalities: dict[str, str],
    *,
    output_dir: Path,
    reference_key: str,
) -> dict[str, str]:
    if not modalities:
        return modalities

    selected_reference = reference_key if reference_key in modalities else next(iter(modalities))
    reference_img = nib.load(modalities[selected_reference])
    reference_shape = tuple(int(value) for value in reference_img.shape[:3])
    reference_affine = reference_img.affine
    harmonized: dict[str, str] = {}
    resampled_dir = output_dir / "service_inputs"

    for key, path in modalities.items():
        image = nib.load(path)
        image_shape = tuple(int(value) for value in image.shape[:3])
        same_grid = image_shape == reference_shape and np.allclose(image.affine, reference_affine, atol=1e-3)
        if same_grid:
            harmonized[key] = path
            continue

        resampled_dir.mkdir(parents=True, exist_ok=True)
        resampled_img = resample_from_to(image, reference_img, order=1)
        data = np.asanyarray(resampled_img.dataobj).astype(np.float32, copy=False)
        out_path = resampled_dir / f"{key}.nii.gz"
        header = reference_img.header.copy()
        header.set_data_dtype(np.float32)
        nib.save(nib.Nifti1Image(data, reference_affine, header), str(out_path))
        harmonized[key] = str(out_path.resolve())

    return harmonized


def _resolve_prediction_segmentation(prediction: dict[str, Any]) -> Path:
    value = prediction.get("seg_path") or prediction.get("output_seg") or prediction.get("segmentation_path")
    if not value:
        raise ValueError("Tumor segmentation service response did not include seg_path/output_seg")
    path = Path(str(value)).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Tumor segmentation output does not exist: {path}")
    return path


def _postprocess_segmentation(
    *,
    seg_path: Path,
    reference_image_path: str,
    output_dir: Path,
    qc: dict[str, Any],
    overwrite: bool,
) -> dict[str, Any]:
    seg_img = nib.load(str(seg_path))
    seg_data = np.asanyarray(seg_img.dataobj)
    if seg_data.ndim == 4 and seg_data.shape[-1] == 1:
        seg_data = np.squeeze(seg_data, axis=-1)
    if seg_data.ndim != 3:
        raise ValueError(f"Tumor segmentation must be 3D, got shape {tuple(seg_img.shape)}")

    label_values = sorted(int(v) for v in np.unique(seg_data) if int(v) != 0)
    unknown_labels = [v for v in label_values if v not in TUMOR_LABELS]
    warnings = list(qc.get("warnings", []))
    if unknown_labels:
        warnings.append(f"Segmentation contains unknown labels: {unknown_labels}")
    if not label_values:
        warnings.append("Segmentation contains no nonzero tumor labels")

    voxel_volume_ml = float(np.prod(seg_img.header.get_zooms()[:3])) / 1000.0
    label_regions = _label_region_stats(seg_data, voxel_volume_ml)
    derived_regions = _derived_region_stats(seg_data, voxel_volume_ml)

    tumor_regions_path = output_dir / "tumor_regions.json"
    volumes_csv_path = output_dir / "volumes.csv"
    overlay_preview_path = output_dir / "overlay_preview.png"

    _guard_output(tumor_regions_path, overwrite)
    _guard_output(volumes_csv_path, overwrite)
    _guard_output(overlay_preview_path, overwrite)

    region_payload = {
        "label_schema": TUMOR_LABELS,
        "derived_region_schema": {key: list(value) for key, value in DERIVED_REGIONS.items()},
        "voxel_volume_ml": voxel_volume_ml,
        "label_regions": label_regions,
        "derived_regions": derived_regions,
        "qc": {**qc, "warnings": warnings},
    }
    tumor_regions_path.write_text(json.dumps(region_payload, indent=2), encoding="utf-8")
    _write_volumes_csv(volumes_csv_path, label_regions=label_regions, derived_regions=derived_regions)
    _write_overlay_preview(
        image_path=Path(reference_image_path),
        seg_path=seg_path,
        output_path=overlay_preview_path,
    )

    return {
        "seg_path": str(seg_path),
        "tumor_regions_path": str(tumor_regions_path),
        "volumes_csv_path": str(volumes_csv_path),
        "overlay_preview_path": str(overlay_preview_path),
        "qc": {**qc, "warnings": warnings},
        "label_regions": label_regions,
        "derived_regions": derived_regions,
    }


def _label_region_stats(seg_data: np.ndarray, voxel_volume_ml: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label_id, name in TUMOR_LABELS.items():
        voxels = int(np.count_nonzero(seg_data == label_id))
        rows.append(
            {
                "region": name,
                "label_id": label_id,
                "voxel_count": voxels,
                "volume_ml": voxels * voxel_volume_ml,
            }
        )
    return rows


def _derived_region_stats(seg_data: np.ndarray, voxel_volume_ml: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for region, labels in DERIVED_REGIONS.items():
        voxels = int(np.count_nonzero(np.isin(seg_data, labels)))
        rows.append(
            {
                "region": region,
                "label_ids": list(labels),
                "voxel_count": voxels,
                "volume_ml": voxels * voxel_volume_ml,
            }
        )
    return rows


def _write_volumes_csv(
    path: Path,
    *,
    label_regions: list[dict[str, Any]],
    derived_regions: list[dict[str, Any]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["kind", "region", "label_ids", "voxel_count", "volume_ml"])
        writer.writeheader()
        for row in label_regions:
            writer.writerow(
                {
                    "kind": "label",
                    "region": row["region"],
                    "label_ids": row["label_id"],
                    "voxel_count": row["voxel_count"],
                    "volume_ml": f"{row['volume_ml']:.6f}",
                }
            )
        for row in derived_regions:
            writer.writerow(
                {
                    "kind": "derived",
                    "region": row["region"],
                    "label_ids": ",".join(str(v) for v in row["label_ids"]),
                    "voxel_count": row["voxel_count"],
                    "volume_ml": f"{row['volume_ml']:.6f}",
                }
            )


def _write_overlay_preview(*, image_path: Path, seg_path: Path, output_path: Path) -> None:
    image = nib.load(str(image_path))
    seg = nib.load(str(seg_path))
    image_data = np.asanyarray(image.dataobj)
    seg_data = np.asanyarray(seg.dataobj)
    if image_data.ndim == 4 and image_data.shape[-1] == 1:
        image_data = np.squeeze(image_data, axis=-1)
    if seg_data.ndim == 4 and seg_data.shape[-1] == 1:
        seg_data = np.squeeze(seg_data, axis=-1)

    mask = seg_data > 0
    if mask.any():
        slice_index = int(np.round(np.mean(np.argwhere(mask)[:, 2])))
    else:
        slice_index = int(image_data.shape[2] // 2)

    base_slice = np.asarray(image_data[:, :, slice_index], dtype=np.float32)
    seg_slice = np.asarray(seg_data[:, :, slice_index])
    base = _normalize_to_uint8(base_slice)
    rgb = np.stack([base, base, base], axis=-1)
    overlay_colors = {
        1: np.array([255, 120, 80], dtype=np.uint8),
        2: np.array([80, 180, 255], dtype=np.uint8),
        3: np.array([255, 80, 160], dtype=np.uint8),
        4: np.array([170, 120, 255], dtype=np.uint8),
    }
    for label_id, color in overlay_colors.items():
        region_mask = seg_slice == label_id
        rgb[region_mask] = (0.45 * rgb[region_mask] + 0.55 * color).astype(np.uint8)
    preview = Image.fromarray(np.rot90(rgb), mode="RGB")
    preview.save(output_path)


def _normalize_to_uint8(data: np.ndarray) -> np.ndarray:
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return np.zeros(data.shape, dtype=np.uint8)
    low, high = np.percentile(finite, [1, 99])
    if high <= low:
        high = float(np.max(finite))
        low = float(np.min(finite))
    if high <= low:
        return np.zeros(data.shape, dtype=np.uint8)
    clipped = np.clip(data, low, high)
    return ((clipped - low) / (high - low) * 255.0).astype(np.uint8)


def _guard_output(path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists and overwrite is false: {path}")
