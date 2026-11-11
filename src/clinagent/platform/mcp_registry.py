from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MCPServerRegistration:
    server_id: str
    label: str
    description: str
    workflows: tuple[str, ...]
    workflow_families: tuple[str, ...]
    tool_names: tuple[str, ...]
    transport: str
    availability: str
    health_status: str = "healthy"
    discovery_mode: str = "static_registry"

    def to_summary(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["workflows"] = list(self.workflows)
        payload["workflow_families"] = list(self.workflow_families)
        payload["tool_names"] = list(self.tool_names)
        return payload


@dataclass(frozen=True)
class McpRegistrySnapshot:
    workflow_family: str
    workflow_id: str | None
    servers: tuple[dict[str, Any], ...]
    tool_names: tuple[str, ...]
    availability: str

    def to_summary(self) -> dict[str, Any]:
        return {
            "workflow_family": self.workflow_family,
            "workflow_id": self.workflow_id,
            "servers": [dict(item) for item in self.servers],
            "tool_names": list(self.tool_names),
            "availability": self.availability,
        }


MCP_SERVER_REGISTRY: dict[str, MCPServerRegistration] = {
    "neuro_context": MCPServerRegistration(
        server_id="neuro_context",
        label="Neuro Context Server",
        description="Provides patient, study, planning, capability, and DICOM metadata lookup for neuro workflows.",
        workflows=("neuro_report", "neuro_longitudinal"),
        workflow_families=("neuro",),
        tool_names=(
            "lookup_patient",
            "lookup_study",
            "lookup_demographics",
            "lookup_prior_reports",
            "lookup_planning_result",
            "lookup_dicom_metadata",
            "lookup_analysis_session",
            "lookup_workflow_capabilities",
            "lookup_model_capabilities",
            "lookup_memory_context",
            "lookup_pattern_memory",
        ),
        transport="mcp",
        availability="registered",
    ),
    "report_quality_local": MCPServerRegistration(
        server_id="report_quality_local",
        label="Report Quality Local Context",
        description="Exposes local demo-store report quality context and planning metadata for policy-check workflows.",
        workflows=("report_quality_review",),
        workflow_families=("review",),
        tool_names=(
            "lookup_report_quality_case",
            "lookup_report_quality_planning",
            "lookup_memory_context",
            "lookup_pattern_memory",
        ),
        transport="local",
        availability="registered",
    ),
    "radonc_context": MCPServerRegistration(
        server_id="radonc_context",
        label="RadOnc Planning Context",
        description="Planned family-level context surface for dose prediction, plan review, structures, and treatment-course metadata.",
        workflows=("radonc_plan_optimization",),
        workflow_families=("radonc",),
        tool_names=(
            "lookup_rt_plan",
            "lookup_rt_dose",
            "lookup_rt_structures",
            "lookup_treatment_course",
            "lookup_protocol_template",
        ),
        transport="planned",
        availability="planned",
        health_status="planned",
        discovery_mode="family_placeholder",
    ),
}


def list_mcp_servers() -> list[dict[str, Any]]:
    return [item.to_summary() for item in MCP_SERVER_REGISTRY.values()]


def list_mcp_servers_for_workflow(workflow_id: str) -> list[dict[str, Any]]:
    return [
        item.to_summary()
        for item in MCP_SERVER_REGISTRY.values()
        if workflow_id in item.workflows
    ]


def list_mcp_servers_for_family(workflow_family: str) -> list[dict[str, Any]]:
    return [
        item.to_summary()
        for item in MCP_SERVER_REGISTRY.values()
        if workflow_family in item.workflow_families
    ]


def build_mcp_registry_snapshot(
    *,
    workflow_id: str | None = None,
    workflow_family: str | None = None,
) -> dict[str, Any]:
    family = workflow_family or "general"
    server_map: dict[str, dict[str, Any]] = {}
    if family:
        for server in list_mcp_servers_for_family(family):
            server_map[server["server_id"]] = server
    if workflow_id:
        for server in list_mcp_servers_for_workflow(workflow_id):
            server_map[server["server_id"]] = server

    servers = list(server_map.values())
    tool_names = sorted({tool for server in servers for tool in server.get("tool_names", [])})
    availability = "registered" if servers else "none"
    return McpRegistrySnapshot(
        workflow_family=family,
        workflow_id=workflow_id,
        servers=tuple(servers),
        tool_names=tuple(tool_names),
        availability=availability,
    ).to_summary()


def build_context_availability_summary(
    *,
    workflow_id: str | None = None,
    workflow_family: str | None = None,
) -> list[dict[str, Any]]:
    snapshot = build_mcp_registry_snapshot(workflow_id=workflow_id, workflow_family=workflow_family)
    return [
        {
            "server_id": server["server_id"],
            "label": server["label"],
            "available": server.get("availability") == "registered",
            "availability": server.get("availability"),
            "health_status": server.get("health_status", "healthy"),
            "workflow_families": list(server.get("workflow_families", [])),
            "tool_names": list(server.get("tool_names", [])),
        }
        for server in snapshot.get("servers", [])
    ]
