from __future__ import annotations

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

pytest.importorskip("SimpleITK")

from clinagent.families.neuro.registration import coregister_longitudinal
from clinagent.families.neuro.registration.rigid import correct_bias_field
from clinagent.families.neuro.registration.workflow import align_visit


def phantom():
    grid = np.indices((40, 44, 48), dtype=float)
    data = np.zeros(grid.shape[1:])
    for center, scale, amplitude in [((19, 21, 23), (9, 11, 12), 60), ((12, 15, 18), (3, 4, 5), 80), ((26, 28, 30), (4, 3, 4), 110)]:
        radius = sum(((grid[i] - center[i]) / scale[i]) ** 2 for i in range(3))
        data += amplitude * np.exp(-radius / 2)
    data[data < 5] = 0
    return data.astype(np.float32)


def save(path, data, affine=None):
    image = nib.Nifti1Image(data, np.eye(4) if affine is None else affine)
    image.header.set_xyzt_units("mm")
    nib.save(image, str(path))
    return str(path)


def test_rigid_recovers_rotation_and_translation_in_ras_mm(tmp_path):
    data = phantom()
    affine = np.diag([1.2, 1.5, 1.7, 1.0])
    rotation = Rotation.from_euler("xyz", [4, -3, 7], degrees=True).as_matrix()
    motion = np.eye(4)
    motion[:3, :3] = rotation
    center = nib.affines.apply_affine(affine, (np.array(data.shape) - 1) / 2)
    motion[:3, 3] = center - rotation @ center + [4, -3, 2]
    fixed = save(tmp_path / "fixed.nii.gz", data, affine)
    moving = save(tmp_path / "moving.nii.gz", data, motion @ affine)
    events = []
    result = coregister_longitudinal(baseline_image_path=fixed, followup_image_path=moving,
                                    output_dir=tmp_path / "result", method="rigid", progress=events.append)
    estimated = np.array(result["transform"]["moving_to_fixed_world_affine"])
    points = nib.affines.apply_affine(affine, [[10, 12, 15], [27, 29, 30], [20, 20, 20]])
    restored = nib.affines.apply_affine(estimated @ motion, points)
    assert np.max(np.linalg.norm(restored - points, axis=1)) < 1.0
    assert np.allclose(estimated[:3, :3].T @ estimated[:3, :3], np.eye(3), atol=1e-5)
    assert np.linalg.det(estimated[:3, :3]) == pytest.approx(1)
    assert result["qc"]["ncc_delta"] > 0
    assert result["qc"]["rotation_angle_deg"] > 3
    assert events


def test_workflow_stages_artifacts_and_native_measurements(tmp_path):
    data = phantom()
    baseline = save(tmp_path / "baseline.nii.gz", data)
    affine = np.eye(4)
    affine[:3, 3] = [3, -2, 1]
    moving = save(tmp_path / "moving.nii.gz", data, affine)
    labels = (data > 80).astype(np.uint8) * 3
    mask = save(tmp_path / "seg.nii.gz", labels, affine)
    original = Path(mask).read_bytes()
    events = []
    result = align_visit(reference_t1c=baseline, modalities={"t1c": moving, "t2f": moving},
                         masks={"seg": mask}, output_dir=tmp_path / "result", on_step=events.append)
    steps = result["registration"]["steps"]
    assert [step["status"] for step in steps] == ["complete", "skipped", "complete", "complete", "complete"]
    assert any(event["id"] == "longitudinal" and event["status"] == "running" for event in events)
    assert result["registration"]["measurement_space"] == "native_segmentation"
    assert Path(mask).read_bytes() == original
    aligned_mask = nib.load(result["artifacts"]["seg"])
    assert set(np.unique(aligned_mask.get_fdata())) <= {0, 3}
    assert np.allclose(aligned_mask.affine, nib.load(baseline).affine)
    assert np.mean((aligned_mask.get_fdata() > 0) == (labels > 0)) > 0.99
    transform = json.loads((tmp_path / "result/transform_t2f.json").read_text())
    assert transform["matrix_convention"] == "moving_world_to_fixed_world"


def test_n4_retains_native_geometry_and_source(tmp_path):
    data = phantom()
    data *= np.exp(np.linspace(-0.5, 0.5, data.shape[0]))[:, None, None]
    affine = np.diag([1.0, 1.4, 2.0, 1])
    source = save(tmp_path / "source.nii.gz", data, affine)
    before = Path(source).read_bytes()
    output = correct_bias_field(source, tmp_path / "corrected.nii.gz")
    corrected = nib.load(output)
    assert np.allclose(corrected.affine, affine)
    assert corrected.shape == data.shape
    assert np.isfinite(corrected.get_fdata()).all()
    assert not np.allclose(corrected.get_fdata(), data)
    assert Path(source).read_bytes() == before


def test_failure_marks_actual_step_and_publishes_no_result(tmp_path):
    source = save(tmp_path / "constant.nii.gz", np.ones((8, 8, 8), dtype=np.float32))
    events = []
    with pytest.raises(ValueError, match="nonconstant"):
        align_visit(reference_t1c=source, modalities={"t1c": source}, masks={},
                    output_dir=tmp_path / "result", on_step=events.append)
    assert events[-1]["id"] == "inputs"
    assert events[-1]["status"] == "failed"
    assert not (tmp_path / "result/image_t1c.nii.gz").exists()


def test_agent_uses_the_same_workflow_and_returns_steps(monkeypatch, tmp_path):
    import asyncio
    from clinagent.console.agent import CoregisterNeuroLongitudinalTool
    from clinagent.families.neuro.registration import workflow

    captured = {}
    def run(**kwargs):
        captured.update(kwargs)
        return {"registration": {"steps": workflow.pending_steps()}, "artifacts": {}}
    monkeypatch.setattr(workflow, "align_visit", run)
    result = asyncio.run(CoregisterNeuroLongitudinalTool().execute({
        "baseline_image_path": "baseline.nii.gz", "followup_image_path": "followup.nii.gz",
        "moving_modalities": {"t2f": "flair.nii.gz"}, "output_dir": str(tmp_path), "bias_correction": True,
    }))
    assert result.success
    assert captured["modalities"] == {"t1c": "followup.nii.gz", "t2f": "flair.nii.gz"}
    assert captured["bias_correction"] is True
    assert len(json.loads(result.output)["registration"]["steps"]) == 5
