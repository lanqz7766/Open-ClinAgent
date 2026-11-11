from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def test_gateway_bind_host_uses_explicit_or_environment_value(monkeypatch):
    from clinagent.gateway.server import _gateway_bind_host

    monkeypatch.setenv("CLINAGENT_HOST", "127.0.0.1")
    assert _gateway_bind_host() == "127.0.0.1"
    assert _gateway_bind_host("0.0.0.0") == "0.0.0.0"


def test_installed_gateway_writes_only_to_workspace_and_honors_cors(monkeypatch, tmp_path):
    from clinagent.gateway import server

    monkeypatch.setattr(server, "workspace_root", lambda: tmp_path)
    monkeypatch.setenv("CLINAGENT_CORS_ORIGINS", "https://preview.example.org")
    client = _build_client(monkeypatch, tmp_path, require_auth=True)
    assert (tmp_path / ".clinagent/derived/neuro_longitudinal").is_dir()
    response = client.options("/api/auth/login", headers={
        "Origin": "https://preview.example.org", "Access-Control-Request-Method": "POST",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://preview.example.org"
    assert client.post("/api/auth/login", headers={"Origin": "https://untrusted.example.org"}, json={}).status_code == 403


def _build_client(
    monkeypatch,
    tmp_path,
    *,
    require_auth: bool = False,
    local_reset: bool = False,
    self_registration: bool = True,
    preview_scope: str = "",
    curated_only: bool = False,
    curated_case_ids: str = "",
) -> TestClient:
    env_file = tmp_path / "test.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("CLINAGENT_ENV_FILE", str(env_file))
    monkeypatch.setenv("CLINAGENT_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("CLINAGENT_DATABASE_PATH", str(tmp_path / "state.sqlite3"))
    monkeypatch.setenv("CLINAGENT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CLINAGENT_LOCAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("CLINAGENT_REQUIRE_USER_AUTH", "1" if require_auth else "0")
    monkeypatch.setenv("CLINAGENT_ALLOW_SELF_REGISTRATION", "1" if self_registration else "0")
    monkeypatch.setenv("CLINAGENT_AUTH_ALLOW_LOCAL_PASSWORD_RESET", "1" if local_reset else "0")
    monkeypatch.setenv("CLINAGENT_PREVIEW_SCOPE", preview_scope)
    monkeypatch.setenv("CLINAGENT_PHYSICIAN_CURATED_ONLY", "1" if curated_only else "0")
    monkeypatch.setenv("CLINAGENT_BRAIN_TUMOR_CURATED_CASE_IDS", curated_case_ids)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-api-key")

    from clinagent.platform import config as platform_config

    monkeypatch.setattr(platform_config, "_loaded", False)
    monkeypatch.setattr(platform_config, "_env_file", None)

    from clinagent.gateway.server import create_app

    app, _, _ = create_app()
    return TestClient(app)


def test_register_sets_session_and_records_dua(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/auth/register",
        json={
            "email": "radiologist@example.org",
            "password": "correct horse battery",
            "name": "Clinical User",
            "organization": "Example Hospital",
            "role": "radiologist",
            "dua_accepted": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["user"]["email"] == "radiologist@example.org"
    assert payload["user"]["dua_version"] == "clinagent-dua-v1"

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["user"]["email"] == "radiologist@example.org"

    audit_response = client.get("/api/auth/audit/recent")
    assert audit_response.status_code == 200
    actions = [event["action"] for event in audit_response.json()["events"]]
    assert "account_registered" in actions


def test_required_user_auth_blocks_protected_demo_api_until_login(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path, require_auth=True)

    blocked = client.get("/api/demo/workspace")
    assert blocked.status_code == 401

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "reader@example.org",
            "password": "long secure password",
            "name": "Reader",
            "organization": "Example Hospital",
            "role": "resident",
            "dua_accepted": True,
        },
    )
    assert register_response.status_code == 200

    allowed = client.get("/api/version")
    assert allowed.status_code == 200


def test_version_endpoint_is_protected_and_reports_release_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("CLINAGENT_BUILD_GIT_COMMIT", "abc123")
    monkeypatch.setenv("CLINAGENT_RELEASE_ID", "preview-abc123")
    monkeypatch.setenv("CLINAGENT_BUILD_TIME", "2026-08-12T12:00:00Z")
    client = _build_client(monkeypatch, tmp_path, require_auth=True)

    blocked = client.get("/api/version")
    assert blocked.status_code == 401

    registered = client.post(
        "/api/auth/register",
        json={
            "email": "version@example.org",
            "password": "long secure password",
            "name": "Version Reader",
            "organization": "Example Hospital",
            "role": "radiologist",
            "dua_accepted": True,
        },
    )
    assert registered.status_code == 200

    response = client.get("/api/version")
    assert response.status_code == 200
    payload = response.json()
    assert payload["git_commit"] == "abc123"
    assert payload["release_id"] == "preview-abc123"
    assert payload["build_time"] == "2026-08-12T12:00:00Z"
    assert payload["auth_schema_version"] == 4
    assert "server_time" in payload


def test_invitation_registration_is_single_use_and_disables_self_registration(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path, require_auth=True, self_registration=False)

    from clinagent.gateway.auth import ClinAgentAuthStore

    store = ClinAgentAuthStore.from_env()
    invitation, token = store.create_invitation(
        email="invited@example.org",
        name="Invited Reader",
        organization="Example Hospital",
        role="radiologist",
    )
    assert invitation["email"] == "invited@example.org"

    blocked = client.post(
        "/api/auth/register",
        json={
            "email": "walkin@example.org",
            "password": "long secure password",
            "name": "Walk In",
            "organization": "Example Hospital",
            "role": "radiologist",
            "dua_accepted": True,
        },
    )
    assert blocked.status_code == 400

    summary = client.get(f"/api/auth/invitations/{token}")
    assert summary.status_code == 200
    assert summary.json()["invitation"]["name"] == "Invited Reader"

    accepted = client.post(
        "/api/auth/invitations/accept",
        json={"token": token, "password": "invited secure password", "dua_accepted": True},
    )
    assert accepted.status_code == 200
    assert accepted.json()["user"]["email_verified_at"]

    reused = client.post(
        "/api/auth/invitations/accept",
        json={"token": token, "password": "another secure password", "dua_accepted": True},
    )
    assert reused.status_code == 400


def test_auth_store_migrates_existing_v1_database(monkeypatch, tmp_path):
    db_path = tmp_path / "auth.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                organization TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT 'radiologist',
                password_hash TEXT NOT NULL, password_salt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active', dua_version TEXT NOT NULL,
                dua_accepted_at TEXT NOT NULL, created_at TEXT NOT NULL, last_login_at TEXT
            );
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT,
                ip_address TEXT, user_agent TEXT
            );
            CREATE TABLE audit_events (
                id TEXT PRIMARY KEY, user_id TEXT, action TEXT NOT NULL, resource TEXT NOT NULL,
                status TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
                ip_address TEXT, user_agent TEXT
            );
            CREATE TABLE password_reset_tokens (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT,
                ip_address TEXT, user_agent TEXT
            );
            """
        )
    monkeypatch.setenv("CLINAGENT_AUTH_DB", str(db_path))

    from clinagent.gateway.auth import ClinAgentAuthStore

    store = ClinAgentAuthStore.from_env()
    assert store.schema_version == 4
    with sqlite3.connect(db_path) as conn:
        user_columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        session_columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        job_columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "email_verified_at" in user_columns
    assert "last_seen_at" in session_columns
    assert {"status", "stage", "payload_json", "result_json", "updated_at", "completed_at"} <= job_columns
    assert {"invitations", "owned_cases", "case_assets", "jobs", "feedback"} <= tables


def test_durable_job_queue_limits_one_active_job_per_user_and_recovers(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    registered = client.post(
        "/api/auth/register",
        json={
            "email": "queue@example.org",
            "password": "long secure password",
            "name": "Queue Reader",
            "organization": "Example Hospital",
            "role": "radiologist",
            "dua_accepted": True,
        },
    )
    user_id = registered.json()["user"]["id"]

    from clinagent.gateway.auth import ClinAgentAuthStore

    store = ClinAgentAuthStore.from_env()
    first, first_created = store.create_queued_job(
        user_id=user_id,
        job_type="brain_tumor_registry_segment",
        job_id="job-first",
        payload={"case_id": "case-one"},
        initial_result={"job_id": "job-first", "case_id": "case-one", "visits": []},
    )
    duplicate, duplicate_created = store.create_queued_job(
        user_id=user_id,
        job_type="brain_tumor_registry_segment",
        job_id="job-second",
        payload={"case_id": "case-two"},
    )
    assert first_created is True
    assert duplicate_created is False
    assert duplicate["id"] == first["id"] == "job-first"

    claimed = store.claim_next_job(job_type="brain_tumor_registry_segment")
    assert claimed is not None
    assert claimed["status"] == "running"
    assert store.recover_running_jobs(job_type="brain_tumor_registry_segment") == 1
    recovered = store.get_job(job_id="job-first")
    assert recovered is not None
    assert recovered["status"] == "queued"
    assert recovered["stage"] == "queued"

    store.claim_next_job(job_type="brain_tumor_registry_segment")
    completed = store.update_job(
        job_id="job-first",
        status="completed",
        stage="complete",
        result={"ok": True, "visits": []},
    )
    assert completed["completed_at"]
    second, second_created = store.create_queued_job(
        user_id=user_id,
        job_type="brain_tumor_registry_segment",
        job_id="job-second",
        payload={"case_id": "case-two"},
    )
    assert second_created is True
    assert second["id"] == "job-second"


def test_login_rate_limit_returns_429(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    for _ in range(8):
        response = client.post("/api/auth/login", json={"email": "missing@example.org", "password": "incorrect"})
        assert response.status_code == 401
    limited = client.post("/api/auth/login", json={"email": "missing@example.org", "password": "incorrect"})
    assert limited.status_code == 429


def test_brain_tumor_session_access_is_owner_scoped(monkeypatch, tmp_path):
    client_one = _build_client(monkeypatch, tmp_path, require_auth=True)
    client_two = TestClient(client_one.app)

    def register(client: TestClient, email: str) -> str:
        response = client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "long secure password",
                "name": email.split("@", 1)[0],
                "organization": "Example Hospital",
                "role": "radiologist",
                "dua_accepted": True,
            },
        )
        assert response.status_code == 200
        return response.json()["user"]["id"]

    user_one = register(client_one, "one@example.org")
    register(client_two, "two@example.org")

    from clinagent.gateway.auth import ClinAgentAuthStore
    from clinagent.gateway import server as gateway_server

    store = ClinAgentAuthStore.from_env()
    store.register_case_access(case_id="owned-session", owner_user_id=user_one, source="nifti_upload")
    store.register_case_access(case_id="shared-session", owner_user_id=None, source="curated", shared=True)

    class FakeBrainTumorStore:
        @staticmethod
        def get_session(session_id: str):
            return {"ok": True, "session_id": session_id}

        @staticmethod
        def get_registration_artifact(*args):
            artifact = tmp_path / "aligned.nii.gz"
            artifact.write_bytes(b"test-aligned-volume")
            return artifact

    monkeypatch.setattr(gateway_server, "_get_brain_tumor_demo_store", lambda: FakeBrainTumorStore())

    assert client_one.get("/api/demo/brain-tumor/sessions/owned-session").status_code == 200
    assert client_two.get("/api/demo/brain-tumor/sessions/owned-session").status_code == 404
    assert client_one.get("/api/demo/brain-tumor/sessions/shared-session").status_code == 200
    assert client_two.get("/api/demo/brain-tumor/sessions/shared-session").status_code == 200
    for fixed, moving in (("shared-session", "owned-session"), ("owned-session", "shared-session")):
        path = f"/api/demo/brain-tumor/longitudinal/artifacts/{fixed}/{moving}/rigid_v1/012345abcdef/image_t1c.nii.gz"
        assert client_one.get(path).status_code == 200
        assert client_two.get(path).status_code == 404
        assert TestClient(client_one.app).get(path).status_code == 401
    report = client_two.post(
        "/api/demo/brain-tumor/report/draft",
        json={"session_id": "owned-session", "active_measurements": None},
    )
    assert report.status_code == 404


def test_brain_tumor_preview_scope_hides_other_product_apis(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path, require_auth=True, preview_scope="brain_tumor")
    registered = client.post(
        "/api/auth/register",
        json={
            "email": "scope@example.org",
            "password": "long secure password",
            "name": "Scope Reader",
            "organization": "Example Hospital",
            "role": "radiologist",
            "dua_accepted": True,
        },
    )
    assert registered.status_code == 200
    assert client.get("/api/demo/brain-tumor/service").status_code == 200
    assert client.get("/api/demo/workspace").status_code == 404
    assert client.get("/api/version").status_code == 200


def test_curated_brain_tumor_mode_can_run_inside_full_product_scope(monkeypatch, tmp_path):
    client = _build_client(
        monkeypatch,
        tmp_path,
        preview_scope="full",
        curated_only=True,
        curated_case_ids="case-allowed",
    )

    config = client.get("/api/auth/config")
    assert config.status_code == 200
    assert config.json()["preview_scope"] == "full"
    assert config.json()["physician_curated_only"] is True
    assert client.get("/api/demo/neuro-report/segmentation/service").status_code == 200
    assert client.post("/api/demo/brain-tumor/analyze").status_code == 404


def test_curated_physician_preview_filters_cases_and_blocks_non_curated_workflows(monkeypatch, tmp_path):
    client = _build_client(
        monkeypatch,
        tmp_path,
        preview_scope="brain_tumor",
        curated_only=True,
        curated_case_ids="case-allowed",
    )

    from clinagent.gateway import server as gateway_server

    class FakeBrainTumorStore:
        @staticmethod
        def service_status():
            return {"ok": True, "configured": True}

        @staticmethod
        def get_case_registry():
            return {
                "ok": True,
                "case_count": 2,
                "cases": [
                    {"id": "case-allowed", "title": "Allowed"},
                    {"id": "case-hidden", "title": "Hidden"},
                ],
            }

        @staticmethod
        def get_preload_examples():
            return {
                "ok": True,
                "configured": True,
                "default_example_id": "case-hidden",
                "examples": [
                    {"id": "case-allowed", "title": "Allowed"},
                    {"id": "case-hidden", "title": "Hidden"},
                ],
            }

        @staticmethod
        def load_case_registry_case(*, case_id: str, timepoint_ids=None, prefer_cached: bool = False):
            assert case_id == "case-allowed"
            assert timepoint_ids is None
            assert prefer_cached is True
            return {"ok": True, "case_id": case_id, "points": [{"session_id": "allowed-session"}]}

        @staticmethod
        def get_session(session_id: str):
            return {"ok": True, "session_id": session_id}

    monkeypatch.setattr(gateway_server, "_get_brain_tumor_demo_store", lambda: FakeBrainTumorStore())

    config = client.get("/api/auth/config")
    assert config.status_code == 200
    assert config.json()["physician_curated_only"] is True

    service = client.get("/api/demo/brain-tumor/service")
    assert service.status_code == 200
    assert service.json()["physician_curated_only"] is True

    registry = client.get("/api/demo/brain-tumor/registry/cases")
    assert registry.status_code == 200
    assert registry.json()["case_count"] == 1
    assert [item["id"] for item in registry.json()["cases"]] == ["case-allowed"]

    preloads = client.get("/api/demo/brain-tumor/preload/examples")
    assert preloads.status_code == 200
    assert preloads.json()["default_example_id"] == "case-allowed"
    assert [item["id"] for item in preloads.json()["examples"]] == ["case-allowed"]

    hidden = client.post("/api/demo/brain-tumor/registry/load", json={"case_id": "case-hidden"})
    assert hidden.status_code == 404
    loaded = client.post("/api/demo/brain-tumor/registry/load", json={"case_id": "case-allowed"})
    assert loaded.status_code == 200
    assert client.get("/api/demo/brain-tumor/sessions/allowed-session").status_code == 200

    assert client.post("/api/demo/brain-tumor/analyze").status_code == 404
    assert client.get("/api/demo/brain-tumor/dicom/studies").status_code == 404
    assert client.post("/api/demo/brain-tumor/registry/run", json={"case_id": "case-allowed"}).status_code == 404


def test_curated_physician_preview_fails_closed_without_allowlist(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path, preview_scope="brain_tumor", curated_only=True)

    from clinagent.gateway import server as gateway_server

    class FakeBrainTumorStore:
        @staticmethod
        def get_case_registry():
            return {"ok": True, "case_count": 1, "cases": [{"id": "case-one"}]}

    monkeypatch.setattr(gateway_server, "_get_brain_tumor_demo_store", lambda: FakeBrainTumorStore())

    registry = client.get("/api/demo/brain-tumor/registry/cases")
    assert registry.status_code == 200
    assert registry.json()["case_count"] == 0
    assert registry.json()["cases"] == []
    assert client.post("/api/demo/brain-tumor/registry/load", json={"case_id": "case-one"}).status_code == 404


def test_curated_physician_preview_rejects_legacy_shared_session(monkeypatch, tmp_path):
    client = _build_client(
        monkeypatch,
        tmp_path,
        require_auth=True,
        self_registration=True,
        preview_scope="brain_tumor",
        curated_only=True,
        curated_case_ids="case-allowed",
    )
    registered = client.post(
        "/api/auth/register",
        json={
            "email": "curated@example.org",
            "password": "long secure password",
            "name": "Curated Reader",
            "organization": "Example Hospital",
            "role": "radiologist",
            "dua_accepted": True,
        },
    )
    assert registered.status_code == 200

    from clinagent.gateway.auth import ClinAgentAuthStore
    from clinagent.gateway import server as gateway_server

    store = ClinAgentAuthStore.from_env()
    store.register_case_access(case_id="legacy-shared", owner_user_id=None, source="curated", shared=True)
    store.register_case_access(
        case_id="allowed-session",
        owner_user_id=None,
        source="curated_registry:case-allowed",
        shared=True,
    )

    class FakeBrainTumorStore:
        @staticmethod
        def get_session(session_id: str):
            return {"ok": True, "session_id": session_id}

    monkeypatch.setattr(gateway_server, "_get_brain_tumor_demo_store", lambda: FakeBrainTumorStore())

    assert client.get("/api/demo/brain-tumor/sessions/legacy-shared").status_code == 404
    assert client.get("/api/demo/brain-tumor/sessions/allowed-session").status_code == 200


def test_authenticated_registry_segmentation_uses_durable_queue(monkeypatch, tmp_path):
    client = _build_client(
        monkeypatch,
        tmp_path,
        require_auth=True,
        preview_scope="brain_tumor",
        curated_only=True,
        curated_case_ids="case-allowed",
    )
    registered = client.post(
        "/api/auth/register",
        json={
            "email": "rerun@example.org",
            "password": "long secure password",
            "name": "Rerun Reader",
            "organization": "Example Hospital",
            "role": "radiologist",
            "dua_accepted": True,
        },
    )
    assert registered.status_code == 200

    from clinagent.gateway import server as gateway_server

    class FakeBrainTumorStore:
        @staticmethod
        def describe_registry_segment_job(*, job_id: str, case_id: str, timepoint_ids, force_rerun: bool):
            assert case_id == "case-allowed"
            assert timepoint_ids == ["visit-2"]
            assert force_rerun is True
            return {
                "ok": True,
                "job_id": job_id,
                "case_id": case_id,
                "status": "queued",
                "stage": "queued",
                "total_count": 1,
                "completed_count": 0,
                "visits": [{"timepoint_id": "visit-2", "status": "queued"}],
                "force_rerun": True,
            }

    monkeypatch.setattr(gateway_server, "_get_brain_tumor_demo_store", lambda: FakeBrainTumorStore())

    created = client.post(
        "/api/demo/brain-tumor/registry/segment-jobs",
        json={"case_id": "case-allowed", "timepoint_ids": ["visit-2"], "force_rerun": True},
    )
    assert created.status_code == 200
    job = created.json()
    assert job["status"] == "queued"
    assert job["stage"] == "queued"
    assert job["total_count"] == 1

    active = client.get("/api/demo/brain-tumor/registry/segment-jobs/active")
    assert active.status_code == 200
    assert active.json()["job"]["job_id"] == job["job_id"]

    fetched = client.get(f"/api/demo/brain-tumor/registry/segment-jobs/{job['job_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["force_rerun"] is True

    duplicate = client.post(
        "/api/demo/brain-tumor/registry/segment-jobs",
        json={"case_id": "case-allowed", "timepoint_ids": ["visit-2"], "force_rerun": True},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["job_id"] == job["job_id"]

    from clinagent.gateway.auth import ClinAgentAuthStore

    store = ClinAgentAuthStore.from_env()
    store.update_job(
        job_id=job["job_id"],
        status="completed",
        stage="complete",
        result={**job, "status": "completed", "stage": "complete", "completed_count": 1},
    )
    assert client.get("/api/demo/brain-tumor/registry/segment-jobs/active").json()["job"] is None
    current = client.get("/api/demo/brain-tumor/registry/segment-jobs/current")
    assert current.status_code == 200
    assert current.json()["job"]["status"] == "completed"
    assert current.json()["job"]["job_id"] == job["job_id"]


def test_case_access_can_upgrade_generic_shared_source(monkeypatch, tmp_path):
    _build_client(monkeypatch, tmp_path)

    from clinagent.gateway.auth import ClinAgentAuthStore

    store = ClinAgentAuthStore.from_env()
    store.register_case_access(case_id="cached-session", owner_user_id=None, source="curated_registry", shared=True)
    store.register_case_access(
        case_id="cached-session",
        owner_user_id=None,
        source="curated_registry:case-allowed",
        shared=True,
    )

    access = store.get_case_access(case_id="cached-session")
    assert access is not None
    assert access["source"] == "curated_registry:case-allowed"


def test_required_auth_rejects_cross_origin_state_change(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path, require_auth=True)
    blocked = client.post(
        "/api/auth/login",
        headers={"Origin": "https://untrusted.example.org"},
        json={"email": "reader@example.org", "password": "long secure password"},
    )
    assert blocked.status_code == 403

    same_origin = client.post(
        "/api/auth/login",
        headers={"Origin": "http://testserver"},
        json={"email": "reader@example.org", "password": "long secure password"},
    )
    assert same_origin.status_code == 401


def test_idle_session_is_not_restored(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path, require_auth=True)
    registered = client.post(
        "/api/auth/register",
        json={
            "email": "idle@example.org",
            "password": "long secure password",
            "name": "Idle Reader",
            "organization": "Example Hospital",
            "role": "radiologist",
            "dua_accepted": True,
        },
    )
    assert registered.status_code == 200
    old = (datetime.now(UTC) - timedelta(hours=13)).isoformat()
    with sqlite3.connect(tmp_path / "auth.sqlite3") as conn:
        conn.execute("UPDATE sessions SET last_seen_at = ?", (old,))

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"] is None


def test_auth_route_serves_demo_spa(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.get("/auth")

    assert response.status_code == 200
    assert "ClinAgent" in response.text


def test_password_change_requires_current_password_and_revokes_old_session(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "reader@example.org",
            "password": "long secure password",
            "name": "Reader",
            "organization": "Example Hospital",
            "role": "resident",
            "dua_accepted": True,
        },
    )
    assert register_response.status_code == 200

    wrong = client.post(
        "/api/auth/password/change",
        json={"current_password": "wrong password", "new_password": "new secure password"},
    )
    assert wrong.status_code == 400

    changed = client.post(
        "/api/auth/password/change",
        json={"current_password": "long secure password", "new_password": "new secure password"},
    )
    assert changed.status_code == 200

    old_login = client.post("/api/auth/login", json={"email": "reader@example.org", "password": "long secure password"})
    assert old_login.status_code == 401

    new_login = client.post("/api/auth/login", json={"email": "reader@example.org", "password": "new secure password"})
    assert new_login.status_code == 200


def test_local_password_reset_token_is_env_gated_and_single_use(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path, local_reset=True)
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "reader@example.org",
            "password": "long secure password",
            "name": "Reader",
            "organization": "Example Hospital",
            "role": "resident",
            "dua_accepted": True,
        },
    )
    assert register_response.status_code == 200
    client.post("/api/auth/logout")

    forgot = client.post("/api/auth/password/forgot", json={"email": "reader@example.org"})
    assert forgot.status_code == 200
    token = forgot.json()["reset_token"]
    assert token

    reset = client.post("/api/auth/password/reset", json={"token": token, "password": "reset secure password"})
    assert reset.status_code == 200

    reused = client.post("/api/auth/password/reset", json={"token": token, "password": "another secure password"})
    assert reused.status_code == 400

    new_login = client.post(
        "/api/auth/login",
        json={"email": "reader@example.org", "password": "reset secure password"},
    )
    assert new_login.status_code == 200
