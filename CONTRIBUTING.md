# Contributing to ClinAgent

ClinAgent is designed for collaboration between clinicians, researchers, and engineers. Most contributors should start by adding a scenario or a skill before changing runtime internals.

## Common Contribution Paths

| Contribution | Where | Typical change |
|---|---|---|
| Add a scenario | `scenarios/` | New JSON task contract |
| Add a skill | `skills/` or `src/clinagent/families/*/skills/` | New `SKILL.md` |
| Extend a family | `src/clinagent/families/` | New tool, workflow logic, or demo behavior |
| Extend platform or gateway | `src/clinagent/platform/`, `src/clinagent/gateway/` | Shared runtime or app-surface changes |

## Add a Scenario

Scenarios are the fastest way to add a new controlled task.

Create a new JSON file in `scenarios/` with:

- a stable `id`
- a clear name and summary
- explicit inputs and outputs
- connector and tool policy
- review requirements

Use an existing scenario as the template, keep the contract narrow, and validate it through the scenario-loading tests and gateway flow.

## Add a Skill

Skills are Markdown instructions that shape reasoning and output quality without changing runtime code.

Create `skills/<skill_name>/SKILL.md` or add a family-local skill under `src/clinagent/families/*/skills/`.

A good skill usually includes:

- frontmatter with `name`, `description`, and optional `allowed-tools`
- a short goal
- rules and constraints
- expected inputs
- expected output shape

Start from the closest existing skill and keep the instructions specific to one workflow or presentation style.

## Local Setup

```bash
git clone https://github.com/lanqz7766/Open-ClinAgent.git
cd Open-ClinAgent

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
cd frontend && npm install && cd ..
cp .env.example .env
```

Then verify and run:

```bash
clinagent --doctor
clinagent --serve
```

## Validation

Run the smallest relevant checks for your change, then always run:

```bash
python3 scripts/check_boundary_compliance.py
```

Common checks:

```bash
pytest tests/test_config_consistency.py -q
pytest tests/test_clinicalclaw_contracts.py -q
pytest tests/test_clinicalclaw_console_agent.py -q
```

## Collaboration Rules

- Never commit `.env`, API keys, patient data, or real imaging files.
- Keep active product guidance in `README.md`.
- Open focused PRs and explain the clinical or workflow impact clearly.
- If a change can be expressed as a scenario or skill, prefer that over modifying core runtime code.
