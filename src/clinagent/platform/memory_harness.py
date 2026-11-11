from __future__ import annotations

from functools import lru_cache
from typing import Any

from clinagent.platform.config import load_settings
from clinagent.platform.store import SQLiteStore


MEMORY_SUMMARY_LIMIT = 6
MEMORY_RETRIEVAL_ORDER = ["entity", "workflow", "user", "session"]


@lru_cache(maxsize=1)
def get_harness_memory_store() -> SQLiteStore:
    settings = load_settings()
    return SQLiteStore(settings.database_path)


def save_user_memory(user_id: str, payload: dict[str, Any]) -> None:
    get_harness_memory_store().save_user_memory(user_id=user_id, payload=payload)


def get_user_memory(user_id: str) -> dict[str, Any] | None:
    return get_harness_memory_store().get_user_memory(user_id)


def save_session_memory(session_id: str, workflow_id: str, payload: dict[str, Any]) -> None:
    get_harness_memory_store().save_session_memory(session_id=session_id, workflow_id=workflow_id, payload=payload)


def get_session_memory(session_id: str) -> dict[str, Any] | None:
    return get_harness_memory_store().get_session_memory(session_id)


def save_workflow_memory(workflow_id: str, memory_key: str, payload: dict[str, Any]) -> None:
    get_harness_memory_store().save_workflow_memory(workflow_id=workflow_id, memory_key=memory_key, payload=payload)


def get_workflow_memory(workflow_id: str, memory_key: str) -> dict[str, Any] | None:
    return get_harness_memory_store().get_workflow_memory(workflow_id, memory_key)


def save_entity_memory(entity_type: str, entity_id: str, payload: dict[str, Any]) -> None:
    get_harness_memory_store().save_entity_memory(entity_type=entity_type, entity_id=entity_id, payload=payload)


def get_entity_memory(entity_type: str, entity_id: str) -> dict[str, Any] | None:
    return get_harness_memory_store().get_entity_memory(entity_type, entity_id)


def save_proposed_pattern_memory(workflow_family: str, pattern_id: str, payload: dict[str, Any]) -> None:
    get_harness_memory_store().save_proposed_pattern_memory(
        workflow_family=workflow_family,
        pattern_id=pattern_id,
        payload=payload,
    )


def get_proposed_pattern_memory(workflow_family: str, pattern_id: str) -> dict[str, Any] | None:
    return get_harness_memory_store().get_proposed_pattern_memory(workflow_family, pattern_id)


def save_reviewed_pattern_memory(workflow_family: str, pattern_id: str, payload: dict[str, Any]) -> None:
    get_harness_memory_store().save_reviewed_pattern_memory(
        workflow_family=workflow_family,
        pattern_id=pattern_id,
        payload=payload,
    )


def get_reviewed_pattern_memory(workflow_family: str, pattern_id: str) -> dict[str, Any] | None:
    return get_harness_memory_store().get_reviewed_pattern_memory(workflow_family, pattern_id)


def build_memory_context(
    *,
    entity_keys: list[tuple[str, str]] | None = None,
    workflow_keys: list[tuple[str, str]] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    entity_items: list[dict[str, Any]] = []
    workflow_items: list[dict[str, Any]] = []

    for entity_type, entity_id in entity_keys or []:
        payload = get_entity_memory(entity_type, entity_id)
        if payload:
            entity_items.append(
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "updated_at": payload.get("updated_at"),
                    "payload": payload.get("payload"),
                }
            )
    for workflow_id, memory_key in workflow_keys or []:
        payload = get_workflow_memory(workflow_id, memory_key)
        if payload:
            workflow_items.append(
                {
                    "workflow_id": workflow_id,
                    "memory_key": memory_key,
                    "updated_at": payload.get("updated_at"),
                    "payload": payload.get("payload"),
                }
            )

    user_item = get_user_memory(user_id) if user_id else None
    session_item = get_session_memory(session_id) if session_id else None
    return {
        "retrieval_order": MEMORY_RETRIEVAL_ORDER.copy(),
        "entity_memory": entity_items[:MEMORY_SUMMARY_LIMIT],
        "workflow_memory": workflow_items[:MEMORY_SUMMARY_LIMIT],
        "user_memory": user_item,
        "session_memory": session_item,
    }


