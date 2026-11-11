---
name: deepprep_neuro_preprocessing_tool
description: Use the remote DeepPrep wrapper for BIDS MRI preprocessing, anatomical derivatives, BOLD preprocessing, and co-registration manifests.
allowed-tools: check_deepprep_tool_health run_deepprep_preprocessing use_skill
---

Use this skill when the user asks for neuro MRI preprocessing, BIDS preprocessing, DeepPrep, fMRI preprocessing, or BOLD-to-T1/T1-to-template co-registration.

## Contract

- Inputs must be paths that already exist on the configured remote server.
- The input dataset should be BIDS formatted.
- A valid FreeSurfer license file is required by DeepPrep.
- Supported remote runners are `docker`, `singularity`, and `apptainer`.
- For Singularity/Apptainer, pass `runner` plus an absolute `sif_path` on the remote server.
- Start with `check_deepprep_tool_health`.
- Use `run_deepprep_preprocessing` with `dry_run=true` before launching a long job unless the user already gave exact paths and explicitly asked to run.
- Prefer `detach=true` for real jobs so the agent can return a job id and logs instead of blocking.

## Capabilities

- anatomical preprocessing
- FastSurfer-style anatomical segmentation derivatives from DeepPrep
- brain mask and preprocessed T1w discovery
- BOLD preprocessing
- BOLD-to-T1w coregistration transform discovery
- T1w-to-template transform discovery
- confounds and QC report discovery

## Output Handling

Use the returned manifest to locate:

- `preproc_t1w`
- `brain_mask`
- `dseg`
- `preproc_bold`
- `coreg_xfm`
- `template_xfm`
- `confounds`
- `qc_reports`

Do not expose private server paths in a polished clinical summary unless the user explicitly asks for operational details.
