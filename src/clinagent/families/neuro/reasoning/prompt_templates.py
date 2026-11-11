"""Jinja2-based prompt templates for the multi-step reasoning chain."""
from __future__ import annotations

from jinja2 import Template

STEP1_OBSERVATION = Template("""You are an experienced neuroradiologist reviewing a brain MRI study.

## Images Provided
You are viewing {{ num_slices }} representative slices:
{% for s in slices %}
- {{ s.description }}
{% endfor %}

## Automated Analysis Results
The following quantitative analysis was performed by automated tools:

{{ tool_outputs_json }}

## Task
Systematically describe your observations. Organize by anatomical region:
1. Brain parenchyma (gray matter, white matter) — volume, signal, symmetry
2. Ventricular system — size, symmetry, morphology
3. Extra-axial spaces — sulcal prominence, subdural/epidural collections
4. Midline structures — shift, corpus callosum, brainstem
5. Vascular structures (if visible) — flow voids, aneurysms
6. Calvarium and soft tissues

Rules:
- Do NOT make diagnoses yet. Only describe what you observe.
- Note any discrepancies between your visual observations and the automated measurements.
- Be specific with laterality (left/right) and location.
- If a region appears normal, state it explicitly as a pertinent negative.""")

STEP2_INTEGRATION = Template("""Based on your observations and the automated quantitative analysis:

## Your Observations from Step 1
{{ step1_output }}

## Quantitative Data Summary
{{ tool_summary }}

## Task
Synthesize your findings:
1. **Key positive findings** — list all abnormalities detected, with severity
2. **Pertinent negatives** — important normals that help narrow the differential
3. **Concordance check** — are visual and quantitative findings consistent? Flag any discrepancies.
4. **Differential diagnosis** — ranked by likelihood, with brief justification for each
5. **Confidence level** — high / moderate / low, with reasoning

For any abnormal automated measurement, keep the exact region name and quantitative values (volume, z-score, percentile) in your synthesis so they can be cited in the final report.

Be concise and clinically focused.""")

STEP3_REPORT = Template("""Generate a structured radiology report based on your integrated assessment.

## Your Integrated Assessment
{{ step2_output }}

## Patient Information
Age: {{ patient_age }} | Sex: {{ patient_sex }} | Clinical Indication: {{ clinical_indication | default("Brain MRI for clinical evaluation") }}

## Instructions
Write a formal radiology report with EXACTLY these four sections:

**CLINICAL INFORMATION:**
Brief clinical context based on the indication provided.

**TECHNIQUE:**
MRI of the brain. Sequences: {{ sequences | join(", ") }}. Reference automated volumetric and segmentation analysis.

**FINDINGS:**
Systematic description of all findings, organized anatomically. Include:
- Specific measurements where available (volumes, z-scores)
- Comparison to normative data
- All pertinent negatives

**IMPRESSION:**
Numbered list of key findings, most important first. Each item should be one concise sentence.

Style requirements:
- Use standard radiology report language (concise, professional, third-person)
- Use appropriate medical terminology
- Do not hedge excessively — state findings clearly
- You MUST explicitly reference the automated quantitative findings when they are provided, especially hippocampal volumes, ventricular volumes, cortical/white matter volumes, and total brain volume
- Do not include recommendations unless directly relevant to findings
- Output plain text only, not Markdown
- Do not add a report title
- Use these section headers exactly, each on its own line:
CLINICAL INFORMATION:
TECHNIQUE:
FINDINGS:
IMPRESSION:""")

SINGLE_STEP_REPORT = Template("""You are an experienced neuroradiologist. Generate a structured radiology report for the following brain MRI study.

## Images
You are viewing {{ num_slices }} representative slices of a brain MRI.

## Automated Analysis Results
{{ tool_outputs_json }}

## Patient Information
Age: {{ patient_age }} | Sex: {{ patient_sex }} | Clinical Indication: {{ clinical_indication | default("Brain MRI for clinical evaluation") }}
Available sequences: {{ sequences | join(", ") }}

## Task
Write a complete radiology report with sections: CLINICAL INFORMATION, TECHNIQUE, FINDINGS, IMPRESSION.
Use standard radiology report style.
You MUST explicitly reference the automated hippocampal, ventricular, cortical, white matter, and total brain measurements when they are provided.
If the automated quantitative findings are abnormal, include them in both FINDINGS and IMPRESSION.
In the TECHNIQUE section, mention only the sequences listed above. Do not invent additional sequences or contrast usage.
Output plain text only, not Markdown.
Do not add a report title.
Do not include recommendations unless directly relevant to findings.
Use these exact section headers on separate lines:
CLINICAL INFORMATION:
TECHNIQUE:
FINDINGS:
IMPRESSION:""")

