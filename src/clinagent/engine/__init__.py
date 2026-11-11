__version__ = "5.24.0"

from clinagent.engine.agent import ClinAgent, create_agent
from clinagent.engine.graph.agent_loop import (
    AgentState, OnEvent, EventKind,
    BeforeLLMHook, BeforeToolHook, AfterToolHook,
)
from clinagent.engine.trajectory import (
    TrajectoryRecorder, TurnRecord, RunSummary,
    extract_lessons, save_lessons, load_lessons,
    build_lesson_preamble, build_rethink_with_lessons,
)
from clinagent.engine.context import (
    ContextEngine, ContextEngineConfig, DefaultContextEngine,
    register_context_engine, resolve_context_engine, list_context_engines,
)
from clinagent.engine.channels import (
    ChannelMessage, ChannelAdapter, ChannelRouter, KeyedAsyncQueue,
)
