from __future__ import annotations

import os
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any


def _package_version() -> str:
    try:
        return version("clinagent")
    except PackageNotFoundError:
        return "development"


def public_build_info(*, auth_schema_version: int) -> dict[str, Any]:
    """Return deployment metadata without exposing filesystem or host details."""
    return {
        "ok": True,
        "package_version": _package_version(),
        "git_commit": os.getenv("CLINAGENT_BUILD_GIT_COMMIT", "unknown").strip() or "unknown",
        "release_id": os.getenv("CLINAGENT_RELEASE_ID", "development").strip() or "development",
        "build_time": os.getenv("CLINAGENT_BUILD_TIME", "unknown").strip() or "unknown",
        "auth_schema_version": auth_schema_version,
        "server_time": datetime.now(UTC).isoformat(),
    }
