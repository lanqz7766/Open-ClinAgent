# families/radonc/

Radiation oncology planning family. Currently in development.

## Goal

Bring the same agent-driven workflow pattern to radiation therapy plan review and optimization. The agent evaluates treatment plans against clinical protocols, identifies trade-offs, and assists with iterative plan improvement.

## Planned Capabilities

- **DVH analysis** — Dose-volume histogram evaluation using the agent ReAct loop
- **Clinical goal checking** — Automated Dmax, Dmean, Vx, Dx constraint evaluation against protocol targets
- **OAR tolerance engine** — Organ-at-risk tolerance checking with configurable rule sets
- **Trade-off analysis** — LLM-assisted reasoning about competing planning objectives
- **Protocol management** — YAML-defined treatment protocols with versioning

## Structure

```
radonc/
├── tools/       DVH analysis, goal evaluation, OAR checking
├── workflows/   YAML protocol definitions
└── skills/      RadOnc-specific advisory skills
```
