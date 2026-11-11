from __future__ import annotations

import asyncio
from pathlib import Path

from clinagent.engine.agent import _auto_discover_skills
from clinagent.engine.tools.skills import SkillStore
from clinagent.platform.scenarios import load_scenario_map


def test_scenarios_fall_back_to_default_sources(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    scenarios = load_scenario_map("scenarios")

    assert {"diagnostic_prep", "imaging_qc"} <= set(scenarios)


def test_skill_auto_discovery_loads_default_skill_set(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    skill_dirs = _auto_discover_skills()
    assert skill_dirs

    store = SkillStore()
    for directory in skill_dirs:
        store.add_directory(directory)
    asyncio.run(store.load_all())

    loaded = {skill.name for skill in store.list()}
    assert "neuro_report_generator" in loaded
    assert "nnunet_brain_segmentation_tool" in loaded
    assert "nnunet_brain_tumor_segmentation_tool" in loaded
