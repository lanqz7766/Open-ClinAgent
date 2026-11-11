from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


PACKAGE_ROOT = Path(__file__).resolve().parent
_DEFAULT_SKILL_DIR_NAMES = ("skills", ".skills", "skill", ".skill", "Skills")


def _unique_existing_paths(paths: Iterable[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        expanded = path.expanduser()
        if not expanded.exists():
            continue
        resolved = expanded.resolve()
        normalized = str(resolved).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(resolved)
    return unique


def source_tree_root() -> Path | None:
    candidate = PACKAGE_ROOT.parent.parent
    if (candidate / "pyproject.toml").exists():
        return candidate.resolve()
    return None


def workspace_root() -> Path:
    return source_tree_root() or Path.cwd().resolve()


def bundled_dir(name: str) -> Path | None:
    candidate = PACKAGE_ROOT / "_bundled" / name
    if candidate.exists():
        return candidate.resolve()
    return None


def source_tree_dir(name: str) -> Path | None:
    root = source_tree_root()
    if root is None:
        return None
    candidate = root / name
    if candidate.exists():
        return candidate.resolve()
    return None


def resolve_resource_path(relative_path: str | Path) -> Path:
    path = Path(relative_path)
    if path.exists() or path.is_absolute():
        return path

    cwd_candidate = Path.cwd().resolve() / path
    if cwd_candidate.exists():
        return cwd_candidate

    parent = str(path.parent) if str(path.parent) != "." else ""
    source_parent = source_tree_dir(parent)
    if source_parent is not None:
        source_candidate = source_parent / path.name
        if source_candidate.exists():
            return source_candidate

    bundled_parent = bundled_dir(parent)
    if bundled_parent is not None:
        bundled_candidate = bundled_parent / path.name
        if bundled_candidate.exists():
            return bundled_candidate

    return path


def _split_env_paths(var_name: str) -> list[Path]:
    raw = os.getenv(var_name, "").strip()
    if not raw:
        return []
    return [Path(item) for item in raw.split(os.pathsep) if item.strip()]


def resolve_default_skill_dirs() -> list[str]:
    candidates: list[Path] = []
    candidates.extend(_split_env_paths("CLINAGENT_SKILLS_DIRS"))
    cwd = Path.cwd().resolve()
    for name in _DEFAULT_SKILL_DIR_NAMES:
        candidates.append(cwd / name)
    source_skills = source_tree_dir("skills")
    if source_skills is not None:
        candidates.append(source_skills)
    bundled_skills = bundled_dir("skills")
    if bundled_skills is not None:
        candidates.append(bundled_skills)
    return [str(path) for path in _unique_existing_paths(candidates)]


def resolve_default_scenario_dirs(directory: str | Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    if directory is not None:
        candidates.append(Path(directory))
    candidates.append(Path.cwd().resolve() / "scenarios")
    source_scenarios = source_tree_dir("scenarios")
    if source_scenarios is not None:
        candidates.append(source_scenarios)
    bundled_scenarios = bundled_dir("scenarios")
    if bundled_scenarios is not None:
        candidates.append(bundled_scenarios)
    return _unique_existing_paths(candidates)
