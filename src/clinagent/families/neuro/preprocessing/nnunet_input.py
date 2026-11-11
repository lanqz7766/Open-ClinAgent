"""Prepare T1 NIfTI inputs for the brain segmentation nnUNet service."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

from clinagent.families.neuro.preprocessing.sequence_router import MRISequence, SequenceRouter

TARGET_AXCODES = ("L", "I", "A")


class PreprocessingQualificationError(ValueError):
    """Raised when an input volume is not safe to pass into the nnUNet service."""


@dataclass(frozen=True)
class BasicQCResult:
    shape: tuple[int, int, int]
    spacing_mm: tuple[float, float, float]
    dtype: str
    intensity_min: float
    intensity_max: float
    nonzero_voxels: int
    finite_fraction: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape": list(self.shape),
            "spacing_mm": [float(value) for value in self.spacing_mm],
            "dtype": self.dtype,
            "intensity_min": self.intensity_min,
            "intensity_max": self.intensity_max,
            "nonzero_voxels": self.nonzero_voxels,
            "finite_fraction": self.finite_fraction,
        }


def prepare_nnunet_service_input(
    input_nifti_path: str | Path,
    *,
    output_path: str | Path | None = None,
    sequence_hint: str | None = None,
    require_t1: bool = True,
) -> dict[str, Any]:
    """Validate and reorient a NIfTI input for the nnUNet service.

    Current default profile:
    - keep the original intensity distribution
    - require `T1` unless explicitly disabled
    - reorient to `LIA`
    - run basic QC before inference
    """

    source_path = Path(input_nifti_path).expanduser().resolve()
    if not source_path.exists():
        raise PreprocessingQualificationError(f"Input NIfTI does not exist: {source_path}")

    image = nib.load(str(source_path))
    data = np.asanyarray(image.dataobj)

    if data.ndim == 4 and data.shape[-1] == 1:
        data = np.squeeze(data, axis=-1)
        image = nib.Nifti1Image(data, image.affine, image.header)
    if data.ndim != 3:
        raise PreprocessingQualificationError(
            f"Expected a single 3D volume for nnUNet input, got shape {tuple(int(v) for v in data.shape)}"
        )

    sequence_type = _resolve_sequence_type(source_path, sequence_hint)
    if require_t1 and sequence_type is not MRISequence.T1W:
        raise PreprocessingQualificationError(
            f"nnUNet brain structure service expects T1 input, got {sequence_type.value}"
        )

    qc = _run_basic_qc(data, image.header)

    original_orientation = tuple(str(code) for code in nib.aff2axcodes(image.affine))
    prepared_image = _reorient_to_lia(image)
    prepared_orientation = tuple(str(code) for code in nib.aff2axcodes(prepared_image.affine))

    reused_original_path = original_orientation == TARGET_AXCODES and output_path is None
    prepared_path = source_path if reused_original_path else _resolve_output_path(source_path, output_path)
    if not reused_original_path:
        nib.save(prepared_image, str(prepared_path))

    return {
        "input_path": str(source_path),
        "prepared_input_path": str(prepared_path),
        "reused_original_path": reused_original_path,
        "sequence_type": sequence_type.value,
        "original_orientation": list(original_orientation),
        "prepared_orientation": list(prepared_orientation),
        "orientation_policy": "LIA",
        "qc": qc.to_dict(),
        "preprocessing_profile": "lia_basic_qc",
        "intensity_handling": "unchanged",
    }


def _resolve_sequence_type(source_path: Path, sequence_hint: str | None) -> MRISequence:
    if sequence_hint:
        normalized = sequence_hint.strip().lower()
        if normalized in {"t1", "t1w", "t1-weighted"}:
            return MRISequence.T1W
        if normalized in {"t2", "t2w", "t2-weighted"}:
            return MRISequence.T2W
        if normalized == "flair":
            return MRISequence.FLAIR
        if normalized == "swi":
            return MRISequence.SWI
        if normalized == "mra":
            return MRISequence.MRA
    return SequenceRouter().identify_from_filename(source_path.name)


def _run_basic_qc(data: np.ndarray, header: nib.nifti1.Nifti1Header) -> BasicQCResult:
    shape = tuple(int(value) for value in data.shape[:3])
    if min(shape) < 32:
        raise PreprocessingQualificationError(f"Input volume shape is unexpectedly small: {shape}")

    spacing = tuple(float(value) for value in header.get_zooms()[:3])
    if len(spacing) != 3 or any((not np.isfinite(value)) or value <= 0 or value > 10 for value in spacing):
        raise PreprocessingQualificationError(f"Invalid voxel spacing for nnUNet input: {spacing}")

    finite_mask = np.isfinite(data)
    finite_fraction = float(np.mean(finite_mask))
    if finite_fraction < 0.999:
        raise PreprocessingQualificationError(
            f"Input volume contains too many non-finite voxels (finite_fraction={finite_fraction:.6f})"
        )

    nonzero_voxels = int(np.count_nonzero(data))
    if nonzero_voxels == 0:
        raise PreprocessingQualificationError("Input volume is empty or all-zero")

    return BasicQCResult(
        shape=shape,
        spacing_mm=spacing,
        dtype=str(data.dtype),
        intensity_min=float(np.min(data)),
        intensity_max=float(np.max(data)),
        nonzero_voxels=nonzero_voxels,
        finite_fraction=finite_fraction,
    )


def _reorient_to_lia(image: nib.spatialimages.SpatialImage) -> nib.spatialimages.SpatialImage:
    current = nib.orientations.io_orientation(image.affine)
    target = nib.orientations.axcodes2ornt(TARGET_AXCODES)
    transform = nib.orientations.ornt_transform(current, target)
    return image.as_reoriented(transform)


def _resolve_output_path(source_path: Path, output_path: str | Path | None) -> Path:
    if output_path is not None:
        return Path(output_path).expanduser().resolve()
    stem = source_path.name
    if stem.endswith(".nii.gz"):
        stem = stem[:-7]
    elif source_path.suffix:
        stem = source_path.stem
    return source_path.with_name(f"{stem}_lia.nii.gz")
