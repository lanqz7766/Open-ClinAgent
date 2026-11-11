from __future__ import annotations

import os
from pathlib import Path

from clinagent.bundled_resources import resolve_default_skill_dirs, source_tree_root, workspace_root

REPO_ROOT = source_tree_root() or workspace_root()

NEURO_LONGITUDINAL_DATA_ENV = "CLINAGENT_NEURO_LONGITUDINAL_DATA_ROOT"
NEURO_REPORT_DATA_ENV = "CLINAGENT_NEURO_REPORT_DATA_ROOT"
RADONC_DEMO_ROOT_ENV = "CLINAGENT_RADONC_DEMO_ROOT"
SKILLS_DIRS_ENV = "CLINAGENT_SKILLS_DIRS"
LOCAL_UPLOAD_DIR_ENV = "CLINAGENT_LOCAL_UPLOAD_DIR"


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _paths_from_env(var_name: str) -> list[Path]:
    raw = os.getenv(var_name, "").strip()
    if not raw:
        return []
    return _unique_paths([Path(item) for item in raw.split(os.pathsep) if item.strip()])


def _looks_like_radonc_patient_dir(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    return any(path.glob("Input_Iteration*.xlsx"))


def resolve_skills_dirs() -> list[str]:
    explicit = [str(path.resolve()) for path in _paths_from_env(SKILLS_DIRS_ENV) if path.exists()]
    discovered = resolve_default_skill_dirs()
    if not explicit:
        return discovered
    merged: list[str] = []
    seen: set[str] = set()
    for path in [*explicit, *discovered]:
        if path in seen:
            continue
        seen.add(path)
        merged.append(path)
    return merged


def resolve_local_upload_dir() -> Path:
    configured = os.getenv(LOCAL_UPLOAD_DIR_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (REPO_ROOT / ".clinagent" / "uploads").resolve()


def radonc_demo_root_candidates(explicit_root: str | Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit_root is not None:
        candidates.append(Path(explicit_root))
    candidates.extend(_paths_from_env(RADONC_DEMO_ROOT_ENV))
    repo_default = REPO_ROOT.parent / "AIRTPlanAgent-main"
    candidates.extend([repo_default / "Anony", repo_default / "test_data"])
    return _unique_paths(candidates)


def discover_radonc_demo_patients(explicit_root: str | Path | None = None) -> dict[str, Path]:
    patients: dict[str, Path] = {}

    for candidate in radonc_demo_root_candidates(explicit_root):
        if _looks_like_radonc_patient_dir(candidate):
            patients.setdefault(candidate.name, candidate.resolve())
            continue
        if not candidate.exists() or not candidate.is_dir():
            continue
        for child in sorted(candidate.iterdir()):
            if _looks_like_radonc_patient_dir(child):
                patients.setdefault(child.name, child.resolve())
    return patients


def neuro_report_data_root_candidates(explicit_root: str | Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit_root is not None:
        candidates.append(Path(explicit_root))
    candidates.extend(_paths_from_env(NEURO_REPORT_DATA_ENV))

    candidate_bases = [
        REPO_ROOT.parent / "Data",
        Path.home() / "Documents" / "Agent" / "Data",
    ]
    for base in candidate_bases:
        candidates.append(base / "longitudinal_patient")
        if base.exists() and base.is_dir():
            for child in sorted(base.iterdir()):
                if not child.is_dir():
                    continue
                if (child / "metadata" / "longitudinal_manifest.csv").exists():
                    candidates.append(child)

    candidates.append(REPO_ROOT / ".clinagent" / "local" / "longitudinal_patient")
    return _unique_paths(candidates)


def resolve_neuro_longitudinal_data_root(explicit_root: str | Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit_root is not None:
        candidates.append(Path(explicit_root))
    candidates.extend(_paths_from_env(NEURO_LONGITUDINAL_DATA_ENV))
    for candidate in _unique_paths(candidates):
        if candidate.exists():
            return candidate.resolve()
    return None


def resolve_radonc_demo_root(patient_id: str = "Patient001", explicit_root: str | Path | None = None) -> Path | None:
    for candidate in radonc_demo_root_candidates(explicit_root):
        if candidate.is_dir() and candidate.name == patient_id:
            return candidate.resolve()
        nested = candidate / patient_id
        if nested.exists():
            return nested.resolve()
    return None
