from __future__ import annotations

import json
from pathlib import Path

import httpx
import nibabel as nib
import numpy as np
import pytest

from clinagent.families.neuro.preprocessing import PreprocessingQualificationError, prepare_nnunet_service_input
from clinagent.families.neuro.tools import NNUNetBrainSegmentationTool


def _write_nifti(path: Path, data: np.ndarray, affine: np.ndarray | None = None) -> Path:
    image = nib.Nifti1Image(data, affine if affine is not None else np.eye(4))
    nib.save(image, str(path))
    return path


def test_prepare_nnunet_service_input_reorients_to_lia(tmp_path: Path) -> None:
    image_path = _write_nifti(
        tmp_path / "subject_t1w.nii.gz",
        np.random.default_rng(7).integers(0, 128, size=(64, 64, 64), dtype=np.uint8),
        affine=np.diag([1.0, 1.0, 1.0, 1.0]),
    )

    result = prepare_nnunet_service_input(image_path, sequence_hint="T1w")

    prepared_image = nib.load(result["prepared_input_path"])
    assert tuple(str(code) for code in nib.aff2axcodes(prepared_image.affine)) == ("L", "I", "A")
    assert result["sequence_type"] == "T1w"
    assert result["preprocessing_profile"] == "lia_basic_qc"
    assert result["intensity_handling"] == "unchanged"
    assert result["qc"]["nonzero_voxels"] > 0


def test_prepare_nnunet_service_input_rejects_non_t1(tmp_path: Path) -> None:
    image_path = _write_nifti(
        tmp_path / "subject_flair.nii.gz",
        np.random.default_rng(9).integers(0, 128, size=(64, 64, 64), dtype=np.uint8),
        affine=np.diag([1.0, 1.0, 1.0, 1.0]),
    )

    with pytest.raises(PreprocessingQualificationError, match="expects T1 input"):
        prepare_nnunet_service_input(image_path)


def test_nnunet_brain_segmentation_tool_calls_service_and_returns_contract(tmp_path: Path) -> None:
    image_path = _write_nifti(
        tmp_path / "subject_t1w.nii.gz",
        np.random.default_rng(5).integers(0, 255, size=(64, 64, 64), dtype=np.uint8),
        affine=np.diag([1.0, 1.0, 1.0, 1.0]),
    )
    output_seg = tmp_path / "subject_seg.nii.gz"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/model-info":
            return httpx.Response(
                200,
                json={
                    "model_id": "brain_structure_1k",
                    "model_type": "nnunetv2",
                    "label_schema_path": "/tmp/labels.json",
                    "input_modalities": ["T1w"],
                },
            )
        if request.url.path == "/predict":
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["device"] == "auto"
            assert payload["engine"] == "auto"
            assert payload["input_image"].endswith(".nii.gz")
            assert payload["output_seg"] == str(output_seg.resolve())
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "output_seg": payload["output_seg"],
                    "device_used": "cuda:0",
                    "elapsed_sec": 1.23,
                    "label_schema_path": "/tmp/labels.json",
                    "qc": {
                        "nonzero_voxels": 1024,
                        "label_count": 105,
                        "unknown_labels": [],
                        "suspicious": False,
                        "warnings": [],
                    },
                },
            )
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    tool = NNUNetBrainSegmentationTool(
        service_url="http://127.0.0.1:8000",
        transport=httpx.MockTransport(handler),
    )
    tool._remote_host = ""
    result = tool.run(
        input_nifti_path=str(image_path),
        output_seg_path=str(output_seg),
        sequence_hint="T1w",
    )

    assert result["health"]["ok"] is True
    assert result["model_info"]["model_id"] == "brain_structure_1k"
    assert result["prepared_input"]["orientation_policy"] == "LIA"
    assert result["preprocessing_profile"] == "lia_basic_qc"
    assert result["output_seg_path"] == str(output_seg.resolve())
    assert result["label_schema_path"] == "/tmp/labels.json"
    assert result["prediction"]["qc"]["label_count"] == 105


def test_nnunet_brain_segmentation_tool_stages_files_for_remote_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = _write_nifti(
        tmp_path / "subject_t1w.nii.gz",
        np.random.default_rng(11).integers(0, 255, size=(64, 64, 64), dtype=np.uint8),
        affine=np.diag([1.0, 1.0, 1.0, 1.0]),
    )
    output_seg = tmp_path / "subject_seg.nii.gz"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/model-info":
            return httpx.Response(
                200,
                json={
                    "model_id": "brain_structure_1k",
                    "model_type": "nnunetv2",
                    "label_schema_path": "/remote/config/labels.json",
                    "input_modalities": ["T1w"],
                },
            )
        if request.url.path == "/predict":
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["input_image"].startswith("/remote/staging/")
            assert payload["output_seg"].startswith("/remote/staging/")
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "output_seg": payload["output_seg"],
                    "device_used": "cuda:0",
                    "elapsed_sec": 1.23,
                    "label_schema_path": "/remote/config/labels.json",
                    "qc": {
                        "nonzero_voxels": 1024,
                        "label_count": 105,
                        "unknown_labels": [],
                        "suspicious": False,
                        "warnings": [],
                    },
                },
            )
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    tool = NNUNetBrainSegmentationTool(
        service_url="http://127.0.0.1:18000",
        transport=httpx.MockTransport(handler),
    )
    tool._remote_host = "ssh-host"
    tool._remote_root = "/remote/staging"

    def fake_create_remote_run(*, prepared_input_path: str, local_output_seg_path: str):
        return type("RemoteRun", (), {
            "remote_host": "ssh-host",
            "remote_dir": "/remote/staging/run-1",
            "remote_input_path": "/remote/staging/run-1/input.nii.gz",
            "remote_output_path": "/remote/staging/run-1/output_seg.nii.gz",
            "local_output_path": str(Path(local_output_seg_path).resolve()),
            "local_label_schema_path": str((tmp_path / "labels.json").resolve()),
        })()

    def fake_materialize_remote_results(*, remote_run, remote_output_path: str, remote_label_schema_path: str) -> None:
        _write_nifti(Path(remote_run.local_output_path), np.ones((8, 8, 8), dtype=np.uint8))
        Path(remote_run.local_label_schema_path).write_text("[]", encoding="utf-8")

    monkeypatch.setattr(tool, "_create_remote_run", fake_create_remote_run)
    monkeypatch.setattr(tool, "_materialize_remote_results", fake_materialize_remote_results)
    monkeypatch.setattr(tool, "_cleanup_remote_run", lambda remote_run: None)

    result = tool.run(
        input_nifti_path=str(image_path),
        output_seg_path=str(output_seg),
        sequence_hint="T1w",
    )

    assert result["output_seg_path"] == str(output_seg.resolve())
    assert result["label_schema_path"] == str((tmp_path / "labels.json").resolve())
    assert result["remote_staging"]["enabled"] is True
    assert result["remote_staging"]["remote_host"] == "ssh-host"
