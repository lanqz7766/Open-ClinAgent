from __future__ import annotations

import csv
import base64
import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import socket
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import nibabel as nib
import numpy as np
from PIL import Image

from clinagent.connectors.base import ConnectorError, ConnectorMode
from clinagent.connectors.imaging import DICOMWebConnector
from clinagent.families.neuro.registration.workflow import align_visit, pending_steps
from clinagent.families.neuro.tools import BrainTumorSegmentationTool
from clinagent.platform.config import load_settings
from clinagent.platform.local_data import REPO_ROOT

MODALITY_KEYS = ("t1n", "t1c", "t2w", "t2f")
REQUIRED_MODALITIES = MODALITY_KEYS


@dataclass(frozen=True)
class ModalityCandidate:
    modality: str
    score: float
    reason: str


class BrainTumorDemoStore:
    """Daily-use brain tumor segmentation workspace backing store.

    This store keeps real imaging artifacts under the local `.clinagent` tree and
    exposes only session-scoped URLs to the browser.
    """

    def __init__(self, *, asset_root: Path | None = None) -> None:
        configured_root = os.getenv("CLINAGENT_BRAIN_TUMOR_ASSET_ROOT", "").strip()
        default_root = Path(configured_root).expanduser() if configured_root else REPO_ROOT / ".clinagent" / "derived" / "brain_tumor"
        self.asset_root = (asset_root or default_root).resolve()
        self.asset_root.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, dict[str, Any]] = {}
        self._internal_sessions: dict[str, dict[str, Any]] = {}
        self._registry_session_path_index: dict[tuple[str, str, str], list[Path]] | None = None
        self._registry_background_runs: set[tuple[str, str, str]] = set()
        self._registry_background_run_lock = threading.Lock()
        self._registry_case_summary_cache_path = self.asset_root / "registry_case_demo_summary.json"
        self._registry_segment_jobs: dict[str, dict[str, Any]] = {}
        self._registry_segment_jobs_lock = threading.Lock()
        self._longitudinal_align_jobs: dict[str, dict[str, Any]] = {}
        self._longitudinal_align_jobs_lock = threading.Lock()

    def service_status(self) -> dict[str, Any]:
        settings = load_settings()
        tool = BrainTumorSegmentationTool()
        payload: dict[str, Any] = {
            "ok": False,
            "ready": False,
            "service_url_configured": bool(settings.tumor_segmentation_service_url),
            "model_id": settings.tumor_segmentation_model_id or "default",
            "intended_use": "research_demo_segmentation_not_diagnosis",
        }
        try:
            health = tool.check_health()
            model_info = tool.get_model_info()
            payload.update(
                {
                    "ok": bool(health.get("ok", True)),
                    "ready": bool(health.get("ok", True)),
                    "health": health,
                    "model_info": model_info,
                    "model_id": model_info.get("model_id") or payload["model_id"],
                }
            )
        except Exception as exc:  # pragma: no cover - exact service exceptions vary by transport.
            payload["error"] = str(exc)
        return payload

    def get_case_registry(self) -> dict[str, Any]:
        registry = _load_case_registry()
        summary_cache = self._load_registry_case_summary_cache()
        cases = []
        for case_index, case in enumerate(registry.get("cases", [])):
            if not isinstance(case, dict):
                continue
            timepoints = [tp for tp in case.get("timepoints", []) if isinstance(tp, dict)]
            demo_quality = dict(summary_cache.get(str(case.get("id") or ""), _pending_registry_demo_quality()))
            cases.append(
                {
                    "id": case.get("id"),
                    "title": case.get("title") or case.get("patient_id") or case.get("id"),
                    "dataset": case.get("dataset"),
                    "patient_id": case.get("patient_id"),
                    "description": case.get("description", ""),
                    "timepoint_count": len(timepoints),
                    "gt_available": any(tp.get("ground_truth_seg") for tp in timepoints),
                    "demo_quality": demo_quality,
                    "timepoints": [
                        {
                            "id": tp.get("id"),
                            "label": tp.get("label") or tp.get("id"),
                            "dateLabel": tp.get("dateLabel") or tp.get("date_label") or tp.get("id"),
                            "relativeDay": tp.get("relative_day"),
                            "relativeDayOrigin": tp.get("relative_day_origin"),
                            "role": tp.get("role") or "follow_up",
                            "modalities": sorted((tp.get("modalities") or {}).keys()),
                            "gt_available": bool(tp.get("ground_truth_seg")),
                        }
                        for tp in timepoints
                    ],
                    "_registry_order": case_index,
                    "_demo_sort_score": float(demo_quality.get("sort_score", 0.0)),
                }
            )
        cases.sort(key=lambda item: (-float(item.get("_demo_sort_score", 0.0)), int(item.get("_registry_order", 0))))
        for case in cases:
            case.pop("_registry_order", None)
            case.pop("_demo_sort_score", None)
            if isinstance(case.get("demo_quality"), dict):
                case["demo_quality"].pop("sort_score", None)
        return {
            "ok": True,
            "configured": bool(os.getenv("CLINAGENT_BRAIN_TUMOR_CASE_REGISTRY_JSON", "").strip()),
            "registry_id": registry.get("id", "brain-tumor-case-registry"),
            "title": registry.get("title", "Brain tumor case registry"),
            "source_note": registry.get("source_note", ""),
            "case_count": len(cases),
            "cases": cases,
            "intended_use": "research_demo_case_registry_not_diagnosis",
        }

    def _summarize_registry_case_for_demo(
        self,
        *,
        registry: dict[str, Any],
        case: dict[str, Any],
        timepoints: list[dict[str, Any]],
    ) -> dict[str, Any]:
        settings = load_settings()
        model_id = str(settings.tumor_segmentation_model_id or registry.get("model_id") or "dataset802-unified-4class")
        sessions = [
            session
            for timepoint in timepoints
            if (session := self._load_registry_cached_session(registry=registry, case=case, timepoint=timepoint, model_id=model_id))
        ]
        if not sessions:
            return {
                "cache_count": 0,
                "recommended": False,
                "note": "Preview pending",
                "sort_score": 0.0,
            }

        max_et_ml = max((_session_region_ml(session, "enhancing_tumor") for session in sessions), default=0.0)
        max_flair_ml = max((_session_region_ml(session, "flair_abnormality") for session in sessions), default=0.0)
        max_wt_ml = max((_session_region_ml(session, "whole_tumor") for session in sessions), default=0.0)
        if max_wt_ml <= 0:
            max_wt_ml = max_et_ml + max_flair_ml
        max_cavity_ml = max((_session_region_ml(session, "cavity_or_post_surgical_change") for session in sessions), default=0.0)
        max_cavity_to_wt = max((max_cavity_ml / max_wt_ml) if max_wt_ml > 0 else 0.0, 0.0)

        score = 40.0
        score += 30.0 if 0.5 <= max_et_ml <= 6.0 else 20.0 if max_et_ml > 6.0 else -20.0
        score += 20.0 if 12.0 <= max_wt_ml <= 60.0 else 10.0 if max_wt_ml > 60.0 else 5.0 if max_wt_ml > 0 else 0.0
        score += min(max_flair_ml, 80.0) * 0.05
        score -= min(max_cavity_to_wt, 2.0) * 80.0
        score = max(score, 5.0)

        recommended = max_et_ml >= 0.5 and max_cavity_to_wt <= 0.35 and max_wt_ml >= 10.0
        if recommended:
            note = "Cleaner cached preview"
        elif max_cavity_to_wt > 0.5:
            note = "Cached preview; cavity/exclusion label dominates"
        elif max_et_ml < 0.5:
            note = "Cached preview; low enhancing-tumor signal"
        else:
            note = "Cached preview"
        return {
            "cache_count": len(sessions),
            "recommended": recommended,
            "note": note,
            "max_enhancing_ml": round(max_et_ml, 3),
            "max_flair_ml": round(max_flair_ml, 3),
            "max_cavity_ml": round(max_cavity_ml, 3),
            "max_cavity_to_wt": round(max_cavity_to_wt, 3),
            "sort_score": round(score, 3),
        }

    def run_case_registry_case(self, *, case_id: str, timepoint_ids: list[str] | None = None) -> dict[str, Any]:
        registry = _load_case_registry()
        case = next((item for item in registry.get("cases", []) if isinstance(item, dict) and item.get("id") == case_id), None)
        if not case:
            raise KeyError(case_id)

        selected_ids = set(timepoint_ids or [])
        timepoints = [tp for tp in case.get("timepoints", []) if isinstance(tp, dict)]
        if selected_ids:
            timepoints = [tp for tp in timepoints if str(tp.get("id")) in selected_ids]
        if not timepoints:
            raise ValueError("No runnable timepoints were selected.")

        settings = load_settings()
        model_id = str(settings.tumor_segmentation_model_id or registry.get("model_id") or "dataset802-unified-4class")
        cached_by_timepoint_id: dict[str, dict[str, Any]] = {}
        uncached_timepoints: list[dict[str, Any]] = []
        for timepoint in timepoints:
            cached_session = self._load_registry_cached_session(
                registry=registry,
                case=case,
                timepoint=timepoint,
                model_id=model_id,
            )
            if cached_session:
                cached_by_timepoint_id[str(timepoint.get("id") or "")] = cached_session
            else:
                uncached_timepoints.append(timepoint)

        max_sync_uncached = max(1, int(os.getenv("CLINAGENT_BRAIN_TUMOR_REGISTRY_MAX_SYNC_UNCACHED_TIMEPOINTS", "1") or "1"))
        partial_background = len(timepoints) > 2 and len(uncached_timepoints) > max_sync_uncached
        sync_uncached_remaining = max_sync_uncached if partial_background else len(uncached_timepoints)
        background_timepoints: list[dict[str, Any]] = []

        points: list[dict[str, Any]] = []
        sessions: list[dict[str, Any]] = []
        for index, timepoint in enumerate(timepoints):
            timepoint_id = str(timepoint.get("id") or "")
            session = cached_by_timepoint_id.get(timepoint_id)
            if not session:
                if sync_uncached_remaining <= 0:
                    background_timepoints.append(timepoint)
                    continue
                session = self._run_remote_registry_timepoint(registry=registry, case=case, timepoint=timepoint)
                sync_uncached_remaining -= 1
            sessions.append(session)
            points.append(self._registry_point_from_session(case=case, case_id=case_id, timepoint=timepoint, timepoint_index=index, session=session, provenance="remote_registry_run"))
        if background_timepoints:
            self._start_registry_background_cache(
                registry=registry,
                case=case,
                timepoints=background_timepoints,
            )
        if sessions:
            self._write_registry_case_summary_cache(case_id=case_id, sessions=sessions)
        return {
            "ok": True,
            "case_id": case_id,
            "same_patient_longitudinal": len(timepoints) > 1,
            "partial": bool(background_timepoints),
            "completed_timepoint_count": len(points),
            "pending_timepoint_count": len(background_timepoints),
            "background_caching": bool(background_timepoints),
            "points": points,
            "sessions": sessions,
            "intended_use": "research_demo_remote_registry_run_not_diagnosis",
        }

    def load_case_registry_case(
        self,
        *,
        case_id: str,
        timepoint_ids: list[str] | None = None,
        prefer_cached: bool = False,
    ) -> dict[str, Any]:
        registry = _load_case_registry()
        case = next((item for item in registry.get("cases", []) if isinstance(item, dict) and item.get("id") == case_id), None)
        if not case:
            raise KeyError(case_id)

        selected_ids = set(timepoint_ids or [])
        timepoints = [tp for tp in case.get("timepoints", []) if isinstance(tp, dict)]
        if selected_ids:
            timepoints = [tp for tp in timepoints if str(tp.get("id")) in selected_ids]
        if not timepoints:
            raise ValueError("No loadable timepoints were selected.")

        points: list[dict[str, Any]] = []
        sessions: list[dict[str, Any]] = []
        settings = load_settings()
        model_id = str(settings.tumor_segmentation_model_id or registry.get("model_id") or "dataset802-unified-4class")
        for index, timepoint in enumerate(timepoints):
            session = None
            if prefer_cached:
                session = self._load_registry_cached_session(
                    registry=registry,
                    case=case,
                    timepoint=timepoint,
                    model_id=model_id,
                )
            if session is None:
                session = self._load_remote_registry_image_timepoint(registry=registry, case=case, timepoint=timepoint)
            sessions.append(session)
            points.append(self._registry_point_from_session(case=case, case_id=case_id, timepoint=timepoint, timepoint_index=index, session=session, provenance="remote_registry_image_load"))
        measured_sessions = [session for session in sessions if session.get("volumes")]
        if measured_sessions:
            self._write_registry_case_summary_cache(case_id=case_id, sessions=measured_sessions)
        return {
            "ok": True,
            "case_id": case_id,
            "same_patient_longitudinal": len(timepoints) > 1,
            "points": points,
            "sessions": sessions,
            "intended_use": "research_demo_remote_registry_image_load_not_diagnosis",
        }

    def _hydrate_registry_alignment_cache(self, points: list[dict[str, Any]]) -> None:
        if len(points) < 2:
            return
        baseline_session_id = str(points[0].get("sessionId") or points[0].get("id") or "")
        if not baseline_session_id:
            return
        for point in points[1:]:
            followup_session_id = str(point.get("sessionId") or point.get("id") or "")
            if not followup_session_id or point.get("registration"):
                continue
            cached = self._load_cached_longitudinal_registration(
                baseline_session_id=baseline_session_id,
                followup_session_id=followup_session_id,
            )
            if cached and isinstance(cached.get("registration"), dict):
                point["registration"] = cached["registration"]

    def _registry_point_from_session(
        self,
        *,
        case: dict[str, Any],
        case_id: str,
        timepoint: dict[str, Any],
        timepoint_index: int,
        session: dict[str, Any],
        provenance: str,
    ) -> dict[str, Any]:
        return {
            "id": session["session_id"],
            "sessionId": session["session_id"],
            "caseId": case_id,
            "timepointId": str(timepoint.get("id") or ""),
            "label": f"{case.get('title') or case.get('patient_id') or case_id} · {timepoint.get('label') or timepoint.get('id')}",
            "role": timepoint.get("role") or ("pre_treatment_baseline" if timepoint_index == 0 else "follow_up"),
            "dateLabel": timepoint.get("dateLabel") or timepoint.get("date_label") or timepoint.get("id") or f"Time {timepoint_index + 1}",
            "scanDate": timepoint.get("scan_date") or timepoint.get("date") or timepoint.get("study_date") or timepoint.get("dateLabel") or timepoint.get("date_label") or None,
            "relativeDay": timepoint.get("relative_day"),
            "relativeDayOrigin": timepoint.get("relative_day_origin"),
            "reviewState": "pending",
            "volumes": session.get("volumes", []),
            "overlayUrl": session.get("viewer_assets", {}).get("overlay_preview_url"),
            "modalityVolumeUrls": session.get("viewer_assets", {}).get("modality_volume_urls", {}),
            "segmentationUrl": session.get("viewer_assets", {}).get("segmentation_url"),
            "groundTruthSegmentationUrl": session.get("viewer_assets", {}).get("ground_truth_segmentation_url"),
            "reportSlices": session.get("viewer_assets", {}).get("report_slices"),
            "viewerType": "nifti_volume",
            "previewProvenance": provenance,
        }

    def create_registry_segment_job(self, *, case_id: str, timepoint_ids: list[str] | None = None) -> dict[str, Any]:
        registry = _load_case_registry()
        case = next((item for item in registry.get("cases", []) if isinstance(item, dict) and item.get("id") == case_id), None)
        if not case:
            raise KeyError(case_id)

        selected_ids = set(timepoint_ids or [])
        timepoints = [tp for tp in case.get("timepoints", []) if isinstance(tp, dict)]
        if selected_ids:
            timepoints = [tp for tp in timepoints if str(tp.get("id")) in selected_ids]
        if not timepoints:
            raise ValueError("No runnable timepoints were selected.")

        settings = load_settings()
        model_id = str(settings.tumor_segmentation_model_id or registry.get("model_id") or "dataset802-unified-4class")
        job_id = f"gbmseg_{uuid.uuid4().hex[:12]}"
        visits: list[dict[str, Any]] = []
        pending: list[tuple[int, dict[str, Any]]] = []

        for index, timepoint in enumerate(timepoints):
            visit = {
                "timepoint_id": str(timepoint.get("id") or ""),
                "label": timepoint.get("label") or timepoint.get("id") or f"Time {index + 1}",
                "dateLabel": timepoint.get("dateLabel") or timepoint.get("date_label") or timepoint.get("id") or f"Time {index + 1}",
                "role": timepoint.get("role") or ("pre_treatment_baseline" if index == 0 else "follow_up"),
                "status": "queued",
                "point": None,
                "session": None,
                "error": None,
            }
            cached_session = self._load_registry_cached_session(
                registry=registry,
                case=case,
                timepoint=timepoint,
                model_id=model_id,
            )
            if cached_session:
                visit["status"] = "complete"
                visit["session"] = cached_session
                visit["point"] = self._registry_point_from_session(
                    case=case,
                    case_id=case_id,
                    timepoint=timepoint,
                    timepoint_index=index,
                    session=cached_session,
                    provenance="remote_registry_run",
                )
            else:
                pending.append((index, timepoint))
            visits.append(visit)

        job = {
            "ok": True,
            "job_id": job_id,
            "case_id": case_id,
            "status": "completed" if not pending else "running",
            "total_count": len(visits),
            "completed_count": sum(1 for visit in visits if visit["status"] == "complete"),
            "failed_count": 0,
            "visits": visits,
            "same_patient_longitudinal": len(visits) > 1,
            "intended_use": "research_demo_remote_registry_segmentation_job_not_diagnosis",
        }
        with self._registry_segment_jobs_lock:
            self._registry_segment_jobs[job_id] = job

        if pending:
            registry_snapshot = json.loads(json.dumps(registry))
            case_snapshot = json.loads(json.dumps(case))
            pending_snapshot = [(index, json.loads(json.dumps(timepoint))) for index, timepoint in pending]
            thread = threading.Thread(
                target=self._run_registry_segment_job,
                args=(job_id, registry_snapshot, case_snapshot, pending_snapshot),
                name=f"clinagent-gbm-segment-job-{job_id}",
                daemon=True,
            )
            thread.start()
        elif any(visit.get("session") for visit in visits):
            self._write_registry_case_summary_cache(
                case_id=case_id,
                sessions=[visit["session"] for visit in visits if isinstance(visit.get("session"), dict)],
            )
        return self.get_registry_segment_job(job_id)

    def run_registry_segment_job(
        self,
        *,
        job_id: str,
        case_id: str,
        timepoint_ids: list[str] | None = None,
        force_rerun: bool = False,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        registry = _load_case_registry()
        case = next((item for item in registry.get("cases", []) if isinstance(item, dict) and item.get("id") == case_id), None)
        if not case:
            raise KeyError(case_id)

        selected_ids = set(timepoint_ids or [])
        timepoints = [tp for tp in case.get("timepoints", []) if isinstance(tp, dict)]
        if selected_ids:
            timepoints = [tp for tp in timepoints if str(tp.get("id")) in selected_ids]
        if not timepoints:
            raise ValueError("No runnable timepoints were selected.")

        settings = load_settings()
        model_id = str(settings.tumor_segmentation_model_id or registry.get("model_id") or "dataset802-unified-4class")
        visits = [
            {
                "timepoint_id": str(timepoint.get("id") or ""),
                "label": timepoint.get("label") or timepoint.get("id") or f"Time {index + 1}",
                "dateLabel": timepoint.get("dateLabel") or timepoint.get("date_label") or timepoint.get("id") or f"Time {index + 1}",
                "role": timepoint.get("role") or ("pre_treatment_baseline" if index == 0 else "follow_up"),
                "status": "queued",
                "point": None,
                "session": None,
                "error": None,
            }
            for index, timepoint in enumerate(timepoints)
        ]
        result: dict[str, Any] = {
            "ok": True,
            "job_id": job_id,
            "case_id": case_id,
            "status": "running",
            "stage": "preparing",
            "total_count": len(visits),
            "completed_count": 0,
            "failed_count": 0,
            "visits": visits,
            "same_patient_longitudinal": len(visits) > 1,
            "force_rerun": force_rerun,
            "intended_use": "research_demo_remote_registry_segmentation_job_not_diagnosis",
        }

        def publish(stage: str) -> None:
            result["stage"] = stage
            self._refresh_registry_segment_job_counts(result)
            if on_progress:
                on_progress(stage, json.loads(json.dumps(result)))

        publish("preparing")
        for index, timepoint in enumerate(timepoints):
            visit = visits[index]
            visit["status"] = "running"
            publish("segmenting")
            try:
                session = None
                if not force_rerun:
                    session = self._load_registry_cached_session(
                        registry=registry,
                        case=case,
                        timepoint=timepoint,
                        model_id=model_id,
                    )
                if session is None:
                    session = self._run_remote_registry_timepoint(
                        registry=registry,
                        case=case,
                        timepoint=timepoint,
                        force_rerun=force_rerun,
                        run_id=job_id,
                    )
                visit["session"] = session
                visit["point"] = self._registry_point_from_session(
                    case=case,
                    case_id=case_id,
                    timepoint=timepoint,
                    timepoint_index=index,
                    session=session,
                    provenance="remote_registry_rerun" if force_rerun else "remote_registry_run",
                )
                visit["status"] = "complete"
                visit["error"] = None
                publish("materializing")
            except Exception as exc:
                sys.stderr.write(
                    f"Brain tumor segmentation failed for {case_id}/{visit.get('timepoint_id')}: "
                    f"{type(exc).__name__}: {exc}\n"
                )
                visit["status"] = "failed"
                visit["error"] = "Segmentation failed for this visit. Review the worker logs or retry."
                publish("segmenting")

        complete_sessions = [
            visit["session"]
            for visit in visits
            if visit.get("status") == "complete" and isinstance(visit.get("session"), dict)
        ]
        if complete_sessions and not force_rerun:
            self._write_registry_case_summary_cache(case_id=case_id, sessions=complete_sessions)
        publish("finalizing")
        result["status"] = "completed_with_errors" if result["failed_count"] else "completed"
        result["stage"] = "complete" if not result["failed_count"] else "completed_with_errors"
        if on_progress:
            on_progress(str(result["stage"]), json.loads(json.dumps(result)))
        return result

    def describe_registry_segment_job(
        self,
        *,
        job_id: str,
        case_id: str,
        timepoint_ids: list[str] | None = None,
        force_rerun: bool = False,
    ) -> dict[str, Any]:
        registry = _load_case_registry()
        case = next((item for item in registry.get("cases", []) if isinstance(item, dict) and item.get("id") == case_id), None)
        if not case:
            raise KeyError(case_id)
        selected_ids = set(timepoint_ids or [])
        timepoints = [tp for tp in case.get("timepoints", []) if isinstance(tp, dict)]
        if selected_ids:
            timepoints = [tp for tp in timepoints if str(tp.get("id")) in selected_ids]
        if not timepoints:
            raise ValueError("No runnable timepoints were selected.")
        visits = [
            {
                "timepoint_id": str(timepoint.get("id") or ""),
                "label": timepoint.get("label") or timepoint.get("id") or f"Time {index + 1}",
                "dateLabel": timepoint.get("dateLabel") or timepoint.get("date_label") or timepoint.get("id") or f"Time {index + 1}",
                "role": timepoint.get("role") or ("pre_treatment_baseline" if index == 0 else "follow_up"),
                "status": "queued",
                "point": None,
                "session": None,
                "error": None,
            }
            for index, timepoint in enumerate(timepoints)
        ]
        return {
            "ok": True,
            "job_id": job_id,
            "case_id": case_id,
            "status": "queued",
            "stage": "queued",
            "total_count": len(visits),
            "completed_count": 0,
            "failed_count": 0,
            "visits": visits,
            "same_patient_longitudinal": len(visits) > 1,
            "force_rerun": force_rerun,
            "intended_use": "research_demo_remote_registry_segmentation_job_not_diagnosis",
        }

    def get_registry_segment_job(self, job_id: str) -> dict[str, Any]:
        with self._registry_segment_jobs_lock:
            job = self._registry_segment_jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            return json.loads(json.dumps(job))

    def _run_registry_segment_job(
        self,
        job_id: str,
        registry: dict[str, Any],
        case: dict[str, Any],
        pending: list[tuple[int, dict[str, Any]]],
    ) -> None:
        for index, timepoint in pending:
            timepoint_id = str(timepoint.get("id") or "")
            with self._registry_segment_jobs_lock:
                job = self._registry_segment_jobs.get(job_id)
                if not job:
                    return
                for visit in job["visits"]:
                    if visit.get("timepoint_id") == timepoint_id:
                        visit["status"] = "running"
                        break
                self._refresh_registry_segment_job_counts(job)

            try:
                session = self._run_remote_registry_timepoint(registry=registry, case=case, timepoint=timepoint)
                point = self._registry_point_from_session(
                    case=case,
                    case_id=str(case.get("id") or ""),
                    timepoint=timepoint,
                    timepoint_index=index,
                    session=session,
                    provenance="remote_registry_run",
                )
                with self._registry_segment_jobs_lock:
                    job = self._registry_segment_jobs.get(job_id)
                    if not job:
                        return
                    for visit in job["visits"]:
                        if visit.get("timepoint_id") == timepoint_id:
                            visit["status"] = "complete"
                            visit["session"] = session
                            visit["point"] = point
                            visit["error"] = None
                            break
                    self._refresh_registry_segment_job_counts(job)
                    complete_sessions = [
                        visit["session"]
                        for visit in job["visits"]
                        if visit.get("status") == "complete" and isinstance(visit.get("session"), dict)
                    ]
                if complete_sessions:
                    self._write_registry_case_summary_cache(case_id=str(case.get("id") or ""), sessions=complete_sessions)
            except Exception as exc:
                with self._registry_segment_jobs_lock:
                    job = self._registry_segment_jobs.get(job_id)
                    if not job:
                        return
                    for visit in job["visits"]:
                        if visit.get("timepoint_id") == timepoint_id:
                            visit["status"] = "failed"
                            visit["error"] = "Segmentation failed for this visit. Review the service logs or retry."
                            break
                    self._refresh_registry_segment_job_counts(job)
                sys.stderr.write(
                    f"Brain tumor segmentation failed for {case.get('id')}/{timepoint_id}: "
                    f"{type(exc).__name__}: {exc}\n"
                )

    def _refresh_registry_segment_job_counts(self, job: dict[str, Any]) -> None:
        visits = job.get("visits") if isinstance(job.get("visits"), list) else []
        completed = sum(1 for visit in visits if isinstance(visit, dict) and visit.get("status") == "complete")
        failed = sum(1 for visit in visits if isinstance(visit, dict) and visit.get("status") == "failed")
        running = any(isinstance(visit, dict) and visit.get("status") == "running" for visit in visits)
        queued = any(isinstance(visit, dict) and visit.get("status") == "queued" for visit in visits)
        job["completed_count"] = completed
        job["failed_count"] = failed
        if running or queued:
            job["status"] = "running"
        elif failed:
            job["status"] = "completed_with_errors"
        else:
            job["status"] = "completed"

    def _load_remote_registry_image_timepoint(self, *, registry: dict[str, Any], case: dict[str, Any], timepoint: dict[str, Any]) -> dict[str, Any]:
        modalities = {key: str(value) for key, value in (timepoint.get("modalities") or {}).items() if key in MODALITY_KEYS and value}
        _validate_required_modalities(modalities)

        session_id = _registry_image_session_id(
            registry_id=str(registry.get("id") or "registry"),
            case_id=str(case.get("id") or ""),
            timepoint_id=str(timepoint.get("id") or ""),
        )
        session_root = self.asset_root / session_id
        session_path = session_root / "session.json"
        if session_path.exists():
            try:
                session = json.loads(session_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                session = {}
            session = _normalize_session_artifact_paths(session, asset_root=self.asset_root)
            if session and _session_artifacts_complete(session, require_segmentation=False):
                refreshed = _refresh_session_artifact_urls(session)
                self._sessions[str(refreshed["session_id"])] = refreshed
                return refreshed

        remote_host = (
            str(timepoint.get("remote_host") or case.get("remote_host") or registry.get("remote_host") or "")
            or load_settings().segmentation_tool_remote_host
            or load_settings().brain_tumor_dicom_remote_host
        ).strip() or "local"
        input_root = session_root / "input" / "nifti"
        input_root.mkdir(parents=True, exist_ok=True)

        copied_inputs: dict[str, str] = {}
        for modality, remote_path in modalities.items():
            copied_inputs[modality] = _copy_remote_file(
                remote_host=remote_host,
                remote_path=remote_path,
                local_path=input_root / f"image_{modality}.nii.gz",
                required=True,
            )

        session = self._build_image_only_session(
            session_id=session_id,
            patient_label=str(case.get("title") or case.get("patient_id") or case.get("id") or session_id),
            source={
                "type": "remote_case_registry_image_load",
                "registry_id": registry.get("id"),
                "case_id": case.get("id"),
                "timepoint_id": timepoint.get("id"),
                "dataset": case.get("dataset"),
            },
            modality_paths=copied_inputs,
        )
        self._sessions[session_id] = session
        session_path.write_text(json.dumps(session, indent=2), encoding="utf-8")
        self._write_internal_session(session_id=session_id, session_root=session_root, modality_paths=copied_inputs)
        return session

    def _build_image_only_session(
        self,
        *,
        session_id: str,
        patient_label: str,
        source: dict[str, Any],
        modality_paths: dict[str, str],
    ) -> dict[str, Any]:
        artifacts = {f"image_{key}": path for key, path in modality_paths.items() if key in MODALITY_KEYS and path}
        artifact_urls = _session_artifact_urls(
            session_id=session_id,
            artifacts=artifacts,
            source=source,
        )
        return {
            "ok": True,
            "session_id": session_id,
            "status": "images_loaded",
            "patient_label": patient_label,
            "source": source,
            "modality_status": {
                key: {
                    "present": key in modality_paths,
                    "required": key in REQUIRED_MODALITIES,
                    "path_name": Path(modality_paths[key]).name if key in modality_paths else "",
                }
                for key in MODALITY_KEYS
            },
            "volumes": [],
            "label_volumes": [],
            "qc": {
                "warnings": [],
                "source": "remote_case_registry_image_load",
                "cache": "image_only",
            },
            "report_snippet": {
                "findings": "Raw MRI has been loaded. Run segmentation to generate tumor measurements.",
                "impression": "Segmentation has not been run for this loaded image session.",
                "copy_text": "Raw MRI loaded; segmentation pending.",
            },
            "service": {
                "model_id": None,
                "mode": "image_only_load",
                "remote_staging": None,
            },
            "viewer_assets": {
                "viewer_type": "nifti",
                "overlay_preview_url": None,
                "segmentation_url": None,
                "modality_volume_urls": {
                    key: artifact_urls.get(f"image_{key}")
                    for key in MODALITY_KEYS
                    if artifact_urls.get(f"image_{key}")
                },
                "ground_truth_segmentation_url": None,
            },
            "artifacts": artifacts,
            "artifact_urls": artifact_urls,
            "intended_use": "research_demo_image_load_not_diagnosis",
        }

    def _start_registry_background_cache(
        self,
        *,
        registry: dict[str, Any],
        case: dict[str, Any],
        timepoints: list[dict[str, Any]],
    ) -> None:
        key = (
            str(registry.get("id") or "registry"),
            str(case.get("id") or ""),
            ",".join(str(timepoint.get("id") or "") for timepoint in timepoints),
        )
        with self._registry_background_run_lock:
            if key in self._registry_background_runs:
                return
            self._registry_background_runs.add(key)

        registry_snapshot = json.loads(json.dumps(registry))
        case_snapshot = json.loads(json.dumps(case))
        timepoint_snapshots = json.loads(json.dumps(timepoints))

        def worker() -> None:
            try:
                sessions: list[dict[str, Any]] = []
                for timepoint in timepoint_snapshots:
                    sessions.append(
                        self._run_remote_registry_timepoint(
                            registry=registry_snapshot,
                            case=case_snapshot,
                            timepoint=timepoint,
                        )
                    )
                if sessions:
                    self._write_registry_case_summary_cache(
                        case_id=str(case_snapshot.get("id") or ""),
                        sessions=sessions,
                    )
            finally:
                with self._registry_background_run_lock:
                    self._registry_background_runs.discard(key)

        thread = threading.Thread(
            target=worker,
            name=f"clinagent-gbm-registry-cache-{case.get('id') or 'case'}",
            daemon=True,
        )
        thread.start()

    def _load_registry_case_summary_cache(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self._registry_case_summary_cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        cases = payload.get("cases") if isinstance(payload, dict) else {}
        if not isinstance(cases, dict):
            return {}
        return {str(key): value for key, value in cases.items() if isinstance(value, dict)}

    def _write_registry_case_summary_cache(self, *, case_id: str, sessions: list[dict[str, Any]]) -> None:
        case_id = str(case_id or "")
        if not case_id or not sessions:
            return
        payload: dict[str, Any] = {"cases": {}}
        try:
            existing = json.loads(self._registry_case_summary_cache_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                payload.update(existing)
        except (OSError, json.JSONDecodeError):
            pass
        cases = payload.get("cases") if isinstance(payload.get("cases"), dict) else {}
        cases[case_id] = _summarize_registry_sessions_for_demo(sessions)
        payload["cases"] = cases
        tmp_path = self._registry_case_summary_cache_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self._registry_case_summary_cache_path)

    def _run_remote_registry_timepoint(
        self,
        *,
        registry: dict[str, Any],
        case: dict[str, Any],
        timepoint: dict[str, Any],
        force_rerun: bool = False,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        modalities = {key: str(value) for key, value in (timepoint.get("modalities") or {}).items() if key in MODALITY_KEYS and value}
        _validate_required_modalities(modalities)

        settings = load_settings()
        model_id = settings.tumor_segmentation_model_id or registry.get("model_id") or "dataset802-unified-4class"
        if not force_rerun:
            cached_session = self._load_registry_cached_session(
                registry=registry,
                case=case,
                timepoint=timepoint,
                model_id=str(model_id),
            )
            if cached_session:
                return cached_session

        remote_host = (
            str(timepoint.get("remote_host") or case.get("remote_host") or registry.get("remote_host") or "")
            or settings.segmentation_tool_remote_host
            or settings.brain_tumor_dicom_remote_host
        ).strip() or "local"

        session_id = (
            _registry_rerun_session_id(
                registry_id=str(registry.get("id") or "registry"),
                case_id=str(case.get("id") or ""),
                timepoint_id=str(timepoint.get("id") or ""),
                model_id=str(model_id),
                run_id=run_id or uuid.uuid4().hex,
            )
            if force_rerun
            else _registry_cache_session_id(
                registry_id=str(registry.get("id") or "registry"),
                case_id=str(case.get("id") or ""),
                timepoint_id=str(timepoint.get("id") or ""),
                model_id=str(model_id),
            )
        )
        session_root = self.asset_root / session_id
        input_root = session_root / "input" / "nifti"
        output_dir = session_root / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        input_root.mkdir(parents=True, exist_ok=True)

        remote_output_root = os.getenv("CLINAGENT_BRAIN_TUMOR_REMOTE_OUTPUT_ROOT", "/tmp/clinagent-brain-tumor-runs").rstrip("/")
        remote_output_dir = f"{remote_output_root}/{session_id}"

        copied_inputs: dict[str, str] = {}
        for modality, remote_path in modalities.items():
            copied_inputs[modality] = _copy_remote_file(
                remote_host=remote_host,
                remote_path=remote_path,
                local_path=input_root / f"image_{modality}.nii.gz",
                required=True,
            )

        if _is_same_host_registry(remote_host):
            Path(remote_output_dir).expanduser().mkdir(parents=True, exist_ok=True)
        else:
            _run_checked(["ssh", remote_host, f"mkdir -p {shlex.quote(remote_output_dir)}"], "create remote registry output directory")

        tool = BrainTumorSegmentationTool()
        client = tool._client()
        health = client.check_health()
        model_info = client.get_model_info()
        prediction = client.predict(
            {
                "modalities": modalities,
                "output_dir": remote_output_dir,
                "device": "auto",
                "model_id": model_id,
                "mode": "fast",
                "overwrite": True,
            }
        )

        materialized = dict(prediction)
        optional_artifacts = {
            "tumor_regions_path": "tumor_regions.json",
            "volumes_csv_path": "volumes.csv",
            "overlay_preview_path": "overlay_preview.png",
            "qc_summary_path": "qc_summary.json",
        }
        for response_key, local_name in {
            "seg_path": "seg.nii.gz",
            "segmentation_path": "seg.nii.gz",
            **optional_artifacts,
        }.items():
            remote_path = prediction.get(response_key)
            if not remote_path:
                continue
            local_key = "seg_path" if response_key in {"seg_path", "segmentation_path"} else response_key
            materialized[local_key] = _copy_remote_file(
                remote_host=remote_host,
                remote_path=str(remote_path),
                local_path=output_dir / local_name,
                required=response_key in {"seg_path", "segmentation_path"},
            )
        for response_key, local_name in optional_artifacts.items():
            if materialized.get(response_key):
                continue
            materialized[response_key] = _copy_remote_file(
                remote_host=remote_host,
                remote_path=f"{remote_output_dir}/{local_name}",
                local_path=output_dir / local_name,
                required=False,
            )
        if timepoint.get("ground_truth_seg"):
            materialized["ground_truth_seg_path"] = _copy_remote_file(
                remote_host=remote_host,
                remote_path=str(timepoint["ground_truth_seg"]),
                local_path=output_dir / "ground_truth_seg.nii.gz",
                required=False,
            )

        materialized["qc"] = {
            "warnings": list(prediction.get("warnings") or []),
            "source": "remote_case_registry_rerun" if force_rerun else "remote_case_registry",
            "remote_host": remote_host,
            "dataset": case.get("dataset"),
            "case_id": case.get("id"),
            "timepoint_id": timepoint.get("id"),
            "cache_key": session_id,
        }
        materialized["model_info"] = model_info
        materialized["health"] = health
        materialized["mode"] = "remote_registry_service"
        session = self._build_session(
            session_id=session_id,
            patient_label=str(case.get("title") or case.get("patient_id") or case.get("id") or session_id),
            source={
                "type": "remote_case_registry_rerun" if force_rerun else "remote_case_registry",
                "registry_id": registry.get("id"),
                "case_id": case.get("id"),
                "timepoint_id": timepoint.get("id"),
                "dataset": case.get("dataset"),
                "rerun_job_id": run_id if force_rerun else None,
            },
            modality_paths=copied_inputs,
            tool_result=materialized,
        )
        self._sessions[session_id] = session
        (session_root / "session.json").write_text(json.dumps(session, indent=2), encoding="utf-8")
        self._write_internal_session(session_id=session_id, session_root=session_root, modality_paths=copied_inputs)
        self._registry_session_path_index = None
        return session

    def _load_registry_cached_session(
        self,
        *,
        registry: dict[str, Any],
        case: dict[str, Any],
        timepoint: dict[str, Any],
        model_id: str,
        use_deterministic_probe: bool = True,
    ) -> dict[str, Any] | None:
        session_id = _registry_cache_session_id(
            registry_id=str(registry.get("id") or "registry"),
            case_id=str(case.get("id") or ""),
            timepoint_id=str(timepoint.get("id") or ""),
            model_id=model_id,
        )
        deterministic = self.asset_root / session_id / "session.json"
        if use_deterministic_probe and deterministic.exists():
            try:
                session = json.loads(deterministic.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                session = {}
            session = _normalize_session_artifact_paths(session, asset_root=self.asset_root)
            if (
                session
                and _registry_session_matches(session=session, case=case, timepoint=timepoint, model_id=model_id)
                and _session_artifacts_complete(session)
            ):
                refreshed = _refresh_session_artifact_urls(session)
                service = refreshed.get("service") if isinstance(refreshed.get("service"), dict) else {}
                service["cache"] = "local_hit"
                refreshed["service"] = service
                qc = refreshed.get("qc") if isinstance(refreshed.get("qc"), dict) else {}
                qc.setdefault("warnings", [])
                qc["cache"] = "local_hit"
                refreshed["qc"] = qc
                self._sessions[str(refreshed["session_id"])] = refreshed
                return refreshed

        matching_paths = self._matching_registry_session_paths(case=case, timepoint=timepoint, model_id=model_id)
        for session_path in matching_paths:
            if not session_path.exists():
                continue
            try:
                session = json.loads(session_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            session = _normalize_session_artifact_paths(session, asset_root=self.asset_root)
            if not _registry_session_matches(session=session, case=case, timepoint=timepoint, model_id=model_id):
                continue
            if not _session_artifacts_complete(session):
                continue
            refreshed = _refresh_session_artifact_urls(session)
            service = refreshed.get("service") if isinstance(refreshed.get("service"), dict) else {}
            service["cache"] = "local_hit"
            refreshed["service"] = service
            qc = refreshed.get("qc") if isinstance(refreshed.get("qc"), dict) else {}
            qc.setdefault("warnings", [])
            qc["cache"] = "local_hit"
            refreshed["qc"] = qc
            self._sessions[str(refreshed["session_id"])] = refreshed
            return refreshed
        return None

    def _matching_registry_session_paths(self, *, case: dict[str, Any], timepoint: dict[str, Any], model_id: str) -> list[Path]:
        if self._registry_session_path_index is None:
            index: dict[tuple[str, str, str], list[Path]] = {}
            candidates = sorted(
                self.asset_root.glob("brain-tumor-*/session.json"),
                key=lambda path: path.stat().st_mtime if path.exists() else 0,
                reverse=True,
            )
            for session_path in candidates:
                try:
                    session = json.loads(session_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                source = session.get("source") if isinstance(session.get("source"), dict) else {}
                service = session.get("service") if isinstance(session.get("service"), dict) else {}
                if source.get("type") != "remote_case_registry":
                    continue
                key = (
                    str(source.get("case_id") or ""),
                    str(source.get("timepoint_id") or ""),
                    str(service.get("model_id") or ""),
                )
                index.setdefault(key, []).append(session_path)
            self._registry_session_path_index = index

        matches: list[Path] = []
        key_with_model = (str(case.get("id") or ""), str(timepoint.get("id") or ""), model_id)
        key_without_model = (str(case.get("id") or ""), str(timepoint.get("id") or ""), "")
        for session_path in [
            *self._registry_session_path_index.get(key_with_model, []),
            *self._registry_session_path_index.get(key_without_model, []),
        ]:
            try:
                session = json.loads(session_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if _registry_session_matches(session=session, case=case, timepoint=timepoint, model_id=model_id):
                matches.append(session_path)
        return matches

    def mounted_dicom_status(self) -> dict[str, Any]:
        settings = load_settings()
        roots = _configured_dicom_roots(settings.brain_tumor_dicom_roots)
        return {
            "ok": True,
            "configured": bool(roots),
            "root_count": len(roots),
            "remote": bool(settings.brain_tumor_dicom_remote_host),
            "scan_limit": int(settings.brain_tumor_dicom_scan_limit),
        }

    async def search_dicom_studies(
        self,
        *,
        patient_id: str | None = None,
        accession_number: str | None = None,
    ) -> dict[str, Any]:
        settings = load_settings()
        if ConnectorMode(settings.imaging_connector_mode) == ConnectorMode.mock:
            return {
                "ok": True,
                "configured": False,
                "studies": [],
                "message": "PACS/DICOMweb is not configured for brain tumor segmentation. Use Mounted DICOM or configure a real DICOMweb endpoint.",
            }
        connector = _dicom_connector()
        studies = await connector.search_studies(
            patient_id=patient_id or None,
            accession_number=accession_number or None,
            modality="MR",
        )
        return {
            "ok": True,
            "studies": [
                {
                    "study_instance_uid": study.study_instance_uid,
                    "patient_id": study.patient_id,
                    "accession_number": accession_number or "",
                    "modality": study.modality,
                    "description": study.description,
                    "study_date": study.study_date,
                    "series_count": study.series_count,
                    "metadata": study.metadata,
                }
                for study in studies
            ],
        }

    async def search_dicom_series(self, *, study_instance_uid: str) -> dict[str, Any]:
        connector = _dicom_connector()
        series = await connector.search_series(study_instance_uid=study_instance_uid, modality="MR")
        rows: list[dict[str, Any]] = []
        for item in series:
            metadata: dict[str, Any] = {}
            try:
                metadata = await connector.get_series_metadata(
                    study_instance_uid=study_instance_uid,
                    series_instance_uid=item.series_instance_uid,
                )
            except Exception:
                metadata = {}
            candidate = classify_series_for_tumor_modality(
                {
                    "description": item.description,
                    "modality": item.modality,
                    "metadata": metadata,
                }
            )
            rows.append(
                {
                    "study_instance_uid": item.study_instance_uid,
                    "series_instance_uid": item.series_instance_uid,
                    "modality": item.modality,
                    "description": item.description,
                    "instance_count": item.instance_count,
                    "metadata": item.metadata,
                    "candidate_modality": candidate.modality if candidate else None,
                    "candidate_score": candidate.score if candidate else 0,
                    "candidate_reason": candidate.reason if candidate else "",
                }
            )
        return {"ok": True, "series": rows, "suggested_mapping": suggest_modality_mapping(rows)}

    def search_mounted_dicom_studies(
        self,
        *,
        patient_id: str | None = None,
        accession_number: str | None = None,
    ) -> dict[str, Any]:
        settings = load_settings()
        roots = _configured_dicom_roots(settings.brain_tumor_dicom_roots)
        if not roots:
            return {"ok": True, "configured": False, "studies": []}
        if settings.brain_tumor_dicom_remote_host:
            return _run_remote_mount_action(
                host=settings.brain_tumor_dicom_remote_host,
                request={
                    "action": "studies",
                    "roots": roots,
                    "patient_id": patient_id or "",
                    "accession_number": accession_number or "",
                    "scan_limit": int(settings.brain_tumor_dicom_scan_limit),
                },
            )
        return _scan_local_mounted_studies(
            roots=roots,
            patient_id=patient_id or "",
            accession_number=accession_number or "",
            scan_limit=int(settings.brain_tumor_dicom_scan_limit),
        )

    def search_mounted_dicom_series(self, *, study_ref: str) -> dict[str, Any]:
        settings = load_settings()
        roots = _configured_dicom_roots(settings.brain_tumor_dicom_roots)
        if settings.brain_tumor_dicom_remote_host:
            return _run_remote_mount_action(
                host=settings.brain_tumor_dicom_remote_host,
                request={"action": "series", "roots": roots, "study_ref": study_ref},
            )
        return _list_local_mounted_series(roots=roots, study_ref=study_ref)

    async def analyze_dicomweb(
        self,
        *,
        study_instance_uid: str,
        modality_mapping: dict[str, str],
        patient_label: str = "",
        model_id: str | None = None,
    ) -> dict[str, Any]:
        settings = load_settings()
        if ConnectorMode(settings.imaging_connector_mode) == ConnectorMode.mock:
            raise RuntimeError(
                "PACS/DICOMweb is not configured for brain tumor segmentation. "
                "Use Mounted DICOM for the public UPENN demo data or configure a real DICOMweb endpoint."
            )
        session_id = f"brain-tumor-{uuid.uuid4().hex[:10]}"
        session_root = self.asset_root / session_id
        dicom_root = session_root / "input" / "dicom"
        nifti_root = session_root / "input" / "nifti"
        output_dir = session_root / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)

        converter = shutil.which("dcm2niix")
        if not converter:
            raise RuntimeError("DICOM conversion requires dcm2niix on the gateway host.")

        connector = _dicom_connector()
        modality_paths: dict[str, str] = {}
        for modality, series_uid in modality_mapping.items():
            if modality not in MODALITY_KEYS or not series_uid:
                continue
            series_dir = dicom_root / modality
            converted_dir = nifti_root / modality
            series_dir.mkdir(parents=True, exist_ok=True)
            converted_dir.mkdir(parents=True, exist_ok=True)
            await _download_dicom_series(
                connector=connector,
                study_instance_uid=study_instance_uid,
                series_instance_uid=series_uid,
                output_dir=series_dir,
            )
            modality_paths[modality] = _convert_dicom_series(
                dcm2niix_bin=converter,
                dicom_dir=series_dir,
                output_dir=converted_dir,
                output_stem=modality,
            )

        return self.analyze_nifti_paths(
            modality_paths=modality_paths,
            output_dir=output_dir,
            patient_label=patient_label,
            source={"type": "dicomweb", "study_instance_uid": study_instance_uid},
            model_id=model_id,
        )

    def analyze_mounted_dicom(
        self,
        *,
        study_ref: str,
        modality_mapping: dict[str, str],
        patient_label: str = "",
        model_id: str | None = None,
    ) -> dict[str, Any]:
        settings = load_settings()
        roots = _configured_dicom_roots(settings.brain_tumor_dicom_roots)
        if not roots:
            raise ValueError("Mounted DICOM roots are not configured.")

        session_id = f"brain-tumor-{uuid.uuid4().hex[:10]}"
        session_root = self.asset_root / session_id
        nifti_root = session_root / "input" / "nifti"
        output_dir = session_root / "outputs"
        nifti_root.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        modality_paths: dict[str, str] = {}
        if settings.brain_tumor_dicom_remote_host:
            for modality, series_ref in modality_mapping.items():
                if modality not in MODALITY_KEYS or not series_ref:
                    continue
                modality_paths[modality] = _convert_remote_mounted_series(
                    host=settings.brain_tumor_dicom_remote_host,
                    roots=roots,
                    series_ref=series_ref,
                    local_output_dir=nifti_root / modality,
                    remote_work_root=settings.brain_tumor_dicom_remote_work_root,
                    dcm2niix_bin=settings.brain_tumor_dicom_dcm2niix_bin,
                    output_stem=modality,
                )
        else:
            converter = shutil.which("dcm2niix")
            if not converter:
                raise RuntimeError("Mounted DICOM conversion requires dcm2niix on the gateway host.")
            for modality, series_ref in modality_mapping.items():
                if modality not in MODALITY_KEYS or not series_ref:
                    continue
                series_dir = _mounted_ref_path(roots=roots, ref=series_ref)
                modality_paths[modality] = _convert_dicom_series(
                    dcm2niix_bin=converter,
                    dicom_dir=series_dir,
                    output_dir=nifti_root / modality,
                    output_stem=modality,
                )

        return self.analyze_nifti_paths(
            modality_paths=modality_paths,
            output_dir=output_dir,
            patient_label=patient_label,
            source={"type": "dicom_mount", "study_ref": study_ref},
            model_id=model_id,
        )

    def analyze_nifti_paths(
        self,
        *,
        modality_paths: dict[str, str],
        output_dir: Path | None = None,
        patient_label: str = "",
        source: dict[str, Any] | None = None,
        model_id: str | None = None,
        precomputed_seg_path: str | None = None,
    ) -> dict[str, Any]:
        _validate_required_modalities(modality_paths)
        session_id = f"brain-tumor-{uuid.uuid4().hex[:10]}"
        session_root = self.asset_root / session_id
        output_dir = output_dir or session_root / "outputs"
        session_root.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        tool = BrainTumorSegmentationTool()
        result = tool.run(
            t1n_nifti_path=modality_paths.get("t1n"),
            t1c_nifti_path=modality_paths.get("t1c"),
            t2w_nifti_path=modality_paths.get("t2w"),
            t2f_nifti_path=modality_paths.get("t2f"),
            output_dir=str(output_dir),
            model_id=model_id,
            precomputed_seg_path=precomputed_seg_path,
        )
        session = self._build_session(
            session_id=session_id,
            patient_label=patient_label,
            source=source or {"type": "nifti_upload"},
            modality_paths=modality_paths,
            tool_result=result,
        )
        self._sessions[session_id] = session
        (session_root / "session.json").write_text(json.dumps(session, indent=2), encoding="utf-8")
        self._write_internal_session(
            session_id=session_id,
            session_root=session_root,
            modality_paths=modality_paths,
        )
        return session

    def get_session(self, session_id: str) -> dict[str, Any]:
        if session_id in self._sessions:
            session = _normalize_session_artifact_paths(self._sessions[session_id], asset_root=self.asset_root)
            self._sessions[session_id] = session
            return session
        session_path = self.asset_root / session_id / "session.json"
        if not session_path.exists():
            raise KeyError(session_id)
        session = json.loads(session_path.read_text(encoding="utf-8"))
        session = _normalize_session_artifact_paths(session, asset_root=self.asset_root)
        self._sessions[session_id] = session
        return session

    def get_artifact_path(self, session_id: str, artifact_name: str) -> Path:
        session = self.get_session(session_id)
        artifact = session.get("artifacts", {}).get(artifact_name)
        if not artifact:
            raise KeyError(artifact_name)
        path = Path(artifact).expanduser().resolve()
        if not path.exists() or self.asset_root not in path.parents:
            raise KeyError(artifact_name)
        return path

    def get_preload_examples(self) -> dict[str, Any]:
        preload_root = self.asset_root / "preload"
        examples: list[dict[str, Any]] = []
        for manifest_path in sorted(preload_root.glob("*/examples.json")):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for example in payload.get("examples", []):
                if isinstance(example, dict):
                    points = [
                        {
                            **point,
                            "curationReviewState": point.get("curationReviewState", point.get("reviewState", "pending")),
                            "reviewState": "pending",
                        }
                        for point in example.get("points", [])
                        if isinstance(point, dict)
                    ]
                    examples.append({**example, "points": points})
        return {
            "ok": True,
            "configured": bool(examples),
            "default_example_id": examples[0]["id"] if examples else None,
            "examples": examples,
            "intended_use": "research_demo_preload_not_diagnosis",
        }

    def get_preload_artifact_path(self, example_id: str, case_id: str, artifact_name: str) -> Path:
        allowed_artifacts = {
            "overlay_preview.png",
            "preview_t1c.png",
            "preview_t2f.png",
            "preview_t2w.png",
            "preview_t1n.png",
            "image_t1c.nii.gz",
            "image_t2f.nii.gz",
            "image_t2w.nii.gz",
            "image_t1n.nii.gz",
            "seg.nii.gz",
            "gt_seg.nii.gz",
            "overlay_gt.png",
            "tumor_regions.json",
            "tumor_regions_gt.json",
            "volumes.csv",
            "volumes_gt.csv",
        }
        if artifact_name not in allowed_artifacts:
            raise KeyError(artifact_name)
        path = (
            self.asset_root
            / "preload"
            / _safe_id_fragment(example_id)
            / _safe_id_fragment(case_id)
            / artifact_name
        ).resolve()
        preload_root = (self.asset_root / "preload").resolve()
        if not path.exists() or path.parent.parent.parent != preload_root:
            raise KeyError(artifact_name)
        return path

    def _longitudinal_registration_session_key(self, session_id: str) -> str:
        try:
            session = self.get_session(session_id)
        except KeyError:
            return f"session-{_safe_id_fragment(session_id)}"
        source = session.get("source") if isinstance(session.get("source"), dict) else {}
        dataset = str(source.get("dataset") or "")
        registry_id = str(source.get("registry_id") or "registry")
        case_id = str(source.get("case_id") or "")
        timepoint_id = str(source.get("timepoint_id") or "")
        if case_id and timepoint_id:
            if dataset:
                return (
                    f"dataset-{_safe_id_fragment(dataset)}"
                    f"-case-{_safe_id_fragment(case_id)}"
                    f"-timepoint-{_safe_id_fragment(timepoint_id)}"
                )
            return (
                f"registry-{_safe_id_fragment(registry_id)}"
                f"-case-{_safe_id_fragment(case_id)}"
                f"-timepoint-{_safe_id_fragment(timepoint_id)}"
            )
        return f"session-{_safe_id_fragment(session_id)}"

    def _longitudinal_registration_visit_identity(self, session_id: str) -> dict[str, Any]:
        try:
            session = self.get_session(session_id)
        except KeyError:
            return {}
        source = session.get("source") if isinstance(session.get("source"), dict) else {}
        identity: dict[str, Any] = {}
        for key in ("registry_id", "case_id", "timepoint_id", "dataset"):
            value = source.get(key)
            if value is not None and str(value):
                identity[key] = str(value)
        return identity

    def _longitudinal_registration_output_dir(self, *, baseline_session_id: str, followup_session_id: str) -> Path:
        baseline_key = self._longitudinal_registration_session_key(baseline_session_id)
        followup_key = self._longitudinal_registration_session_key(followup_session_id)
        return (
            self.asset_root
            / "longitudinal"
            / f"{baseline_key}__{followup_key}"
            / "registration"
        )

    def _load_cached_longitudinal_registration(self, *, baseline_session_id: str, followup_session_id: str, bias_correction: bool = False) -> dict[str, Any] | None:
        result_path = self._longitudinal_registration_output_dir(
            baseline_session_id=baseline_session_id,
            followup_session_id=followup_session_id,
        ) / ("rigid_n4_v1" if bias_correction else "rigid_v1") / "registration_result.json"
        if not result_path.exists():
            return None
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("registration"), dict):
            return None
        registration = dict(payload["registration"])
        if registration.get("backend") != "simpleitk_rigid_v1":
            return None
        sources = payload.pop("sources", None)
        if sources != self._registration_sources(baseline_session_id, followup_session_id):
            return None
        artifacts = payload.pop("artifacts", {})
        if not artifacts or not all(Path(path).is_file() for path in artifacts.values()):
            return None
        payload["baseline_session_id"] = baseline_session_id
        payload["followup_session_id"] = followup_session_id
        payload["cache"] = "local_hit"
        registration["cache"] = "local_hit"
        payload["registration"] = registration
        self._set_registration_asset_urls(payload, artifacts, bias_correction)
        return payload

    def _registration_sources(self, baseline_session_id, followup_session_id):
        baseline = self._get_internal_session(baseline_session_id)
        followup = self._get_internal_session(followup_session_id)
        artifacts = self.get_session(followup_session_id).get("artifacts", {})
        paths = {"reference": baseline["modality_paths"]["t1c"], **followup["modality_paths"],
                 **{name: artifacts[name] for name in ("seg", "ground_truth_seg") if artifacts.get(name)}}
        return {name: {"path": str(Path(path).resolve()), "size": Path(path).stat().st_size,
                       "modified_ns": Path(path).stat().st_mtime_ns} for name, path in paths.items()}

    def _set_registration_asset_urls(self, payload, artifacts, bias_correction):
        variant = "rigid_n4_v1" if bias_correction else "rigid_v1"
        prefix = (f"/api/demo/brain-tumor/longitudinal/artifacts/{payload['baseline_session_id']}/"
                  f"{payload['followup_session_id']}/{variant}/{payload['run_id']}")
        urls = {name: f"{prefix}/{name}.nii.gz" for name in artifacts}
        payload["registration"].update(
            baseline_session_id=payload["baseline_session_id"],
            modality_volume_urls={key: urls[f"image_{key}"] for key in MODALITY_KEYS if f"image_{key}" in urls},
            segmentation_url=urls.get("seg"), ground_truth_segmentation_url=urls.get("ground_truth_seg"),
        )

    def get_registration_artifact(self, baseline_session_id, followup_session_id, variant, run_id, artifact_name):
        if variant not in {"rigid_v1", "rigid_n4_v1"} or not re.fullmatch(r"[a-f0-9]{12}", run_id):
            raise KeyError(artifact_name)
        if artifact_name not in {"image_t1c", "image_t1n", "image_t2w", "image_t2f", "seg", "ground_truth_seg"}:
            raise KeyError(artifact_name)
        root = self._longitudinal_registration_output_dir(
            baseline_session_id=baseline_session_id, followup_session_id=followup_session_id,
        ) / variant / run_id
        if not (root / "complete.json").is_file():
            raise KeyError(artifact_name)
        path = (root / f"{artifact_name}.nii.gz").resolve()
        if not path.is_file() or root.resolve() not in path.parents:
            raise KeyError(artifact_name)
        return path

    def register_longitudinal_sessions(self, *, baseline_session_id: str, followup_session_id: str, overwrite: bool = False,
                                      bias_correction: bool = False, on_step=None) -> dict[str, Any]:
        baseline = self._get_internal_session(baseline_session_id)
        followup = self._get_internal_session(followup_session_id)
        baseline_t1c = baseline.get("modality_paths", {}).get("t1c")
        followup_t1c = followup.get("modality_paths", {}).get("t1c")
        if not baseline_t1c or not followup_t1c:
            raise ValueError("Longitudinal registration requires T1c inputs for both sessions.")
        for label, path in (("reference", baseline_t1c), ("follow-up", followup_t1c)):
            if not Path(path).is_file():
                raise ValueError(f"The {label} T1c image is unavailable. Reload the case before aligning visits.")

        if not overwrite:
            cached = self._load_cached_longitudinal_registration(
                baseline_session_id=baseline_session_id,
                followup_session_id=followup_session_id,
                bias_correction=bias_correction,
            )
            if cached:
                return cached

        output_dir = self._longitudinal_registration_output_dir(
            baseline_session_id=baseline_session_id,
            followup_session_id=followup_session_id,
        )
        variant_dir = output_dir / ("rigid_n4_v1" if bias_correction else "rigid_v1")
        run_id = uuid.uuid4().hex[:12]
        run_dir = variant_dir / run_id
        run_dir.mkdir(parents=True)
        session_artifacts = self.get_session(followup_session_id).get("artifacts", {})
        masks = {name: session_artifacts[name] for name in ("seg", "ground_truth_seg") if session_artifacts.get(name)}
        sources = self._registration_sources(baseline_session_id, followup_session_id)
        result = align_visit(reference_t1c=baseline_t1c, modalities=followup["modality_paths"],
                             masks=masks, output_dir=run_dir, bias_correction=bias_correction, on_step=on_step)
        registration = result["registration"]
        payload = {
            "ok": True,
            "status": "complete",
            "baseline_session_id": baseline_session_id,
            "followup_session_id": followup_session_id,
            "run_id": run_id,
            "registration": registration,
            "policy": {
                "reference": "baseline_t1c",
                "moving": "followup_t1c",
                "backend": registration["backend"],
                "deformation_model": registration["deformation_model"],
                "nonlinear_deformation_allowed": registration["nonlinear_deformation_allowed"],
                "clinical_rationale": "Preserve interval lesion-size change; do not use nonlinear deformation by default.",
            },
            "intended_use": "research_demo_registration_qc_not_diagnosis",
        }
        (run_dir / "complete.json").write_text(json.dumps({"run_id": run_id}))
        result_path = variant_dir / "registration_result.json"
        pending_path = variant_dir / f"{run_id}.json"
        pending_path.write_text(json.dumps({**payload, "artifacts": result["artifacts"], "sources": sources}, indent=2))
        pending_path.replace(result_path)
        self._set_registration_asset_urls(payload, result["artifacts"], bias_correction)
        return payload

    def create_longitudinal_align_job(self, *, baseline_session_id: str, followup_session_ids: list[str], bias_correction: bool = False) -> dict[str, Any]:
        if not baseline_session_id:
            raise ValueError("baseline_session_id is required.")
        self._get_internal_session(baseline_session_id)
        unique_followups: list[str] = []
        seen: set[str] = set()
        for session_id in followup_session_ids:
            session_id = str(session_id or "").strip()
            if not session_id or session_id == baseline_session_id or session_id in seen:
                continue
            self._get_internal_session(session_id)
            unique_followups.append(session_id)
            seen.add(session_id)
        if not unique_followups:
            raise ValueError("At least one follow-up session is required.")

        job_id = f"gbmalign_{uuid.uuid4().hex[:12]}"
        visits: list[dict[str, Any]] = [
            {
                "session_id": baseline_session_id,
                "baseline_session_id": baseline_session_id,
                "followup_session_id": None,
                **self._longitudinal_registration_visit_identity(baseline_session_id),
                "status": "reference",
                "registration": None,
                "error": None,
            }
        ]
        pending: list[str] = []
        for session_id in unique_followups:
            cached = self._load_cached_longitudinal_registration(
                baseline_session_id=baseline_session_id,
                followup_session_id=session_id,
                bias_correction=bias_correction,
            )
            visit = {
                "session_id": session_id,
                "baseline_session_id": baseline_session_id,
                "followup_session_id": session_id,
                **self._longitudinal_registration_visit_identity(session_id),
                "status": "complete" if cached else "queued",
                "registration": cached.get("registration") if cached else None,
                "error": None,
                "steps": cached["registration"].get("steps", []) if cached else pending_steps(),
            }
            if not cached:
                pending.append(session_id)
            visits.append(visit)

        job = {
            "ok": True,
            "job_id": job_id,
            "status": "completed" if not pending else "running",
            "baseline_session_id": baseline_session_id,
            "bias_correction": bias_correction,
            "workflow": "brain_tumor_alignment_v1",
            "total_count": len(visits),
            "completed_count": sum(1 for visit in visits if visit["status"] in {"reference", "complete"}),
            "failed_count": 0,
            "visits": visits,
            "intended_use": "research_demo_longitudinal_alignment_job_not_diagnosis",
        }
        with self._longitudinal_align_jobs_lock:
            self._longitudinal_align_jobs[job_id] = job

        if pending:
            thread = threading.Thread(
                target=self._run_longitudinal_align_job,
                args=(job_id, baseline_session_id, pending, bias_correction),
                name=f"clinagent-gbm-align-job-{job_id}",
                daemon=True,
            )
            thread.start()
        return self.get_longitudinal_align_job(job_id)

    def get_longitudinal_align_job(self, job_id: str) -> dict[str, Any]:
        with self._longitudinal_align_jobs_lock:
            job = self._longitudinal_align_jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            return json.loads(json.dumps(job))

    def _run_longitudinal_align_job(self, job_id: str, baseline_session_id: str, followup_session_ids: list[str], bias_correction: bool = False) -> None:
        for followup_session_id in followup_session_ids:
            with self._longitudinal_align_jobs_lock:
                job = self._longitudinal_align_jobs.get(job_id)
                if not job:
                    return
                for visit in job["visits"]:
                    if visit.get("followup_session_id") == followup_session_id:
                        visit["status"] = "running"
                        break
                self._refresh_longitudinal_align_job_counts(job)
            try:
                def on_step(step):
                    with self._longitudinal_align_jobs_lock:
                        for visit in self._longitudinal_align_jobs[job_id]["visits"]:
                            if visit.get("followup_session_id") == followup_session_id:
                                visit["steps"] = [step if item["id"] == step["id"] else item for item in visit["steps"]]
                                break
                result = self.register_longitudinal_sessions(
                    baseline_session_id=baseline_session_id,
                    followup_session_id=followup_session_id,
                    overwrite=False,
                    bias_correction=bias_correction,
                    on_step=on_step,
                )
                with self._longitudinal_align_jobs_lock:
                    job = self._longitudinal_align_jobs.get(job_id)
                    if not job:
                        return
                    for visit in job["visits"]:
                        if visit.get("followup_session_id") == followup_session_id:
                            visit["status"] = "complete"
                            visit["registration"] = result.get("registration")
                            visit["steps"] = result["registration"].get("steps", [])
                            visit["error"] = None
                            break
                    self._refresh_longitudinal_align_job_counts(job)
            except Exception:
                logging.getLogger(__name__).exception("Longitudinal alignment job failed: %s", job_id)
                with self._longitudinal_align_jobs_lock:
                    job = self._longitudinal_align_jobs.get(job_id)
                    if not job:
                        return
                    for visit in job["visits"]:
                        if visit.get("followup_session_id") == followup_session_id:
                            visit["status"] = "failed"
                            visit["error"] = "Alignment could not complete. Check input geometry and image quality, then retry."
                            break
                    self._refresh_longitudinal_align_job_counts(job)

    def _refresh_longitudinal_align_job_counts(self, job: dict[str, Any]) -> None:
        visits = job.get("visits") if isinstance(job.get("visits"), list) else []
        completed = sum(
            1
            for visit in visits
            if isinstance(visit, dict) and visit.get("status") in {"reference", "complete"}
        )
        failed = sum(1 for visit in visits if isinstance(visit, dict) and visit.get("status") == "failed")
        running = any(isinstance(visit, dict) and visit.get("status") == "running" for visit in visits)
        queued = any(isinstance(visit, dict) and visit.get("status") == "queued" for visit in visits)
        job["completed_count"] = completed
        job["failed_count"] = failed
        if running or queued:
            job["status"] = "running"
        elif failed:
            job["status"] = "completed_with_errors"
        else:
            job["status"] = "completed"

    def _write_internal_session(
        self,
        *,
        session_id: str,
        session_root: Path,
        modality_paths: dict[str, str],
    ) -> None:
        payload = {
            "session_id": session_id,
            "modality_paths": dict(modality_paths),
            "session_root": str(session_root),
        }
        self._internal_sessions[session_id] = payload
        (session_root / "internal_paths.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _get_internal_session(self, session_id: str) -> dict[str, Any]:
        payload = self._internal_sessions.get(session_id)
        if payload is None:
            internal_path = self.asset_root / session_id / "internal_paths.json"
            if not internal_path.exists():
                raise KeyError(session_id)
            payload = json.loads(internal_path.read_text(encoding="utf-8"))
        # Curated sessions may be read-only mounts relocated from an earlier release.
        normalized = _normalize_session_artifact_paths(
            {"session_id": session_id, "artifacts": payload.get("modality_paths", {})},
            asset_root=self.asset_root,
        )
        payload = {
            **payload,
            "session_root": str(self.asset_root / session_id),
            "modality_paths": normalized["artifacts"],
        }
        self._internal_sessions[session_id] = payload
        return payload

    def _build_session(
        self,
        *,
        session_id: str,
        patient_label: str,
        source: dict[str, Any],
        modality_paths: dict[str, str],
        tool_result: dict[str, Any],
    ) -> dict[str, Any]:
        derived_regions = list(tool_result.get("derived_regions") or [])
        label_regions = list(tool_result.get("label_regions") or [])
        qc = dict(tool_result.get("qc") or {})
        warnings = list(qc.get("warnings") or [])
        optional_missing = [key for key in MODALITY_KEYS if key not in modality_paths and key not in REQUIRED_MODALITIES]
        for key in optional_missing:
            warning = f"Missing optional modality: {key}"
            if warning not in warnings:
                warnings.append(warning)
        qc["warnings"] = warnings

        report_snippet = _build_report_snippet(derived_regions=derived_regions, warnings=warnings)
        artifacts = {
            "seg": tool_result.get("seg_path"),
            "tumor_regions": tool_result.get("tumor_regions_path"),
            "volumes_csv": tool_result.get("volumes_csv_path"),
            "overlay_preview": tool_result.get("overlay_preview_path"),
        }
        for key, path in modality_paths.items():
            if key in MODALITY_KEYS and path:
                artifacts[f"image_{key}"] = path
        if tool_result.get("ground_truth_seg_path"):
            artifacts["ground_truth_seg"] = tool_result.get("ground_truth_seg_path")
        report_slices: dict[str, dict[str, Any]] = {}
        for plane, report_slice in report_slices.items():
            if isinstance(report_slice, dict) and report_slice.get("path"):
                artifacts[f"report_slice_{plane}"] = report_slice["path"]
        artifact_urls = _session_artifact_urls(
            session_id=session_id,
            artifacts=artifacts,
            source=source,
        )
        report_slice_assets = {
            plane: {
                "url": artifact_urls.get(f"report_slice_{plane}"),
                "slice_index": report_slice.get("slice_index"),
                "modality": "t1c",
            }
            for plane, report_slice in report_slices.items()
            if isinstance(report_slice, dict) and artifact_urls.get(f"report_slice_{plane}")
        }
        return {
            "ok": True,
            "session_id": session_id,
            "status": "complete",
            "patient_label": patient_label,
            "source": source,
            "modality_status": {
                key: {
                    "present": key in modality_paths,
                    "required": key in REQUIRED_MODALITIES,
                    "path_name": Path(modality_paths[key]).name if key in modality_paths else "",
                }
                for key in MODALITY_KEYS
            },
            "volumes": derived_regions,
            "label_volumes": label_regions,
            "qc": qc,
            "report_snippet": report_snippet,
            "service": {
                "model_id": tool_result.get("model_info", {}).get("model_id")
                if isinstance(tool_result.get("model_info"), dict)
                else tool_result.get("model_id_hint"),
                "mode": tool_result.get("mode"),
                "remote_staging": tool_result.get("remote_staging"),
            },
            "viewer_assets": {
                "viewer_type": "nifti",
                "overlay_preview_url": artifact_urls.get("overlay_preview"),
                "segmentation_url": artifact_urls.get("seg"),
                "modality_volume_urls": {
                    key: artifact_urls.get(f"image_{key}")
                    for key in MODALITY_KEYS
                    if artifact_urls.get(f"image_{key}")
                },
                "ground_truth_segmentation_url": artifact_urls.get("ground_truth_seg"),
                "report_slices": {
                    "modality": "t1c",
                    **report_slice_assets,
                } if report_slice_assets else None,
            },
            "artifacts": artifacts,
            "artifact_urls": artifact_urls,
            "intended_use": "research_demo_segmentation_not_diagnosis",
        }


    def _ensure_report_slice_assets(self, session: dict[str, Any]) -> dict[str, Any]:
        session_id = str(session.get("session_id") or "")
        if not session_id:
            return session
        artifacts = dict(session.get("artifacts") or {})
        viewer_assets = dict(session.get("viewer_assets") or {})
        report_slices = viewer_assets.get("report_slices")
        if isinstance(report_slices, dict) and all(report_slices.get(plane) for plane in ("axial", "coronal", "sagittal")):
            return session
        image_path = artifacts.get("image_t1c") or next((artifacts.get(f"image_{key}") for key in MODALITY_KEYS if artifacts.get(f"image_{key}")), None)
        seg_path = artifacts.get("seg")
        materialized = self._materialize_report_slices(
            session_id=session_id,
            image_path=str(image_path) if image_path else None,
            seg_path=str(seg_path) if seg_path else None,
        )
        if not materialized:
            return session
        for plane, report_slice in materialized.items():
            if isinstance(report_slice, dict) and report_slice.get("path"):
                artifacts[f"report_slice_{plane}"] = report_slice["path"]
        artifact_urls = {
            key: _artifact_url(session_id=session_id, artifact_name=str(key), artifact_path=str(value))
            for key, value in artifacts.items()
            if value
        }
        viewer_assets["report_slices"] = {
            "modality": "t1c",
            **{
                plane: {
                    "url": artifact_urls.get(f"report_slice_{plane}"),
                    "slice_index": report_slice.get("slice_index"),
                    "modality": "t1c",
                }
                for plane, report_slice in materialized.items()
                if isinstance(report_slice, dict) and artifact_urls.get(f"report_slice_{plane}")
            },
        }
        refreshed = dict(session)
        refreshed["artifacts"] = artifacts
        refreshed["artifact_urls"] = artifact_urls
        refreshed["viewer_assets"] = viewer_assets
        return refreshed

    def _materialize_report_slices(self, *, session_id: str, image_path: str | None, seg_path: str | None) -> dict[str, dict[str, Any]]:
        if not session_id or not image_path or not seg_path:
            return {}
        image_file = Path(image_path).expanduser().resolve()
        seg_file = Path(seg_path).expanduser().resolve()
        if not image_file.exists() or not seg_file.exists():
            return {}
        try:
            image_data = _load_nifti_array(image_file)
            seg_data = _load_nifti_array(seg_file)
        except Exception:
            return {}
        if image_data.ndim < 3 or seg_data.ndim < 3:
            return {}
        image_data = image_data[..., 0] if image_data.ndim == 4 else image_data
        seg_data = seg_data[..., 0] if seg_data.ndim == 4 else seg_data
        if image_data.shape[:3] != seg_data.shape[:3]:
            return {}
        output_dir = self.asset_root / session_id / "outputs" / "report_slices"
        output_dir.mkdir(parents=True, exist_ok=True)
        result: dict[str, dict[str, Any]] = {}
        for plane, axis in (("sagittal", 0), ("coronal", 1), ("axial", 2)):
            index = _select_max_mask_slice(seg_data, axis=axis)
            image_slice = np.take(image_data, index, axis=axis)
            seg_slice = np.take(seg_data, index, axis=axis)
            panel = _compose_report_slice_panel(image_slice=image_slice, seg_slice=seg_slice, plane=plane)
            output_path = output_dir / f"{plane}.png"
            panel.save(output_path)
            result[plane] = {"path": str(output_path), "slice_index": int(index)}
        return result


def _load_nifti_array(path: Path) -> np.ndarray:
    data = nib.load(str(path)).get_fdata(dtype=np.float32)
    return np.asarray(data)


def _select_max_mask_slice(mask: np.ndarray, *, axis: int) -> int:
    if mask.ndim < 3 or mask.shape[axis] <= 0:
        return 0
    positive = mask > 0
    if not np.any(positive):
        return int(mask.shape[axis] // 2)
    reduce_axes = tuple(idx for idx in range(3) if idx != axis)
    areas = positive.sum(axis=reduce_axes)
    return int(np.clip(np.argmax(areas), 0, mask.shape[axis] - 1))


def _normalize_report_slice(image_slice: np.ndarray) -> np.ndarray:
    data = np.asarray(image_slice, dtype=np.float32)
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return np.zeros(data.shape, dtype=np.uint8)
    low, high = np.percentile(finite, [1, 99])
    if high <= low:
        low, high = float(np.min(finite)), float(np.max(finite))
    if high <= low:
        return np.zeros(data.shape, dtype=np.uint8)
    clipped = np.clip(data, low, high)
    return ((clipped - low) / max(high - low, 1e-6) * 255.0).astype(np.uint8)


def _orient_report_slice(slice_data: np.ndarray, *, plane: str) -> np.ndarray:
    oriented = np.rot90(np.asarray(slice_data))
    if plane == "sagittal":
        oriented = np.fliplr(oriented)
    return oriented


def _compose_report_slice_panel(*, image_slice: np.ndarray, seg_slice: np.ndarray, plane: str) -> Image.Image:
    base = _orient_report_slice(_normalize_report_slice(image_slice), plane=plane)
    seg = _orient_report_slice(np.asarray(seg_slice), plane=plane)
    rgb = np.stack([base, base, base], axis=-1).astype(np.float32)
    colors = {
        1: np.array([124, 92, 255], dtype=np.float32),
        2: np.array([47, 142, 199], dtype=np.float32),
        3: np.array([223, 91, 120], dtype=np.float32),
        4: np.array([219, 151, 57], dtype=np.float32),
    }
    for label_id, color in colors.items():
        region = seg == label_id
        if np.any(region):
            rgb[region] = rgb[region] * 0.44 + color * 0.56
    image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), mode="RGB")
    image.thumbnail((640, 640), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (640, 640), (14, 17, 22))
    offset = ((640 - image.width) // 2, (640 - image.height) // 2)
    canvas.paste(image, offset)
    return canvas


def classify_series_for_tumor_modality(series: dict[str, Any]) -> ModalityCandidate | None:
    text = " ".join(
        str(value)
        for value in [
            series.get("description", ""),
            series.get("modality", ""),
            _flatten_metadata_text(series.get("metadata")),
        ]
        if value
    ).lower()
    compact = text.replace("-", "").replace("_", "").replace(" ", "")

    candidates: list[ModalityCandidate] = []
    if any(token in text for token in ("flair", "fluid attenuated", "flr")) or "t2flair" in compact:
        candidates.append(ModalityCandidate("t2f", 0.95, "FLAIR/T2-FLAIR sequence name"))
    if (
        any(token in compact for token in ("t1c", "t1gd", "t1ce", "t1+c", "mpragegd", "postgd"))
        or ("post" in compact and "t1" in compact)
    ) or any(
        token in text for token in ("post contrast", "post-contrast", "post gd", "gadolinium", "contrast enhanced")
    ):
        candidates.append(ModalityCandidate("t1c", 0.93, "contrast-enhanced T1 sequence name"))
    if "t2" in compact and not any(token in compact for token in ("flair", "flr")):
        candidates.append(ModalityCandidate("t2w", 0.75, "T2-weighted sequence name"))
    if any(token in compact for token in ("t1", "mprage", "spgr", "bravo")) and not candidates:
        candidates.append(ModalityCandidate("t1n", 0.7, "non-contrast T1-like sequence name"))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item.score, reverse=True)[0]


def suggest_modality_mapping(series_rows: list[dict[str, Any]]) -> dict[str, str]:
    selected: dict[str, tuple[float, str]] = {}
    for row in series_rows:
        modality = row.get("candidate_modality")
        series_uid = row.get("series_instance_uid")
        score = float(row.get("candidate_score") or 0)
        if not modality or not series_uid:
            continue
        current = selected.get(str(modality))
        if current is None or score > current[0]:
            selected[str(modality)] = (score, str(series_uid))
    return {key: value for key, (_, value) in selected.items()}


def _safe_id_fragment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:80] or "session"


def _configured_dicom_roots(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(os.pathsep) if item.strip()]


def _encode_mount_ref(
    *,
    root_index: int,
    rel_path: str,
    patient_rel: str | None = None,
    study_group: str | None = None,
) -> str:
    data: dict[str, Any] = {"root_index": int(root_index), "rel_path": rel_path}
    if patient_rel is not None:
        data["patient_rel"] = patient_rel
    if study_group is not None:
        data["study_group"] = study_group
    payload = json.dumps(data, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_mount_ref(ref: str) -> dict[str, Any]:
    padded = ref + ("=" * (-len(ref) % 4))
    payload = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    decoded = json.loads(payload)
    if not isinstance(decoded, dict) or "root_index" not in decoded or "rel_path" not in decoded:
        raise ValueError("Invalid mounted DICOM reference.")
    return decoded


def _mounted_ref_path(*, roots: list[str], ref: str) -> Path:
    decoded = _decode_mount_ref(ref)
    root_index = int(decoded["root_index"])
    if root_index < 0 or root_index >= len(roots):
        raise ValueError("Mounted DICOM root reference is out of range.")
    root = Path(roots[root_index]).expanduser().resolve()
    path = (root / str(decoded["rel_path"])).resolve()
    if root != path and root not in path.parents:
        raise ValueError("Mounted DICOM reference escapes the configured root.")
    if not path.exists():
        raise ValueError("Mounted DICOM reference does not exist.")
    return path


def _scan_local_mounted_studies(
    *,
    roots: list[str],
    patient_id: str,
    accession_number: str,
    scan_limit: int,
) -> dict[str, Any]:
    query = " ".join([patient_id, accession_number]).strip().lower()
    grouped: dict[tuple[int, str], dict[str, Any]] = {}
    files_seen = 0
    for root_index, raw_root in enumerate(roots):
        root = Path(raw_root).expanduser().resolve()
        if not root.exists():
            continue
        for dicom_path in root.rglob("*.dcm"):
            files_seen += 1
            if files_seen > scan_limit:
                break
            series_dir = dicom_path.parent
            study_dir = series_dir.parent
            if study_dir == root or study_dir.parent == study_dir:
                continue
            patient_dir = study_dir.parent
            searchable = f"{patient_dir.name} {study_dir.name} {series_dir.name}".lower()
            if query and query not in searchable:
                continue
            patient_rel = str(patient_dir.relative_to(root))
            study_group = _mounted_study_group_key(study_dir.name)
            key = (root_index, patient_rel, study_group)
            record = grouped.setdefault(
                key,
                {
                    "study_instance_uid": _encode_mount_ref(
                        root_index=root_index,
                        rel_path="",
                        patient_rel=patient_rel,
                        study_group=study_group,
                    ),
                    "patient_id": patient_dir.name,
                    "modality": "MR",
                    "description": study_group,
                    "study_date": _extract_date_like_text(study_group),
                    "series_count": 0,
                    "metadata": {"source": "mounted_dicom", "remote": False},
                    "_series": set(),
                },
            )
            record["_series"].add(series_dir.name)
        else:
            continue
        break

    studies: list[dict[str, Any]] = []
    for record in grouped.values():
        series_names = record.pop("_series")
        record["series_count"] = len(series_names)
        studies.append(record)
    studies.sort(key=lambda item: (item.get("patient_id", ""), item.get("description", "")))
    return {"ok": True, "configured": True, "studies": studies, "files_scanned": files_seen}


def _list_local_mounted_series(*, roots: list[str], study_ref: str) -> dict[str, Any]:
    decoded = _decode_mount_ref(study_ref)
    root_index = int(decoded["root_index"])
    root = Path(roots[root_index]).expanduser().resolve()
    if decoded.get("patient_rel") and decoded.get("study_group"):
        patient_dir = (root / str(decoded["patient_rel"])).resolve()
        study_dirs = [
            path
            for path in sorted(patient_dir.iterdir())
            if path.is_dir() and _mounted_study_group_key(path.name) == str(decoded["study_group"])
        ]
    else:
        study_dirs = [_mounted_ref_path(roots=roots, ref=study_ref)]
    rows: list[dict[str, Any]] = []
    for study_dir in study_dirs:
        for series_dir in sorted(path for path in study_dir.iterdir() if path.is_dir()):
            dicom_files = list(series_dir.glob("*.dcm"))
            if not dicom_files:
                continue
            candidate = classify_series_for_tumor_modality({"description": series_dir.name, "modality": "MR"})
            rel_series = str(series_dir.relative_to(root))
            rows.append(
                {
                    "study_instance_uid": study_ref,
                    "series_instance_uid": _encode_mount_ref(root_index=root_index, rel_path=rel_series),
                    "modality": "MR",
                    "description": series_dir.name,
                    "instance_count": len(dicom_files),
                    "metadata": {"source": "mounted_dicom", "remote": False},
                    "candidate_modality": candidate.modality if candidate else None,
                    "candidate_score": candidate.score if candidate else 0,
                    "candidate_reason": candidate.reason if candidate else "",
                }
            )
    return {"ok": True, "series": rows, "suggested_mapping": suggest_modality_mapping(rows)}


def _run_remote_mount_action(*, host: str, request: dict[str, Any]) -> dict[str, Any]:
    command = f"python3 -c {shlex.quote(_REMOTE_MOUNT_SCRIPT)} {shlex.quote(json.dumps(request))}"
    completed = subprocess.run(
        ["ssh", host, command],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        details = _clean_remote_process_output(completed.stderr, completed.stdout) or "no remote output"
        raise RuntimeError(f"Mounted DICOM remote query failed: {details}")
    return _load_remote_json(completed.stdout)


def _convert_remote_mounted_series(
    *,
    host: str,
    roots: list[str],
    series_ref: str,
    local_output_dir: Path,
    remote_work_root: str,
    dcm2niix_bin: str,
    output_stem: str,
) -> str:
    decoded = _decode_mount_ref(series_ref)
    root_index = int(decoded["root_index"])
    if root_index < 0 or root_index >= len(roots):
        raise ValueError("Mounted DICOM root reference is out of range.")
    remote_series_dir = f"{roots[root_index].rstrip('/')}/{str(decoded['rel_path']).lstrip('/')}"
    remote_out = f"{remote_work_root.rstrip('/')}/{uuid.uuid4().hex}/{output_stem}"
    quoted_converter = shlex.quote(dcm2niix_bin or "dcm2niix")
    remote_command = (
        f"mkdir -p {shlex.quote(remote_out)} && "
        f"if ! command -v {quoted_converter} >/dev/null 2>&1 && [ ! -x {quoted_converter} ]; then "
        f"echo dcm2niix_not_found:{quoted_converter} >&2; exit 127; fi && "
        f"{quoted_converter} -z y -f {shlex.quote(output_stem)} -o {shlex.quote(remote_out)} "
        f"{shlex.quote(remote_series_dir)} >/dev/null && "
        f"find {shlex.quote(remote_out)} \\( -name '*.nii.gz' -o -name '*.nii' \\) | head -n 1"
    )
    completed = subprocess.run(["ssh", host, remote_command], check=False, capture_output=True, text=True, timeout=300)
    if completed.returncode != 0:
        details = _clean_remote_process_output(completed.stderr, completed.stdout) or "no remote converter output"
        if "dcm2niix_not_found:" in details or "command not found" in details:
            raise RuntimeError(
                "Remote mounted DICOM conversion requires dcm2niix. "
                "Install dcm2niix on the remote host or set CLINAGENT_BRAIN_TUMOR_DICOM_DCM2NIIX_BIN."
            )
        raise RuntimeError(f"Remote mounted DICOM conversion failed for {output_stem}: {details}")
    remote_nifti = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    if not remote_nifti:
        raise RuntimeError(f"Remote mounted DICOM conversion did not produce a NIfTI for {output_stem}.")
    local_output_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_output_dir / (Path(remote_nifti).name or f"{output_stem}.nii.gz")
    copy = subprocess.run(["scp", f"{host}:{remote_nifti}", str(local_path)], check=False, capture_output=True, text=True)
    if copy.returncode != 0:
        details = _clean_remote_process_output(copy.stderr, copy.stdout) or "no scp output"
        raise RuntimeError(f"Failed to copy converted mounted DICOM NIfTI for {output_stem}: {details}")
    return str(local_path.resolve())


def _clean_remote_process_output(*chunks: str) -> str:
    text = "\n".join(chunk for chunk in chunks if chunk)
    if not text:
        return ""
    noisy_fragments = (
        "State Goverment Computer System",
        "State Government Computer System",
        "Unauthorized attempts to upload",
        "programming language, or any other part",
        "strictly prohibited and are subject",
        "Consistent with the above",
        "using this system expressly consents",
        "advised that if such monitoring",
        "monitoring reveals possible evidence",
        "The State of Texas may provide",
        "evidence of such monitoring",
        "post-quantum key exchange",
        "store now, decrypt later",
        "server may need to be upgraded",
        "openssh.com/pq.html",
    )
    cleaned: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if any(fragment in line for fragment in noisy_fragments):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _load_remote_json(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        for line in reversed(stdout.splitlines()):
            candidate = line.strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                payload = json.loads(candidate)
                break
        else:
            details = _clean_remote_process_output(stdout) or "remote response was not JSON"
            raise RuntimeError(f"Mounted DICOM remote query returned invalid JSON: {details}") from None
    if not isinstance(payload, dict):
        raise RuntimeError("Mounted DICOM remote query returned an unexpected payload.")
    return payload


def _extract_date_like_text(value: str) -> str:
    match = re.search(r"(19|20)\d{2}[-_]\d{2}[-_]\d{2}", value)
    return match.group(0).replace("_", "-") if match else ""


def _mounted_study_group_key(study_dir_name: str) -> str:
    return re.sub(r"-\d{3,}$", "", study_dir_name)


_REMOTE_MOUNT_SCRIPT = r'''
import base64, json, pathlib, re, sys

def enc(root_index, rel_path, patient_rel=None, study_group=None):
    data = {"root_index": int(root_index), "rel_path": rel_path}
    if patient_rel is not None:
        data["patient_rel"] = patient_rel
    if study_group is not None:
        data["study_group"] = study_group
    payload = json.dumps(data, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")

def dec(ref):
    ref = ref + ("=" * (-len(ref) % 4))
    return json.loads(base64.urlsafe_b64decode(ref.encode()).decode())

def date_like(text):
    m = re.search(r"(19|20)\d{2}[-_]\d{2}[-_]\d{2}", text)
    return m.group(0).replace("_", "-") if m else ""

def study_group_key(text):
    return re.sub(r"-\d{3,}$", "", text)

def classify(description):
    text = description.lower()
    compact = text.replace("-", "").replace("_", "").replace(" ", "")
    if "flair" in text or "flr" in text or "t2flair" in compact:
        return "t2f", 0.95, "FLAIR/T2-FLAIR sequence name"
    if any(t in compact for t in ("t1c", "t1gd", "t1ce", "postgd")) or ("post" in compact and "t1" in compact) or any(t in text for t in ("post contrast", "post-contrast", "post gd", "gadolinium", "contrast enhanced")):
        return "t1c", 0.93, "contrast-enhanced T1 sequence name"
    if "t2" in compact:
        return "t2w", 0.75, "T2-weighted sequence name"
    if any(t in compact for t in ("t1", "mprage", "spgr", "bravo")):
        return "t1n", 0.70, "non-contrast T1-like sequence name"
    return None, 0, ""

req = json.loads(sys.argv[1])
roots = req.get("roots", [])
if req.get("action") == "studies":
    query = " ".join([req.get("patient_id", ""), req.get("accession_number", "")]).strip().lower()
    limit = int(req.get("scan_limit") or 5000)
    files_seen = 0
    grouped = {}
    for root_index, raw_root in enumerate(roots):
        root = pathlib.Path(raw_root)
        if not root.exists():
            continue
        for dicom_path in root.rglob("*.dcm"):
            files_seen += 1
            if files_seen > limit:
                break
            series_dir = dicom_path.parent
            study_dir = series_dir.parent
            patient_dir = study_dir.parent
            searchable = f"{patient_dir.name} {study_dir.name} {series_dir.name}".lower()
            if query and query not in searchable:
                continue
            patient_rel = str(patient_dir.relative_to(root))
            group = study_group_key(study_dir.name)
            key = (root_index, patient_rel, group)
            record = grouped.setdefault(key, {"study_instance_uid": enc(root_index, "", patient_rel, group), "patient_id": patient_dir.name, "modality": "MR", "description": group, "study_date": date_like(group), "series_count": 0, "metadata": {"source": "mounted_dicom", "remote": True}, "_series": set()})
            record["_series"].add(series_dir.name)
        else:
            continue
        break
    studies = []
    for record in grouped.values():
        record["series_count"] = len(record.pop("_series"))
        studies.append(record)
    studies.sort(key=lambda item: (item.get("patient_id", ""), item.get("description", "")))
    print(json.dumps({"ok": True, "configured": True, "studies": studies, "files_scanned": files_seen}))
elif req.get("action") == "series":
    decoded = dec(req["study_ref"])
    root_index = int(decoded["root_index"])
    root = pathlib.Path(roots[root_index])
    if decoded.get("patient_rel") and decoded.get("study_group"):
        patient_dir = root / decoded["patient_rel"]
        study_dirs = [p for p in sorted(patient_dir.iterdir()) if p.is_dir() and study_group_key(p.name) == decoded["study_group"]]
    else:
        study_dirs = [root / decoded["rel_path"]]
    rows = []
    for study_dir in study_dirs:
        for series_dir in sorted(p for p in study_dir.iterdir() if p.is_dir()):
            count = sum(1 for _ in series_dir.glob("*.dcm"))
            if not count:
                continue
            modality, score, reason = classify(series_dir.name)
            rel = str(series_dir.relative_to(root))
            rows.append({"study_instance_uid": req["study_ref"], "series_instance_uid": enc(root_index, rel), "modality": "MR", "description": series_dir.name, "instance_count": count, "metadata": {"source": "mounted_dicom", "remote": True}, "candidate_modality": modality, "candidate_score": score, "candidate_reason": reason})
    selected = {}
    for row in rows:
        m = row.get("candidate_modality")
        if not m:
            continue
        if m not in selected or row["candidate_score"] > selected[m][0]:
            selected[m] = (row["candidate_score"], row["series_instance_uid"])
    print(json.dumps({"ok": True, "series": rows, "suggested_mapping": {k: v for k, (_, v) in selected.items()}}))
else:
    print(json.dumps({"ok": False, "error": "unknown action"}))
'''


def _dicom_connector() -> DICOMWebConnector:
    settings = load_settings()
    mode = ConnectorMode(settings.imaging_connector_mode)
    return DICOMWebConnector(
        mode=mode,
        base_url=settings.dicomweb_base_url,
        access_token=settings.dicomweb_access_token,
        timeout_s=settings.connector_timeout_s,
    )


async def _download_dicom_series(
    *,
    connector: DICOMWebConnector,
    study_instance_uid: str,
    series_instance_uid: str,
    output_dir: Path,
) -> None:
    instances = await connector.search_instances(
        study_instance_uid=study_instance_uid,
        series_instance_uid=series_instance_uid,
    )
    if not instances:
        raise ConnectorError("No DICOM instances were returned for the selected series.")
    for index, instance in enumerate(instances, start=1):
        retrieved = await connector.retrieve_instance(
            study_instance_uid=study_instance_uid,
            series_instance_uid=series_instance_uid,
            sop_instance_uid=instance.sop_instance_uid,
        )
        target = output_dir / f"{index:05d}_{instance.sop_instance_uid}.dcm"
        target.write_bytes(retrieved.data)


def _convert_dicom_series(*, dcm2niix_bin: str, dicom_dir: Path, output_dir: Path, output_stem: str) -> str:
    completed = subprocess.run(
        [dcm2niix_bin, "-z", "y", "-f", output_stem, "-o", str(output_dir), str(dicom_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "no converter output"
        raise RuntimeError(f"DICOM conversion failed for {output_stem}: {details}")
    candidates = sorted([*output_dir.glob("*.nii.gz"), *output_dir.glob("*.nii")])
    if not candidates:
        raise RuntimeError(f"DICOM conversion did not produce a NIfTI for {output_stem}.")
    return str(candidates[0].resolve())


def _validate_required_modalities(modality_paths: dict[str, str]) -> None:
    missing = [key for key in REQUIRED_MODALITIES if not modality_paths.get(key)]
    if missing:
        raise ValueError(f"Unified glioma segmentation requires t1n, t1c, t2w, and t2f; missing: {', '.join(missing)}")


def _load_case_registry() -> dict[str, Any]:
    registry_path = os.getenv("CLINAGENT_BRAIN_TUMOR_CASE_REGISTRY_JSON", "").strip()
    if not registry_path:
        return {"id": "unconfigured", "cases": []}
    path = Path(registry_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Brain tumor case registry is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Brain tumor case registry must be a JSON object.")
    if not isinstance(payload.get("cases", []), list):
        raise ValueError("Brain tumor case registry requires a cases list.")
    return payload


def _registry_cache_session_id(*, registry_id: str, case_id: str, timepoint_id: str, model_id: str) -> str:
    cache_key = json.dumps(
        {
            "registry_id": registry_id,
            "case_id": case_id,
            "timepoint_id": timepoint_id,
            "model_id": model_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:16]
    return f"brain-tumor-cache-{digest}"


def _registry_rerun_session_id(
    *,
    registry_id: str,
    case_id: str,
    timepoint_id: str,
    model_id: str,
    run_id: str,
) -> str:
    cache_key = json.dumps(
        {
            "registry_id": registry_id,
            "case_id": case_id,
            "timepoint_id": timepoint_id,
            "model_id": model_id,
            "run_id": run_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:16]
    return f"brain-tumor-rerun-{digest}"


def _registry_image_session_id(*, registry_id: str, case_id: str, timepoint_id: str) -> str:
    cache_key = json.dumps(
        {
            "registry_id": registry_id,
            "case_id": case_id,
            "timepoint_id": timepoint_id,
            "stage": "image_only_load",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:16]
    return f"brain-tumor-image-{digest}"


def _registry_session_matches(*, session: dict[str, Any], case: dict[str, Any], timepoint: dict[str, Any], model_id: str) -> bool:
    source = session.get("source") if isinstance(session.get("source"), dict) else {}
    service = session.get("service") if isinstance(session.get("service"), dict) else {}
    if source.get("type") != "remote_case_registry":
        return False
    if source.get("case_id") != case.get("id"):
        return False
    if source.get("timepoint_id") != timepoint.get("id"):
        return False
    cached_model_id = str(service.get("model_id") or "")
    return not cached_model_id or cached_model_id == model_id


def _session_artifacts_complete(session: dict[str, Any], *, require_segmentation: bool = True) -> bool:
    artifacts = session.get("artifacts") if isinstance(session.get("artifacts"), dict) else {}
    required = [f"image_{key}" for key in MODALITY_KEYS]
    if require_segmentation:
        required = ["seg", "tumor_regions", "volumes_csv", "overlay_preview", *required]
    for key in required:
        value = artifacts.get(key)
        if not value:
            return False
        path = Path(str(value)).expanduser()
        if not path.exists() or not path.is_file():
            return False
    return True


def _normalize_session_artifact_paths(session: dict[str, Any], *, asset_root: Path) -> dict[str, Any]:
    if not session:
        return session
    session_id = str(session.get("session_id") or "")
    artifacts = session.get("artifacts") if isinstance(session.get("artifacts"), dict) else {}
    if not session_id or not artifacts:
        return session

    asset_root = asset_root.resolve()
    session_root = asset_root / session_id
    normalized_artifacts = dict(artifacts)
    changed = False

    for key, value in artifacts.items():
        if not value:
            continue
        artifact_path = Path(str(value)).expanduser()
        resolved = artifact_path.resolve(strict=False)
        if _path_is_relative_to(resolved, asset_root):
            continue
        parts = artifact_path.parts
        matching_indexes = [index for index, part in enumerate(parts) if part == session_id]
        if not matching_indexes:
            continue
        relative_parts = parts[matching_indexes[-1] + 1 :]
        if not relative_parts:
            continue
        candidate = (session_root / Path(*relative_parts)).resolve(strict=False)
        if candidate.exists() and _path_is_relative_to(candidate, asset_root):
            normalized_artifacts[key] = str(candidate)
            changed = True

    if not changed:
        return session
    normalized = dict(session)
    normalized["artifacts"] = normalized_artifacts
    return _refresh_session_artifact_urls(normalized)


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _pending_registry_demo_quality() -> dict[str, Any]:
    return {
        "cache_count": 0,
        "recommended": False,
        "note": "Preview pending",
        "sort_score": 0.0,
    }


def _summarize_registry_sessions_for_demo(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    if not sessions:
        return _pending_registry_demo_quality()

    max_et_ml = max((_session_region_ml(session, "enhancing_tumor") for session in sessions), default=0.0)
    max_flair_ml = max((_session_region_ml(session, "flair_abnormality") for session in sessions), default=0.0)
    max_wt_ml = max((_session_region_ml(session, "whole_tumor") for session in sessions), default=0.0)
    if max_wt_ml <= 0:
        max_wt_ml = max_et_ml + max_flair_ml
    max_cavity_ml = max((_session_region_ml(session, "cavity_or_post_surgical_change") for session in sessions), default=0.0)
    max_cavity_to_wt = max((max_cavity_ml / max_wt_ml) if max_wt_ml > 0 else 0.0, 0.0)

    score = 40.0
    score += 30.0 if 0.5 <= max_et_ml <= 6.0 else 20.0 if max_et_ml > 6.0 else -20.0
    score += 20.0 if 12.0 <= max_wt_ml <= 60.0 else 10.0 if max_wt_ml > 60.0 else 5.0 if max_wt_ml > 0 else 0.0
    score += min(max_flair_ml, 80.0) * 0.05
    score -= min(max_cavity_to_wt, 2.0) * 80.0
    score = max(score, 5.0)

    recommended = max_et_ml >= 0.5 and max_cavity_to_wt <= 0.35 and max_wt_ml >= 10.0
    if recommended:
        note = "Cleaner cached preview"
    elif max_cavity_to_wt > 0.5:
        note = "Cached preview; cavity/exclusion label dominates"
    elif max_et_ml < 0.5:
        note = "Cached preview; low enhancing-tumor signal"
    else:
        note = "Cached preview"
    return {
        "cache_count": len(sessions),
        "recommended": recommended,
        "note": note,
        "max_enhancing_ml": round(max_et_ml, 3),
        "max_flair_ml": round(max_flair_ml, 3),
        "max_cavity_ml": round(max_cavity_ml, 3),
        "max_cavity_to_wt": round(max_cavity_to_wt, 3),
        "sort_score": round(score, 3),
    }


def _session_region_ml(session: dict[str, Any], region: str) -> float:
    volumes = session.get("volumes") if isinstance(session.get("volumes"), list) else []
    for volume in volumes:
        if not isinstance(volume, dict) or volume.get("region") != region:
            continue
        try:
            if volume.get("volume_ml") is not None:
                return float(volume["volume_ml"])
            if volume.get("volume_mm3") is not None:
                return float(volume["volume_mm3"]) / 1000.0
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _refresh_session_artifact_urls(session: dict[str, Any]) -> dict[str, Any]:
    refreshed = dict(session)
    session_id = str(refreshed.get("session_id") or "")
    artifacts = refreshed.get("artifacts") if isinstance(refreshed.get("artifacts"), dict) else {}
    source = refreshed.get("source") if isinstance(refreshed.get("source"), dict) else {}
    artifact_urls = _session_artifact_urls(
        session_id=session_id,
        artifacts=artifacts,
        source=source,
    )
    refreshed["artifact_urls"] = artifact_urls
    viewer_assets = dict(refreshed.get("viewer_assets") or {})
    viewer_assets.update(
        {
            "viewer_type": viewer_assets.get("viewer_type") or "nifti",
            "overlay_preview_url": artifact_urls.get("overlay_preview"),
            "segmentation_url": artifact_urls.get("seg"),
            "modality_volume_urls": {
                key: artifact_urls.get(f"image_{key}")
                for key in MODALITY_KEYS
                if artifact_urls.get(f"image_{key}")
            },
            "ground_truth_segmentation_url": artifact_urls.get("ground_truth_seg"),
        }
    )
    report_slices = dict(viewer_assets.get("report_slices") or {})
    report_slice_assets = {
        plane: {
            "url": artifact_urls.get(f"report_slice_{plane}"),
            "slice_index": report_slices.get(plane, {}).get("slice_index") if isinstance(report_slices.get(plane), dict) else None,
            "modality": "t1c",
        }
        for plane in ("axial", "coronal", "sagittal")
        if artifact_urls.get(f"report_slice_{plane}")
    }
    if report_slice_assets:
        viewer_assets["report_slices"] = {"modality": "t1c", **report_slice_assets}
    refreshed["viewer_assets"] = viewer_assets
    return refreshed


def _run_checked(argv: list[str], action: str) -> None:
    completed = subprocess.run(argv, check=False, text=True, capture_output=True)
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"Failed to {action}: {stderr}")


def _is_same_host_registry(remote_host: str) -> bool:
    host = (remote_host or "").strip().lower()
    if not host:
        return True
    if os.getenv("CLINAGENT_BRAIN_TUMOR_CASE_REGISTRY_SAME_HOST", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True

    aliases = {"local", "localhost", "127.0.0.1", "::1"}
    for candidate in (socket.gethostname(), socket.getfqdn()):
        candidate = candidate.strip().lower()
        if candidate:
            aliases.add(candidate)
            aliases.add(candidate.split(".", 1)[0])
    for candidate in os.getenv("CLINAGENT_BRAIN_TUMOR_LOCAL_HOST_ALIASES", "").split(","):
        candidate = candidate.strip().lower()
        if candidate:
            aliases.add(candidate)

    host = host.rsplit("@", 1)[-1]
    host = host.strip("[]")
    host = host.split(":", 1)[0] if ":" in host and host.count(":") == 1 else host
    return host in aliases


def _copy_remote_file(*, remote_host: str, remote_path: str, local_path: Path, required: bool) -> str:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    if local_path.exists() and local_path.is_file() and local_path.stat().st_size > 0:
        return str(local_path.resolve())
    if _is_same_host_registry(remote_host):
        source_path = Path(remote_path).expanduser()
        if source_path.exists() and source_path.is_file():
            if source_path.resolve() != local_path.resolve():
                shutil.copy2(source_path, local_path)
            return str(local_path.resolve())
        if required and not remote_host.strip():
            raise RuntimeError(f"Failed to copy local registry artifact {remote_path}: file does not exist")
        if not remote_host.strip():
            return ""
    completed = subprocess.run(
        ["scp", f"{remote_host}:{remote_path}", str(local_path)],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        if required:
            stderr = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"Failed to copy remote artifact {remote_path}: {stderr}")
        return ""
    return str(local_path.resolve())


def _artifact_url(*, session_id: str, artifact_name: str, artifact_path: str) -> str:
    filename = quote(Path(artifact_path).name)
    return f"/api/demo/brain-tumor/sessions/{session_id}/artifact/{artifact_name}/{filename}"


def _session_artifact_urls(
    *,
    session_id: str,
    artifacts: dict[str, Any],
    source: dict[str, Any] | None = None,
) -> dict[str, str]:
    source = source or {}
    upload_case_id = str(source.get("case_id") or "").strip() if source.get("type") == "nifti_upload" else ""
    urls: dict[str, str] = {}
    for key, value in artifacts.items():
        if not value:
            continue
        artifact_name = str(key)
        modality = artifact_name.removeprefix("image_")
        if upload_case_id and artifact_name.startswith("image_") and modality in MODALITY_KEYS:
            visit_id = str(source.get("visit_id") or "")
            visit_path = f"/visits/{quote(visit_id, safe='')}" if visit_id else ""
            urls[artifact_name] = (
                f"/api/demo/brain-tumor/uploads/{quote(upload_case_id, safe='')}{visit_path}/modality/{modality}/{modality}.nii.gz"
            )
            continue
        urls[artifact_name] = _artifact_url(
            session_id=session_id,
            artifact_name=artifact_name,
            artifact_path=str(value),
        )
    return urls


def _build_report_snippet(*, derived_regions: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    volumes = {str(row.get("region")): float(row.get("volume_ml") or 0.0) for row in derived_regions}
    wt = volumes.get("whole_tumor", 0.0)
    flair = volumes.get("flair_abnormality", 0.0)
    et = volumes.get("enhancing_tumor", 0.0)
    rc = volumes.get("cavity_or_post_surgical_change", 0.0)
    findings = (
        "Research tumor segmentation estimates contrast-enhancing tumor "
        f"{et:.2f} mL, T2/FLAIR abnormality {flair:.2f} mL, whole abnormality context {wt:.2f} mL, "
        f"and resection/treatment cavity candidate {rc:.2f} mL."
    )
    impression = (
        "Automated glioma segmentation outputs are available for RANO-oriented radiologist review; "
        "verify the enhancing target lesion, T2/FLAIR context, and treatment-cavity exclusion before clinical use."
    )
    if warnings:
        impression += f" QC warnings: {'; '.join(warnings[:3])}."
    return {
        "findings": findings,
        "impression": impression,
        "copy_text": f"Findings: {findings}\nImpression: {impression}",
    }


def _flatten_metadata_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        pieces: list[str] = []
        for key, item in value.items():
            if key in {"7FE00010", "PixelData"}:
                continue
            pieces.append(str(key))
            pieces.append(_flatten_metadata_text(item))
        return " ".join(pieces)
    if isinstance(value, list):
        return " ".join(_flatten_metadata_text(item) for item in value[:40])
    return str(value)


def parse_volumes_csv(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


brain_tumor_demo_store = BrainTumorDemoStore()
