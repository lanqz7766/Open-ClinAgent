"""Extract representative 2D slices from 3D NIfTI MRI volumes."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class VolumePayload:
    data: np.ndarray
    voxel_size_mm: tuple[float, float, float]


class SliceSelector:
    """Selects and renders key 2D slices from a 3D brain MRI volume.

    The selection strategy mimics how a neuroradiologist reviews a scan:
    - Axial: through the body of lateral ventricles (mid-to-upper brain)
    - Coronal: through the hippocampal formation (anterior temporal lobe)
    - Sagittal: mid-sagittal (midline structures, corpus callosum)
    """

    # Slice distribution by num_slices:
    # 1: 1 axial (55% z)
    # 3: 1 axial (55% z) + 1 coronal (40% y) + 1 sagittal (50% x)
    # 5: 2 axial (50%, 60% z) + 2 coronal (35%, 45% y) + 1 sagittal (50% x)
    # 7: 3 axial (45%, 55%, 65% z) + 2 coronal (35%, 45% y) + 2 sagittal (45%, 55% x)

    SLICE_PLANS: dict[int, list[tuple[str, float, str]]] = {
        1: [("axial", 0.55, "Axial slice through lateral ventricle body")],
        3: [
            ("axial", 0.55, "Axial slice through lateral ventricle body"),
            ("coronal", 0.40, "Coronal slice through hippocampal formation"),
            ("sagittal", 0.50, "Mid-sagittal slice"),
        ],
        5: [
            ("axial", 0.50, "Axial slice through lower lateral ventricles"),
            ("axial", 0.60, "Axial slice through upper lateral ventricles"),
            ("coronal", 0.35, "Coronal slice through anterior hippocampus"),
            ("coronal", 0.45, "Coronal slice through posterior hippocampus"),
            ("sagittal", 0.50, "Mid-sagittal slice"),
        ],
        7: [
            ("axial", 0.45, "Axial slice through inferior lateral ventricles"),
            ("axial", 0.55, "Axial slice through lateral ventricle body"),
            ("axial", 0.65, "Axial slice through superior lateral ventricles"),
            ("coronal", 0.35, "Coronal slice through anterior hippocampus"),
            ("coronal", 0.45, "Coronal slice through posterior hippocampus"),
            ("sagittal", 0.45, "Left parasagittal slice"),
            ("sagittal", 0.55, "Right parasagittal slice"),
        ],
    }

    PLANE_AXIS = {"sagittal": 0, "coronal": 1, "axial": 2}
    ORIENTATION_LABELS = {
        "axial": {"left": "R", "right": "L", "top": "A", "bottom": "P"},
        "coronal": {"left": "R", "right": "L", "top": "S", "bottom": "I"},
        "sagittal": {"left": "A", "right": "P", "top": "S", "bottom": "I"},
    }
    OVERLAY_COLOURS: tuple[tuple[int, int, int], ...] = (
        (230, 57, 70),
        (29, 78, 216),
        (22, 163, 74),
        (245, 158, 11),
        (168, 85, 247),
        (236, 72, 153),
        (14, 165, 233),
        (132, 204, 22),
        (249, 115, 22),
        (99, 102, 241),
    )
    DEFAULT_FRACTIONS: dict[str, float] = {
        "axial": 0.55,
        "coronal": 0.40,
        "sagittal": 0.50,
    }

    def __init__(self, num_slices: int | None = 5, output_size: tuple[int, int] = (512, 512)):
        if num_slices is not None and num_slices not in self.SLICE_PLANS:
            raise ValueError(f"num_slices must be one of {list(self.SLICE_PLANS)}, got {num_slices}")
        self.num_slices = num_slices
        self.output_size = output_size
        self._volume_cache: dict[str, VolumePayload] = {}

    def select_slices(self, nifti_path: str | Path) -> list[dict]:
        """Extract key slices from a NIfTI volume.

        Returns list of dicts each containing:
            plane, slice_index, slice_fraction, image_array (uint8 0-255), description
        """
        if self.num_slices is None:
            raise ValueError("select_slices requires a selector configured with num_slices.")
        volume = self._load_volume(nifti_path)
        data = volume.data

        results = []
        for plane, fraction, desc in self.SLICE_PLANS[self.num_slices]:
            axis = self.PLANE_AXIS[plane]
            idx = int(round(fraction * (data.shape[axis] - 1)))
            results.append(
                self._slice_entry(
                    data=data,
                    plane=plane,
                    index=idx,
                    description=desc,
                    voxel_size_mm=volume.voxel_size_mm,
                )
            )
        return results

    def select_dense_slices(
        self,
        nifti_path: str | Path,
        *,
        stride: int = 1,
        max_slices_per_plane: int | None = None,
    ) -> list[dict]:
        """Extract a dense slice payload for tri-view browsing.

        This is intended for interactive structural viewers where smooth plane
        navigation matters more than hand-picked representative descriptions.
        """
        if stride <= 0:
            raise ValueError("stride must be >= 1")

        volume = self._load_volume(nifti_path)
        data = volume.data

        results = []
        for plane, axis in self.PLANE_AXIS.items():
            indices = list(range(0, data.shape[axis], stride))
            if indices[-1] != data.shape[axis] - 1:
                indices.append(data.shape[axis] - 1)
            if max_slices_per_plane and len(indices) > max_slices_per_plane:
                sampled = np.linspace(0, len(indices) - 1, max_slices_per_plane, dtype=int)
                indices = [indices[position] for position in sampled]

            for idx in indices:
                results.append(
                    self._slice_entry(
                        data=data,
                        plane=plane,
                        index=idx,
                        description="",
                        voxel_size_mm=volume.voxel_size_mm,
                    )
                )
        return results

    def get_slice_manifest(
        self,
        nifti_path: str | Path,
        *,
        has_overlay: bool,
        seg_nifti_path: str | Path | None = None,
    ) -> dict:
        data = self._load_volume(nifti_path).data
        planes: dict[str, dict[str, int]] = {}
        seg_data = None
        if has_overlay and seg_nifti_path is not None:
            seg_data = self._load_volume(seg_nifti_path).data
        for plane, axis in self.PLANE_AXIS.items():
            slice_count = int(data.shape[axis])
            default_index = (
                self._default_overlay_index(seg_data, axis)
                if seg_data is not None
                else int(round(self.DEFAULT_FRACTIONS[plane] * max(slice_count - 1, 1)))
            )
            planes[plane] = {
                "slice_count": slice_count,
                "default_index": default_index,
            }
        return {
            "mode": "on_demand",
            "orientation_policy": "radiological",
            "output_size": [int(self.output_size[0]), int(self.output_size[1])],
            "has_overlay": bool(has_overlay),
            "planes": planes,
        }

    @staticmethod
    def _default_overlay_index(seg_data: np.ndarray, axis: int) -> int:
        nonzero_mask = seg_data > 0
        collapsed_axes = tuple(dim for dim in range(nonzero_mask.ndim) if dim != axis)
        coverage = nonzero_mask.sum(axis=collapsed_axes)
        if coverage.size == 0 or np.max(coverage) <= 0:
            slice_count = int(seg_data.shape[axis])
            return int(round(0.5 * max(slice_count - 1, 1)))
        return int(np.argmax(coverage))

    def select_slice(self, nifti_path: str | Path, *, plane: str, index: int, description: str = "") -> dict:
        volume = self._load_volume(nifti_path)
        return self._slice_entry(
            data=volume.data,
            plane=plane,
            index=index,
            description=description,
            voxel_size_mm=volume.voxel_size_mm,
        )

    def render_to_png_bytes(self, slice_data: dict) -> bytes:
        """Convert a slice dict to PNG bytes for base64 encoding to VLM."""
        image_array, _ = self._render_image_with_padding(
            slice_data["image_array"],
            display_spacing_mm=slice_data.get("display_spacing_mm"),
            display_extent_mm=slice_data.get("display_extent_mm"),
        )
        buf = io.BytesIO()
        Image.fromarray(image_array, mode="L").save(buf, format="PNG")
        buf.seek(0)
        return buf.read()

    def render_with_overlay(self, slice_data: dict, seg_nifti_path: str | Path) -> bytes:
        """Render slice with segmentation mask overlay (Config 2 ablation).

        Each non-zero label gets a distinct colour with alpha=0.3.
        """
        anatomy_image, _ = self._render_image_with_padding(
            slice_data["image_array"],
            display_spacing_mm=slice_data.get("display_spacing_mm"),
            display_extent_mm=slice_data.get("display_extent_mm"),
        )
        anat = anatomy_image.astype(np.float32) / 255.0
        seg_slice = self.extract_segmentation_slice(slice_data, seg_nifti_path)
        # Create RGB base from anatomical image (grayscale -> RGB)
        h, w = anat.shape
        rgb = np.zeros((h, w, 3), dtype=np.float32)
        rgb[..., 0] = anat
        rgb[..., 1] = anat
        rgb[..., 2] = anat

        # Blend each non-zero label with a deterministic colour so the overlay
        # remains stable without relying on matplotlib in the main runtime.
        labels = np.unique(seg_slice)
        labels = labels[labels != 0]

        for i, label_id in enumerate(labels):
            mask = seg_slice == label_id
            colour = np.array(self.OVERLAY_COLOURS[i % len(self.OVERLAY_COLOURS)], dtype=np.float32) / 255.0
            alpha = 0.3
            for c in range(3):
                rgb[..., c][mask] = (1 - alpha) * rgb[..., c][mask] + alpha * colour[c]

        buf = io.BytesIO()
        Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), mode="RGB").save(buf, format="PNG")
        buf.seek(0)
        return buf.read()

    def extract_segmentation_slice(self, slice_data: dict, seg_nifti_path: str | Path) -> np.ndarray:
        """Return an oriented, resized integer label map for a selected slice."""
        seg_volume = self._load_volume(seg_nifti_path)
        seg_data = seg_volume.data
        axis = self.PLANE_AXIS[slice_data["plane"]]
        fraction = float(slice_data.get("slice_fraction", 0.0) or 0.0)
        seg_index = int(round(clamp(fraction, 0.0, 1.0) * max(seg_data.shape[axis] - 1, 0)))
        seg_slice = np.take(seg_data, seg_index, axis=axis).astype(np.int32)
        rendered, _ = self._render_mask_with_padding(
            seg_slice,
            display_spacing_mm=self._display_spacing_for_plane(slice_data["plane"], seg_volume.voxel_size_mm),
            display_extent_mm=slice_data.get("display_extent_mm"),
        )
        return rendered

    def get_render_metadata(self, slice_data: dict) -> dict:
        """Return rendering metadata for padded square display without distorting aspect ratio."""
        _, metadata = self._render_image_with_padding(
            slice_data["image_array"],
            display_spacing_mm=slice_data.get("display_spacing_mm"),
            display_extent_mm=slice_data.get("display_extent_mm"),
        )
        return metadata

    def _load_volume(self, nifti_path: str | Path) -> VolumePayload:
        key = str(Path(nifti_path).resolve())
        cached = self._volume_cache.get(key)
        if cached is not None:
            return cached
        image = nib.load(key)
        image = nib.as_closest_canonical(image)
        data = image.get_fdata(dtype=np.float32)
        voxel_size_mm = tuple(float(value) for value in image.header.get_zooms()[:3])
        payload = VolumePayload(data=data, voxel_size_mm=voxel_size_mm)
        self._volume_cache[key] = payload
        return payload

    def _slice_entry(
        self,
        *,
        data: np.ndarray,
        plane: str,
        index: int,
        description: str,
        voxel_size_mm: tuple[float, float, float],
    ) -> dict:
        axis = self.PLANE_AXIS[plane]
        clamped_index = int(np.clip(index, 0, max(data.shape[axis] - 1, 0)))
        raw_slice = np.take(data, clamped_index, axis=axis)
        normed = self._normalize(raw_slice)
        display_spacing_mm = self._display_spacing_for_plane(plane, voxel_size_mm)
        display_extent_mm = [
            float(raw_slice.shape[1] * display_spacing_mm[0]),
            float(raw_slice.shape[0] * display_spacing_mm[1]),
        ]
        return {
            "plane": plane,
            "slice_index": clamped_index,
            "slice_fraction": clamped_index / max(data.shape[axis] - 1, 1),
            "image_array": normed,
            "display_spacing_mm": [float(display_spacing_mm[0]), float(display_spacing_mm[1])],
            "display_extent_mm": display_extent_mm,
            "description": description,
            "orientation_labels": self.ORIENTATION_LABELS[plane],
            "orientation_policy": "radiological",
        }

    @staticmethod
    def _normalize(arr: np.ndarray) -> np.ndarray:
        """Clip to 1st-99th percentile and scale to uint8 0-255."""
        p1, p99 = np.percentile(arr, (1, 99))
        if p99 - p1 < 1e-6:
            return np.zeros_like(arr, dtype=np.uint8)
        clipped = np.clip(arr, p1, p99)
        scaled = (clipped - p1) / (p99 - p1) * 255.0
        return scaled.astype(np.uint8)

    def _resize_image(self, arr: np.ndarray) -> np.ndarray:
        """Resize image arrays to the configured output size."""
        target_width = self.output_size[1]
        target_height = self.output_size[0]
        if arr.shape == (target_height, target_width):
            return arr
        image = Image.fromarray(arr)
        resized = image.resize((target_width, target_height), resample=Image.Resampling.BILINEAR)
        return np.asarray(resized, dtype=np.uint8)

    def _resize_mask(self, arr: np.ndarray) -> np.ndarray:
        """Resize label masks without interpolating label IDs."""
        target_width = self.output_size[1]
        target_height = self.output_size[0]
        if arr.shape == (target_height, target_width):
            return arr
        image = Image.fromarray(arr.astype(np.int32), mode="I")
        resized = image.resize((target_width, target_height), resample=Image.Resampling.NEAREST)
        return np.asarray(resized, dtype=np.int32)

    @staticmethod
    def _display_spacing_for_plane(
        plane: str,
        voxel_size_mm: tuple[float, float, float],
    ) -> tuple[float, float]:
        x_mm, y_mm, z_mm = voxel_size_mm
        if plane == "axial":
            return y_mm, x_mm
        if plane == "coronal":
            return z_mm, x_mm
        return z_mm, y_mm

    def _fit_shape(
        self,
        shape: tuple[int, int],
        *,
        physical_shape: tuple[float, float] | None = None,
    ) -> tuple[int, int, dict[str, int]]:
        src_height, src_width = shape
        target_height, target_width = self.output_size
        if src_height <= 0 or src_width <= 0:
            return target_height, target_width, {
                "left": 0,
                "right": 0,
                "top": 0,
                "bottom": 0,
            }

        physical_height = float(physical_shape[0]) if physical_shape else float(src_height)
        physical_width = float(physical_shape[1]) if physical_shape else float(src_width)
        physical_height = max(physical_height, 1e-6)
        physical_width = max(physical_width, 1e-6)

        scale = min(target_width / physical_width, target_height / physical_height)
        render_width = max(1, min(target_width, int(round(physical_width * scale))))
        render_height = max(1, min(target_height, int(round(physical_height * scale))))
        pad_left = max(0, (target_width - render_width) // 2)
        pad_top = max(0, (target_height - render_height) // 2)
        pad_right = max(0, target_width - render_width - pad_left)
        pad_bottom = max(0, target_height - render_height - pad_top)
        return render_height, render_width, {
            "left": pad_left,
            "right": pad_right,
            "top": pad_top,
            "bottom": pad_bottom,
        }

    def _physical_shape(
        self,
        *,
        source_shape: tuple[int, int],
        display_spacing_mm: list[float] | tuple[float, float] | None,
        display_extent_mm: list[float] | tuple[float, float] | None,
    ) -> tuple[float, float]:
        if display_extent_mm and len(display_extent_mm) == 2:
            return float(display_extent_mm[0]), float(display_extent_mm[1])
        if display_spacing_mm and len(display_spacing_mm) == 2:
            return (
                float(source_shape[0]) * float(display_spacing_mm[0]),
                float(source_shape[1]) * float(display_spacing_mm[1]),
            )
        return float(source_shape[0]), float(source_shape[1])

    def _render_image_with_padding(
        self,
        arr: np.ndarray,
        *,
        display_spacing_mm: list[float] | tuple[float, float] | None = None,
        display_extent_mm: list[float] | tuple[float, float] | None = None,
    ) -> tuple[np.ndarray, dict]:
        oriented = self._orient_for_display(arr)
        source_height, source_width = oriented.shape
        physical_shape = self._physical_shape(
            source_shape=(source_height, source_width),
            display_spacing_mm=display_spacing_mm,
            display_extent_mm=display_extent_mm,
        )
        render_height, render_width, padding = self._fit_shape((source_height, source_width), physical_shape=physical_shape)
        if (render_height, render_width) == (source_height, source_width):
            resized = oriented.astype(np.uint8, copy=False)
        else:
            image = Image.fromarray(oriented)
            resized = np.asarray(
                image.resize((render_width, render_height), resample=Image.Resampling.BILINEAR),
                dtype=np.uint8,
            )
        canvas = np.zeros(self.output_size, dtype=np.uint8)
        top = padding["top"]
        left = padding["left"]
        canvas[top : top + render_height, left : left + render_width] = resized
        metadata = {
            "original_shape": [int(source_height), int(source_width)],
            "render_shape": [int(self.output_size[0]), int(self.output_size[1])],
            "content_bbox": {
                "x": int(left),
                "y": int(top),
                "width": int(render_width),
                "height": int(render_height),
            },
            "padding": {key: int(value) for key, value in padding.items()},
            "display_spacing_mm": [float(display_spacing_mm[0]), float(display_spacing_mm[1])] if display_spacing_mm else None,
        }
        return canvas, metadata

    def _render_mask_with_padding(
        self,
        arr: np.ndarray,
        *,
        display_spacing_mm: list[float] | tuple[float, float] | None = None,
        display_extent_mm: list[float] | tuple[float, float] | None = None,
    ) -> tuple[np.ndarray, dict]:
        oriented = self._orient_for_display(arr)
        source_height, source_width = oriented.shape
        physical_shape = self._physical_shape(
            source_shape=(source_height, source_width),
            display_spacing_mm=display_spacing_mm,
            display_extent_mm=display_extent_mm,
        )
        render_height, render_width, padding = self._fit_shape((source_height, source_width), physical_shape=physical_shape)
        if (render_height, render_width) == (source_height, source_width):
            resized = oriented.astype(np.int32, copy=False)
        else:
            image = Image.fromarray(oriented.astype(np.int32), mode="I")
            resized = np.asarray(
                image.resize((render_width, render_height), resample=Image.Resampling.NEAREST),
                dtype=np.int32,
            )
        canvas = np.zeros(self.output_size, dtype=np.int32)
        top = padding["top"]
        left = padding["left"]
        canvas[top : top + render_height, left : left + render_width] = resized
        metadata = {
            "original_shape": [int(source_height), int(source_width)],
            "render_shape": [int(self.output_size[0]), int(self.output_size[1])],
            "content_bbox": {
                "x": int(left),
                "y": int(top),
                "width": int(render_width),
                "height": int(render_height),
            },
            "padding": {key: int(value) for key, value in padding.items()},
            "display_spacing_mm": [float(display_spacing_mm[0]), float(display_spacing_mm[1])] if display_spacing_mm else None,
        }
        return canvas, metadata

    @staticmethod
    def _orient_for_display(arr: np.ndarray) -> np.ndarray:
        oriented = np.transpose(arr)
        oriented = np.flipud(oriented)
        oriented = np.fliplr(oriented)
        return oriented


def clamp(value: float, min_value: float, max_value: float) -> float:
    return min(max_value, max(min_value, value))