VANILLA_REPORT = Template("""You are an experienced neuroradiologist. Generate a structured radiology report based only on the brain MRI images provided.

## Patient Information
Age: {{ patient_age }} | Sex: {{ patient_sex }} | Clinical Indication: {{ clinical_indication | default("Brain MRI for clinical evaluation") }}
Available sequences: {{ sequences | join(", ") }}

## Task
Examine the provided brain MRI slices carefully and write a complete radiology report with sections: CLINICAL INFORMATION, TECHNIQUE, FINDINGS, IMPRESSION.
Use standard radiology report style. Base your findings only on what you can observe in the images.
In the TECHNIQUE section, mention only the sequences listed above. Do not invent additional sequences.
Output plain text only, not Markdown.
Do not add a report title.
Do not include recommendations unless directly relevant to findings.
Use these exact section headers on separate lines:
CLINICAL INFORMATION:
TECHNIQUE:
FINDINGS:
IMPRESSION:""")

SEG_OVERLAY_REPORT = Template("""You are an experienced neuroradiologist. Generate a structured radiology report from brain MRI slices that include registered segmentation overlays.

## Patient Information
Age: {{ patient_age }} | Sex: {{ patient_sex }} | Clinical Indication: {{ clinical_indication | default("Brain MRI for clinical evaluation") }}
Available sequences: {{ sequences | join(", ") }}

## Image Context
The images are standard brain MRI slices with color overlays from an automated anatomical segmentation.
Use the underlying MRI appearance as the primary source of truth.
Use the overlays only as an anatomical guide to identify structures and ventricular boundaries.

## Task
Write a complete radiology report with sections: CLINICAL INFORMATION, TECHNIQUE, FINDINGS, IMPRESSION.
Use standard radiology report style. Base your findings on what is visible in the MRI and on the segmentation overlay support.
In the TECHNIQUE section, mention only the sequences listed above. Do not invent additional sequences.
Output plain text only, not Markdown.
Do not add a report title.
Do not include recommendations unless directly relevant to findings.
Use these exact section headers on separate lines:
CLINICAL INFORMATION:
TECHNIQUE:
FINDINGS:
IMPRESSION:""")


class PromptTemplates:
    """Helper class for rendering neuro reasoning templates."""

    @staticmethod
    def _patient_descriptor(patient_age: int | None, patient_sex: str | None) -> dict[str, str]:
        return {
            "patient_age": str(patient_age) if patient_age is not None else "Unknown",
            "patient_sex": patient_sex or "Unknown",
        }

    def render_step1(self, slices_metadata: list[dict], tool_outputs_json: str) -> str:
        return STEP1_OBSERVATION.render(
            num_slices=len(slices_metadata),
            slices=slices_metadata,
            tool_outputs_json=tool_outputs_json,
        )

    def render_step2(self, step1_output: str, tool_summary: str) -> str:
        return STEP2_INTEGRATION.render(step1_output=step1_output, tool_summary=tool_summary)

    def render_step3(
        self,
        step2_output: str,
        patient_age: int | None,
        patient_sex: str | None,
        clinical_indication: str,
        sequences: list[str],
    ) -> str:
        patient = self._patient_descriptor(patient_age, patient_sex)
        return STEP3_REPORT.render(
            step2_output=step2_output,
            patient_age=patient["patient_age"],
            patient_sex=patient["patient_sex"],
            clinical_indication=clinical_indication,
            sequences=sequences,
        )

    def render_single_step(
        self,
        num_slices: int,
        tool_outputs_json: str,
        patient_age: int | None,
        patient_sex: str | None,
        clinical_indication: str,
        sequences: list[str] | None = None,
    ) -> str:
        patient = self._patient_descriptor(patient_age, patient_sex)
        return SINGLE_STEP_REPORT.render(
            num_slices=num_slices,
            tool_outputs_json=tool_outputs_json,
            patient_age=patient["patient_age"],
            patient_sex=patient["patient_sex"],
            clinical_indication=clinical_indication,
            sequences=sequences or ["T1w"],
        )

    def render_vanilla(
        self,
        patient_age: int | None,
        patient_sex: str | None,
        clinical_indication: str,
        sequences: list[str] | None = None,
    ) -> str:
        patient = self._patient_descriptor(patient_age, patient_sex)
        return VANILLA_REPORT.render(
            patient_age=patient["patient_age"],
            patient_sex=patient["patient_sex"],
            clinical_indication=clinical_indication,
            sequences=sequences or ["T1w"],
        )

    def render_seg_overlay(
        self,
        patient_age: int | None,
        patient_sex: str | None,
        clinical_indication: str,
        sequences: list[str] | None = None,
    ) -> str:
        patient = self._patient_descriptor(patient_age, patient_sex)
        return SEG_OVERLAY_REPORT.render(
            patient_age=patient["patient_age"],
            patient_sex=patient["patient_sex"],
            clinical_indication=clinical_indication,
            sequences=sequences or ["T1w"],
        )
