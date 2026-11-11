from types import SimpleNamespace

import pytest

from clinagent.gateway.server import _brain_tumor_report_model_response


@pytest.mark.parametrize("text,status", [("", "completed"), ("  ", "completed"), ("Partial draft", "incomplete")])
def test_empty_or_incomplete_output_is_not_reported_as_ai_generated(text, status):
    result = _brain_tumor_report_model_response(
        SimpleNamespace(output_text=text, status=status), model="test-model", local_draft="Measured local draft",
    )
    assert result["generated"] is False
    assert result["provider_status"] == "local_fallback"
    assert result["report_text"] == "Measured local draft"


def test_complete_model_output_is_preserved():
    result = _brain_tumor_report_model_response(
        SimpleNamespace(output_text="  Complete draft  ", status="completed"), model="test-model", local_draft="Local",
    )
    assert result["generated"] is True
    assert result["report_text"] == "Complete draft"
    assert result["model"] == "test-model"


def test_clinical_timing_stays_out_of_external_ai_payload():
    from clinagent.gateway.server import _brain_tumor_external_report_payload
    measurements = {"ET_mm3": 50, "scan_date": "2024-01-01", "relative_day": 56.40625,
                    "relative_day_origin": "diagnosis", "interval_days": 12, "days_from_reference": 12}
    result = _brain_tumor_external_report_payload({"date": "2024-01-01", "active_measurements": measurements, "timepoints": [measurements]})
    assert result["active_measurements"] == {"ET_mm3": 50}
    assert result["timepoints"] == [{"visit_index": 1, "ET_mm3": 50}]
