from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import nibabel as nib
import numpy as np

from clinagent.families.neuro.registration import apply_neuro_transform, coregister_longitudinal, coregister_sequences
from clinagent.families.neuro.tools.registration import NeuroSequenceCoregistrationTool


def _write_nifti(path: Path, data: np.ndarray, affine: np.ndarray | None = None) -> Path:
    image = nib.Nifti1Image(data, affine if affine is not None else np.eye(4))
    nib.save(image, str(path))
    return path


def test_coregister_sequences_writes_resampled_image_and_transform(tmp_path: Path) -> None:
    data = np.zeros((24, 24, 24), dtype=np.float32)
    data[7:16, 8:17, 9:18] = 10.0
    fixed_path = _write_nifti(tmp_path / "sub-001_T1w.nii.gz", data)

    moving_affine = np.eye(4)
    moving_affine[:3, 3] = [6.0, -4.0, 2.0]
    moving_path = _write_nifti(tmp_path / "sub-001_FLAIR.nii.gz", data, moving_affine)

    result = coregister_sequences(
        fixed_image_path=fixed_path,
        moving_image_path=moving_path,
        output_dir=tmp_path / "coreg",
        case_id="case-1",
        fixed_label="T1w",
        moving_label="FLAIR",
        initialization="center",
    )

    assert result["status"] == "ok"
    assert Path(result["output_image_path"]).exists()
    assert Path(result["transform_path"]).exists()
    assert result["qc"]["translation_mm"] == [-6.0, 4.0, -2.0]
    assert result["qc"]["ncc_after"] is not None
    assert result["manifest_fragment"]["operation"] == "coregister_sequences"

    transformed = json.loads(Path(result["transform_path"]).read_text())
    assert transformed["source_label"] == "FLAIR"
    assert transformed["target_label"] == "T1w"


def test_apply_neuro_transform_preserves_label_values_with_nearest(tmp_path: Path) -> None:
    reference = np.zeros((16, 16, 16), dtype=np.float32)
    fixed_path = _write_nifti(tmp_path / "fixed.nii.gz", reference)

    labels = np.zeros((16, 16, 16), dtype=np.int16)
    labels[4:9, 4:9, 4:9] = 7
    moving_affine = np.eye(4)
    moving_affine[:3, 3] = [3.0, 0.0, 0.0]
    moving_label_path = _write_nifti(tmp_path / "labels.nii.gz", labels, moving_affine)

    coreg = coregister_sequences(
        fixed_image_path=fixed_path,
        moving_image_path=moving_label_path,
        output_dir=tmp_path / "coreg",
        initialization="center",
        interpolation="nearest",
    )
    output_path = tmp_path / "labels_on_fixed.nii.gz"
    result = apply_neuro_transform(
        source_image_path=moving_label_path,
        reference_image_path=fixed_path,
        transform_path=coreg["transform_path"],
        output_image_path=output_path,
        interpolation="nearest",
    )

    assert result["status"] == "ok"
    output = np.asanyarray(nib.load(str(output_path)).dataobj)
    assert set(np.unique(output).astype(int)) == {0, 7}


def test_coregister_longitudinal_marks_conservative_policy(tmp_path: Path) -> None:
    baseline = np.zeros((20, 20, 20), dtype=np.float32)
    baseline[6:13, 6:13, 6:13] = 8.0
    baseline_path = _write_nifti(tmp_path / "baseline_T1w.nii.gz", baseline)

    followup_affine = np.eye(4)
    followup_affine[:3, 3] = [0.0, 5.0, 0.0]
    followup_path = _write_nifti(tmp_path / "followup_T1w.nii.gz", baseline, followup_affine)

    result = coregister_longitudinal(
        baseline_image_path=baseline_path,
        followup_image_path=followup_path,
        output_dir=tmp_path / "longitudinal",
        case_id="case-long",
        baseline_label="2024-01-01",
        followup_label="2024-04-01",
        initialization="center",
    )

    assert result["status"] == "ok"
    assert result["operation"] == "coregister_longitudinal"
    assert result["longitudinal_policy"]["nonlinear_deformation_allowed"] is False
    assert result["qc"]["longitudinal_mode"] is True
    assert result["qc"]["translation_mm"] == [0.0, -5.0, 0.0]
    assert result["manifest_fragment"]["operation"] == "coregister_longitudinal"


def test_sequence_coregistration_tool_can_call_remote_cli(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"status": "ok", "output_image_path": "/remote/out.nii.gz"}),
            stderr="",
        )

    monkeypatch.setenv("CLINAGENT_NEURO_REGISTRATION_REMOTE_HOST", "remote-gpu")
    monkeypatch.setenv("CLINAGENT_NEURO_REGISTRATION_REMOTE_CLI", "/opt/agent-tools/bin/register")
    monkeypatch.setenv("CLINAGENT_NEURO_REGISTRATION_SSH_CONFIG", "/tmp/ssh_config")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = NeuroSequenceCoregistrationTool().run(
        fixed_image_path="/data/fixed.nii.gz",
        moving_image_path="/data/moving.nii.gz",
        output_dir="/data/out",
        fixed_label="T1w",
        moving_label="FLAIR",
        initialization="center",
        interpolation="linear",
        overwrite=False,
    )

    assert result["status"] == "ok"
    assert result["remote_host"] == "remote-gpu"
    assert captured["argv"][:5] == ["ssh", "-q", "-F", "/tmp/ssh_config", "remote-gpu"]
    remote_command = captured["argv"][5]
    assert "/opt/agent-tools/bin/register coregister-sequences" in remote_command
    assert "--fixed-image-path /data/fixed.nii.gz" in remote_command
    assert "--moving-image-path /data/moving.nii.gz" in remote_command
    assert "--no-overwrite" in remote_command
    assert captured["kwargs"]["capture_output"] is True
