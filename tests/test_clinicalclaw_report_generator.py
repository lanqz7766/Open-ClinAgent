from __future__ import annotations

import os
from pathlib import Path

import pytest

from clinagent.families.neuro.longitudinal_proteas import build_neuro_longitudinal_workspace


PROTEAS_ROOT = os.getenv("CLINAGENT_TEST_PROTEAS_DATA_ROOT") or os.getenv("CLINAGENT_NEURO_LONGITUDINAL_DATA_ROOT")
P28_ZIP = Path(PROTEAS_ROOT) / "P28.zip" if PROTEAS_ROOT else None


def test_neuro_report_contract_and_export_paths(tmp_path: Path):
    if P28_ZIP is None or not P28_ZIP.exists():
        pytest.skip("Set CLINAGENT_TEST_PROTEAS_DATA_ROOT to run the real PROTEAS workspace export test.")

    workspace = build_neuro_longitudinal_workspace(
        data_root=P28_ZIP.parent,
        patient_id="P28",
        output_root=tmp_path,
        materialize_assets=True,
    )

    report = workspace.report

    assert report["title"]
    assert report["rendered_html"].startswith("<section")
    assert "Trend" in report["rendered_html"]
    assert "Interpretation" in report["rendered_html"]
    assert report["quality_review"]["status"] in {
        "ready_for_review",
        "needs_completion",
        "needs_revision",
        "needs_redaction",
    }
    assert report["quality_review"]["template_id"] == "radiology"
    assert "Clinical Indication" in report["structured_text"]
    assert "Impression" in report["structured_text"]
    assert report["rendered_document_html"].lstrip().startswith("<!doctype html>")
    assert Path(report["html_path"]).exists()
    if report.get("pdf_path"):
        assert Path(report["pdf_path"]).exists()
