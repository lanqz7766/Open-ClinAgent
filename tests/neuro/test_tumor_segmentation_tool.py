from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import nibabel as nib
import numpy as np
import pytest

import clinagent.families.neuro.tools.tumor_segmentation as tumor_segmentation_module
from clinagent.families.neuro.tools import BrainTumorSegmentationTool


def _write_nifti(path: Path, data: np.ndarray, affine: np.ndarray | None = None) -> Path:
    image = nib.Nifti1Image(data, affine if affine is not None else np.eye(4))
    nib.save(image, str(path))
    return path


def test_brain_tumor_segmentation_requires_minimum_modalities(tmp_path: Path) -> None:
    t1c = _write_nifti(
        tmp_path / "case_t1c.nii.gz",
        np.random.default_rng(13).integers(0, 255, size=(48, 48, 48), dtype=np.uint8),
    )
    tool = BrainTumorSegmentationTool(service_url="http://127.0.0.1:9000")

    with pytest.raises(ValueError, match="requires t1n, t1c, t2w, and t2f"):
        tool.run(t1c_nifti_path=str(t1c), precomputed_seg_path=str(t1c))


def test_brain_tumor_segmentation_postprocesses_precomputed_segmentation(tmp_path: Path) -> None:
    t1c = _write_nifti(
        tmp_path / "case_t1c.nii.gz",
        np.random.default_rng(17).integers(0, 255, size=(48, 48, 48), dtype=np.uint8),
    )
    t1n = _write_nifti(
        tmp_path / "case_t1n.nii.gz",
        np.random.default_rng(18).integers(0, 255, size=(48, 48, 48), dtype=np.uint8),
    )
    t2w = _write_nifti(
        tmp_path / "case_t2w.nii.gz",
        np.random.default_rng(20).integers(0, 255, size=(48, 48, 48), dtype=np.uint8),
    )
    t2f = _write_nifti(
        tmp_path / "case_t2f.nii.gz",
        np.random.default_rng(19).integers(0, 255, size=(48, 48, 48), dtype=np.uint8),
    )
    seg = np.zeros((48, 48, 48), dtype=np.uint8)
    seg[16:24, 16:24, 20:24] = 1
    seg[20:30, 20:30, 22:26] = 2
    seg[24:28, 24:28, 24:28] = 3
    seg[28:32, 28:32, 24:28] = 4
    seg_path = _write_nifti(tmp_path / "case_seg.nii.gz", seg)

    result = BrainTumorSegmentationTool().run(
        t1n_nifti_path=str(t1n),
        t1c_nifti_path=str(t1c),
        t2w_nifti_path=str(t2w),
        t2f_nifti_path=str(t2f),
        output_dir=str(tmp_path / "out"),
        precomputed_seg_path=str(seg_path),
    )

    assert result["mode"] == "precomputed"
    assert Path(result["tumor_regions_path"]).exists()
    assert Path(result["volumes_csv_path"]).exists()
    assert Path(result["overlay_preview_path"]).exists()
    whole_tumor = next(row for row in result["derived_regions"] if row["region"] == "whole_tumor")
    assert whole_tumor["voxel_count"] == int(np.count_nonzero(np.isin(seg, [1, 2, 3])))
    cavity = next(row for row in result["derived_regions"] if row["region"] == "cavity_or_post_surgical_change")
    assert cavity["voxel_count"] == int(np.count_nonzero(seg == 4))
    assert result["qc"]["intended_use"] == "research_demo_segmentation_not_diagnosis"