def summarize_memory_context(memory_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "retrieval_order": list(memory_context.get("retrieval_order", [])),
        "entity_memory_count": len(memory_context.get("entity_memory", [])),
        "workflow_memory_count": len(memory_context.get("workflow_memory", [])),
        "has_user_memory": memory_context.get("user_memory") is not None,
        "has_session_memory": memory_context.get("session_memory") is not None,
    }


def build_reviewed_memory_context(
    *,
    workflow_family: str,
    reviewed_pattern_ids: list[str] | None = None,
    entity_keys: list[tuple[str, str]] | None = None,
    workflow_keys: list[tuple[str, str]] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    memory_context = build_memory_context(
        entity_keys=entity_keys,
        workflow_keys=workflow_keys,
        user_id=user_id,
        session_id=session_id,
    )
    reviewed_patterns: list[dict[str, Any]] = []
    for pattern_id in reviewed_pattern_ids or []:
        payload = get_reviewed_pattern_memory(workflow_family, pattern_id)
        if payload:
            reviewed_patterns.append(
                {
                    "workflow_family": workflow_family,
                    "pattern_id": pattern_id,
                    "updated_at": payload.get("updated_at"),
                    "payload": payload.get("payload"),
                }
            )
    memory_context["reviewed_pattern_memory"] = reviewed_patterns[:MEMORY_SUMMARY_LIMIT]
    return memory_context


def derive_reviewed_memory_defaults(memory_context: dict[str, Any]) -> dict[str, Any]:
    user_payload = (memory_context.get("user_memory") or {}).get("payload") or {}
    session_payload = (memory_context.get("session_memory") or {}).get("payload") or {}
    workflow_payloads = [
        item.get("payload") or {}
        for item in memory_context.get("workflow_memory", [])
    ]
    reviewed_payloads = [
        item.get("payload") or {}
        for item in memory_context.get("reviewed_pattern_memory", [])
    ]

    preferred_dashboard_profile = user_payload.get("preferred_dashboard_profile")
    autorun_examples = user_payload.get("autorun_examples")
    output_style = user_payload.get("output_style")
    review_lane_default_open = bool(user_payload.get("review_lane_default_open", False))

    reviewed_tool_bundles = [
        {
            "pattern_id": item.get("pattern_id"),
            "tool_bundle": list((item.get("payload") or {}).get("tool_bundle", [])),
            "dashboard_profile": (item.get("payload") or {}).get("dashboard_profile"),
        }
        for item in memory_context.get("reviewed_pattern_memory", [])
    ]
    if not preferred_dashboard_profile:
        for payload in reviewed_payloads:
            dashboard = payload.get("dashboard_profile")
            if isinstance(dashboard, str) and dashboard:
                preferred_dashboard_profile = dashboard
                break
    if autorun_examples is None:
        autorun_examples = bool(session_payload.get("autorun_examples", False))
    if not output_style:
        for payload in workflow_payloads:
            value = payload.get("output_style")
            if isinstance(value, str) and value:
                output_style = value
                break
    if not review_lane_default_open:
        review_lane_default_open = any(bool(payload.get("review_lane_default_open")) for payload in reviewed_payloads)

    return {
        "preferred_dashboard_profile": preferred_dashboard_profile,
        "autorun_examples": bool(autorun_examples),
        "review_lane_default_open": review_lane_default_open,
        "output_style": output_style or "structured_clinical",
        "reviewed_tool_bundles": reviewed_tool_bundles,
        "retrieval_order": list(memory_context.get("retrieval_order", MEMORY_RETRIEVAL_ORDER)),
    }
