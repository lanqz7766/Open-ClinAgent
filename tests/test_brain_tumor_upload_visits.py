from __future__ import annotations

import json
import sys
import zipfile

import pytest

from fastapi.testclient import TestClient

from tests.test_brain_tumor_uploads import _client, _register, _upload_files


def _batch(tmp_path, dates):
    parts, rows = [], []
    for value in dates:
        mapping = {}
        for key, payload in _upload_files(tmp_path).items():
            mapping[key.removesuffix("_file")] = len(parts)
            parts.append(("files", payload))
        rows.append({"date": value, "files": mapping})
    return {"deidentified_confirmed": "true", "same_patient_confirmed": "true", "visits_json": json.dumps(rows)}, parts


def test_verified_relative_timing_survives_upload_restore_and_job_serialization(monkeypatch, tmp_path):
    from clinagent.gateway.brain_tumor_uploads import read_upload_manifest
    from clinagent.gateway.brain_tumor_upload_visits import write_manifest, upload_result

    client = _client(monkeypatch, tmp_path)
    _register(client, "timing@example.org")
    data, files = _batch(tmp_path, [None])
    response = client.post("/api/demo/brain-tumor/uploads", data=data, files=files)
    assert response.status_code == 200
    case_id = response.json()["case"]["id"]
    manifest = read_upload_manifest(case_id)
    manifest["visits"][0].update(relative_day=56.40625, relative_day_origin="first scan")
    write_manifest(manifest)
    restored = client.get("/api/demo/brain-tumor/uploads").json()["cases"][0]["visits"][0]
    assert restored["date"] is None
    assert restored["relative_day"] == 56.40625
    assert restored["relative_day_origin"] == "first scan"
    result = upload_result(manifest, status="queued", stage="queued")
    assert result["visits"][0]["relative_day"] == 56.40625


class FakeVisits:
    def __init__(self, root):
        self.asset_root = root
        root.mkdir(exist_ok=True)
        self.calls = []
        self.fail_visit = None

    def service_status(self):
        return {"ready": True}

    def analyze_nifti_paths(self, *, modality_paths, patient_label, source):
        visit = source.get("visit_id", "visit_01")
        self.calls.append(visit)
        if visit == self.fail_visit:
            raise RuntimeError("test failure")
        session_id = f"brain-tumor-{visit}"
        (self.asset_root / session_id).mkdir(exist_ok=True)
        return {"session_id": session_id, "patient_label": patient_label,
                "volumes": [{"region": "enhancing_tumor", "volume_ml": len(self.calls)}],
                "artifacts": {"seg": "/private/path/seg.nii.gz"}, "source": source}


def test_three_visit_upload_partial_retry_append_and_owner_isolation(monkeypatch, tmp_path):
    from clinagent.gateway.auth import ClinAgentAuthStore
    from clinagent.gateway.brain_tumor_worker import BrainTumorJobWorker

    client = _client(monkeypatch, tmp_path)
    other = TestClient(client.app)
    owner = _register(client, "one@example.org")
    _register(other, "two@example.org")
    data, files = _batch(tmp_path, ["2026-01-10", "2026-03-10", None])
    response = client.post("/api/demo/brain-tumor/uploads", data=data, files=files)
    assert response.status_code == 200, response.text
    case = response.json()["case"]
    assert case["visit_count"] == 3
    assert response.json()["job"]["total_count"] == 3
    assert [v["date"] for v in case["visits"]] == ["2026-01-10", "2026-03-10", None]
    paths = [v["modality_volume_urls"]["t1c"] for v in case["visits"]]
    assert len(set(paths)) == 3
    for path in paths:
        assert client.get(path).status_code == 200
        assert other.get(path).status_code == 404
    append_data, append_files = _batch(tmp_path, ["2026-04-01"])
    append_data["target_case_id"] = case["id"]
    assert other.post("/api/demo/brain-tumor/uploads", data=append_data, files=append_files).status_code == 404
    assert client.post("/api/demo/brain-tumor/uploads", data=append_data, files=append_files).status_code == 422

    store = ClinAgentAuthStore.from_env()
    model = FakeVisits(tmp_path / "brain-tumor-assets")
    monkeypatch.setattr("clinagent.gateway.server._get_brain_tumor_demo_store", lambda: model)
    worker = BrainTumorJobWorker(auth_store=store, demo_store=model)
    model.fail_visit = "visit_02"
    assert worker.run_once()
    job_id = response.json()["job"]["job_id"]
    result = client.get(f"/api/demo/brain-tumor/uploads/jobs/{job_id}").json()
    assert result["status"] == "failed"
    assert result["completed_count"] == 2
    assert result["failed_count"] == 1
    assert "artifacts" not in result["visits"][0]["session"]
    assert store.can_access_case(case_id="brain-tumor-visit_03", user_id=owner)
    assert client.get("/api/demo/brain-tumor/uploads").json()["cases"][0]["visits"][2]["session_id"] == "brain-tumor-visit_03"

    model.fail_visit = None
    retried = client.post(f"/api/demo/brain-tumor/uploads/{case['id']}/retry")
    assert retried.json()["total_count"] == 3
    assert worker.run_once()
    assert model.calls == ["visit_01", "visit_02", "visit_03", "visit_02"]
    retried_job = client.get(f"/api/demo/brain-tumor/uploads/jobs/{retried.json()['job_id']}").json()
    assert retried_job["status"] == "completed" and retried_job["completed_count"] == 3

    appended = client.post("/api/demo/brain-tumor/uploads", data=append_data, files=append_files)
    assert appended.status_code == 200, appended.text
    assert appended.json()["case"]["id"] == case["id"]
    assert appended.json()["case"]["visit_count"] == 4
    assert appended.json()["case"]["expires_at"] == case["expires_at"]
    assert worker.run_once()
    assert model.calls[-1] == "visit_04" and len(model.calls) == 5
    assert len(client.get("/api/demo/brain-tumor/uploads").json()["cases"]) == 1
    assert client.delete(f"/api/demo/brain-tumor/uploads/{case['id']}").status_code == 200
    assert not list(model.asset_root.iterdir())
    for index in range(1, 5):
        assert not store.can_access_case(case_id=f"brain-tumor-visit_0{index}", user_id=owner)


