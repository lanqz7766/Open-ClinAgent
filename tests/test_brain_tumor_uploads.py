from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import io
import json
import sys
import zipfile

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    env_file = tmp_path / "test.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("CLINAGENT_ENV_FILE", str(env_file))
    monkeypatch.setenv("CLINAGENT_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("CLINAGENT_DATABASE_PATH", str(tmp_path / "state.sqlite3"))
    monkeypatch.setenv("CLINAGENT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CLINAGENT_LOCAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("CLINAGENT_BRAIN_TUMOR_UPLOAD_ROOT", str(tmp_path / "brain-tumor-uploads"))
    monkeypatch.setenv("CLINAGENT_BRAIN_TUMOR_ASSET_ROOT", str(tmp_path / "brain-tumor-assets"))
    monkeypatch.setenv("CLINAGENT_REQUIRE_USER_AUTH", "1")
    monkeypatch.setenv("CLINAGENT_ALLOW_SELF_REGISTRATION", "1")
    monkeypatch.setenv("CLINAGENT_PHYSICIAN_CURATED_ONLY", "1")
    monkeypatch.setenv("CLINAGENT_BRAIN_TUMOR_CURATED_CASE_IDS", "case-allowed")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-api-key")

    from clinagent.platform import config as platform_config

    monkeypatch.setattr(platform_config, "_loaded", False)
    monkeypatch.setattr(platform_config, "_env_file", None)
    from clinagent.gateway.server import create_app

    app, _, _ = create_app()
    return TestClient(app)


def _register(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "long secure password",
            "name": "Preview Reader",
            "organization": "Example Hospital",
            "role": "radiologist",
            "dua_accepted": True,
        },
    )
    assert response.status_code == 200
    return str(response.json()["user"]["id"])


def _nifti_payload(tmp_path: Path, name: str, *, affine_scale: float = 1.0) -> bytes:
    path = tmp_path / name
    affine = np.diag([affine_scale, affine_scale, affine_scale, 1.0])
    image = nib.Nifti1Image(np.ones((8, 9, 10), dtype=np.float32), affine)
    image.header["descrip"] = b"Patient Jane Doe MRN 123"
    image.header.extensions.append(nib.nifti1.Nifti1Extension(6, b"private metadata"))
    nib.save(image, str(path))
    return path.read_bytes()


def _upload_files(tmp_path: Path) -> dict[str, tuple[str, bytes, str]]:
    return {
        "t1n_file": ("patient_t1.nii.gz", _nifti_payload(tmp_path, "t1.nii.gz"), "application/gzip"),
        "t1c_file": ("patient_t1c.nii.gz", _nifti_payload(tmp_path, "t1c.nii.gz"), "application/gzip"),
        "t2w_file": ("patient_t2.nii.gz", _nifti_payload(tmp_path, "t2.nii.gz", affine_scale=1.2), "application/gzip"),
        "t2f_file": ("patient_flair.nii.gz", _nifti_payload(tmp_path, "flair.nii.gz"), "application/gzip"),
    }


def test_upload_is_streamed_sanitized_queued_and_owner_scoped(monkeypatch, tmp_path):
    client_one = _client(monkeypatch, tmp_path)
    client_two = TestClient(client_one.app)
    user_one = _register(client_one, "one@example.org")
    _register(client_two, "two@example.org")

    rejected = client_one.post(
        "/api/demo/brain-tumor/uploads",
        data={"deidentified_confirmed": "false"},
        files=_upload_files(tmp_path),
    )
    assert rejected.status_code == 422

    created = client_one.post(
        "/api/demo/brain-tumor/uploads",
        data={"deidentified_confirmed": "true"},
        files=_upload_files(tmp_path),
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    case_id = payload["case"]["id"]
    job_id = payload["job"]["job_id"]
    assert payload["job"]["status"] == "queued"
    assert payload["case"]["resample_to_t1c"] == ["t2w"]
    assert set(payload["case"]["modality_volume_urls"]) == {"t1n", "t1c", "t2w", "t2f"}
    assert payload["case"]["modality_volume_urls"]["t2f"].endswith("/modality/t2f/t2f.nii.gz")
    retention = datetime.fromisoformat(payload["case"]["expires_at"]) - datetime.now(UTC)
    assert 29.9 < retention.total_seconds() / 86400 <= 30.0

    upload_root = tmp_path / "brain-tumor-uploads" / case_id / "inputs"
    for modality in ("t1n", "t1c", "t2w", "t2f"):
        image = nib.load(str(upload_root / f"{modality}.nii.gz"))
        assert bytes(image.header["descrip"]).rstrip(b"\x00") == b""
        assert len(image.header.extensions) == 0

    assert client_one.get(f"/api/demo/brain-tumor/uploads/{case_id}/modality/t2f").status_code == 200
    assert client_two.get(f"/api/demo/brain-tumor/uploads/{case_id}/modality/t2f").status_code == 404
    assert client_two.get(f"/api/demo/brain-tumor/uploads/jobs/{job_id}").status_code == 404

    from clinagent.gateway.auth import ClinAgentAuthStore
    from clinagent.gateway.brain_tumor_worker import BrainTumorJobWorker

    class FakeDemoStore:
        asset_root = tmp_path / "brain-tumor-assets"

        @staticmethod
        def service_status():
            return {"ready": True}

        @staticmethod
        def analyze_nifti_paths(*, modality_paths, patient_label, source):
            assert set(modality_paths) == {"t1n", "t1c", "t2w", "t2f"}
            assert patient_label.startswith("Uploaded case ")
            assert source == {"type": "nifti_upload", "case_id": case_id}
            return {
                "ok": True,
                "session_id": "brain-tumor-uploaded",
                "patient_label": patient_label,
                "artifacts": {"seg": "/private/server/path/seg.nii.gz"},
                "modality_status": {"t1c": {"present": True, "path_name": "private-name.nii.gz"}},
                "service": {"remote_staging": {"enabled": True, "root": "/private/server/path"}},
            }

    FakeDemoStore.asset_root.mkdir(parents=True, exist_ok=True)
    worker = BrainTumorJobWorker(auth_store=ClinAgentAuthStore.from_env(), demo_store=FakeDemoStore())
    assert worker.run_once() is True
    completed = client_one.get(f"/api/demo/brain-tumor/uploads/jobs/{job_id}")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["session_id"] == "brain-tumor-uploaded"
    assert "artifacts" not in completed.json()["session"]
    assert completed.json()["session"]["modality_status"]["t1c"]["path_name"] == ""
    assert completed.json()["session"]["service"]["remote_staging"] == {"enabled": True}

    store = ClinAgentAuthStore.from_env()
    assert store.can_access_case(case_id="brain-tumor-uploaded", user_id=user_one) is True
    assert store.can_access_case(case_id="brain-tumor-uploaded", user_id=client_two.cookies.get("missing")) is False

    deleted = client_one.delete(f"/api/demo/brain-tumor/uploads/{case_id}")
    assert deleted.status_code == 200
    assert client_one.get(f"/api/demo/brain-tumor/uploads/{case_id}/modality/t2f").status_code == 404
    assert client_one.get("/api/demo/brain-tumor/uploads").json()["cases"] == []


def test_uploaded_session_uses_owner_scoped_modality_urls():
    from clinagent.families.neuro.brain_tumor_demo import _refresh_session_artifact_urls

    session = _refresh_session_artifact_urls(
        {
            "session_id": "brain-tumor-uploaded",
            "source": {"type": "nifti_upload", "case_id": "upload case/1"},
            "artifacts": {
                "seg": "/private/session/seg.nii.gz",
                "image_t1c": "/private/upload/t1c.nii.gz",
                "image_t2f": "/private/upload/t2f.nii.gz",
            },
        }
    )

    assert session["artifact_urls"]["seg"].endswith("/artifact/seg/seg.nii.gz")
    assert session["viewer_assets"]["modality_volume_urls"] == {
        "t1c": "/api/demo/brain-tumor/uploads/upload%20case%2F1/modality/t1c/t1c.nii.gz",
        "t2f": "/api/demo/brain-tumor/uploads/upload%20case%2F1/modality/t2f/t2f.nii.gz",
    }


def test_approved_example_download_is_authenticated_and_sanitized(monkeypatch, tmp_path):
    from clinagent.gateway.preview_examples import main

    output = tmp_path / "published"
    args = ["prepare-examples", "--output", str(output), "--id", "example_01", "--approved-deidentified"]
    for key in ("t1n", "t1c", "t2w", "t2f"):
        path = tmp_path / f"private_{key}.nii.gz"
        _nifti_payload(tmp_path, path.name)
        args += [f"--{key}", str(path)]
    monkeypatch.setattr(sys, "argv", args)
    main()
    monkeypatch.setenv("CLINAGENT_UPLOAD_EXAMPLES_ROOT", str(output))
    client = _client(monkeypatch, tmp_path)
    endpoint = "/api/demo/brain-tumor/upload-examples"
    assert client.get(endpoint).status_code == 401
    assert client.get(f"{endpoint}/example_01/download").status_code == 401
    _register(client, "example-reader@example.org")
    listing = client.get(endpoint).json()
    assert str(tmp_path) not in json.dumps(listing)
    assert listing["examples"][0]["visit_count"] == 1
    response = client.get(listing["examples"][0]["download_url"])
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert set(archive.namelist()) == {f"example_01/{name}" for name in ("T1.nii.gz", "T1c.nii.gz", "T2.nii.gz", "FLAIR.nii.gz", "README.txt")}
    guide = archive.read("example_01/README.txt").decode()
    assert "Drop this ZIP directly" in guide
    assert "Extract this ZIP archive" not in guide
    path = tmp_path / "downloaded.nii.gz"
    path.write_bytes(archive.read("example_01/T1.nii.gz"))
    image = nib.load(path)
    assert image.shape == (8, 9, 10)
    assert not bytes(image.header["descrip"]).strip(b"\0")
    assert len(image.header.extensions) == 0
    assert client.get(f"{endpoint}/unpublished/download").status_code == 404


def test_examples_do_not_publish_unlisted_files_or_follow_outside_symlinks(monkeypatch, tmp_path):
    from clinagent.gateway.preview_examples import example_archives

    root = tmp_path / "examples"
    root.mkdir()
    monkeypatch.setenv("CLINAGENT_UPLOAD_EXAMPLES_ROOT", str(root))
    (root / "unapproved.zip").write_bytes(b"not approved")
    assert example_archives() == []
    (root / "catalog.json").write_text(json.dumps({"examples": [{"id": "example_01"}]}))
    external = tmp_path / "private.zip"
    external.write_bytes(b"private")
    (root / "example_01.zip").symlink_to(external)
    with pytest.raises(ValueError):
        example_archives()


def test_feedback_validates_ownership_and_persists_only_expected_fields(monkeypatch, tmp_path):
    from clinagent.gateway.auth import ClinAgentAuthStore

    client = _client(monkeypatch, tmp_path)
    endpoint = "/api/demo/brain-tumor/feedback"
    payload = {"category": "suggestion", "workflow_step": "review", "comment": "Make the control easier to find."}
    assert client.post(endpoint, json=payload).status_code == 401
    user = _register(client, "feedback-one@example.org")
    store = ClinAgentAuthStore.from_env()
    store.register_case_access(case_id="test-owned", owner_user_id=user, source="nifti_upload")
    other = TestClient(client.app)
    _register(other, "feedback-two@example.org")
    assert other.post(endpoint, json={**payload, "case_id": "test-owned"}).status_code == 404
    assert client.post(endpoint, json={**payload, "screenshot": "unwanted"}).status_code == 422
    assert client.post(endpoint, json={**payload, "comment": " "}).status_code == 422
    assert client.post(endpoint, json={**payload, "comment": "x" * 2001}).status_code == 422
    result = client.post(endpoint, json={**payload, "case_id": "test-owned"})
    assert result.status_code == 200
    with store._connect() as conn:
        row = conn.execute("SELECT * FROM feedback WHERE id = ?", (result.json()["feedback_id"],)).fetchone()
    assert row["owner_user_id"] == user
    assert row["case_id"] == "test-owned"
    assert row["comment"] == payload["comment"]


def test_external_report_prompt_excludes_identifiers_and_free_text():
    from clinagent.gateway.server import _build_brain_tumor_report_prompt

    prompt = _build_brain_tumor_report_prompt(
        {
            "session_id": "secret-session-id",
            "case_label": "Jane Doe MRN 123",
            "date": "2026-08-17",
            "findings": "Jane Doe filename patient_t1c.nii.gz",
            "impression": "Private clinical text",
            "qc_state": "QC passed",
            "qc_reasons": ["Image quality issue", "Jane Doe"],
            "active_measurements": {"case_id": "secret-case", "label": "Jane Doe", "ET_mm3": 1234},
            "timepoints": [
                {
                    "case_id": "secret-visit",
                    "label": "Jane Doe",
                    "date": "2026-08-17",
                    "registration_status": "private text",
                    "ET_mm3": 1234,
                    "ET_change_pct": 4.5,
                }
            ],
        }
    )

    assert "1234" in prompt
    assert "4.5" in prompt
    for private_value in (
        "secret-session-id",
        "Jane Doe",
        "MRN 123",
        "patient_t1c.nii.gz",
        "Private clinical text",
        "secret-case",
        "secret-visit",
        "2026-08-17",
        "private text",
    ):
        assert private_value not in prompt


def test_external_report_prompt_excludes_scan_dates_and_visit_intervals():
    from clinagent.gateway.server import _build_brain_tumor_report_prompt

    row = {"scan_date": "2024-02-29", "interval_days": 987, "days_from_reference": 654, "ET_mm3": 1234}
    prompt = _build_brain_tumor_report_prompt({"active_measurements": row, "timepoints": [row]})
    assert "1234" in prompt
    for private_value in ("2024-02-29", "987", "654", "scan_date", "interval_days", "days_from_reference"):
        assert private_value not in prompt
