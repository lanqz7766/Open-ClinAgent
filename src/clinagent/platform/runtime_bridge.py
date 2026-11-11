from __future__ import annotations

from importlib import import_module
from typing import Any


PRIVATE_RUNTIME_ROOT = "clinagent_runtime"
FALLBACK_RUNTIME_ROOT = "clinagent.engine"


def _load_runtime_module(relative_name: str):
    private_name = f"{PRIVATE_RUNTIME_ROOT}.{relative_name}"
    fallback_name = f"{FALLBACK_RUNTIME_ROOT}.{relative_name}"
    try:
        return import_module(private_name)
    except ModuleNotFoundError as exc:
        missing_root = exc.name or ""
        if missing_root not in {PRIVATE_RUNTIME_ROOT, private_name} and not missing_root.startswith(f"{PRIVATE_RUNTIME_ROOT}."):
            raise
        return import_module(fallback_name)


_agent_module = _load_runtime_module("agent")
_graph_module = _load_runtime_module("graph.agent_loop")
_config_module = _load_runtime_module("config.config")
_llm_module = _load_runtime_module("providers.llm")
_queue_module = _load_runtime_module("process.command_queue")
_lanes_module = _load_runtime_module("process.lanes")
_registry_module = _load_runtime_module("tools.registry")
_main_module = _load_runtime_module("__main__")

ClinAgent = _agent_module.ClinAgent
create_agent = _agent_module.create_agent

AgentState = _graph_module.AgentState
OnEvent = _graph_module.OnEvent
EventKind = _graph_module.EventKind
BeforeLLMHook = _graph_module.BeforeLLMHook
BeforeToolHook = _graph_module.BeforeToolHook
AfterToolHook = _graph_module.AfterToolHook

load_config = _config_module.load_config
get_default_model = _config_module.get_default_model
EngineConfig = _config_module.EngineConfig

create_provider = _llm_module.create_provider
LLMMessage = _llm_module.LLMMessage
LLMProvider = _llm_module.LLMProvider
NativeToolSchema = getattr(_llm_module, "NativeToolSchema", None)
NativeToolCall = getattr(_llm_module, "NativeToolCall", None)
LLMResponse = getattr(_llm_module, "LLMResponse", None)

enqueue_command_in_lane = _queue_module.enqueue_command_in_lane
get_queue_size = _queue_module.get_queue_size
get_total_queue_size = _queue_module.get_total_queue_size
get_active_task_count = _queue_module.get_active_task_count

CommandLane = _lanes_module.CommandLane

ToolResult = _registry_module.ToolResult
ToolRegistry = getattr(_registry_module, "ToolRegistry", None)

runtime_main = _main_module.main


def runtime_source() -> str:
    module_name = _agent_module.__name__
    if module_name.startswith(f"{PRIVATE_RUNTIME_ROOT}."):
        return PRIVATE_RUNTIME_ROOT
    return FALLBACK_RUNTIME_ROOT


def runtime_uses_private_package() -> bool:
    return runtime_source() == PRIVATE_RUNTIME_ROOT


def require_private_runtime() -> Any:
    if runtime_uses_private_package():
        return True
    raise RuntimeError(
        "ClinAgent private runtime is not installed. Install the private 'clinagent-runtime' wheel "
        "to run the full ClinAgent surface."
    )
