---
name: nnunet_brain_tumor_segmentation_tool
description: Run the research/demo glioma MRI segmentation service from BraTS-style multimodal NIfTI inputs and surface QC, tumor volumes, and preview artifacts.
allowed-tools: check_brain_tumor_seg_service_health get_brain_tumor_seg_model_info run_brain_tumor_segmentation use_skill
---

Use this skill when a user asks to segment a suspected glioma/GBM MRI, estimate tumor burden, or produce tumor segmentation artifacts from multimodal brain MRI.

## Goal

Produce research/demo glioma segmentation artifacts from BraTS-style NIfTI inputs without presenting the result as a clinical diagnosis.

## Current input contract

- Preferred modalities:
  - `t1n`: native T1
  - `t1c`: contrast-enhanced T1
  - `t2w`: T2-weighted
  - `t2f`: FLAIR/T2-FLAIR
- Minimum v1 input is `t1c` and `t2f`.
- Inputs must be local NIfTI files visible to the configured service.

## Required workflow

1. Call `check_brain_tumor_seg_service_health`.
2. Call `get_brain_tumor_seg_model_info`.
3. Confirm the available modality paths and output directory.
4. Call `run_brain_tumor_segmentation`.
5. Surface QC warnings, especially missing modalities, affine mismatches, unknown labels, or empty tumor masks.

## Rules

- Describe the output as research/demo segmentation, not diagnosis.
- Do not infer GBM diagnosis from the segmentation.
- Do not hide missing modality or affine warnings.
- Do not expose internal server paths in polished user-facing summaries unless explicitly requested.
- Treat `tumor_regions.json` as the source of truth for derived WT/TC/ET-style volumes.

## Expected outputs

- segmentation NIfTI path
- `tumor_regions.json`
- `volumes.csv`
- `overlay_preview.png`
- QC summary
- WT/TC/ET-style derived volumes when labels are present
