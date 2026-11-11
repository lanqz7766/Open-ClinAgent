"""CPU rigid registration and optional N4 correction; never deform anatomy."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import nibabel as nib
import numpy as np


def _sitk():
    try:
        import SimpleITK as sitk
    except ImportError as exc:
        raise RuntimeError("Rigid registration requires the clinagent[preview] extra.") from exc
    return sitk


def _to_sitk(image: nib.Nifti1Image):
    sitk = _sitk()
    data = np.asarray(image.dataobj, dtype=np.float32)
    if data.ndim != 3 or not np.isfinite(data).all() or np.ptp(data) <= 0:
        raise ValueError("Registration requires a finite, nonconstant 3D MRI.")
    affine = np.diag([-1., -1., 1., 1.]) @ image.affine
    spacing = np.linalg.norm(affine[:3, :3], axis=0)
    direction = affine[:3, :3] / spacing
    if not np.allclose(direction.T @ direction, np.eye(3), atol=1e-4):
        raise ValueError("MRI geometry contains shear; orthogonal acquisition axes are required.")
    volume = sitk.GetImageFromArray(data.transpose(2, 1, 0))
    volume.SetSpacing(spacing.tolist())
    volume.SetOrigin(affine[:3, 3].tolist())
    volume.SetDirection(direction.ravel().tolist())
    return volume


def estimate_rigid(fixed, moving, initial_matrix, progress: Callable[[str], None] | None = None):
    sitk = _sitk()
    fixed_volume, moving_volume = _to_sitk(fixed), _to_sitk(moving)
    initial = sitk.Euler3DTransform()
    initial.SetCenter(fixed_volume.TransformContinuousIndexToPhysicalPoint(
        [(size - 1) / 2 for size in fixed_volume.GetSize()]))
    ras_lps = np.diag([-1., -1., 1., 1.])
    initial.SetTranslation((ras_lps @ np.linalg.inv(initial_matrix) @ ras_lps)[:3, 3].tolist())
    registration = sitk.ImageRegistrationMethod()
    registration.SetNumberOfThreads(2)
    registration.SetMetricAsMattesMutualInformation(32)
    if min(fixed.shape) >= 32:
        registration.SetMetricSamplingStrategy(registration.REGULAR)
        registration.SetMetricSamplingPercentage(0.15, 42)
        registration.SetShrinkFactorsPerLevel([4, 2, 1])
        registration.SetSmoothingSigmasPerLevel([2, 1, 0])
    else:
        registration.SetShrinkFactorsPerLevel([1])
        registration.SetSmoothingSigmasPerLevel([0])
    registration.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
    registration.SetInterpolator(sitk.sitkLinear)
    registration.SetOptimizerAsRegularStepGradientDescent(
        learningRate=1.0, minStep=0.001, numberOfIterations=120,
        gradientMagnitudeTolerance=1e-6)
    registration.SetOptimizerScalesFromPhysicalShift()
    registration.SetInitialTransform(initial, inPlace=False)
    if progress:
        registration.AddCommand(sitk.sitkMultiResolutionIterationEvent,
                                lambda: progress(f"Resolution level {registration.GetCurrentLevel() + 1}"))
    transform = registration.Execute(fixed_volume, moving_volume)
    # ITK resampling maps fixed LPS -> moving LPS. Persist moving RAS -> fixed RAS.
    origin = np.asarray(transform.TransformPoint((0., 0., 0.)))
    matrix = np.eye(4)
    matrix[:3, 3] = origin
    matrix[:3, :3] = np.column_stack([
        np.asarray(transform.TransformPoint(tuple(axis))) - origin for axis in np.eye(3)])
    forward = ras_lps @ np.linalg.inv(matrix) @ ras_lps
    angle = np.degrees(np.arccos(np.clip((np.trace(forward[:3, :3]) - 1) / 2, -1, 1)))
    return forward, {
        "backend": "simpleitk_rigid_v1", "deformation_model": "rigid_6dof",
        "similarity_metric": "Mattes mutual information", "rotation_angle_deg": float(angle),
        "optimizer_stop": registration.GetOptimizerStopConditionDescription(),
    }


def correct_bias_field(source: str | Path, destination: Path) -> str:
    sitk = _sitk()
    image = nib.load(str(source))
    volume = _to_sitk(image)
    mask = sitk.OtsuThreshold(volume, 0, 1, 200)
    shrink = 4 if min(image.shape) >= 64 else 1
    n4 = sitk.N4BiasFieldCorrectionImageFilter()
    n4.SetNumberOfThreads(2)
    n4.SetMaximumNumberOfIterations([30, 20, 10])
    n4.Execute(sitk.Shrink(volume, [shrink] * 3), sitk.Shrink(mask, [shrink] * 3))
    corrected = volume / sitk.Exp(n4.GetLogBiasFieldAsImage(volume))
    data = sitk.GetArrayFromImage(corrected).transpose(2, 1, 0)
    destination.parent.mkdir(parents=True, exist_ok=True)
    output = nib.Nifti1Image(data, image.affine, image.header)
    output.set_data_dtype(np.float32)
    nib.save(output, str(destination))
    return str(destination)
