#!/usr/bin/env python3
"""Build a wheel/Docker context from a clean, committed checkout, never local data."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise SystemExit("Commit the intended changes and leave a clean worktree before building.")
    commit = git("rev-parse", "HEAD")
    now = datetime.now(timezone.utc)
    release_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}_{commit[:12]}"
    output = args.output.expanduser().resolve() / release_id
    output.mkdir(parents=True, exist_ok=False)
    try:
        with tempfile.TemporaryDirectory(prefix="clinagent-release-") as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            archive = subprocess.check_output(["git", "archive", commit], cwd=ROOT)
            subprocess.run(["tar", "-xf", "-", "-C", str(source)], input=archive, check=True)
            subprocess.run(
                [sys.executable, "-m", "build", "--wheel", "--outdir", str(output / "dist")],
                cwd=source, check=True,
            )
            shutil.copytree(source / "deploy", output / "deploy")
            shutil.copy2(source / ".dockerignore", output / ".dockerignore")
        wheel = next((output / "dist").glob("*.whl"))
        metadata = {
            "git_commit": commit,
            "release_id": release_id,
            "build_time": now.isoformat(),
            "wheel": wheel.name,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        }
        (output / "release.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(json.dumps(metadata, indent=2))
        print(f"Release directory: {output}")
    except Exception:
        # A failed build must not look like a complete release.
        (output / "BUILD_FAILED").touch()
        raise


if __name__ == "__main__":
    main()
