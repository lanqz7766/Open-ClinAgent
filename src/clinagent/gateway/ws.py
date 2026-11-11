"""
WebSocket handler for the ClinAgents gateway (FastAPI native).

Supports:
  - chat.send    — run an agent task with real-time streaming events
  - chat.history — retrieve session history
  - chat.inject  — inject an assistant note without triggering a run
  - ping         — keepalive
"""

from __future__ import annotations

import json
import time
import math
import secrets
import os
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query

from clinagent.gateway.protocol import is_valid_request, make_response, make_event
from clinagent.gateway.auth import SESSION_COOKIE_NAME
from clinagent.platform.runtime_bridge import CommandLane, create_agent, enqueue_command_in_lane, get_queue_size

VALID_LANES = {"main", "cron", "subagent", "nested"}

_sessions: dict[str, dict] = {}


def websocket_origin_allowed(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin", "").rstrip("/")
    if not origin:
        return False
    configured = os.getenv("CLINAGENT_CORS_ORIGINS", os.getenv("GATEWAY_CORS_ORIGINS", ""))
    trusted = {value.strip().rstrip("/") for value in configured.split(",") if value.strip() != "*"}
    public_url = os.getenv("CLINAGENT_PUBLIC_URL", "").strip().rstrip("/")
    if public_url:
        trusted.add(public_url)
    proto = ws.headers.get("x-forwarded-proto", "https" if ws.url.scheme == "wss" else "http").split(",", 1)[0].strip()
    trusted.add(f"{proto}://{ws.headers.get('host', '')}")
    return origin in trusted


def _resolve_lane(raw: str | None) -> str:
    lane = (raw or "").strip().lower() or CommandLane.Main.value
    return lane if lane in VALID_LANES else CommandLane.Main.value


def _resolve_session(raw: str | None) -> str:
    if raw and raw.strip():
        return raw.strip()
    return f"ws-{int(time.time())}-{secrets.token_hex(4)}"


def _session_key(session_id: str, owner_id: str) -> str:
    return f"{owner_id}:{session_id}"


def _get_or_create_session(session_id: str, owner_id: str) -> dict:
    key = _session_key(session_id, owner_id)
    if key not in _sessions:
        _sessions[key] = {"messages": []}
    return _sessions[key]


def attach_websocket(
    app: FastAPI,
    llm: Any,
    gateway_api_key: str,
    clinagent: Any | None = None,
    auth_store: Any | None = None,
):
    """Register the /ws WebSocket endpoint on the FastAPI app."""

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket, token: str = Query(default="")):
        if os.getenv("CLINAGENT_PREVIEW_SCOPE", "").strip().lower() == "brain_tumor":
            await ws.close(code=4003, reason="Unavailable in this preview")
            return
        if gateway_api_key and token != gateway_api_key:
            await ws.close(code=4001, reason="Unauthorized")
            return
        user = auth_store.user_from_token(ws.cookies.get(SESSION_COOKIE_NAME)) if auth_store is not None else None
        if auth_store is not None and auth_store.require_user_auth and user is None:
            await ws.close(code=4001, reason="Authentication required")
            return
        if auth_store is not None and auth_store.require_user_auth:
            if not websocket_origin_allowed(ws) or user.get("role") != "admin" or user.get("account_setup_required"):
                await ws.close(code=4003, reason="Operator access required")
                return
        owner_id = str(user["id"]) if user else "anonymous"

        await ws.accept()

        try:
            while True:
                raw = await ws.receive_text()
                if auth_store is not None and auth_store.require_user_auth and auth_store.user_from_token(ws.cookies.get(SESSION_COOKIE_NAME)) is None:
                    await ws.close(code=4001, reason="Session expired")
                    return
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send_json(make_response("?", False, "Invalid JSON"))
                    continue

                if not is_valid_request(msg):
                    await ws.send_json(make_response("?", False, "Invalid frame"))
                    continue

                method = msg["method"]
                if method == "ping":
                    await ws.send_json(make_response(msg["id"], True, {"pong": int(time.time() * 1000)}))

                elif method == "chat.send":
                    await _handle_chat_send(ws, msg, llm, clinagent, owner_id)

                elif method == "chat.history":
                    _handle_chat_history_sync(ws, msg)
                    await ws.send_json(_chat_history_response(msg, owner_id))

                elif method == "chat.inject":
                    resp = _handle_chat_inject(msg, owner_id)
                    await ws.send_json(resp)

                else:
                    await ws.send_json(make_response(msg["id"], False, f"Unknown method: {method}"))

        except WebSocketDisconnect:
            pass

    print("   WebSocket: enabled on ws:// /ws")


