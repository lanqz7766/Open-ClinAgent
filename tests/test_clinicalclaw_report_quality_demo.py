import os
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

_TEST_STATE_ROOT = Path(tempfile.mkdtemp(prefix="clinagent-report-quality-test-"))
_TEST_ENV_FILE = _TEST_STATE_ROOT / "test.env"
_TEST_ENV_FILE.write_text("", encoding="utf-8")
os.environ["CLINAGENT_ENV_FILE"] = str(_TEST_ENV_FILE)
os.environ["CLINAGENT_DATABASE_PATH"] = str(_TEST_STATE_ROOT / "state.sqlite3")
os.environ["CLINAGENT_ARTIFACT_DIR"] = str(_TEST_STATE_ROOT / "artifacts")
os.environ["CLINAGENT_LOCAL_UPLOAD_DIR"] = str(_TEST_STATE_ROOT / "uploads")

from clinagent.platform import config as platform_config
from clinagent.platform.memory_harness import get_harness_memory_store

platform_config._loaded = False
platform_config._env_file = None
get_harness_memory_store.cache_clear()

from clinagent.families.shared.report_quality_demo import ReportQualityDemoStore


def _build_client():
    from clinagent.gateway.server import create_app

    app, _, _ = create_app()
    return TestClient(app)


def test_report_quality_demo_store_builds_workspace() -> None:
    store = ReportQualityDemoStore()
    payload = store.snapshot()

    assert payload["default_case_id"]
    assert payload["workspace"]["status_label"]
    assert payload["workspace"]["report_html"].startswith("<!doctype html>")
    assert len(payload["workspace"]["findings_groups"]) == 3
    assert "sample_path" not in payload["workspace"]


def test_report_quality_demo_store_builds_workspace_outside_repo_cwd(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    store = ReportQualityDemoStore()
    payload = store.snapshot()

    assert payload["default_case_id"]
    assert payload["workspace"]["report_html"].startswith("<!doctype html>")


def test_report_quality_demo_routes_expose_page_and_case() -> None:
    with patch("clinagent.gateway.server.load_config", return_value=MagicMock()), \
         patch("clinagent.gateway.server.get_default_model", return_value="gpt-5-mini"), \
         patch("clinagent.gateway.server.create_provider", return_value=MagicMock(name="fake-llm")):
        client = _build_client()

        page_response = client.get("/report-quality-demo")
        assert page_response.status_code == 200
        assert "Report Quality" in page_response.text

        workspace_response = client.get("/api/report-quality/workspace")
        assert workspace_response.status_code == 200
        payload = workspace_response.json()
        assert payload["default_case_id"]
        assert payload["workspace"]["report_html"].startswith("<!doctype html>")

        case_response = client.get(f"/api/report-quality/cases/{payload['default_case_id']}")
        assert case_response.status_code == 200
        assert case_response.json()["title"]

        missing_response = client.get("/api/report-quality/cases/not-a-case")
        assert missing_response.status_code == 404
