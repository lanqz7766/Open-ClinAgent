from __future__ import annotations

from typing import Any

from clinagent.platform.config import load_settings
from clinagent.connectors.factory import build_connector_bundle
from clinagent.families.neuro.report_demo import neuro_report_demo_store
from clinagent.platform.mcp_registry import (
    build_mcp_registry_snapshot,
    list_mcp_servers,
    list_mcp_servers_for_family,
    list_mcp_servers_for_workflow,
)
from clinagent.platform.memory_harness import (
    build_memory_context,
    build_reviewed_memory_context,
    derive_reviewed_memory_defaults,
    get_proposed_pattern_memory,
    get_reviewed_pattern_memory,
    summarize_memory_context,
)
from clinagent.platform.capabilities import evaluate_neuro_workflow_capability, get_model_capability
from clinagent.platform.family_registry import (
    get_family_registry_entry,
    get_workflow_registry_entry,
    list_family_registry,
    list_workflow_registry,
)
from clinagent.families.shared.report_quality_demo import report_quality_demo_store

try:
    from fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - optional dependency path
    raise SystemExit(
        "fastmcp is not installed. Install ClinAgent with the optional 'mcp' extra to run the neuro context server."
    ) from exc


mcp = FastMCP("clinagent-neuro-context")


def _connector_bundle():
    settings = load_settings()
    return build_connector_bundle(settings)


@mcp.tool()
def lookup_patient(patient_id: str) -> dict[str, Any]:
    """Return patient-level longitudinal metadata for a neuro demo patient."""
    return neuro_report_demo_store.get_patient_data(patient_id)


@mcp.tool()
def lookup_study(patient_id: str, study_id: str) -> dict[str, Any]:
    """Return study detail, report, viewer assets, and volumetrics for a specific MRI study."""
    return neuro_report_demo_store.get_study_detail(patient_id, study_id)


@mcp.tool()
def lookup_demographics(patient_id: str) -> dict[str, Any]:
    """Return a compact patient demographic summary for the active neuro timeline."""
    patient = neuro_report_demo_store.get_patient_data(patient_id)["patient"]
    return {
        "patient_id": patient["id"],
        "name": patient["name"],
        "age": patient["age"],
        "sex": patient["sex"],
        "study_count": patient["study_count"],
        "date_range": patient["date_range"],
    }


@mcp.tool()
def lookup_prior_reports(patient_id: str) -> dict[str, Any]:
    """Return report sections for all studies in a patient timeline."""
    patient_data = neuro_report_demo_store.get_patient_data(patient_id)
    reports: list[dict[str, Any]] = []
    for study in patient_data["studies"]:
        detail = neuro_report_demo_store.get_study_detail(patient_id, study["study_id"])
        reports.append(
            {
                "study_id": study["study_id"],
                "study_date": study["study_date"],
                "report_sections": detail["report"]["sections"],
            }
        )
    return {"patient_id": patient_id, "reports": reports}


@mcp.tool()
def lookup_planning_result(patient_id: str, study_id: str) -> dict[str, Any]:
    """Return the planning result, analysis plan, and capability summaries for a study."""
    detail = neuro_report_demo_store.get_study_detail(patient_id, study_id)
    return {
        "patient_id": patient_id,
        "study_id": study_id,
        "planning_result": detail.get("planning_result"),
        "analysis_plan": detail.get("analysis_plan"),
        "analysis_plan_summary": detail.get("analysis_plan_summary"),
        "capability_profile": detail.get("capability_profile"),
        "capability_profile_summary": detail.get("capability_profile_summary"),
        "viewer_assets": detail.get("viewer_assets"),
    }


@mcp.tool()
async def lookup_dicom_metadata(study_instance_uid: str, series_instance_uid: str | None = None) -> dict[str, Any]:
    """Return DICOMweb metadata for a study or a specific series."""
    connectors = _connector_bundle()
    if series_instance_uid:
        return await connectors.imaging.get_series_metadata(
            study_instance_uid=study_instance_uid,
            series_instance_uid=series_instance_uid,
        )
    metadata = await connectors.imaging.get_study_metadata(study_instance_uid)
    return metadata.model_dump()


@mcp.tool()
def lookup_analysis_session(session_id: str) -> dict[str, Any]:
    """Return the stored analysis session payload for a prior neuro-report run."""
    return neuro_report_demo_store.get_session(session_id)


@mcp.tool()
def lookup_report_quality_case(case_id: str) -> dict[str, Any]:
    """Return report-quality workspace data, planning, and rendered review output for a case."""
    return report_quality_demo_store.get_case(case_id)


