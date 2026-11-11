from __future__ import annotations

from pathlib import Path

from clinagent.bundled_resources import resolve_default_scenario_dirs
from clinagent.platform.models import ScenarioSpec


def load_scenarios(directory: str | Path) -> list[ScenarioSpec]:
    return list(load_scenario_map(directory).values())


def load_scenario_map(directory: str | Path) -> dict[str, ScenarioSpec]:
    scenario_map: dict[str, ScenarioSpec] = {}
    for scenario_dir in resolve_default_scenario_dirs(directory):
        for path in sorted(scenario_dir.glob("*.json")):
            scenario = ScenarioSpec.model_validate_json(path.read_text(encoding="utf-8"))
            scenario_map.setdefault(scenario.id, scenario)
    return scenario_map