def test_bad_mapping_dates_and_patient_confirmation_create_nothing(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    _register(client, "validate@example.org")
    endpoint = "/api/demo/brain-tumor/uploads"
    for dates in (["2026-03-01", "2026-02-01"], ["2026-02-30"], ["not-a-date"]):
        data, files = _batch(tmp_path, dates)
        response = client.post(endpoint, data=data, files=files)
        assert response.status_code == 422, response.text
    data, files = _batch(tmp_path, [None, None])
    data["same_patient_confirmed"] = "false"
    assert client.post(endpoint, data=data, files=files).status_code == 422
    data["same_patient_confirmed"] = "true"
    rows = json.loads(data["visits_json"])
    rows[1]["files"]["t1c"] = 0
    data["visits_json"] = json.dumps(rows)
    assert client.post(endpoint, data=data, files=files).status_code == 422
    assert client.get(endpoint).json()["cases"] == []


def test_invalid_later_visit_does_not_leave_a_partial_case(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    _register(client, "broken@example.org")
    data, files = _batch(tmp_path, [None, None, None])
    files[-1] = ("files", ("broken.nii.gz", b"not a nifti", "application/gzip"))
    response = client.post("/api/demo/brain-tumor/uploads", data=data, files=files)
    assert response.status_code == 422
    assert client.get("/api/demo/brain-tumor/uploads").json()["cases"] == []
    assert not list((tmp_path / "brain-tumor-uploads").glob("upload_*"))


def test_session_urls_include_followup_visit():
    from clinagent.families.neuro.brain_tumor_demo import _refresh_session_artifact_urls
    session = _refresh_session_artifact_urls({"session_id": "test", "source": {"type": "nifti_upload", "case_id": "upload_test", "visit_id": "visit_03"},
        "artifacts": {"image_t1c": "/private/t1c.nii.gz"}})
    assert session["viewer_assets"]["modality_volume_urls"]["t1c"] == "/api/demo/brain-tumor/uploads/upload_test/visits/visit_03/modality/t1c/t1c.nii.gz"


def test_worker_restart_resumes_unfinished_visits_and_retention_removes_all(monkeypatch, tmp_path):
    from clinagent.gateway.auth import ClinAgentAuthStore
    from clinagent.gateway.brain_tumor_worker import BrainTumorJobWorker
    client = _client(monkeypatch, tmp_path)
    owner = _register(client, "restart@example.org")
    data, files = _batch(tmp_path, [None, None, None])
    response = client.post("/api/demo/brain-tumor/uploads", data=data, files=files).json()
    store = ClinAgentAuthStore.from_env()
    model = FakeVisits(tmp_path / "brain-tumor-assets")
    original = model.analyze_nifti_paths
    def interrupted(**kwargs):
        if kwargs["source"].get("visit_id") == "visit_02":
            raise KeyboardInterrupt("Simulated worker exit")
        return original(**kwargs)
    model.analyze_nifti_paths = interrupted
    worker = BrainTumorJobWorker(auth_store=store, demo_store=model)
    with pytest.raises(KeyboardInterrupt):
        worker.run_once()
    restored = client.get("/api/demo/brain-tumor/uploads").json()["cases"][0]
    assert restored["visits"][0]["status"] == "complete"
    assert restored["visits"][0]["session_id"] == "brain-tumor-visit_01"
    model.analyze_nifti_paths = original
    assert worker.recover() == 1
    assert worker.run_once()
    assert model.calls == ["visit_01", "visit_02", "visit_03"]
    with store._connect() as conn:
        conn.execute("UPDATE owned_cases SET expires_at = ? WHERE owner_user_id = ?", ("2000-01-01T00:00:00+00:00", owner))
    assert worker.cleanup_expired_uploads() == 1
    assert not list(model.asset_root.iterdir())
    assert client.get(response["case"]["visits"][2]["modality_volume_urls"]["t1c"]).status_code == 404


def test_publish_longitudinal_example_preserves_grouping_not_private_names(monkeypatch, tmp_path):
    from clinagent.gateway.preview_examples import main, example_archives
    _upload_files(tmp_path)
    output = tmp_path / "published"
    args = ["prepare-examples", "--output", str(output), "--id", "example_04", "--approved-deidentified"]
    for _ in range(3):
        args += ["--visit", *[str(tmp_path / name) for name in ("t1.nii.gz", "t1c.nii.gz", "t2.nii.gz", "flair.nii.gz")]]
    monkeypatch.setattr(sys, "argv", args)
    main()
    monkeypatch.setenv("CLINAGENT_UPLOAD_EXAMPLES_ROOT", str(output))
    row, path = example_archives()[0]
    assert row["visit_count"] == 3 and row["file_count"] == 12
    with zipfile.ZipFile(path) as archive:
        assert len([name for name in archive.namelist() if name.endswith(".nii.gz")]) == 12
        for index in range(1, 4):
            assert f"example_04/visit_0{index}/T1c.nii.gz" in archive.namelist()
