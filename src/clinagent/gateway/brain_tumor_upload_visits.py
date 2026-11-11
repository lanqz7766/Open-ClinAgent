"""Owned, ordered upload visits and recoverable case manifests."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import date, timedelta
import fcntl
import json
from pathlib import Path
import re
import shutil
from typing import Any
import uuid

from clinagent.gateway.brain_tumor_uploads import (
    MAX_TOTAL_BYTES, UPLOAD_JOB_TYPE, UPLOAD_MODALITIES, _grid_matches, _now,
    _sanitize_nifti, _stream_upload, read_upload_manifest, retention_days, upload_root,
)

MAX_VISITS = 6


def manifest_visits(manifest: dict[str, Any], previous_job: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if isinstance(manifest.get("visits"), list):
        return manifest["visits"]
    result = (previous_job or {}).get("result") or {}
    session = result.get("session")
    return [{
        "id": "visit_01", "date": None, "modalities": manifest.get("modalities", {}),
        "resample_to_t1c": manifest.get("resample_to_t1c", []),
        "session_id": manifest.get("session_id") or result.get("session_id"),
        "session": session, "status": "complete" if session or manifest.get("session_id") else "queued",
    }]


def visit_input_root(case_id: str, visit_id: str) -> Path:
    if not re.fullmatch(r"visit_0[1-6]", visit_id):
        raise ValueError("Invalid visit identifier.")
    root = upload_root() / case_id / "inputs"
    return root if visit_id == "visit_01" else root / visit_id


def write_manifest(manifest: dict[str, Any]) -> None:
    root = upload_root() / manifest["case_id"]
    temporary = root / f".manifest-{uuid.uuid4().hex}.json"
    try:
        temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        temporary.replace(root / "manifest.json")
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def case_mutation_lock(case_id: str):
    root = upload_root() / case_id
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".mutation.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("This case is being updated. Please retry shortly.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def validate_visit_dates(visits: list[dict[str, Any]]) -> None:
    previous = None
    for visit in visits:
        value = visit.get("date")
        if value in (None, ""):
            visit["date"] = None
            continue
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Visit dates must use YYYY-MM-DD, or be left blank.")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("One of the visit dates is invalid.") from exc
        if previous and parsed < previous:
            raise ValueError("Visit dates must follow the confirmed visit order. Check the dates or reorder the new visits.")
        previous = parsed


def parse_visit_uploads(specification: str, files: list) -> list[dict[str, Any]]:
    try:
        rows = json.loads(specification)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid visit mapping.") from exc
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_VISITS:
        raise ValueError("Upload between one and six visits, with four modalities per visit.")
    used = []
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) - {"date", "files"}:
            raise ValueError("Invalid visit mapping.")
        mapping = row.get("files")
        if not isinstance(mapping, dict) or set(mapping) != set(UPLOAD_MODALITIES):
            raise ValueError("Every visit requires T1, T1c, T2 and FLAIR.")
        indices = list(mapping.values())
        if any(type(index) is not int or not 0 <= index < len(files) for index in indices):
            raise ValueError("Invalid file assignment.")
        used.extend(indices)
        result.append({"date": row.get("date"), "uploads": {key: files[index] for key, index in mapping.items()}})
    if len(used) != len(files) or sorted(used) != list(range(len(files))):
        raise ValueError("Each file must be assigned to exactly one visit and modality.")
    validate_visit_dates(result)
    return result


def upload_result(manifest: dict[str, Any], *, status: str, stage: str) -> dict[str, Any]:
    visits = manifest_visits(manifest)
    complete = sum(visit.get("status") == "complete" for visit in visits)
    failed = sum(visit.get("status") == "failed" for visit in visits)
    result = {
        "ok": status != "failed", "case_id": manifest["case_id"], "status": status, "stage": stage,
        "total_count": len(visits), "completed_count": complete, "failed_count": failed,
        "visits": [{key: visit.get(key) for key in ("id", "date", "relative_day", "relative_day_origin", "status", "session_id", "session")} for visit in visits],
    }
    if len(visits) == 1 and visits[0].get("session"):
        result.update(session=visits[0]["session"], session_id=visits[0]["session_id"])
    return result


def remove_upload_sessions(*, auth_store, demo_store, case_id: str, owner_user_id: str) -> None:
    # Include every visit and any older retry session, not only the latest job.
    source = f"nifti_upload:{case_id}"
    sessions = auth_store.list_owned_cases(user_id=owner_user_id, source=source)
    sessions += [row for row in auth_store.list_expired_cases(source=source) if row["owner_user_id"] == owner_user_id]
    for access in sessions:
        session_id = str(access["id"])
        auth_store.mark_case_deleted(case_id=session_id, owner_user_id=owner_user_id)
        path = (demo_store.asset_root / session_id).resolve()
        if demo_store.asset_root.resolve() in path.parents:
            shutil.rmtree(path, ignore_errors=True)


async def create_visit_upload_case(*, auth_store, user_id: str, visits: list[dict[str, Any]], target_case_id: str | None = None):
    if not 1 <= len(visits) <= MAX_VISITS:
        raise ValueError("Upload between one and six visits.")
    if any(set(visit.get("uploads", {})) != set(UPLOAD_MODALITIES) for visit in visits):
        raise ValueError("Every visit requires T1, T1c, T2 and FLAIR.")
    if auth_store.get_active_job(user_id=user_id):
        raise ValueError("Another segmentation job is already active for this account.")
    original = None
    previous_visits = []
    if target_case_id:
        access = auth_store.get_case_access(case_id=target_case_id)
        if not access or access.get("owner_user_id") != user_id or access.get("source") != "nifti_upload":
            raise LookupError("Uploaded case not found.")
        original = read_upload_manifest(target_case_id)
        if original is None:
            raise LookupError("Uploaded case not found.")
    case_id = target_case_id or f"upload_{uuid.uuid4().hex[:16]}"
    root = upload_root() / case_id
    published = []
    registered = False
    with case_mutation_lock(case_id):
        if target_case_id:
            original = read_upload_manifest(case_id)
            if original is None:
                raise LookupError("Uploaded case not found.")
            previous_job = auth_store.get_latest_job_for_case(user_id=user_id, case_id=case_id, job_type=UPLOAD_JOB_TYPE)
            previous_visits = manifest_visits(original, previous_job)
        if len(previous_visits) + len(visits) > MAX_VISITS:
            raise ValueError("A case can contain up to six visits in this preview.")
        validate_visit_dates([*previous_visits, *visits])
        staged = root / f".staging-{uuid.uuid4().hex}"
        staged.mkdir()
        try:
            total_bytes = 0
            prepared = []
            for index, visit in enumerate(visits, start=len(previous_visits) + 1):
                visit_id = f"visit_{index:02d}"
                visit_stage = staged / visit_id
                visit_stage.mkdir()
                metadata = {}
                for modality in UPLOAD_MODALITIES:
                    upload = visit["uploads"][modality]
                    suffix = ".nii.gz" if str(upload.filename or "").lower().endswith(".nii.gz") else ".nii"
                    incoming = visit_stage / f"incoming-{modality}{suffix}"
                    written = await _stream_upload(upload, incoming, remaining_total=MAX_TOTAL_BYTES - total_bytes)
                    total_bytes += written
                    metadata[modality] = await asyncio.to_thread(_sanitize_nifti, incoming, visit_stage / f"{modality}.nii.gz")
                    metadata[modality]["upload_bytes"] = written
                    incoming.unlink()
                prepared.append({"id": visit_id, "date": visit.get("date") or None, "status": "queued", "modalities": metadata,
                    "resample_to_t1c": [key for key in UPLOAD_MODALITIES if key != "t1c" and not _grid_matches(metadata["t1c"], metadata[key])]})
            if target_case_id and not auth_store.can_access_case(case_id=case_id, user_id=user_id):
                raise LookupError("Uploaded case not found.")
            created_at = _now()
            manifest = dict(original) if original else {
                "case_id": case_id, "display_label": f"Uploaded case {case_id[-6:].upper()}",
                "created_at": created_at.isoformat(), "expires_at": (created_at + timedelta(days=retention_days())).isoformat(),
                "retention_days": retention_days(), "deidentified": True,
            }
            manifest["visits"] = [*previous_visits, *prepared]
            manifest["total_upload_bytes"] = int(manifest.get("total_upload_bytes", 0)) + total_bytes
            manifest["modalities"] = manifest["visits"][0]["modalities"]
            manifest["resample_to_t1c"] = manifest["visits"][0]["resample_to_t1c"]
            for visit in prepared:
                target = visit_input_root(case_id, visit["id"])
                target.parent.mkdir(parents=True, exist_ok=True)
                (staged / visit["id"]).rename(target)
                published.append(target)
            write_manifest(manifest)
            if not target_case_id:
                auth_store.register_case_access(case_id=case_id, owner_user_id=user_id, source="nifti_upload", expires_at=manifest["expires_at"])
                registered = True
            job, created = auth_store.create_queued_job(user_id=user_id, job_type=UPLOAD_JOB_TYPE, case_id=case_id,
                payload={"case_id": case_id, "display_label": manifest["display_label"], "expires_at": manifest["expires_at"]},
                initial_result=upload_result(manifest, status="queued", stage="queued"))
            if not created:
                raise ValueError("Another segmentation job is already active for this account.")
            return manifest, job
        except Exception:
            for path in reversed(published):
                shutil.rmtree(path, ignore_errors=True)
            if original and auth_store.can_access_case(case_id=case_id, user_id=user_id):
                write_manifest(original)
            elif not target_case_id:
                if registered:
                    auth_store.mark_case_deleted(case_id=case_id, owner_user_id=user_id)
                shutil.rmtree(root, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(staged, ignore_errors=True)
            for visit in visits:
                for upload in visit.get("uploads", {}).values():
                    await upload.close()
