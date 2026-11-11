from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from fastapi import UploadFile

from clinagent.gateway.auth import ClinAgentAuthStore
from clinagent.platform.local_data import REPO_ROOT


UPLOAD_JOB_TYPE = "brain_tumor_upload_segment"
UPLOAD_MODALITIES = ("t1n", "t1c", "t2w", "t2f")
MAX_FILE_BYTES = 350 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
STREAM_CHUNK_BYTES = 1024 * 1024
DEFAULT_RETENTION_DAYS = 30


def upload_root() -> Path:
    configured = os.getenv("CLINAGENT_BRAIN_TUMOR_UPLOAD_ROOT", "").strip()
    root = Path(configured).expanduser() if configured else REPO_ROOT / ".clinagent" / "derived" / "brain_tumor" / "_uploads"
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def retention_days() -> int:
    raw = os.getenv("CLINAGENT_UPLOAD_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS)).strip()
    try:
        return max(1, min(int(raw), 365))
    except ValueError:
        return DEFAULT_RETENTION_DAYS


def _now() -> datetime:
    return datetime.now(UTC)


def _is_nifti_name(filename: str) -> bool:
    normalized = filename.strip().lower()
    return normalized.endswith(".nii") or normalized.endswith(".nii.gz")


async def _stream_upload(upload: UploadFile, target: Path, *, remaining_total: int) -> int:
    filename = str(upload.filename or "")
    if not _is_nifti_name(filename):
        raise ValueError("Each modality must be a .nii or .nii.gz NIfTI file.")

    written = 0
    try:
        with target.open("wb") as handle:
            while True:
                chunk = await upload.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_FILE_BYTES:
                    raise ValueError("Each NIfTI file must be 350 MB or smaller.")
                if written > remaining_total:
                    raise ValueError("The uploaded NIfTI files must be 1 GB or smaller in total.")
                handle.write(chunk)
    finally:
        await upload.close()
    if written == 0:
        raise ValueError("Uploaded NIfTI files cannot be empty.")
    return written


def _sanitize_nifti(source: Path, target: Path) -> dict[str, Any]:
    try:
        image = nib.load(str(source))
    except Exception as exc:
        raise ValueError("One of the uploaded files is not a readable NIfTI volume.") from exc

    shape = tuple(int(value) for value in image.shape)
    if len(shape) != 3 or any(value < 2 or value > 1024 for value in shape):
        raise ValueError("Each modality must be a three-dimensional MRI volume with valid dimensions.")

    affine = np.asarray(image.affine, dtype=np.float64)
    if affine.shape != (4, 4) or not np.isfinite(affine).all() or abs(float(np.linalg.det(affine[:3, :3]))) < 1e-8:
        raise ValueError("One of the uploaded volumes has an invalid affine transform.")

    spacing = tuple(float(value) for value in image.header.get_zooms()[:3])
    if len(spacing) != 3 or any(not np.isfinite(value) or value <= 0 or value > 20 for value in spacing):
        raise ValueError("One of the uploaded volumes has invalid voxel spacing.")

    header = image.header.copy()
    for key in ("descrip", "aux_file", "db_name", "intent_name"):
        if key in header:
            header[key] = b""
    header.extensions.clear()
    clean_image = nib.Nifti1Image(image.dataobj, affine, header=header)
    qform_code = int(image.header.get("qform_code", 0)) or 1
    sform_code = int(image.header.get("sform_code", 0)) or 1
    clean_image.set_qform(affine, code=qform_code)
    clean_image.set_sform(affine, code=sform_code)
    nib.save(clean_image, str(target))
    return {
        "shape": list(shape),
        "spacing_mm": [round(value, 6) for value in spacing],
        "affine": np.round(affine, 6).tolist(),
    }


def _grid_matches(reference: dict[str, Any], candidate: dict[str, Any]) -> bool:
    return bool(
        reference.get("shape") == candidate.get("shape")
        and np.allclose(reference.get("affine"), candidate.get("affine"), atol=1e-4, rtol=1e-5)
    )


async def create_upload_case(
    *,
    auth_store: ClinAgentAuthStore,
    user_id: str,
    uploads: dict[str, UploadFile],
) -> tuple[dict[str, Any], dict[str, Any]]:
    from clinagent.gateway.brain_tumor_upload_visits import create_visit_upload_case

    return await create_visit_upload_case(auth_store=auth_store, user_id=user_id, visits=[{"date": None, "uploads": uploads}])


def read_upload_manifest(case_id: str) -> dict[str, Any] | None:
    path = upload_root() / case_id / "manifest.json"
    try:
        resolved = path.resolve()
        root = upload_root()
        if root not in resolved.parents or not resolved.exists():
            return None
        return json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def remove_upload_case(case_id: str) -> None:
    root = upload_root()
    target = (root / case_id).resolve()
    if root in target.parents:
        shutil.rmtree(target, ignore_errors=True)
