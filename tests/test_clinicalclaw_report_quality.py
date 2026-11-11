from __future__ import annotations

from clinagent.families.shared.report_quality import (
    build_quality_report_document,
    evaluate_report_quality,
    generate_report_template,
    list_report_templates,
    scan_deidentification,
)


def test_generate_report_template_contains_expected_sections() -> None:
    template = generate_report_template("radiology")

    assert "# Radiology Report" in template
    assert "## Findings" in template
    assert "## Impression" in template


def test_deidentification_and_terminology_checks_flag_expected_patterns() -> None:
    text = """
    Follow-up MRI for Mr. John Carter. MRN: DEMO-1142. MRI on 03/14/2025.
    Call 312-555-0199. The patient received 4U dexamethasone QD.
    """
    bundle = evaluate_report_quality(text, template_id="radiology", compliance_profile="radiology")

    assert bundle.deidentification.status == "non_compliant"
    assert any(item.code == "mrn" for item in bundle.deidentification.findings)
    assert bundle.terminology.status == "needs_revision"
    assert any(item.label == "U" for item in bundle.terminology.do_not_use)
    assert bundle.status == "needs_redaction"


def test_quality_document_builds_compact_html_payload() -> None:
    text = """
    # Radiology Report
    ## Clinical Indication
    Post-radiotherapy follow-up for treated brain metastasis.
    ## Technique
    MRI brain without and with contrast.
    ## Comparison
    Compared with the prior MRI from 2025.
    ## Findings
    Stable treated lesion without a new enhancing focus.
    ## Impression
    Stable appearance of the treated lesion.
    """
    bundle = evaluate_report_quality(text, template_id="radiology", compliance_profile="radiology")
    document = build_quality_report_document(
        sample_name="clean_neuro_followup",
        text=text,
        bundle=bundle,
        template_preview=generate_report_template("radiology"),
    )

    assert document.badge_label in {"Ready for review", "Needs completion"}
    assert any(metric.label == "Privacy issues" for metric in document.metrics)
    assert any(section.title == "Compliance" for section in document.sections)


def test_list_report_templates_exposes_absorbed_templates() -> None:
    templates = list_report_templates()

    assert {item.template_id for item in templates} >= {"radiology", "consult_note", "case_report"}
    assert scan_deidentification("The patient is stable.").status == "compliant"
