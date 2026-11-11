# families/

Clinical domain modules. Each family is a self-contained clinical area with its own tools, workflows, advisory skills, and evaluation logic. Families are the primary extension point for adding new clinical capabilities.

## Active Families

| Family | Description | Status |
|--------|-------------|--------|
| **`neuro/`** | MRI structural review, brain segmentation, volumetrics, longitudinal tracking | Active — flagship |
| **`radonc/`** | Radiation therapy plan optimization, DVH analysis | In development |
| **`findings/`** | Actionable findings closure and follow-up | Active |
| **`screening/`** | Screening gap detection | Active |
| **`queue/`** | Worklist triage and prioritization | Active |
| **`safety/`** | Safety event monitoring | Active |
| **`diagnosis/`** | Missed diagnosis detection | Active |
| **`shared/`** | Cross-family tools (reporting, quality evaluation) | Active |

## Family Structure

Every family follows the same layout:

```
family_name/
├── tools/        Domain-specific tool classes
├── workflows/    YAML workflow definitions
├── skills/       Advisory knowledge (SKILL.md files)
├── evaluator.py  Core evaluation logic
└── workspace.py  Demo workspace and case store
```

## Contributing a New Family

1. Create a new directory under `families/` following the structure above
2. Register the family in `platform/family_registry.py`
3. Add workflow YAML definitions and at least one advisory skill
4. Write an evaluator that validates outputs against clinical criteria

Most contributors start by adding **tools**, **workflows**, or **skills** to an existing family rather than creating a new one from scratch. See [CONTRIBUTING.md](../../../CONTRIBUTING.md) for guidance.