async def _handle_chat_send(
    ws: WebSocket,
    msg: dict,
    llm: Any,
    clinagent: Any | None = None,
    owner_id: str = "anonymous",
):
    params = msg["params"]
    task = str(params.get("task", ""))
    if not task:
        await ws.send_json(make_response(msg["id"], False, "Missing 'task' parameter"))
        return

    lane = _resolve_lane(params.get("lane"))
    scenario_id = params.get("scenario_id") or params.get("scenarioId")
    requested_by = params.get("requested_by") or params.get("requestedBy") or "ws-chat"
    case_id = params.get("case_id") or params.get("caseId")
    external_patient_id = params.get("external_patient_id") or params.get("externalPatientId")
    note = params.get("note")
    session_id = _resolve_session(params.get("sessionId"))
    session = _get_or_create_session(session_id, owner_id)

    seq = 0

    async def send_event(event: str, payload: dict):
        nonlocal seq
        await ws.send_json(make_event(event, {**payload, "sessionId": session_id}, seq))
        seq += 1

    await send_event("queued", {"lane": lane, "position": get_queue_size(lane), "scenario_id": scenario_id})

    try:
        async def _execute():
            await send_event("started", {"lane": lane, "scenario_id": scenario_id})
            if scenario_id:
                if clinagent is None or not clinagent.get_scenario(scenario_id):
                    raise ValueError(f"Unknown scenario_id: {scenario_id}")

                async def on_event(kind, data):
                    await send_event("agent", {"kind": kind, **(data if isinstance(data, dict) else {"data": data})})

                return await clinagent.invoke_scenario(
                    task=task,
                    scenario_id=scenario_id,
                    llm=llm,
                    requested_by=requested_by,
                    case_id=case_id,
                    external_patient_id=external_patient_id,
                    note=note,
                    on_event=on_event,
                )

            agent = create_agent(model=llm)

            async def on_event(kind, data):
                await send_event("agent", {"kind": kind, **(data if isinstance(data, dict) else {"data": data})})

            return await agent.invoke(task, on_event=on_event)

        result = await enqueue_command_in_lane(lane, _execute)

        now_ms = int(time.time() * 1000)
        session["messages"].append({"role": "user", "content": task, "timestamp": now_ms, "scenarioId": scenario_id})
        if scenario_id:
            session["messages"].append({"role": "assistant", "content": result.result.result or "", "timestamp": now_ms, "scenarioId": scenario_id})
            success = result.result.status != "reauth_required"
            await ws.send_json(make_response(msg["id"], success, {
                "sessionId": session_id,
                "lane": lane,
                "scenarioId": result.scenario.id,
                "taskRunId": result.task_run_id,
                "reviewRequired": result.review_required,
                "artifactIds": result.artifact_ids,
                "accessEventIds": result.access_event_ids,
                "status": result.result.status,
                "result": result.result.result,
                "iterations": result.result.iterations,
            }))
        else:
            session["messages"].append({"role": "assistant", "content": result.result or "", "timestamp": now_ms})
            await ws.send_json(make_response(msg["id"], True, {
                "sessionId": session_id,
                "lane": lane,
                "status": result.status,
                "result": result.result,
                "iterations": result.iterations,
            }))
    except Exception as e:
        await ws.send_json(make_response(msg["id"], False, str(e)))


def _chat_history_response(msg: dict, owner_id: str = "anonymous") -> dict:
    session_id = _resolve_session(msg["params"].get("sessionId"))
    session = _sessions.get(_session_key(session_id, owner_id))
    return make_response(msg["id"], True, {
        "sessionId": session_id,
        "messages": session["messages"] if session else [],
    })


def _handle_chat_history_sync(ws: WebSocket, msg: dict):
    pass  # response built by _chat_history_response


def _handle_chat_inject(msg: dict, owner_id: str = "anonymous") -> dict:
    params = msg["params"]
    session_id = _resolve_session(params.get("sessionId"))
    content = str(params.get("content", ""))
    if not content:
        return make_response(msg["id"], False, "Missing 'content' parameter")
    session = _get_or_create_session(session_id, owner_id)
    session["messages"].append({"role": "assistant", "content": content, "timestamp": int(time.time() * 1000)})
    return make_response(msg["id"], True, {"sessionId": session_id, "injected": True})
