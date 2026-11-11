from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np

from clinagent.families.neuro.preprocessing import MRISequence, SequenceRouter, SliceSelector


def _write_nifti(path: Path, data: np.ndarray, affine: np.ndarray | None = None) -> Path:
    image = nib.Nifti1Image(data.astype(np.float32), affine if affine is not None else np.eye(4))
    nib.save(image, str(path))
    return path


def test_slice_selector_returns_expected_slice_count(tmp_path: Path) -> None:
    volume_path = _write_nifti(tmp_path / "brain_t1w.nii.gz", np.random.rand(64, 64, 64))

    selector = SliceSelector(num_slices=5)
    slices = selector.select_slices(volume_path)

    assert len(slices) == 5
    assert {item["plane"] for item in slices} == {"axial", "coronal", "sagittal"}
    assert all(item["image_array"].dtype == np.uint8 for item in slices)


def test_render_to_png_bytes_returns_content(tmp_path: Path) -> None:
    volume_path = _write_nifti(tmp_path / "brain_t1w.nii.gz", np.random.rand(64, 64, 64))

    selector = SliceSelector(num_slices=3)
    first_slice = selector.select_slices(volume_path)[0]
    png_bytes = selector.render_to_png_bytes(first_slice)

    assert png_bytes.startswith(b"\x89PNG")
    assert len(png_bytes) > 100


def test_render_with_overlay_returns_content(tmp_path: Path) -> None:
    volume_path = _write_nifti(tmp_path / "brain_t1w.nii.gz", np.random.rand(64, 64, 64))
    seg = np.zeros((64, 64, 64), dtype=np.int16)
    seg[20:40, 20:40, 30] = 17
    seg_path = _write_nifti(tmp_path / "seg.nii.gz", seg)

    selector = SliceSelector(num_slices=1)
    slice_data = selector.select_slices(volume_path)[0]
    png_bytes = selector.render_with_overlay(slice_data, seg_path)

    assert png_bytes.startswith(b"\x89PNG")
    assert len(png_bytes) > 100


def test_slice_manifest_prefers_segmentation_dense_slice(tmp_path: Path) -> None:
    volume_path = _write_nifti(tmp_path / "brain_t1w.nii.gz", np.random.rand(32, 32, 32))
    seg = np.zeros((32, 32, 32), dtype=np.int16)
    seg[6:26, 5:27, 21] = 3
    seg[10:20, 10:20, 10] = 7
    seg_path = _write_nifti(tmp_path / "seg.nii.gz", seg)

    selector = SliceSelector(num_slices=3)
    manifest = selector.get_slice_manifest(volume_path, has_overlay=True, seg_nifti_path=seg_path)

    assert manifest["planes"]["axial"]["default_index"] == 21


def test_sequence_router_identifies_t1w_from_filename() -> None:
    router = SequenceRouter()

    assert router.identify_from_filename("sub-001_T1w.nii.gz") is MRISequence.T1W
    assert router.identify_from_metadata({"series_description": "Axial FLAIR"}) is MRISequence.FLAIR
