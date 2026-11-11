"""NIfTI registration with explicit translation and SimpleITK rigid modes.

Both modes persist moving-RAS-to-fixed-RAS transforms and share resampling/QC.
The low-level default remains translation for existing lightweight callers;
the Brain Tumor workflow explicitly selects full rigid registration.
"""
from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Literal

import nibabel as nib
import numpy as np
from scipy import ndimage


InterpolationMode = Literal["linear", "nearest"]
InitializationMode = Literal["header", "center", "com"]


def coregister_sequences(
    *,
    fixed_image_path: str | Path,
    moving_image_path: str | Path,
    output_dir: str | Path,
    case_id: str | None = None,
    fixed_label: str = "fixed",
    moving_label: str = "moving",
    initialization: InitializationMode = "com",
    interpolation: InterpolationMode = "linear",
    overwrite: bool = True,
    method: Literal["translation", "rigid"] = "translation",
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Align a moving NIfTI volume to a fixed NIfTI grid and write outputs.

    Initialize from headers, grid centers or foreground center of mass. Rigid
    mode then optimizes three rotations and three translations. Resample onto
    the fixed grid and persist the moving-to-fixed world transform.
    """

    fixed_path = _resolve_existing_file(fixed_image_path, "fixed_image_path")
    moving_path = _resolve_existing_file(moving_image_path, "moving_image_path")
    target_dir = Path(output_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    fixed = _load_3d_nifti(fixed_path)
    moving = _load_3d_nifti(moving_path)
    fixed_data = np.asanyarray(fixed.dataobj)
    moving_data = np.asanyarray(moving.dataobj)

    started = time.monotonic()
    moving_to_fixed = _estimate_world_translation(
        fixed=fixed,
        fixed_data=fixed_data,
        moving=moving,
        moving_data=moving_data,
        initialization=initialization,
    )
    backend_meta = {"backend": "nibabel_scipy_translation_v1", "deformation_model": "translation_affine_only"}
    if method == "rigid":
        from .rigid import estimate_rigid
        moving_to_fixed, backend_meta = estimate_rigid(fixed, moving, moving_to_fixed, progress)
    elif method != "translation":
        raise ValueError("Registration method must be rigid or translation.")
    resampled = _resample_to_reference(
        source_data=moving_data,
        source_affine=moving_to_fixed @ moving.affine,
        reference=fixed,
        interpolation=interpolation,
    )

    output_image_path = target_dir / f"{_nifti_stem(moving_path)}_to_{_nifti_stem(fixed_path)}.nii.gz"
    transform_path = target_dir / f"{_nifti_stem(moving_path)}_to_{_nifti_stem(fixed_path)}_transform.json"
    if not overwrite and (output_image_path.exists() or transform_path.exists()):
        raise FileExistsError(f"Registration output already exists under {target_dir}")

    output_image = nib.Nifti1Image(_coerce_output_dtype(resampled, moving_data, interpolation), fixed.affine, fixed.header)
    output_image.set_data_dtype(np.asanyarray(output_image.dataobj).dtype)
    nib.save(output_image, str(output_image_path))

    before = _resample_to_reference(
        source_data=moving_data,
        source_affine=moving.affine,
        reference=fixed,
        interpolation=interpolation,
    )
    qc = _build_registration_qc(
        fixed_data=fixed_data,
        before_data=before,
        after_data=resampled,
        moving_to_fixed=moving_to_fixed,
        fixed=fixed,
        moving=moving,
    )
    qc.update(backend_meta)
    qc["registration_runtime_sec"] = time.monotonic() - started
    transform_payload = {
        "id": uuid.uuid4().hex,
        "type": method,
        "backend": backend_meta["backend"],
        "initialization": initialization,
        "source_image": str(moving_path),
        "target_image": str(fixed_path),
        "source_label": moving_label,
        "target_label": fixed_label,
        "matrix_convention": "moving_world_to_fixed_world",
        "moving_to_fixed_world_affine": _matrix_to_list(moving_to_fixed),
        "translation_mm": _matrix_to_list(moving_to_fixed)[0][3:4]
        + _matrix_to_list(moving_to_fixed)[1][3:4]
        + _matrix_to_list(moving_to_fixed)[2][3:4],
    }
    transform_path.write_text(json.dumps(transform_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "status": "ok",
        "operation": "coregister_sequences",
        "case_id": case_id,
        "fixed_image_path": str(fixed_path),
        "moving_image_path": str(moving_path),
        "output_image_path": str(output_image_path),
        "transform_path": str(transform_path),
        "transform": transform_payload,
        "qc": qc,
        "manifest_fragment": _manifest_fragment(
            case_id=case_id,
            operation="coregister_sequences",
            inputs=[str(fixed_path), str(moving_path)],
            outputs=[str(output_image_path)],
            transforms=[str(transform_path)],
            qc=[qc],
            warnings=qc["warnings"],
        ),
    }


def coregister_longitudinal(
    *,
    baseline_image_path: str | Path,
    followup_image_path: str | Path,
    output_dir: str | Path,
    case_id: str | None = None,
    baseline_label: str = "baseline",
    followup_label: str = "followup",
    initialization: InitializationMode = "com",
    interpolation: InterpolationMode = "linear",
    overwrite: bool = True,
    method: Literal["translation", "rigid"] = "translation",
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Align a follow-up MRI volume to a baseline/reference timepoint.

    Use the chosen rigid/translation backend and record an explicit
    no-nonlinear-deformation policy. Reported tumor volumes remain native-space.
    """

    result = coregister_sequences(
        fixed_image_path=baseline_image_path,
        moving_image_path=followup_image_path,
        output_dir=output_dir,
        case_id=case_id,
        fixed_label=baseline_label,
        moving_label=followup_label,
        initialization=initialization,
        interpolation=interpolation,
        overwrite=overwrite,
        method=method,
        progress=progress,
    )
    result["operation"] = "coregister_longitudinal"
    result["baseline_image_path"] = result.pop("fixed_image_path")
    result["followup_image_path"] = result.pop("moving_image_path")
    result["longitudinal_policy"] = {
        "moving_timepoint": "followup",
        "reference_timepoint": "baseline",
        "deformation_model": result["qc"]["deformation_model"],
        "nonlinear_deformation_allowed": False,
        "clinical_rationale": "Preserve true interval lesion and anatomy change; avoid nonlinear warping as default.",
    }
    longitudinal_qc = _build_longitudinal_qc(result["qc"])
    result["qc"] = {**result["qc"], **longitudinal_qc}
    result["manifest_fragment"] = {
        **result["manifest_fragment"],
        "operation": "coregister_longitudinal",
        "qc": [result["qc"]],
        "warnings": result["qc"]["warnings"],
        "metadata": {"longitudinal_policy": result["longitudinal_policy"]},
    }
    return result


def apply_neuro_transform(
    *,
    source_image_path: str | Path,
    reference_image_path: str | Path,
    transform_path: str | Path,
    output_image_path: str | Path,
    interpolation: InterpolationMode = "linear",
    invert: bool = False,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Apply a stored affine transform and resample source onto reference grid."""

    source_path = _resolve_existing_file(source_image_path, "source_image_path")
    reference_path = _resolve_existing_file(reference_image_path, "reference_image_path")
    transform_file = _resolve_existing_file(transform_path, "transform_path")
    output_path = Path(output_image_path).expanduser().resolve()
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Output image already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source = _load_3d_nifti(source_path)
    reference = _load_3d_nifti(reference_path)
    payload = load_transform(transform_file)
    matrix = np.asarray(payload["moving_to_fixed_world_affine"], dtype=np.float64)
    if invert:
        matrix = np.linalg.inv(matrix)

    source_data = np.asanyarray(source.dataobj)
    resampled = _resample_to_reference(
        source_data=source_data,
        source_affine=matrix @ source.affine,
        reference=reference,
        interpolation=interpolation,
    )
    output = nib.Nifti1Image(_coerce_output_dtype(resampled, source_data, interpolation), reference.affine, reference.header)
    output.set_data_dtype(np.asanyarray(output.dataobj).dtype)
    nib.save(output, str(output_path))

    return {
        "status": "ok",
        "operation": "apply_neuro_transform",
        "source_image_path": str(source_path),
        "reference_image_path": str(reference_path),
        "transform_path": str(transform_file),
        "output_image_path": str(output_path),
        "interpolation": interpolation,
        "invert": bool(invert),
    }


def load_transform(transform_path: str | Path) -> dict[str, Any]:
    path = _resolve_existing_file(transform_path, "transform_path")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("matrix_convention") != "moving_world_to_fixed_world":
        raise ValueError("Unsupported transform convention")
    matrix = np.asarray(payload.get("moving_to_fixed_world_affine"), dtype=np.float64)
    if matrix.shape != (4, 4):
        raise ValueError("Transform matrix must be 4x4")
    return payload


def save_preprocessing_manifest(
    *,
    manifest_path: str | Path,
    case_id: str | None,
    fragments: list[dict[str, Any]],
    overwrite: bool = True,
) -> dict[str, Any]:
    path = Path(manifest_path).expanduser().resolve()
    if path.exists() and not overwrite:
        raise FileExistsError(f"Manifest already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "clinagent.neuro_preprocessing.v1",
        "case_id": case_id,
        "operations": fragments,
        "inputs": sorted({item for fragment in fragments for item in fragment.get("inputs", [])}),
        "outputs": sorted({item for fragment in fragments for item in fragment.get("outputs", [])}),
        "transforms": sorted({item for fragment in fragments for item in fragment.get("transforms", [])}),
        "warnings": [warning for fragment in fragments for warning in fragment.get("warnings", [])],
    }
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "ok", "manifest_path": str(path), "manifest": manifest}


def _resolve_existing_file(path: str | Path, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"{label} does not exist: {resolved}")
    return resolved


def _load_3d_nifti(path: Path) -> nib.Nifti1Image:
    image = nib.load(str(path))
    data = np.asanyarray(image.dataobj)
    if data.ndim == 4 and data.shape[-1] == 1:
        data = np.squeeze(data, axis=-1)
        image = nib.Nifti1Image(data, image.affine, image.header)
    if data.ndim != 3:
        raise ValueError(f"Expected a 3D NIfTI volume at {path}, got shape {data.shape}")
    return image


def _estimate_world_translation(
    *,
    fixed: nib.Nifti1Image,
    fixed_data: np.ndarray,
    moving: nib.Nifti1Image,
    moving_data: np.ndarray,
    initialization: InitializationMode,
) -> np.ndarray:
    if initialization == "header":
        translation = np.zeros(3, dtype=np.float64)
    elif initialization == "center":
        translation = _grid_center_world(fixed) - _grid_center_world(moving)
    elif initialization == "com":
        translation = _center_of_mass_world(fixed, fixed_data) - _center_of_mass_world(moving, moving_data)
    else:
        raise ValueError(f"Unsupported initialization: {initialization}")
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, 3] = translation
    return matrix


def _grid_center_world(image: nib.Nifti1Image) -> np.ndarray:
    center_vox = (np.asarray(image.shape[:3], dtype=np.float64) - 1.0) / 2.0
    return nib.affines.apply_affine(image.affine, center_vox)


def _center_of_mass_world(image: nib.Nifti1Image, data: np.ndarray) -> np.ndarray:
    weights = np.asarray(data, dtype=np.float64)
    finite = np.isfinite(weights)
    if not finite.any():
        return _grid_center_world(image)
    weights = np.where(finite, np.abs(weights), 0.0)
    positive = weights > np.percentile(weights[weights > 0], 20) if np.any(weights > 0) else weights > 0
    if not np.any(positive):
        return _grid_center_world(image)
    com_vox = np.asarray(ndimage.center_of_mass(positive.astype(np.float32)), dtype=np.float64)
    if np.any(~np.isfinite(com_vox)):
        return _grid_center_world(image)
    return nib.affines.apply_affine(image.affine, com_vox)


def _resample_to_reference(
    *,
    source_data: np.ndarray,
    source_affine: np.ndarray,
    reference: nib.Nifti1Image,
    interpolation: InterpolationMode,
) -> np.ndarray:
    output_to_input = np.linalg.inv(source_affine) @ reference.affine
    matrix = output_to_input[:3, :3]
    offset = output_to_input[:3, 3]
    order = 0 if interpolation == "nearest" else 1
    return ndimage.affine_transform(
        np.asarray(source_data),
        matrix=matrix,
        offset=offset,
        output_shape=reference.shape[:3],
        order=order,
        mode="constant",
        cval=0,
        prefilter=order > 1,
    )


def _coerce_output_dtype(data: np.ndarray, source_data: np.ndarray, interpolation: InterpolationMode) -> np.ndarray:
    if interpolation == "nearest" and np.issubdtype(source_data.dtype, np.integer):
        return np.rint(data).astype(source_data.dtype, copy=False)
    return data.astype(np.float32, copy=False)


def _build_registration_qc(
    *,
    fixed_data: np.ndarray,
    before_data: np.ndarray,
    after_data: np.ndarray,
    moving_to_fixed: np.ndarray,
    fixed: nib.Nifti1Image,
    moving: nib.Nifti1Image,
) -> dict[str, Any]:
    translation = moving_to_fixed[:3, 3]
    warnings: list[str] = []
    if np.linalg.norm(translation) > 80:
        warnings.append("large_translation_mm")
    if fixed.shape[:3] != moving.shape[:3]:
        warnings.append("shape_mismatch")
    fixed_spacing = np.asarray(fixed.header.get_zooms()[:3], dtype=np.float64)
    moving_spacing = np.asarray(moving.header.get_zooms()[:3], dtype=np.float64)
    if np.max(np.abs(fixed_spacing - moving_spacing)) > 1.0:
        warnings.append("spacing_mismatch")
    before_ncc = _normalized_cross_correlation(fixed_data, before_data)
    after_ncc = _normalized_cross_correlation(fixed_data, after_data)
    return {
        "backend": "nibabel_scipy_translation_v1",
        "fixed_shape": [int(value) for value in fixed.shape[:3]],
        "moving_shape": [int(value) for value in moving.shape[:3]],
        "fixed_spacing_mm": [float(value) for value in fixed_spacing],
        "moving_spacing_mm": [float(value) for value in moving_spacing],
        "translation_mm": [float(value) for value in translation],
        "translation_norm_mm": float(np.linalg.norm(translation)),
        "ncc_before": before_ncc,
        "ncc_after": after_ncc,
        "ncc_delta": None if before_ncc is None or after_ncc is None else float(after_ncc - before_ncc),
        "warnings": warnings,
    }


def _build_longitudinal_qc(qc: dict[str, Any]) -> dict[str, Any]:
    warnings = list(qc.get("warnings") or [])
    translation_norm = float(qc.get("translation_norm_mm") or 0.0)
    if translation_norm > 60 and "large_longitudinal_translation_mm" not in warnings:
        warnings.append("large_longitudinal_translation_mm")
    ncc_delta = qc.get("ncc_delta")
    if isinstance(ncc_delta, (float, int)) and ncc_delta < -0.05:
        warnings.append("alignment_similarity_worsened")
    return {
        "longitudinal_mode": True,
        "deformation_model": qc.get("deformation_model", "translation_affine_only"),
        "nonlinear_deformation_allowed": False,
        "followup_to_baseline_translation_norm_mm": translation_norm,
        "warnings": warnings,
    }


def _normalized_cross_correlation(a: np.ndarray, b: np.ndarray) -> float | None:
    left = np.asarray(a, dtype=np.float64).ravel()
    right = np.asarray(b, dtype=np.float64).ravel()
    mask = np.isfinite(left) & np.isfinite(right)
    if int(mask.sum()) < 32:
        return None
    left = left[mask]
    right = right[mask]
    if left.size > 200_000:
        step = int(math.ceil(left.size / 200_000))
        left = left[::step]
        right = right[::step]
    left = left - float(np.mean(left))
    right = right - float(np.mean(right))
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom <= 0:
        return None
    return float(np.dot(left, right) / denom)


def _manifest_fragment(
    *,
    case_id: str | None,
    operation: str,
    inputs: list[str],
    outputs: list[str],
    transforms: list[str],
    qc: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "case_id": case_id,
        "operation": operation,
        "inputs": inputs,
        "outputs": outputs,
        "transforms": transforms,
        "qc": qc,
        "warnings": warnings,
    }


def _nifti_stem(path: Path) -> str:
    name = path.name
    if name.endswith(".nii.gz"):
        return name[:-7]
    if name.endswith(".nii"):
        return name[:-4]
    return path.stem


def _matrix_to_list(matrix: np.ndarray) -> list[list[float]]:
    return [[float(value) for value in row] for row in matrix]
