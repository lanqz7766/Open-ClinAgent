# engine/

Adapted from [ClawAgents](https://github.com/x1jiang/clawagents_py) (MIT License, Copyright (c) 2026 Xiaoqian Jiang). See `LICENSE-clawagents` in this directory.

Core agent runtime that powers all clinical workflows. This is the execution brain — it takes a task, reasons through it step by step, calls tools, and produces structured output.

## How It Works

```
Task input
    │
    ▼
┌──────────────────┐
│  ReAct Loop       │  reason → act → observe → repeat
│  (agent_loop.py)  │  with loop detection + context budgeting
└────────┬─────────┘
         │
    ┌────▼────┐
    │  Tools   │  filesystem, exec, web, subagent
    └────┬────┘
         │
    ┌────▼────────────┐
    │  LLM Provider    │  OpenAI / Gemini / Claude / local
    └────┬────────────┘
         │
    ┌────▼────────────┐
    │  Trajectory      │  recording → lessons → scoring → PTRL
    └─────────────────┘
```

## Key Modules

- **`agent.py`** — `ClinAgent` class and `create_agent()` factory. Entry point for creating configured agent instances.
- **`graph/agent_loop.py`** — The ReAct executor. Handles loop detection, context budget management, and rethink injection when the agent gets stuck.
- **`providers/llm.py`** — Unified LLM interface across OpenAI, Gemini, Claude, Azure, Bedrock, Ollama, and vLLM.
- **`tools/`** — Tool registry with built-in tools (filesystem, exec, web, subagent). Supports parallel execution, result caching, and per-workflow tool policies.
- **`trajectory/`** — Run recording, lesson extraction, scoring, and PTRL (Prompt-Time Reinforcement Learning) for self-improvement across runs.
- **`sandbox/`** — Pluggable execution backends (local process, in-memory) that isolate tool execution.
- **`channels/`** — Messaging integrations for Telegram, WhatsApp, and Signal.
- **`memory/`** — Persistent and session-scoped memory for cross-run context.
