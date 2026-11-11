# platform/

Shared infrastructure that all clinical families build on. The platform layer handles registration, configuration, persistence, and orchestration — so families can focus purely on clinical logic.

## What Lives Here

- **`family_registry.py`** — Registers workflow families (neuro, radonc, findings, etc.) and maps incoming tasks to the right family.
- **`execution_profiles.py`** — Defines per-workflow tool bundles, execution stages, and policy modes. Controls what tools are available at each step.
- **`mcp_registry.py`** — MCP (Model Context Protocol) server registry for structured context injection.
- **`store.py`** — SQLite persistence layer for tasks, artifacts, memory, and token usage.
- **`config.py`** — `ClinAgentSettings` built on Pydantic BaseSettings with `.env` file discovery.
- **`runtime.py`** — Agent factory that wires up scenarios with the right family, skills, and tools.
- **`execution.py`** — `ClinAgentService` orchestrator that manages the full lifecycle of a workflow run.
- **`harness.py`** — Platform capability assessment (what services are available, what's configured).
- **`workflow_engine.py`** — Loads and validates YAML workflow definitions from family directories.
- **`models.py`** — Shared domain models and enums used across families.

## Role in the Architecture

```
Gateway → Platform (routing, config, orchestration) → Family → Engine
```

The platform is the glue between the external-facing gateway and the domain-specific families. It decides *which* family handles a task and *how* that family's agent is configured.
