from __future__ import annotations

from pathlib import Path

from clinagent.gateway.auth import ClinAgentAuthStore
from clinagent.gateway.brain_tumor_worker import BrainTumorJobWorker, JOB_TYPE


def _user(store: ClinAgentAuthStore) -> dict:
    return store.create_user(
        email="worker@example.org",
        password="long secure password",
        name="Worker Reader",
        organization="Example Hospital",
        role="radiologist",
        dua_accepted=True,
    )


def test_worker_completes_job_and_keeps_rerun_result_user_scoped(tmp_path: Path) -> None:
    auth_store = ClinAgentAuthStore(tmp_path / "auth.sqlite3", allow_self_registration=True)
    user = _user(auth_store)
    initial_result = {
        "ok": True,
        "job_id": "gbmseg_test",
        "case_id": "case-allowed",
        "status": "queued",
        "stage": "queued",
        "total_count": 1,
        "completed_count": 0,
        "failed_count": 0,
        "visits": [{"timepoint_id": "visit-2", "status": "queued"}],
        "force_rerun": True,
    }
    auth_store.create_queued_job(
        user_id=user["id"],
        job_type=JOB_TYPE,
        job_id="gbmseg_test",
        payload={"case_id": "case-allowed", "timepoint_ids": ["visit-2"], "force_rerun": True},
        initial_result=initial_result,
    )

    class FakeDemoStore:
        @staticmethod
        def run_registry_segment_job(*, job_id, case_id, timepoint_ids, force_rerun, on_progress):
            assert job_id == "gbmseg_test"
            assert case_id == "case-allowed"
            assert timepoint_ids == ["visit-2"]
            assert force_rerun is True
            running = {
                **initial_result,
                "status": "running",
                "stage": "segmenting",
                "visits": [{"timepoint_id": "visit-2", "status": "running"}],
            }
            on_progress("segmenting", running)
            completed = {
                **initial_result,
                "status": "completed",
                "stage": "complete",
                "completed_count": 1,
                "visits": [
                    {
                        "timepoint_id": "visit-2",
                        "status": "complete",
                        "session": {"session_id": "private-rerun-session"},
                        "point": {"id": "private-rerun-session", "timepointId": "visit-2"},
                    }
                ],
            }
            on_progress("complete", completed)
            return completed

    worker = BrainTumorJobWorker(auth_store=auth_store, demo_store=FakeDemoStore())
    assert worker.run_once() is True

    job = auth_store.get_job(job_id="gbmseg_test")
    assert job is not None
    assert job["status"] == "completed"
    assert job["stage"] == "complete"
    assert job["result"]["completed_count"] == 1

    access = auth_store.get_case_access(case_id="private-rerun-session")
    assert access is not None
    assert access["shared"] is False
    assert access["owner_user_id"] == user["id"]
    assert access["source"] == "curated_registry_rerun:case-allowed"
    assert auth_store.can_access_case(case_id="private-rerun-session", user_id=user["id"]) is True
    assert auth_store.can_access_case(case_id="private-rerun-session", user_id="different-user") is False

    assert worker.run_once() is False


def test_worker_leaves_job_queued_until_model_service_is_ready(tmp_path: Path) -> None:
    auth_store = ClinAgentAuthStore(tmp_path / "auth.sqlite3", allow_self_registration=True)
    user = _user(auth_store)
    auth_store.create_queued_job(
        user_id=user["id"],
        job_type=JOB_TYPE,
        job_id="gbmseg_waiting",
        payload={"case_id": "case-allowed", "timepoint_ids": ["visit-1"], "force_rerun": True},
    )

    class WarmingDemoStore:
        @staticmethod
        def service_status():
            return {"ok": False, "ready": False, "service_url_configured": True}

    worker = BrainTumorJobWorker(auth_store=auth_store, demo_store=WarmingDemoStore())
    assert worker.run_once() is False
    job = auth_store.get_job(job_id="gbmseg_waiting")
    assert job is not None
    assert job["status"] == "queued"
    assert job["started_at"] is None