def test_brain_tumor_segmentation_calls_service_and_returns_contract(tmp_path: Path) -> None:
    t1c = _write_nifti(
        tmp_path / "case_t1c.nii.gz",
        np.random.default_rng(23).integers(0, 255, size=(48, 48, 48), dtype=np.uint8),
    )
    t1n = _write_nifti(
        tmp_path / "case_t1n.nii.gz",
        np.random.default_rng(24).integers(0, 255, size=(48, 48, 48), dtype=np.uint8),
    )
    t2w = _write_nifti(
        tmp_path / "case_t2w.nii.gz",
        np.random.default_rng(28).integers(0, 255, size=(48, 48, 48), dtype=np.uint8),
    )
    t2f = _write_nifti(
        tmp_path / "case_t2f.nii.gz",
        np.random.default_rng(29).integers(0, 255, size=(48, 48, 48), dtype=np.uint8),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/model-info":
            return httpx.Response(
                200,
                json={
                    "model_id": "nnunet_glioma_mixed_v1",
                    "model_type": "nnunetv2",
                    "input_modalities": ["t1n", "t1c", "t2w", "t2f"],
                    "labels": {
                        "1": "non_enhancing_core_candidate",
                        "2": "flair_edema_abnormality",
                        "3": "enhancing_tumor",
                        "4": "cavity_or_post_surgical_change",
                    },
                },
            )
        if request.url.path == "/predict":
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["modalities"]["t1n"] == str(t1n.resolve())
            assert payload["modalities"]["t1c"] == str(t1c.resolve())
            assert payload["modalities"]["t2w"] == str(t2w.resolve())
            assert payload["modalities"]["t2f"] == str(t2f.resolve())
            assert payload["model_id"] == "nnunet_glioma_mixed_v1"
            output_dir = Path(payload["output_dir"])
            output_dir.mkdir(parents=True, exist_ok=True)
            seg = np.zeros((48, 48, 48), dtype=np.uint8)
            seg[12:20, 14:22, 20:24] = 2
            seg[16:18, 16:18, 22:24] = 3
            seg_path = _write_nifti(output_dir / "seg.nii.gz", seg)
            return httpx.Response(200, json={"ok": True, "seg_path": str(seg_path)})
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    tool = BrainTumorSegmentationTool(
        service_url="http://127.0.0.1:9000",
        transport=httpx.MockTransport(handler),
    )
    tool._remote_host = ""
    result = tool.run(
        t1n_nifti_path=str(t1n),
        t1c_nifti_path=str(t1c),
        t2w_nifti_path=str(t2w),
        t2f_nifti_path=str(t2f),
        output_dir=str(tmp_path / "service_out"),
        model_id="nnunet_glioma_mixed_v1",
    )

    assert result["health"]["ok"] is True
    assert result["model_info"]["model_id"] == "nnunet_glioma_mixed_v1"
    assert Path(result["seg_path"]).exists()
    assert Path(result["tumor_regions_path"]).exists()
    assert Path(result["overlay_preview_path"]).exists()
    enhancing = next(row for row in result["derived_regions"] if row["region"] == "enhancing_tumor")
    assert enhancing["voxel_count"] == 8


def test_brain_tumor_segmentation_remote_staging_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t1c = _write_nifti(
        tmp_path / "case_t1c.nii.gz",
        np.random.default_rng(31).integers(0, 255, size=(48, 48, 48), dtype=np.uint8),
    )
    t1n = _write_nifti(
        tmp_path / "case_t1n.nii.gz",
        np.random.default_rng(32).integers(0, 255, size=(48, 48, 48), dtype=np.uint8),
    )
    t2w = _write_nifti(
        tmp_path / "case_t2w.nii.gz",
        np.random.default_rng(36).integers(0, 255, size=(48, 48, 48), dtype=np.uint8),
    )
    t2f = _write_nifti(
        tmp_path / "case_t2f.nii.gz",
        np.random.default_rng(37).integers(0, 255, size=(48, 48, 48), dtype=np.uint8),
    )
    monkeypatch.setenv("CLINAGENT_SEGMENTATION_TOOL_REMOTE_HOST", "remote-test")
    monkeypatch.setenv("CLINAGENT_SEGMENTATION_TOOL_REMOTE_ROOT", "/tmp/clinagent-test")

    def fake_subprocess_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == "ssh" and command[2].startswith("mkdir -p "):
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[0] == "ssh" and command[2].startswith("test -f "):
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[0] == "ssh" and command[2].startswith("rm -rf -- "):
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[0] == "scp" and command[1].startswith("remote-test:"):
            seg = np.zeros((48, 48, 48), dtype=np.uint8)
            seg[10:14, 10:14, 10:14] = 2
            _write_nifti(Path(command[2]), seg)
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[0] == "scp" and command[2].startswith("remote-test:"):
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"Unexpected subprocess command: {command}")

    monkeypatch.setattr(tumor_segmentation_module.subprocess, "run", fake_subprocess_run)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/model-info":
            return httpx.Response(200, json={"model_id": "gliomoda_v0.0.4_default"})
        if request.url.path == "/predict":
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["modalities"]["t1n"].startswith("/tmp/clinagent-test/tumor/")
            assert payload["modalities"]["t1c"].startswith("/tmp/clinagent-test/tumor/")
            assert payload["modalities"]["t2w"].startswith("/tmp/clinagent-test/tumor/")
            assert payload["modalities"]["t2f"].startswith("/tmp/clinagent-test/tumor/")
            assert payload["output_dir"].startswith("/tmp/clinagent-test/tumor/")
            return httpx.Response(200, json={"seg_path": f"{payload['output_dir']}/seg.nii.gz"})
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    result = BrainTumorSegmentationTool(
        service_url="http://127.0.0.1:9000",
        transport=httpx.MockTransport(handler),
    ).run(
        t1n_nifti_path=str(t1n),
        t1c_nifti_path=str(t1c),
        t2w_nifti_path=str(t2w),
        t2f_nifti_path=str(t2f),
        output_dir=str(tmp_path / "remote_out"),
    )

    assert result["remote_staging"]["enabled"] is True
    assert Path(result["seg_path"]).exists()
    assert Path(result["volumes_csv_path"]).exists()
