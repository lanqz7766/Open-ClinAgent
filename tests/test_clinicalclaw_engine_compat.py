from __future__ import annotations

import importlib


def test_top_level_clinagent_exports_create_agent():
    from clinagent import create_agent as top_level_factory
    from clinagent.engine import create_agent as engine_factory

    assert top_level_factory is engine_factory


def test_clinagent_engine_import_exposes_create_agent():
    engine = importlib.import_module("clinagent.engine")

    assert hasattr(engine, "create_agent")
    assert callable(engine.create_agent)


def test_clinagent_engine_key_submodule_aliases_import():
    llm_module = importlib.import_module("clinagent.engine.providers.llm")
    gateway_module = importlib.import_module("clinagent.gateway.server")

    assert hasattr(llm_module, "LLMProvider")
    assert hasattr(gateway_module, "create_app")


def test_clinagent_top_level_main_delegates_to_engine_main():
    top_level_main = importlib.import_module("clinagent.__main__")
    engine_main = importlib.import_module("clinagent.engine.__main__")

    assert top_level_main.main is engine_main.main


def test_clinagent_engine_exports_eventkind():
    engine = importlib.import_module("clinagent.engine")

    assert hasattr(engine, "EventKind")
