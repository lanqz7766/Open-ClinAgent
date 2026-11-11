# families/neuro/

Flagship clinical family for neuro MRI analysis. Implements a multi-step VLM reasoning chain that takes raw imaging data through preprocessing, segmentation, observation, integration, and structured reporting.

## Pipeline

```
DICOM / NIfTI
      │
  ┌───▼────────────┐
  │ Preprocessing   │  Slice selection, sequence routing, input preparation
  └───┬────────────┘
      │
  ┌───▼────────────┐
  │ Segmentation    │  Brain segmentation tool (optional)
  └───┬────────────┘
      │
  ┌───▼────────────┐
  │ Observation     │  Per-sequence VLM analysis
  └───┬────────────┘
      │
  ┌───▼────────────┐
  │ Integration     │  Cross-sequence synthesis and correlation
  └───┬────────────┘
      │
  ┌───▼────────────┐
  │ Report          │  Structured findings, impressions, measurements
  └───┬────────────┘
      │
  ┌───▼────────────┐
  │ Evidence Review │  Verification against source imaging
  └────────────────┘
```

## Key Modules

- **`reasoning/`** — Multi-step VLM reasoning chain: observation, integration, and report generation stages.
- **`preprocessing/`** — Slice selection, sequence identification and routing, segmentation input preparation.
- **`tools/`** — Segmentation wrappers, volumetric measurement tools, and analysis utilities.
- **`mcp/`** — MCP context server providing structured neuro context to the agent.
- **`skills/`** — Neuro-specific advisory skills for report formatting and clinical heuristics.
- **`workflows/`** — YAML workflow definitions for different neuro review scenarios.
- **`report_generator.py`** — Structured report builder with configurable templates.
- **`visualization.py`** — Imaging visualization and overlay rendering.
- **`evidence_review.py`** — Evidence board for cross-referencing findings with source data.
- **`longitudinal_proteas.py`** — Longitudinal response tracking and PROTEAS assessment.
