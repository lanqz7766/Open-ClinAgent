---
name: neuro_registration_tool
description: Coregister neuro MRI sequences or timepoints, apply stored transforms to images or masks, and preserve QC/manifest outputs for ClinAgent review.
allowed-tools: coregister_neuro_sequences coregister_neuro_longitudinal apply_neuro_transform use_skill
---

Use this skill when the user asks to align MRI sequences, co-register follow-up studies, transfer a segmentation or ROI between spaces, or prepare aligned inputs for neuro review.

## Rules

- Use `coregister_neuro_sequences` before transferring masks unless a valid transform already exists.
- Use `coregister_neuro_longitudinal` with `method="rigid"` for baseline/follow-up alignment. Rigid means six degrees of freedom, not merely translation.
- For the GBM workflow, default to T1c as the within-visit reference and match follow-up T1c to reference T1c. Verify that the visits belong to the same patient. Supply `moving_modalities` for within-visit alignment, and `mask_paths` only for masks known to be in moving T1c space.
- Enable `bias_correction` only when N4 is requested. It changes derived intensity images, not the original inputs or segmentation measurements. Report skipped steps honestly and retain the returned workflow steps and outputs.
- Use `linear` interpolation for MRI intensity images.
- Use `nearest` interpolation for masks, segmentations, labels, and atlas ROIs.
- Prefer rigid alignment for longitudinal comparison; translation is only a coarse mode. Do not use nonlinear deformation to hide true lesion change.
- A completed computation is not human QC acceptance. Keep reported volumes in the original segmentation space with voxel spacing; do not recalculate longitudinal burden from display-resampled masks.
- Surface warnings from QC, especially shape mismatch, spacing mismatch, or large translation.
- If `CLINAGENT_NEURO_REGISTRATION_REMOTE_HOST` is configured, the same tools execute through the remote CLI over SSH; otherwise they run in the local Python environment.
- The remote CLI can be configured with `CLINAGENT_NEURO_REGISTRATION_REMOTE_CLI`; do not hardcode private hosts or mounted data roots in prompts, docs, or tracked config.

## Output Contract

Capture:

- aligned image path
- transform JSON path
- QC metrics
- warnings
- preprocessing manifest fragment

Do not expose private local paths in polished clinician-facing text unless the user asks for operational details.