@mcp.tool()
def lookup_report_quality_planning(case_id: str) -> dict[str, Any]:
    """Return planning and capability metadata for a report-quality case."""
    case = report_quality_demo_store.get_case(case_id)
    return {
        "case_id": case_id,
        "planning_result": case.get("planning_result"),
        "analysis_plan": case.get("analysis_plan"),
        "analysis_plan_summary": case.get("analysis_plan_summary"),
        "capability_profile": case.get("capability_profile"),
        "capability_profile_summary": case.get("capability_profile_summary"),
        "workspace_contract": case.get("workspace_contract"),
    }


@mcp.tool()
def lookup_workflow_capabilities(
    imaging_format: str,
    has_single_study_mri: bool,
    has_segmentation: bool,
    has_demographics: bool,
    has_longitudinal_priors: bool = False,
    lesion_context: bool = False,
) -> dict[str, Any]:
    """Return the allowed neuro workflow modes for a given input capability set."""
    capability = evaluate_neuro_workflow_capability(
        has_single_study_mri=has_single_study_mri,
        imaging_format=imaging_format,
        has_segmentation=has_segmentation,
        has_demographics=has_demographics,
        has_longitudinal_priors=has_longitudinal_priors,
        lesion_context=lesion_context,
    )
    return capability.to_dict()


@mcp.tool()
def lookup_model_capabilities(model_name: str) -> dict[str, Any]:
    """Return the registered capability summary for a chat or neuro model."""
    return get_model_capability(model_name).to_dict()


@mcp.tool()
def lookup_family_registry(family_id: str | None = None) -> dict[str, Any]:
    """Return the family-first harness registry or a specific family entry."""
    if family_id:
        return {"family": get_family_registry_entry(family_id)}
    return {"families": list_family_registry()}


@mcp.tool()
def lookup_workflow_registry(workflow_id: str | None = None, family_id: str | None = None) -> dict[str, Any]:
    """Return the workflow registry or a specific workflow entry."""
    if workflow_id:
        return {"workflow": get_workflow_registry_entry(workflow_id)}
    return {"workflows": list_workflow_registry(family_id=family_id)}


@mcp.tool()
def lookup_mcp_registry() -> dict[str, Any]:
    """Return the registered MCP/local context servers known to the ClinAgent harness."""
    return {"servers": list_mcp_servers()}


@mcp.tool()
def lookup_workflow_mcp_registry(workflow_id: str) -> dict[str, Any]:
    """Return MCP/local context servers available to a specific workflow."""
    return {"workflow_id": workflow_id, "servers": list_mcp_servers_for_workflow(workflow_id)}


@mcp.tool()
def lookup_family_mcp_registry(workflow_family: str) -> dict[str, Any]:
    """Return MCP/local context servers available to a workflow family."""
    return {
        "workflow_family": workflow_family,
        "servers": list_mcp_servers_for_family(workflow_family),
        "snapshot": build_mcp_registry_snapshot(workflow_family=workflow_family),
    }


@mcp.tool()
def lookup_memory_context(
    workflow_id: str,
    workflow_family: str,
    user_id: str | None = None,
    session_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    memory_key: str | None = None,
    reviewed_pattern_id: str | None = None,
) -> dict[str, Any]:
    """Return the structured four-layer memory context used for harness retrieval."""
    context = build_reviewed_memory_context(
        workflow_family=workflow_family,
        reviewed_pattern_ids=[reviewed_pattern_id] if reviewed_pattern_id else [],
        entity_keys=[(entity_type, entity_id)] if entity_type and entity_id else [],
        workflow_keys=[(workflow_id, memory_key)] if memory_key else [],
        user_id=user_id,
        session_id=session_id,
    )
    return {
        "workflow_id": workflow_id,
        "workflow_family": workflow_family,
        "summary": summarize_memory_context(context),
        "memory_context": context,
        "reviewed_defaults": derive_reviewed_memory_defaults(context),
    }


@mcp.tool()
def lookup_pattern_memory(workflow_family: str, pattern_id: str) -> dict[str, Any]:
    """Return proposed and reviewed workflow patterns for a family-level heuristic id."""
    return {
        "workflow_family": workflow_family,
        "pattern_id": pattern_id,
        "proposed_pattern": get_proposed_pattern_memory(workflow_family, pattern_id),
        "reviewed_pattern": get_reviewed_pattern_memory(workflow_family, pattern_id),
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
