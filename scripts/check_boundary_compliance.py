#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_PATH_PREFIXES = (
    "docs/",
    "reports/",
    ".clinagent/",
    ".clinicalclaw/",
    ".clawagents/",
    ".clinagent/derived/",
    ".clinicalclaw/derived/",
)
FORBIDDEN_EXACT_PATHS = {
    ".env",
    ".env.local",
    ".envrc",
}
FORBIDDEN_GLOBS = (
    "*.nii",
    "*.nii.gz",
    "*.dcm",
    "*.dicom",
    "*.nrrd",
    "*.mha",
    "*.mhd",
    "*.raw",
)
ALLOWED_ENV_EXCEPTIONS = {
    ".env.example",
}
TEXT_SCAN_EXEMPTIONS = {
    "scripts/check_boundary_compliance.py",
}

SECRET_ASSIGNMENT_RE = re.compile(
    r"^\s*(?:export\s+)?"
    r"(?:OPENAI_API_KEY|GEMINI_API_KEY|ANTHROPIC_API_KEY|GATEWAY_API_KEY|CLINAGENT_FHIR_CLIENT_SECRET|CLINAGENT_DICOMWEB_ACCESS_TOKEN)"
    r"\s*=\s*.+$"
)
SECRET_TOKEN_PATTERNS = (
    re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
)
LOCAL_DATA_PATTERNS = (
    re.compile(r"/Users/[^/\n]+/Documents/Agent/Data/"),
    re.compile(r"/Users/[^/\n]+/Documents/Agent/AIRTPlanAgent-main/"),
    re.compile(r"/home/[^/\n]+/.*?/Data/"),
)
# Absolute personal home directories. Placeholder user names are allowed in docs.
HOME_PATH_RE = re.compile(r"(?:/Users|/home)/([A-Za-z0-9._-]+)/")
HOME_PATH_PLACEHOLDERS = {"you", "your-user", "user", "username", "me", "example", "runner", "app"}


def private_patterns() -> list[re.Pattern[str]]:
    """Extra private strings (hosts, mounts) supplied locally, never committed.

    Set CLINAGENT_BOUNDARY_PRIVATE_PATTERNS to a comma-separated list of regexes.
    """
    raw = os.getenv("CLINAGENT_BOUNDARY_PRIVATE_PATTERNS", "")
    return [re.compile(item.strip()) for item in raw.split(",") if item.strip()]


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line.strip()]


def is_forbidden_path(relpath: str) -> str | None:
    if relpath in FORBIDDEN_EXACT_PATHS:
        return f"{relpath}: environment files must never be tracked"
    if relpath.startswith(".env.") and relpath not in ALLOWED_ENV_EXCEPTIONS:
        return f"{relpath}: derived env files must never be tracked"
    for prefix in FORBIDDEN_PATH_PREFIXES:
        if relpath.startswith(prefix):
            return f"{relpath}: forbidden tracked path prefix '{prefix}'"
    for pattern in FORBIDDEN_GLOBS:
        if Path(relpath).match(pattern):
            return f"{relpath}: forbidden sensitive data extension"
    return None


def check_text_content(path: Path, relpath: str, extra_patterns: list[re.Pattern[str]]) -> list[str]:
    violations: list[str] = []
    if relpath in TEXT_SCAN_EXEMPTIONS:
        return violations
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return violations

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        stripped = raw_line.strip()
        is_comment = stripped.startswith("#")

        if SECRET_ASSIGNMENT_RE.match(raw_line):
            if relpath == ".env.example" and is_comment:
                pass
            elif is_comment:
                pass
            else:
                violations.append(f"{relpath}:{line_number}: contains a tracked secret assignment")

        if not is_comment:
            for pattern in SECRET_TOKEN_PATTERNS:
                if pattern.search(raw_line):
                    violations.append(f"{relpath}:{line_number}: contains a token-shaped secret value")
                    break

        for pattern in LOCAL_DATA_PATTERNS:
            if pattern.search(raw_line):
                violations.append(f"{relpath}:{line_number}: contains a local data path")
                break

        for match in HOME_PATH_RE.finditer(raw_line):
            if match.group(1).lower() not in HOME_PATH_PLACEHOLDERS:
                violations.append(f"{relpath}:{line_number}: contains a personal home-directory path")
                break

        for pattern in extra_patterns:
            if pattern.search(raw_line):
                violations.append(f"{relpath}:{line_number}: matches a private pattern")
                break

    return violations


def main() -> int:
    violations: list[str] = []
    extra_patterns = private_patterns()
    for path in tracked_files():
        if not path.exists():
            continue
        relpath = path.relative_to(ROOT).as_posix()
        path_violation = is_forbidden_path(relpath)
        if path_violation:
            violations.append(path_violation)
            continue
        if path.is_file():
            violations.extend(check_text_content(path, relpath, extra_patterns))

    if violations:
        print("Boundary compliance check failed:\n", file=sys.stderr)
        for item in violations:
            print(f"- {item}", file=sys.stderr)
        print(
            "\nFix the tracked files above before pushing. "
            "Do not push docs/, secrets, local data, or generated report outputs.",
            file=sys.stderr,
        )
        return 1

    print("Boundary compliance check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
