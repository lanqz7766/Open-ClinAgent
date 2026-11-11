from __future__ import annotations

import re
from typing import Any

from clinagent.platform.memory_harness import get_session_memory, save_session_memory

_SESSION_HISTORY_LIMIT = 6

_FOLLOW_UP_PREFIXES = (
    "and ",
    "also ",
    "what about",
    "how about",
    "then ",
    "next ",
    "can you ",
    "could you ",
    "please ",
    "why ",
    "what if",
)

_FOLLOW_UP_EXACT = {
    "continue",
    "go on",
    "more",
    "again",
    "same",
    "same one",
    "that one",
    "this one",
    "it",
    "them",
    "those",
}

_EXPLICIT_SWITCH_MARKERS = (
    "different question",
    "switch topic",
    "new question",
    "unrelated",
    "another thing",
)


def load_session_intent_state(session_id: str | None) -> dict[str, Any] | None:
    if not session_id:
        return None
    item = get_session_memory(session_id)
    if not item:
        return None
    payload = item.get("payload")
    return payload if isinstance(payload, dict) else None


def is_follow_up_message(message: str) -> bool:
    lowered = re.sub(r"\s+", " ", message.strip().lower())
    if not lowered:
        return False
    if any(marker in lowered for marker in _EXPLICIT_SWITCH_MARKERS):
        return False
    if lowered in _FOLLOW_UP_EXACT:
        return True
    if any(lowered.startswith(prefix) for prefix in _FOLLOW_UP_PREFIXES):
        return True
    words = lowered.split()
    if len(words) <= 8 and any(token in {"this", "that", "it", "them", "those", "again", "more"} for token in words):
        return True
    return False


def build_session_router_context(session_state: dict[str, Any] | None) -> str:
    if not session_state:
        return "None"
    recent_messages = session_state.get("recent_user_messages") or []
    recent_routes = session_state.get("recent_routes") or []
    lines = [
        f"active_workflow_id: {session_state.get('active_workflow_id') or 'none'}",
        f"active_intent_label: {session_state.get('active_intent_label') or 'none'}",
        f"conversation_mode: {session_state.get('conversation_mode') or 'general_chat'}",
        f"last_confidence: {session_state.get('last_confidence') or 0.0}",
    ]
    if recent_messages:
        lines.append("recent_user_messages:")
        lines.extend(f"- {str(item)}" for item in recent_messages[-3:])
    if recent_routes:
        lines.append("recent_routes:")
        for item in recent_routes[-3:]:
            if not isinstance(item, dict):
                continue
            lines.append(
                "- "
                f"{item.get('workflow_id', 'unknown')} "
                f"({item.get('intent_label', 'unknown intent')}, confidence={item.get('confidence', 0.0)})"
            )
    return "\n".join(lines)


def should_bias_to_session_workflow(
    message: str,
    session_state: dict[str, Any] | None,
) -> bool:
    if not session_state:
        return False
    active_workflow_id = str(session_state.get("active_workflow_id") or "").strip()
    if not active_workflow_id or active_workflow_id == "general_chat":
        return False
    last_confidence = float(session_state.get("last_confidence") or 0.0)
    if last_confidence < 0.6:
        return False
    return is_follow_up_message(message)


def persist_session_intent_state(
    session_id: str | None,
    message: str,
    route: dict[str, Any],
) -> None:
    if not session_id:
        return

    existing_state = load_session_intent_state(session_id) or {}
    workflow_id = str(route.get("workflow_id") or "general_chat").strip() or "general_chat"
    intent_label = str(route.get("intent_label") or workflow_id).strip() or workflow_id
    target_module = str(route.get("target_module") or "home").strip() or "home"
    conversation_mode = "workflow" if workflow_id != "general_chat" else "general_chat"

    recent_messages = [
        str(item).strip()
        for item in existing_state.get("recent_user_messages", [])
        if str(item).strip()
    ]
    if message.strip():
        recent_messages.append(message.strip())

    recent_routes = [
        item
        for item in existing_state.get("recent_routes", [])
        if isinstance(item, dict)
    ]
    recent_routes.append(
        {
            "workflow_id": workflow_id,
            "intent_label": intent_label,
            "confidence": round(float(route.get("confidence") or 0.0), 4),
            "target_module": target_module,
            "needs_clarification": bool(route.get("needs_clarification", False)),
        }
    )

    payload = dict(existing_state)
    payload.update(
        {
            "active_workflow_id": workflow_id,
            "active_intent_label": intent_label,
            "conversation_mode": conversation_mode,
            "last_confidence": round(float(route.get("confidence") or 0.0), 4),
            "last_target_module": target_module,
            "last_reason": str(route.get("reason") or "").strip(),
            "needs_clarification": bool(route.get("needs_clarification", False)),
            "recent_user_messages": recent_messages[-_SESSION_HISTORY_LIMIT:],
            "recent_routes": recent_routes[-_SESSION_HISTORY_LIMIT:],
        }
    )
    save_session_memory(session_id=session_id, workflow_id=workflow_id, payload=payload)
