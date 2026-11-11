"""Serve data-first ingest/profile/confirm/workspace APIs for local datasets.
Input: source paths or uploaded files plus workflow confirmation parameters.
Output: standardized FastAPI JSON envelopes containing DataProfile or WorkspaceContract payloads.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from clinagent.platform.case_assembler import assemble_workspace
from clinagent.platform.data_profiler import profile_data_source
from clinagent.platform.local_data import resolve_local_upload_dir


def _response(*, ok: bool, data: Any = None, error: str | None = None) -> dict[str, Any]:
    return {"ok": ok, "data": data, "error": error}


class IngestWorkspaceStore:
    def __init__(self) -> None:
        self._profiles: dict[str, Any] = {}
        self._workspaces: dict[str, Any] = {}

    def profile(self, source_path: str) -> Any:
        profile = profile_data_source(source_path)
        self._profiles[str(Path(source_path).expanduser().resolve())] = profile
        return profile

    def confirm(self, source_path: str, selected_workflow: str, patient_overrides: dict[str, Any] | None = None) -> Any:
        resolved = str(Path(source_path).expanduser().resolve())
        profile = self._profiles.get(resolved) or self.profile(resolved)
        patient_uid = None
        if patient_overrides:
            patient_uid = patient_overrides.get("patient_uid") or patient_overrides.get("selected_patient_uid")
        workspace = assemble_workspace(profile, selected_workflow=selected_workflow, patient_uid=patient_uid)
        self._workspaces[workspace.workspace_id] = workspace
        return workspace

    def get_workspace(self, workspace_id: str) -> Any | None:
        return self._workspaces.get(workspace_id)


router = APIRouter()
ingest_workspace_store = IngestWorkspaceStore()


async def _extract_source_path(request: Request) -> str:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
        source_path = str((payload or {}).get("source_path") or "").strip()
        if source_path:
            return source_path
    if "multipart/form-data" in content_type:
        form = await request.form()
        source_path = str(form.get("source_path") or "").strip()
        if source_path:
            return source_path
        upload = form.get("upload")
        if upload is not None:
            upload_root = resolve_local_upload_dir()
            upload_root.mkdir(parents=True, exist_ok=True)
            filename = getattr(upload, "filename", "upload.bin") or "upload.bin"
            content = await upload.read()
            destination = upload_root / filename
            destination.write_bytes(content)
            return str(destination.resolve())
    raise ValueError("source_path or upload is required")


@router.post("/api/ingest/profile")
async def ingest_profile(request: Request) -> dict[str, Any]:
    try:
        resolved_source = await _extract_source_path(request)
        profile = ingest_workspace_store.profile(resolved_source)
        return _response(ok=True, data=asdict(profile), error=None)
    except Exception as exc:
        return _response(ok=False, data=None, error=str(exc))


@router.post("/api/ingest/confirm")
async def ingest_confirm(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
        source_path = str(payload.get("source_path") or "").strip()
        selected_workflow = str(payload.get("selected_workflow") or "").strip()
        patient_overrides = payload.get("patient_overrides") or {}
        if not source_path:
            raise ValueError("source_path is required")
        if not selected_workflow:
            raise ValueError("selected_workflow is required")
        workspace = ingest_workspace_store.confirm(source_path, selected_workflow, patient_overrides)
        return _response(
            ok=True,
            data={"workspace_id": workspace.workspace_id, "status": "assembling"},
            error=None,
        )
    except Exception as exc:
        return _response(ok=False, data=None, error=str(exc))


@router.get("/api/ingest/workspace/{workspace_id}")
async def ingest_workspace(workspace_id: str) -> dict[str, Any]:
    workspace = ingest_workspace_store.get_workspace(workspace_id)
    if workspace is None:
        return _response(ok=False, data=None, error=f"Unknown workspace_id: {workspace_id}")
    return _response(ok=True, data=asdict(workspace), error=None)
