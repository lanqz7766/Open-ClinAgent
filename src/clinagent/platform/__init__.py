"""Structured platform entrypoints for shared ClinAgent infrastructure."""

from clinagent.platform.capabilities import (
    MODEL_CAPABILITY_REGISTRY,
    WORKFLOW_CAPABILITY_REGISTRY,
    ModelCapability,
    WorkflowCapability,
    evaluate_neuro_workflow_capability,
    get_model_capability,
)
from clinagent.platform.config import ClinAgentSettings, load_settings
from clinagent.platform.runtime import build_agent_for_scenario, build_tool_gate
from clinagent.platform.store import MemoryStore, SQLiteStore
from clinagent.platform.workflow_engine import load_workflow_map

__all__ = [
    "MODEL_CAPABILITY_REGISTRY",
    "WORKFLOW_CAPABILITY_REGISTRY",
    "ModelCapability",
    "WorkflowCapability",
    "evaluate_neuro_workflow_capability",
    "get_model_capability",
    "ClinAgentSettings",
    "load_settings",
    "build_agent_for_scenario",
    "build_tool_gate",
    "MemoryStore",
    "SQLiteStore",
    "load_workflow_map",
]
