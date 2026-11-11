---
name: nnunet_brain_segmentation_tool
description: Prepare a T1 NIfTI with LIA + basic QC, call the local brain segmentation nnUNet service, and use labels.json as the single source of truth for anatomy labels.
allowed-tools: check_brain_seg_service_health get_brain_structure_model_info run_brain_structure_segmentation use_skill
---

Use this skill when you need to run the local whole-brain segmentation service for a structural neuro case.

## Goal

Produce a segmentation NIfTI from a `T1` brain MRI using the local nnUNet service without silently changing the model's expected preprocessing path.

## Current input contract

- input must be a local `T1 .nii.gz`
- external preprocessing should default to:
  - `LIA`
  - `basic QC`
- do **not** add default intensity matching
  - no forced `uint8`
  - no forced `0..255` scaling
- spacing and shape are handled by the service

## Required workflow

1. Call `check_brain_seg_service_health`.
2. Call `get_brain_structure_model_info`.
3. Confirm the input is a `T1` NIfTI on the same server.
4. Call `run_brain_structure_segmentation`.
5. Read `label_schema_path` from the response.

## Rules

- Treat `labels.json` as the only source of truth for label meanings.
- Do not hardcode anatomy names separately from `labels.json`.
- Do not assume the input must be externally converted to `uint8` or `0..255`.
- If the service returns QC warnings, surface them instead of pretending the segmentation is clean.
- Do not expose internal server file paths in a polished user-facing summary unless the user explicitly asks for them.

## Expected outputs

- service health result
- model metadata
- prepared input summary
- segmentation output path
- label schema path
- QC summary

## Good follow-up actions

- Use the segmentation output for grouped region extraction.
- Use the grouped regions for volumetrics and report generation.
- If segmentation fails, report whether the blocker was:
  - missing T1 input
  - failed LIA/basic QC
  - service unavailable
  - service-side inference error
