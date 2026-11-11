from __future__ import annotations

import argparse
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from clinagent.families.neuro.brain_tumor_demo import BrainTumorDemoStore
from clinagent.gateway.auth import ClinAgentAuthStore
from clinagent.gateway.brain_tumor_uploads import UPLOAD_JOB_TYPE, read_upload_manifest, remove_upload_case, upload_root


REGISTRY_JOB_TYPE = "brain_tumor_registry_segment"
JOB_TYPE = REGISTRY_JOB_TYPE


class BrainTumorJobWorker:
    def __init__(
        self,
        *,
        auth_store: ClinAgentAuthStore | None = None,
        demo_store: BrainTumorDemoStore | None = None,
    ) -> None:
        self.auth_store = auth_store or ClinAgentAuthStore.from_env()
        self.demo_store = demo_store or BrainTumorDemoStore()

    def recover(self) -> int:
        return sum(
            self.auth_store.recover_running_jobs(job_type=job_type)
            for job_type in (UPLOAD_JOB_TYPE, REGISTRY_JOB_TYPE)
        )

    def service_ready(self) -> bool:
        status_fn = getattr(self.demo_store, "service_status", None)
        if not callable(status_fn):
            return True
        status = status_fn()
        return bool(status.get("ready"))

    def _register_result_sessions(self, *, job: dict[str, Any], result: dict[str, Any]) -> None:
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        case_id = str(payload.get("case_id") or result.get("case_id") or "").strip()
        force_rerun = bool(payload.get("force_rerun"))
        owner_user_id = str(job.get("owner_user_id") or "").strip() or None
        source_type = "curated_registry_rerun" if force_rerun else "curated_registry"
        for visit in result.get("visits", []):
            if not isinstance(visit, dict) or visit.get("status") != "complete":
                continue
            session = visit.get("session") if isinstance(visit.get("session"), dict) else {}
            session_id = str(session.get("session_id") or "").strip()
            if not session_id or not case_id:
                continue
            self.auth_store.register_case_access(
                case_id=session_id,
                owner_user_id=owner_user_id if force_rerun else None,
                source=f"{source_type}:{case_id}",
                shared=not force_rerun,
            )

    def run_once(self) -> bool:
        job_type = next(
            (candidate for candidate in (UPLOAD_JOB_TYPE, REGISTRY_JOB_TYPE) if self.auth_store.has_queued_job(job_type=candidate)),
            None,
        )
        if job_type is None:
            return False
        if not self.service_ready():
            return False
        job = self.auth_store.claim_next_job(job_type=job_type)
        if job is None:
            return False
        if job_type == UPLOAD_JOB_TYPE:
            try:
                return self._run_upload_job(job)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                previous = self.auth_store.get_job(job_id=str(job["id"])) or job
                result = dict(previous.get("result") or {})
                message = "Upload processing was interrupted. Retry to resume unfinished visits."
                result.update(ok=False, status="failed", stage="failed", error=message)
                self.auth_store.update_job(job_id=str(job["id"]), status="failed", stage="failed",
                    result=result, error_message=message)
                return True

        job_id = str(job["id"])
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        case_id = str(payload.get("case_id") or "").strip()
        timepoint_ids = payload.get("timepoint_ids")
        normalized_timepoints = [str(item) for item in timepoint_ids] if isinstance(timepoint_ids, list) else None
        force_rerun = bool(payload.get("force_rerun"))

        def on_progress(stage: str, result: dict[str, Any]) -> None:
            self._register_result_sessions(job=job, result=result)
            self.auth_store.update_job(job_id=job_id, status="running", stage=stage, result=result)

        try:
            result = self.demo_store.run_registry_segment_job(
                job_id=job_id,
                case_id=case_id,
                timepoint_ids=normalized_timepoints,
                force_rerun=force_rerun,
                on_progress=on_progress,
            )
            self._register_result_sessions(job=job, result=result)
            final_status = str(result.get("status") or "completed")
            self.auth_store.update_job(
                job_id=job_id,
                status=final_status,
                stage=str(result.get("stage") or "complete"),
                result=result,
            )
        except Exception:
            traceback.print_exc(file=sys.stderr)
            previous = self.auth_store.get_job(job_id=job_id) or job
            result = previous.get("result") if isinstance(previous.get("result"), dict) else {}
            result.update(
                {
                    "ok": False,
                    "job_id": job_id,
                    "case_id": case_id,
                    "status": "failed",
                    "stage": "failed",
                    "error": "Segmentation could not be completed. Please retry or contact the preview administrator.",
                }
            )
            self.auth_store.update_job(
                job_id=job_id,
                status="failed",
                stage="failed",
                result=result,
                error_message="Segmentation worker failed; see worker logs for details.",
            )
        return True

    def _run_upload_job(self, job: dict[str, Any]) -> bool:
        from clinagent.gateway.brain_tumor_upload_visits import manifest_visits, upload_result, visit_input_root, write_manifest

        job_id = str(job["id"])
        case_id = str(job["case_id"])
        owner = str(job["owner_user_id"])
        manifest = read_upload_manifest(case_id)
        if manifest is None or not self.auth_store.can_access_case(case_id=case_id, user_id=owner):
            self.auth_store.update_job(job_id=job_id, status="failed", stage="failed", error_message="Uploaded case is no longer available.")
            return True
        visits = manifest_visits(manifest, job)
        manifest["visits"] = visits
        for index, visit in enumerate(visits):
            if visit.get("status") == "complete":
                if not visit.get("session") and visit.get("session_id"):
                    visit["session"] = self.demo_store.get_session(visit["session_id"])
                continue
            if not self.auth_store.can_access_case(case_id=case_id, user_id=owner):
                self.auth_store.update_job(job_id=job_id, status="failed", stage="failed", error_message="Uploaded case was deleted.")
                return True
            visit["status"] = "running"
            progress = upload_result(manifest, status="running", stage="segmenting")
            progress["active_visit_index"] = index + 1
            self.auth_store.update_job(job_id=job_id, status="running", stage="segmenting", result=progress)
            session_id = ""
            try:
                paths = {key: str(visit_input_root(case_id, visit["id"]) / f"{key}.nii.gz") for key in ("t1n", "t1c", "t2w", "t2f")}
                case_root = (upload_root() / case_id).resolve()
                if any(case_root not in Path(path).resolve().parents or not Path(path).is_file() for path in paths.values()):
                    raise ValueError("An uploaded modality is missing or outside this case.")
                source = {"type": "nifti_upload", "case_id": case_id}
                if visit["id"] != "visit_01":
                    source["visit_id"] = visit["id"]
                session = self.demo_store.analyze_nifti_paths(
                    modality_paths=paths, patient_label=manifest["display_label"], source=source,
                )
                session_id = str(session.get("session_id") or "")
                if not session_id:
                    raise RuntimeError("Segmentation returned no session identifier.")
                if not self.auth_store.can_access_case(case_id=case_id, user_id=owner):
                    shutil.rmtree(self.demo_store.asset_root / session_id, ignore_errors=True)
                    raise ValueError("The uploaded case was deleted during segmentation.")
                self.auth_store.register_case_access(case_id=session_id, owner_user_id=owner,
                    source=f"nifti_upload:{case_id}", expires_at=manifest["expires_at"])
                visit.update(status="complete", session_id=session_id, session=session)
                visit.pop("error", None)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                visit.update(status="failed", error="Segmentation failed. Check the modalities and retry.")
            if not self.auth_store.can_access_case(case_id=case_id, user_id=owner):
                self.auth_store.update_job(job_id=job_id, status="failed", stage="failed", error_message="Uploaded case was deleted.")
                return True
            write_manifest(manifest)
            progress = upload_result(manifest, status="running", stage="segmenting")
            progress["active_visit_index"] = index + 1
            self.auth_store.update_job(job_id=job_id, status="running", stage="segmenting", result=progress)
        failed = any(visit.get("status") != "complete" for visit in visits)
        status, stage = ("failed", "failed") if failed else ("completed", "complete")
        result = upload_result(manifest, status=status, stage=stage)
        if failed:
            result["error"] = "Some visits could not be segmented. Completed visits are retained; retry runs unfinished visits only."
        manifest["status"] = status
        if len(visits) == 1:
            manifest["session_id"] = visits[0].get("session_id")
        write_manifest(manifest)
        self.auth_store.update_job(job_id=job_id, status=status, stage=stage, result=result,
            error_message=result.get("error"))
        return True

    def cleanup_expired_uploads(self) -> int:
        removed = 0
        for case in self.auth_store.list_expired_cases(source="nifti_upload"):
            case_id = str(case.get("id") or "")
            if not case_id:
                continue
            if self.auth_store.mark_case_deleted(case_id=case_id):
                from clinagent.gateway.brain_tumor_upload_visits import remove_upload_sessions
                remove_upload_sessions(auth_store=self.auth_store, demo_store=self.demo_store,
                    case_id=case_id, owner_user_id=str(case.get("owner_user_id") or ""))
                remove_upload_case(case_id)
                removed += 1
        return removed

    def run_forever(self, *, poll_seconds: float = 1.0) -> None:
        recovered = self.recover()
        if recovered:
            print(f"Recovered {recovered} interrupted brain tumor job(s).", flush=True)
        cleanup_deadline = 0.0
        while True:
            now = time.monotonic()
            if now >= cleanup_deadline:
                removed = self.cleanup_expired_uploads()
                if removed:
                    print(f"Removed {removed} expired uploaded case(s).", flush=True)
                cleanup_deadline = now + 3600
            if not self.run_once():
                time.sleep(max(0.1, poll_seconds))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ClinAgent brain tumor segmentation queue worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit")
    parser.add_argument("--poll-seconds", type=float, default=1.0, help="Idle queue polling interval")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    worker = BrainTumorJobWorker()
    if args.once:
        worker.recover()
        return 0 if worker.run_once() else 1
    worker.run_forever(poll_seconds=args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
