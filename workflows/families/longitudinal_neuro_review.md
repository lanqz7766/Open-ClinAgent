# Longitudinal Neuro Review

This family is for neuro-imaging workflows where the core task is not a single-study read, but a review across time.

## When to use it

- Serial MRI or CT exists for the same neuro-oncology or neurodegenerative case
- The timeline includes a treatment event, clinical transition, or explicit follow-up question
- The output should be concise, review-first, and visually anchored to longitudinal evidence

## Common pattern

1. Load the longitudinal imaging context and compact clinical metadata
2. Align treatment or follow-up events to the imaging timeline
3. Quantify or summarize the dominant interval signal
4. Render a clinician-facing brief and compact visual comparison
5. Run report QA before final sign-off or export

## Why this family matters

Longitudinal neuro workflows are often where an agent can save the most time for clinicians:

- serial dates need alignment
- treatment context matters
- interval change is more important than one-off image description
- the final product should be brief, reviewable, and privacy-safe

## Current workflow

- `post_rt_brain_met_longitudinal_review`

## Future workflows

- hippocampal atrophy review
- glioma post-treatment response review
- compact tumor-board pre-read generation
