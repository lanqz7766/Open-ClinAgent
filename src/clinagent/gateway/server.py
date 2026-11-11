import asyncio
import json
import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urlencode, urlparse
import uuid

import httpx
from fastapi import FastAPI, File, Form, Query, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from clinagent.gateway.api.ingest import router as ingest_router
from clinagent.bundled_resources import workspace_root
from clinagent.gateway.auth import SESSION_COOKIE_NAME, ClinAgentAuthStore, RateLimitExceeded
from clinagent.gateway.account_management import account_management_router
from clinagent.gateway.neuro_access import NeuroAccess, public_neuro_payload
from clinagent.gateway.build_info import public_build_info
from clinagent.gateway.email_delivery import ClinAgentEmailSender
from clinagent.gateway.ws import attach_websocket, websocket_origin_allowed
from clinagent.console.demo import demo_workspace_store
from clinagent.platform.config import load_settings
from clinagent.families.neuro.config import NeuroAgentConfig
from clinagent.families.neuro.intake import build_planning_result, intake_plan_from_message
from clinagent.console.workspace import console_snapshot, dev_console_snapshot, route_general_query
from clinagent.console.agent import build_console_agent, build_routed_task, get_smalltalk_reply, route_with_llm
from clinagent.console.intent_session import persist_session_intent_state
from clinagent.families.findings.workspace import findings_closure_store
from clinagent.families.diagnosis.workspace import missed_diagnosis_store
from clinagent.families.queue.workspace import queue_triage_store
from clinagent.families.radonc import radonc_plan_demo_store
from clinagent.families.radonc.connectors import AirtMockPlanningConnector, MockRTPlanningConnector
from clinagent.families.radonc.engine import (
    OptimizationOrchestrator,
    apply_planner_command_update,
    build_goal_statuses,
    build_objective_results,
    build_reference_comparison,
)
from clinagent.families.radonc.models import DVHSnapshot, ObjectiveResult, OptimizationIteration, PlannerCommand, PlanObjective
from clinagent.families.screening.workspace import screening_gap_store
from clinagent.families.safety.workspace import safety_monitor_store
from clinagent.families.neuro.evidence_review import VerifyEvidenceBoardRequest, verify_evidence_board
from clinagent.families.neuro.knowledge import MRRateKnowledgeServiceClient, MRRateLocalLaunchStore
from clinagent.families.neuro.knowledge.longitudinal import MRRateLongitudinalBuilder
from clinagent.platform.execution import ClinAgentService
from clinagent.platform.capabilities import MODEL_CAPABILITY_REGISTRY, get_model_capability
from clinagent.platform.execution_profiles import build_route_runtime, build_workflow_runtime_bundle
from clinagent.platform.family_registry import list_family_registry, list_workflow_registry
from clinagent.platform.memory_harness import build_reviewed_memory_context, derive_reviewed_memory_defaults
from clinagent.platform.mcp_registry import list_mcp_servers
from clinagent.families.shared.report_quality_intake import (
    build_report_quality_analysis_plan,
    build_report_quality_capability_profile,
    build_report_quality_planning_result,
    intake_plan_from_report_quality_message,
)
from clinagent.families.shared.report_quality_demo import report_quality_demo_store
from clinagent.families.radonc.intake import (
    build_radonc_planning_result,
    infer_radonc_context,
    intake_plan_from_radonc_message,
)
from clinagent.platform.runtime_bridge import (
    CommandLane,
    LLMMessage,
    create_agent,
    create_provider,
    enqueue_command_in_lane,
    get_active_task_count,
    get_default_model,
    get_queue_size,
    get_total_queue_size,
    load_config,
)

VALID_LANES = {"main", "cron", "subagent", "nested"}
VALID_REASONING_EFFORTS = {"low", "medium", "high"}
_GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_id_set(name: str) -> set[str]:
    return {item.strip() for item in os.getenv(name, "").split(",") if item.strip()}


@lru_cache(maxsize=1)
def _get_neuro_report_demo_components():
    from clinagent.families.neuro.report_demo import SUPPORTED_ANALYSIS_MODES, neuro_report_demo_store

    return SUPPORTED_ANALYSIS_MODES, neuro_report_demo_store


@lru_cache(maxsize=1)
def _get_brain_tumor_demo_store():
    from clinagent.families.neuro.brain_tumor_demo import brain_tumor_demo_store

    return brain_tumor_demo_store


def _resolve_lane(raw: str | None) -> str:
    lane = (raw or "").strip().lower() or CommandLane.Main.value
    return lane if lane in VALID_LANES else CommandLane.Main.value


def _check_auth(request: Request) -> bool:
    if not _GATEWAY_API_KEY:
        return True
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:] == _GATEWAY_API_KEY
    return request.headers.get("x-api-key", "") == _GATEWAY_API_KEY


def _requires_user_session(path: str) -> bool:
    protected_prefixes = (
        "/api/demo",
        "/api/dev",
        "/api/diagnosis",
        "/api/findings",
        "/api/ingest",
        "/api/neuro-knowledge",
        "/api/queue",
        "/api/report-quality",
        "/api/safety",
        "/api/screening",
        "/api/version",
    )
    public_prefixes = ("/api/auth", "/api/chat/options")
    if path.startswith(public_prefixes):
        return False
    return (
        path.startswith(protected_prefixes)
        or path.startswith("/neuro-assets")
        or path in {"/chat", "/chat/stream", "/queue"}
    )


def _audit_resource_for_path(path: str) -> str:
    if "/neuro-report" in path:
        return "neuro_report"
    if "/radonc-plan" in path:
        return "radonc_plan"
    if "/ingest" in path or "/upload" in path:
        return "data_ingest"
    if "/findings" in path:
        return "findings"
    if "/queue" in path:
        return "queue"
    if "/diagnosis" in path:
        return "diagnosis"
    if "/screening" in path:
        return "screening"
    if "/safety" in path:
        return "safety"
    if "/dev" in path:
        return "dev_console"
    return "workspace"


def _audit_action_for_request(method: str, path: str) -> str | None:
    if method == "GET" and path.endswith(".csv"):
        return "data_export"
    if method == "GET":
        return None
    if "execute-stream" in path or path.endswith("/chat"):
        return "agent_invocation"
    if "upload" in path or "ingest" in path or "analyze" in path:
        return "data_intake"
    if "review" in path:
        return "clinical_review"
    if "rerun" in path:
        return "workflow_rerun"
    if "explain" in path:
        return "explanation_request"
    return "workspace_action"


def _provider_available_for_model(config, model_name: str) -> bool:
    lower = model_name.lower()
    if lower.startswith("gemini"):
        return bool(config.gemini_api_key)
    if lower.startswith("claude") or lower.startswith("anthropic"):
        return bool(config.anthropic_api_key)
    return bool(config.openai_api_key or config.openai_base_url)


def _is_local_openai_base_url(base_url: str) -> bool:
    if not base_url:
        return False
    try:
        parsed = urlparse(base_url)
    except Exception:
        return False
    host = (parsed.hostname or "").strip().lower()
    return host in {"127.0.0.1", "localhost", "::1"}


async def _openai_compatible_base_url_ready(base_url: str) -> bool:
    if not base_url:
        return False
    url = base_url.rstrip("/")
    probe_url = f"{url}/models" if url.endswith("/v1") else f"{url}/v1/models"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(1.5, connect=0.5)) as client:
            response = await client.get(probe_url)
        return response.status_code < 500
    except Exception:
        return False


def _brain_tumor_report_local_fallback(local_draft: str, reason: str) -> dict[str, Any]:
    return {
        "ok": True,
        "generated": False,
        "report_text": local_draft,
        "model": "deterministic-local",
        "provider_status": "local_fallback",
        "warning": reason,
    }


def _brain_tumor_report_model_response(response: Any, *, model: str, local_draft: str) -> dict[str, Any]:
    text = str(getattr(response, "output_text", "") or "").strip()
    if not text or getattr(response, "status", "completed") != "completed":
        return _brain_tumor_report_local_fallback(
            local_draft,
            "Model draft was empty or incomplete; exported a deterministic local draft.",
        )
    return {"ok": True, "generated": True, "report_text": text, "model": model}


def _brain_tumor_report_count_line(label: str, value: dict[str, Any], noun: str) -> str:
    completed = value.get("completed_count")
    total = value.get("total_count")
    try:
        completed_int = int(completed)
        total_int = int(total)
    except (TypeError, ValueError):
        return f"- **{label}:** not available."
    if total_int <= 0:
        return f"- **{label}:** not available."
    return f"- **{label}:** {completed_int}/{total_int} {noun}."


def _brain_tumor_report_measurement_line(label: str, value: Any) -> str:
    rendered_value = value if value not in (None, "") else "--"
    return f"- **{label}:** {rendered_value} mm³"


def _brain_tumor_report_findings_text(findings: str, active: dict[str, Any]) -> str:
    cleaned = findings.strip()
    if active and "contrast-enhancing tumor" in cleaned.lower() and "t2/flair" in cleaned.lower():
        return "Selected scan has measurable enhancing and T2/FLAIR abnormality; exact volumes are listed above."
    return cleaned or "Selected quantitative imaging measurements are listed above. No additional narrative finding was supplied."


def _build_brain_tumor_local_report_draft(payload: dict[str, Any]) -> str:
    case_label = str(payload.get("case_label") or "GBM case")
    date_label = str(payload.get("date") or "unspecified date")
    qc_state = str(payload.get("qc_state") or "Pending")
    qc_reasons = payload.get("qc_reasons") if isinstance(payload.get("qc_reasons"), list) else []
    findings = str(payload.get("findings") or "")
    impression = str(payload.get("impression") or "")
    active = payload.get("active_measurements") if isinstance(payload.get("active_measurements"), dict) else {}
    segmentation = payload.get("segmentation") if isinstance(payload.get("segmentation"), dict) else {}
    alignment = payload.get("alignment") if isinstance(payload.get("alignment"), dict) else {}
    qc_reason_text = "; ".join(str(item) for item in qc_reasons) if qc_reasons else "None recorded"
    lines = [
        "**Case context:**",
        f"**Case:** {case_label}",
        f"**Scan:** {date_label}",
        f"**QC:** {qc_state}. Reasons: {qc_reason_text}.",
        "",
        "**Key measurements:**",
    ]
    if active:
        lines.extend(
            [
                _brain_tumor_report_measurement_line("Contrast-enhancing tumor", active.get("ET_mm3")),
                _brain_tumor_report_measurement_line("T2/FLAIR abnormality", active.get("FLAIR_abnormality_mm3")),
                _brain_tumor_report_measurement_line("Whole abnormality context", active.get("WT_mm3")),
                _brain_tumor_report_measurement_line("Resection/treatment cavity candidate", active.get("RC_mm3")),
            ]
        )
    else:
        lines.append("- No active measurement row is available.")
    lines.extend(
        [
            "",
            "**Workflow status:**",
            _brain_tumor_report_count_line("Segmentation", segmentation, "visits ready"),
            _brain_tumor_report_count_line("Alignment", alignment, "visits aligned"),
            "",
            "**Findings:**",
            _brain_tumor_report_findings_text(findings, active),
            "",
            "**Impression:**",
            impression,
            "",
            "**Reviewer note:** Confirm source imaging, modality mapping, registration QC, and segmentation overlay before clinical handoff.",
        ]
    )
    return "\n".join(lines)


def _brain_tumor_external_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    measurement_keys = {
        "WT_mm3",
        "FLAIR_abnormality_mm3",
        "TC_mm3",
        "ET_mm3",
        "NET_mm3",
        "RC_mm3",
        "ET_change_pct",
        "FLAIR_change_pct",
        "WT_change_pct",
        "registration_ncc_delta",
    }

    def measurements(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        return {key: value.get(key) for key in measurement_keys if key in value}

    def counts(value: Any) -> dict[str, int] | None:
        if not isinstance(value, dict):
            return None
        result: dict[str, int] = {}
        for key in ("completed_count", "total_count"):
            raw = value.get(key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                result[key] = max(0, int(raw))
        return result or None

    timepoints = []
    for index, value in enumerate(payload.get("timepoints") or []):
        sanitized = measurements(value)
        if sanitized is not None:
            timepoints.append({"visit_index": index + 1, **sanitized})
    allowed_qc_states = {"QC passed", "Needs rerun", "Excluded from report", "Pending"}
    allowed_qc_reasons = {
        "Modality mapping wrong",
        "Registration failed",
        "Tumor overlay inaccurate",
        "Wrong patient / timepoint",
        "Image quality issue",
    }
    qc_state = str(payload.get("qc_state") or "Pending")
    qc_reasons = [value for value in (payload.get("qc_reasons") or []) if value in allowed_qc_reasons]
    return {
        "qc_state": qc_state if qc_state in allowed_qc_states else "Pending",
        "qc_reasons": qc_reasons,
        "active_measurements": measurements(payload.get("active_measurements")),
        "alignment": counts(payload.get("alignment")),
        "segmentation": counts(payload.get("segmentation")),
        "timepoints": timepoints,
        "intended_use": "research quantitative imaging draft; not a standalone diagnosis",
    }


def _build_brain_tumor_report_prompt(payload: dict[str, Any]) -> str:
    deidentified_payload = _brain_tumor_external_report_payload(payload)
    return (
        "Draft a concise GBM quantitative imaging handoff report from this JSON payload.\n"
        "Write for a radiologist/research reviewer who needs the evidence chain, not a final diagnosis.\n"
        "Use exactly these markdown section headings and keep each section compact:\n"
        "**Case context:**\n"
        "**Key measurements:**\n"
        "**Workflow status:**\n"
        "**Findings:**\n"
        "**Impression:**\n"
        "Requirements:\n"
        "- Start with the selected/active scan and its contrast-enhancing tumor, T2/FLAIR abnormality, whole abnormality, and cavity/context volumes.\n"
        "- Render volume units as mm³ in prose; do not switch to mL unless the payload already says mL.\n"
        "- Put quantitative values only in Key measurements; do not repeat the same volumes again in Findings.\n"
        "- State segmentation readiness as completed_count/total_count when present; if missing, write not available, never NA/NA.\n"
        "- State alignment readiness as completed_count/total_count when present; if missing, write not available, never NA/NA.\n"
        "- Mention NCC delta / translation warnings only when present.\n"
        "- Preserve segmentation QC state and QC reasons.\n"
        "- If segmentation QC is not passed, say the case is not cleared for final quantitative reporting.\n"
        "- Do not use phrases such as Generated draft, AI-assisted, research-use note, or next-generation.\n"
        "- Do not infer diagnosis, treatment response, survival, recurrence, pseudoprogression, or RANO category beyond the provided measurements.\n"
        "- Do not invent missing visits, dates, imaging findings, or clinical history.\n\n"
        f"{json.dumps(deidentified_payload, ensure_ascii=False, indent=2)}"
    )


def _humanize_model_label(model_name: str) -> str:
    parts = model_name.replace("_", "-").split("-")
    label_parts: list[str] = []
    for part in parts:
        if part.lower() in {"gpt", "claude"}:
            label_parts.append(part.upper())
        elif part.lower() in {"gemini", "anthropic"}:
            label_parts.append(part.capitalize())
        elif part.lower() == "o":
            label_parts.append(part.upper())
        elif part.lower() in {"mini", "nano", "turbo", "latest", "chat", "preview", "flash", "pro", "sonnet", "haiku"}:
            label_parts.append(part.capitalize())
        else:
            label_parts.append(part.upper() if part.isalpha() and len(part) <= 3 else part)
    return " ".join(label_parts)


def _build_chat_options(config, active_model: str) -> dict[str, Any]:
    available_ids = sorted(
        model_name for model_name in MODEL_CAPABILITY_REGISTRY.keys() if _provider_available_for_model(config, model_name)
    )

    if active_model not in available_ids:
        available_ids.insert(0, active_model)

    seen: set[str] = set()
    models: list[dict[str, Any]] = []
    for model_name in available_ids:
        if model_name in seen:
            continue
        seen.add(model_name)
        capability = get_model_capability(model_name)
        models.append(
            {
                "id": model_name,
                "label": _humanize_model_label(model_name),
                "supports_reasoning_effort": capability.supports_reasoning_effort,
            }
        )

    return {
        "default_model": active_model,
        "default_reasoning_effort": "high",
        "models": models,
        "reasoning_efforts": ["low", "medium", "high"],
    }


def create_app() -> tuple:
    config = load_config()
    active_model = get_default_model(config)
    neuro_config = NeuroAgentConfig()
    settings = load_settings()
    llm = create_provider(active_model, config)
    clinagent = ClinAgentService()
    auth_store = ClinAgentAuthStore.from_env()
    email_sender = ClinAgentEmailSender.from_env()
    neuro_access = NeuroAccess(auth_store, {
        value.strip() for value in os.getenv("CLINAGENT_NEURO_CURATED_PATIENT_IDS", "").split(",") if value.strip()
    })
    preview_scope = os.getenv("CLINAGENT_PREVIEW_SCOPE", "").strip().lower()
    physician_curated_only = _env_flag(
        "CLINAGENT_PHYSICIAN_CURATED_ONLY",
        default=preview_scope == "brain_tumor",
    )
    durable_brain_tumor_queue = _env_flag(
        "CLINAGENT_BRAIN_TUMOR_DURABLE_QUEUE",
        default=physician_curated_only,
    )
    curated_case_ids = _env_id_set("CLINAGENT_BRAIN_TUMOR_CURATED_CASE_IDS")

    # Pre-build a shared registry for agent reuse
    _shared_registry = None

    app = FastAPI(title="ClinAgents Gateway")
    app.include_router(ingest_router)
    app.include_router(account_management_router(auth_store))
    demo_root = Path(__file__).resolve().parents[2] / "clinagent" / "ui" / "demo"
    demo_index = demo_root / "index.html"
    demo_next_root = Path(__file__).resolve().parents[2] / "clinagent" / "ui" / "demo-next"
    demo_next_index = demo_next_root / "index.html"
    safety_root = Path(__file__).resolve().parents[2] / "clinagent" / "ui" / "safety"
    safety_index = safety_root / "index.html"
    findings_root = Path(__file__).resolve().parents[2] / "clinagent" / "ui" / "findings"
    findings_index = findings_root / "index.html"
    queue_root = Path(__file__).resolve().parents[2] / "clinagent" / "ui" / "queue"
    queue_index = queue_root / "index.html"
    report_quality_root = Path(__file__).resolve().parents[2] / "clinagent" / "ui" / "report_quality"
    report_quality_index = report_quality_root / "index.html"
    repo_root = workspace_root()
    neuro_asset_root = repo_root / ".clinagent" / "derived" / "neuro_longitudinal"
    neuro_asset_root.mkdir(parents=True, exist_ok=True)

    cors_setting = os.getenv("CLINAGENT_CORS_ORIGINS", os.getenv("GATEWAY_CORS_ORIGINS", "*"))
    cors_origins = [origin.strip().rstrip("/") for origin in cors_setting.split(",") if origin.strip()]
    public_url = os.getenv("CLINAGENT_PUBLIC_URL", "").strip().rstrip("/")
    trusted_origins = {origin for origin in cors_origins if origin != "*"}
    if public_url:
        trusted_origins.add(public_url)
    effective_cors_origins = [] if auth_store.require_user_auth and "*" in cors_origins else cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=effective_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def user_session_middleware(request: Request, call_next):
        path = request.url.path
        current_user = auth_store.user_from_request(request)
        request.state.current_user = current_user
        origin = request.headers.get("origin", "").rstrip("/")
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip()
        same_origin = f"{forwarded_proto}://{request.headers.get('host', '')}".rstrip("/")
        if (
            auth_store.require_user_auth
            and request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
            and origin
            and origin not in trusted_origins
            and origin != same_origin
        ):
            return JSONResponse({"ok": False, "error": "Request origin is not allowed."}, status_code=403)
        if auth_store.require_user_auth and _requires_user_session(path) and current_user is None:
            return JSONResponse({"ok": False, "error": "Authentication required."}, status_code=401)
        setup_paths = {
            "/api/auth/config", "/api/auth/me", "/api/auth/login", "/api/auth/logout",
            "/api/auth/account/setup", "/api/auth/password/forgot", "/api/auth/password/reset",
        }
        if current_user and current_user.get("account_setup_required") and (
            path.startswith("/api/") or _requires_user_session(path)
        ) and path not in setup_paths:
            return JSONResponse({"ok": False, "error": "Complete account setup before opening the workspace.",
                                 "code": "account_setup_required"}, status_code=403)
        if preview_scope == "brain_tumor" and path in {"/chat", "/chat/stream", "/queue"}:
            return JSONResponse({"ok": False, "error": "Resource not found."}, status_code=404)
        if auth_store.require_user_auth:
            physician_api = path.startswith((
                "/api/auth/", "/api/demo/brain-tumor/", "/api/demo/neuro-report/",
            )) or path in {"/api/version", "/api/chat/options"}
            if path.startswith("/api/") and not physician_api and (not current_user or current_user.get("role") != "admin"):
                return JSONResponse({"ok": False, "error": "Resource not found."}, status_code=404)
            operator_paths = {
                "/chat", "/chat/stream", "/queue", "/api/demo/execute-stream",
                "/api/demo/console", "/api/demo/upload", "/api/demo/review",
            }
            if path in operator_paths or path.startswith((
                "/api/dev/", "/api/neuro-knowledge/", "/api/ingest/", "/api/demo/radonc-plan/",
            )):
                if not current_user or current_user.get("role") != "admin":
                    return JSONResponse({"ok": False, "error": "Resource not found."}, status_code=404)
            if path.startswith("/neuro-assets/") and not neuro_access.asset_allowed(
                path, str(current_user["id"]) if current_user else None,
            ):
                return JSONResponse({"ok": False, "error": "Resource not found."}, status_code=404)
            neuro_session = re.fullmatch(r"/api/demo/neuro-report/sessions/([^/]+)(?:/.*)?", path)
            if neuro_session and not neuro_access.session_allowed(neuro_session[1], str(current_user["id"]) if current_user else None):
                return JSONResponse({"ok": False, "error": "Session not found."}, status_code=404)
            neuro_patient = re.fullmatch(r"/api/demo/neuro-report/patients/([^/]+)(?:/.*)?", path)
            if neuro_patient and not neuro_access.patient_allowed(neuro_patient[1]):
                return JSONResponse({"ok": False, "error": "Patient not found."}, status_code=404)
            if path.startswith("/api/demo/neuro-report/knowledge"):
                return JSONResponse({"ok": False, "error": "Resource not found."}, status_code=404)
        if preview_scope == "brain_tumor" and path.startswith("/api/"):
            allowed_preview_prefixes = (
                "/api/auth",
                "/api/demo/brain-tumor",
                "/api/version",
            )
            if not path.startswith(allowed_preview_prefixes):
                return JSONResponse({"ok": False, "error": "Resource not found."}, status_code=404)
        if physician_curated_only and path.startswith("/api/demo/brain-tumor/"):
            blocked_prefixes = (
                "/api/demo/brain-tumor/analyze",
                "/api/demo/brain-tumor/dicom",
                "/api/demo/brain-tumor/dicom-mount",
                "/api/demo/brain-tumor/registry/run",
            )
            if path.startswith(blocked_prefixes):
                return JSONResponse({"ok": False, "error": "Resource not found."}, status_code=404)

        response = await call_next(request)
        action = _audit_action_for_request(request.method, path)
        if action and _requires_user_session(path):
            user_id = current_user["id"] if current_user else None
            auth_store.record_audit(
                user_id=user_id,
                action=action,
                resource=_audit_resource_for_path(path),
                status=str(response.status_code),
                request=request,
                metadata={"method": request.method},
            )
        return response

    if demo_root.exists():
        app.mount("/demo-assets", StaticFiles(directory=str(demo_root)), name="demo-assets")
    if safety_root.exists():
        app.mount("/safety-assets", StaticFiles(directory=str(safety_root)), name="safety-assets")
    if findings_root.exists():
        app.mount("/findings-assets", StaticFiles(directory=str(findings_root)), name="findings-assets")
    if queue_root.exists():
        app.mount("/queue-assets", StaticFiles(directory=str(queue_root)), name="queue-assets")
    if report_quality_root.exists():
        app.mount("/report-quality-assets", StaticFiles(directory=str(report_quality_root)), name="report-quality-assets")
    if demo_next_root.exists():
        app.mount("/demo-static", StaticFiles(directory=str(demo_next_root)), name="demo-next-assets")
    app.mount("/neuro-assets", StaticFiles(directory=str(neuro_asset_root)), name="neuro-assets")
    dev_runtime_state: dict[str, Any] = {
        "recent_trace_summary": {
            "status": "idle",
            "message": "No developer trace has been captured yet.",
            "tool_calls": [],
            "errors": [],
        }
    }

    def _format_sse(event: str, data: Any) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    def _auth_config() -> dict[str, Any]:
        return {
            **auth_store.config(),
            "email_delivery_configured": email_sender.configured,
            "preview_scope": preview_scope or "full",
            "physician_curated_only": physician_curated_only,
            "public_url": public_url,
            "password_min_length": 12,
        }

    def _current_user_id(request: Request) -> str | None:
        user = getattr(request.state, "current_user", None)
        return str(user["id"]) if user else None

    def _register_brain_tumor_sessions(payload: Any, *, user_id: str | None, source: str, shared: bool) -> None:
        session_ids: set[str] = set()

        def collect(value: Any) -> None:
            if isinstance(value, dict):
                direct = value.get("session_id") or value.get("sessionId")
                if isinstance(direct, str) and direct.strip():
                    session_ids.add(direct.strip())
                for key in ("points", "visits", "session", "point"):
                    if key in value:
                        collect(value[key])
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(payload)
        for session_id in session_ids:
            auth_store.register_case_access(
                case_id=session_id,
                owner_user_id=None if shared else user_id,
                source=source,
                shared=shared,
            )

    def _brain_tumor_case_allowed(request: Request, case_id: str) -> bool:
        if not auth_store.require_user_auth and not physician_curated_only:
            return True
        if not auth_store.can_access_case(case_id=case_id, user_id=_current_user_id(request)):
            return False
        if not physician_curated_only:
            return True
        access = auth_store.get_case_access(case_id=case_id)
        source = str((access or {}).get("source") or "")
        source_type, _, source_case_id = source.partition(":")
        if source_type == "nifti_upload":
            return True
        return source_type in {"curated_registry", "curated_registry_rerun", "curated_preload"} and source_case_id in curated_case_ids

    def _brain_tumor_job_allowed(request: Request, job_id: str) -> bool:
        if not auth_store.require_user_auth:
            return True
        return auth_store.can_access_job(job_id=job_id, user_id=_current_user_id(request))

    def _brain_tumor_public_payload(value: Any) -> Any:
        if isinstance(value, list):
            return [_brain_tumor_public_payload(item) for item in value]
        if not isinstance(value, dict):
            return value
        public: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"artifacts", "source", "internal_paths"}:
                continue
            if key == "path_name":
                public[key] = ""
                continue
            if key == "remote_staging":
                public[key] = {"enabled": bool(item.get("enabled"))} if isinstance(item, dict) else {"enabled": False}
                continue
            public[key] = _brain_tumor_public_payload(item)
        return public

    def _brain_tumor_job_api_payload(job: dict[str, Any]) -> dict[str, Any]:
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        payload = dict(result)
        job_payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        payload.update(
            {
                "ok": bool(payload.get("ok", True)) and job.get("status") != "failed",
                "job_id": str(job.get("id") or payload.get("job_id") or ""),
                "case_id": str(payload.get("case_id") or job_payload.get("case_id") or ""),
                "status": str(job.get("status") or payload.get("status") or "queued"),
                "stage": str(job.get("stage") or payload.get("stage") or "queued"),
                "created_at": job.get("created_at"),
                "started_at": job.get("started_at"),
                "updated_at": job.get("updated_at"),
                "completed_at": job.get("completed_at"),
            }
        )
        payload.setdefault("total_count", 0)
        payload.setdefault("completed_count", 0)
        payload.setdefault("failed_count", 0)
        payload.setdefault("visits", [])
        if job.get("error_message") and not payload.get("error"):
            payload["error"] = "Segmentation could not be completed. Please retry or contact the preview administrator."
        return _brain_tumor_public_payload(payload)

    def _brain_tumor_upload_case_api_payload(case: dict[str, Any], job: dict[str, Any] | None) -> dict[str, Any]:
        from clinagent.gateway.brain_tumor_uploads import read_upload_manifest
        from clinagent.gateway.brain_tumor_upload_visits import manifest_visits

        case_id = str(case.get("id") or "")
        manifest = read_upload_manifest(case_id) or {}
        modality_summary = {
            key: {"shape": value.get("shape"), "spacing_mm": value.get("spacing_mm")}
            for key, value in (manifest.get("modalities") or {}).items()
            if isinstance(value, dict)
        }
        visits = []
        for index, visit in enumerate(manifest_visits(manifest, job)):
            visit_path = "" if visit["id"] == "visit_01" else f"/visits/{visit['id']}"
            visits.append({
                "id": visit["id"], "label": f"Visit {index + 1}", "date": visit.get("date"),
                "relative_day": visit.get("relative_day"), "relative_day_origin": visit.get("relative_day_origin"),
                "status": visit.get("status", "queued"), "session_id": visit.get("session_id"),
                "session": _brain_tumor_public_payload(visit.get("session")),
                "resample_to_t1c": visit.get("resample_to_t1c", []),
                "modalities": {key: {"shape": value.get("shape"), "spacing_mm": value.get("spacing_mm")}
                    for key, value in visit.get("modalities", {}).items()},
                "modality_volume_urls": {key: f"/api/demo/brain-tumor/uploads/{case_id}{visit_path}/modality/{key}/{key}.nii.gz"
                    for key in visit.get("modalities", {})},
            })
        return {
            "id": case_id,
            "label": str(manifest.get("display_label") or f"Uploaded case {case_id[-6:].upper()}"),
            "created_at": case.get("created_at") or manifest.get("created_at"),
            "expires_at": case.get("expires_at") or manifest.get("expires_at"),
            "retention_days": manifest.get("retention_days", 30),
            "visit_count": len(visits),
            "visits": visits,
            "modalities": modality_summary,
            "modality_volume_urls": {
                key: f"/api/demo/brain-tumor/uploads/{case_id}/modality/{key}/{key}.nii.gz"
                for key in modality_summary
            },
            "resample_to_t1c": list(manifest.get("resample_to_t1c") or []),
            "job": _brain_tumor_job_api_payload(job) if job else None,
        }

    def _curated_case_allowed(case_id: str) -> bool:
        return not physician_curated_only or case_id in curated_case_ids

    def _filter_curated_cases(payload: dict[str, Any]) -> dict[str, Any]:
        if not physician_curated_only:
            return payload
        filtered = dict(payload)
        cases = [
            item
            for item in payload.get("cases", [])
            if isinstance(item, dict) and str(item.get("id") or "") in curated_case_ids
        ]
        filtered["cases"] = cases
        filtered["case_count"] = len(cases)
        return filtered

    def _filter_curated_preloads(payload: dict[str, Any]) -> dict[str, Any]:
        if not physician_curated_only:
            return payload
        filtered = dict(payload)
        examples = [
            item
            for item in payload.get("examples", [])
            if isinstance(item, dict) and str(item.get("id") or "") in curated_case_ids
        ]
        filtered["examples"] = examples
        filtered["configured"] = bool(examples)
        filtered["default_example_id"] = examples[0].get("id") if examples else None
        return filtered

    def _chunk_text(text: str, chunk_size: int = 180) -> list[str]:
        cleaned = text.strip()
        if not cleaned:
            return []
        words = cleaned.split()
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for word in words:
            extra = len(word) + (1 if current else 0)
            if current and current_len + extra > chunk_size:
                chunks.append(" ".join(current))
                current = [word]
                current_len = len(word)
            else:
                current.append(word)
                current_len += extra
        if current:
            chunks.append(" ".join(current))
        return chunks

    alignment_jobs: dict[str, dict[str, Any]] = {}

    def _alignment_stage_payload(status: str = "completed") -> list[dict[str, str]]:
        if status == "failed":
            return [
                {"stage": "resolve_studies", "label": "Resolve selected studies", "status": "done"},
                {"stage": "align_images", "label": "Align selected imaging", "status": "failed"},
                {"stage": "quality_check", "label": "Quality check", "status": "pending"},
            ]
        return [
            {"stage": "resolve_studies", "label": "Resolve selected studies", "status": "done"},
            {"stage": "align_images", "label": "Align selected imaging", "status": "done"},
            {"stage": "quality_check", "label": "Quality check", "status": "done"},
        ]

    def _demo_alignment_job(payload: dict[str, Any]) -> dict[str, Any]:
        workflow = str(payload.get("workflow") or "longitudinal_coregistration")
        fixed_study_id = str(payload.get("fixed_study_id") or "").strip()
        moving_study_id = str(payload.get("moving_study_id") or "").strip()
        patient_id = str(payload.get("patient_id") or "").strip()
        apply_to_segmentation = bool(payload.get("apply_to_segmentation"))
        translation = [-7.96, 1.07, -12.39] if workflow == "longitudinal_coregistration" else [-0.06, -0.5, 2.39]
        ncc_before = 0.6 if workflow == "longitudinal_coregistration" else 0.724
        ncc_after = 0.746 if workflow == "longitudinal_coregistration" else 0.701
        warnings = ["shape_mismatch"]
        job_id = f"align_demo_{uuid.uuid4().hex[:10]}"
        job = {
            "job_id": job_id,
            "status": "completed",
            "mode": "demo",
            "workflow": workflow,
            "patient_id": patient_id or None,
            "fixed_study_id": fixed_study_id or None,
            "moving_study_id": moving_study_id or None,
            "apply_to_segmentation": apply_to_segmentation,
            "created_at": time.time(),
            "updated_at": time.time(),
            "stages": _alignment_stage_payload(),
            "clinical_summary": (
                "Follow-up imaging was aligned to the selected baseline grid."
                if workflow == "longitudinal_coregistration"
                else "The selected sequence was aligned to the reference sequence grid."
            ),
            "qc": {
                "translation_mm": translation,
                "translation_norm_mm": round(sum(value * value for value in translation) ** 0.5, 2),
                "ncc_before": ncc_before,
                "ncc_after": ncc_after,
                "ncc_delta": round(ncc_after - ncc_before, 3),
                "resampled_to_reference_grid": True,
                "nonlinear_deformation_allowed": False,
                "warnings": warnings,
                "clinical_warnings": [
                    "The selected scans use different voxel grids; the moving study was resampled to the reference grid.",
                    "Nonlinear deformation was not used, preserving true interval change for clinical review.",
                ],
            },
            "outputs": {
                "aligned_image_label": "Registered follow-up" if workflow == "longitudinal_coregistration" else "Registered sequence",
                "transferred_segmentation_label": "Segmentation transferred to baseline" if apply_to_segmentation else None,
                "viewer_hint": "Use the viewer overlay to confirm anatomy before using the trend or report lanes.",
            },
        }
        alignment_jobs[job_id] = job
        return job

    def _failed_alignment_job(payload: dict[str, Any], error: str) -> dict[str, Any]:
        job_id = f"align_failed_{uuid.uuid4().hex[:10]}"
        job = {
            "job_id": job_id,
            "status": "failed",
            "mode": str(payload.get("mode") or "remote"),
            "workflow": str(payload.get("workflow") or "longitudinal_coregistration"),
            "patient_id": str(payload.get("patient_id") or "").strip() or None,
            "fixed_study_id": str(payload.get("fixed_study_id") or "").strip() or None,
            "moving_study_id": str(payload.get("moving_study_id") or "").strip() or None,
            "apply_to_segmentation": bool(payload.get("apply_to_segmentation")),
            "created_at": time.time(),
            "updated_at": time.time(),
            "stages": _alignment_stage_payload("failed"),
            "clinical_summary": "Alignment could not be completed. Please verify that the selected studies expose usable imaging and that remote processing is available.",
            "error": error,
            "qc": {
                "warnings": ["alignment_unavailable"],
                "clinical_warnings": ["Alignment is unavailable for this selection. The existing viewer and report lanes remain usable."],
            },
            "outputs": {},
        }
        alignment_jobs[job_id] = job
        return job

    def _remote_alignment_job(payload: dict[str, Any]) -> dict[str, Any]:
        from clinagent.families.neuro.tools.registration import (
            NeuroLongitudinalCoregistrationTool,
            NeuroSequenceCoregistrationTool,
            NeuroTransformApplicationTool,
        )

        workflow = str(payload.get("workflow") or "longitudinal_coregistration")
        patient_id = str(payload.get("patient_id") or "").strip()
        fixed_study_id = str(payload.get("fixed_study_id") or "").strip()
        moving_study_id = str(payload.get("moving_study_id") or "").strip()
        apply_to_segmentation = bool(payload.get("apply_to_segmentation"))
        output_root = str(payload.get("output_dir") or os.getenv("CLINAGENT_NEURO_ALIGNMENT_OUTPUT_DIR", "")).strip()
        if not patient_id or not fixed_study_id or not moving_study_id:
            return _failed_alignment_job(payload, "Select a patient, reference study, and moving study before running alignment.")
        if not output_root:
            return _failed_alignment_job(payload, "Alignment output storage is not configured for remote processing.")

        try:
            _, neuro_report_demo_store = _get_neuro_report_demo_components()
            fixed_record = neuro_report_demo_store.resolve_analysis_request(patient_id=patient_id, study_id=fixed_study_id)
            moving_record = neuro_report_demo_store.resolve_analysis_request(patient_id=patient_id, study_id=moving_study_id)
            fixed_path = str(fixed_record["analysis_image_path"] if isinstance(fixed_record, dict) else fixed_record.analysis_image_path)
            moving_path = str(moving_record["analysis_image_path"] if isinstance(moving_record, dict) else moving_record.analysis_image_path)
            moving_seg_path = (
                str(moving_record["seg_path"])
                if isinstance(moving_record, dict) and moving_record.get("seg_path")
                else str(moving_record.seg_path)
                if not isinstance(moving_record, dict) and moving_record.seg_path
                else None
            )
            output_name = f"alignment-{uuid.uuid4().hex}" if auth_store.require_user_auth else f"{patient_id}_{fixed_study_id}_{moving_study_id}_{workflow}"
            output_dir = str(Path(output_root).expanduser() / output_name)
            if workflow == "sequence_coregistration":
                result = NeuroSequenceCoregistrationTool().run(
                    fixed_image_path=fixed_path,
                    moving_image_path=moving_path,
                    output_dir=output_dir,
                    case_id=patient_id,
                    fixed_label=fixed_study_id,
                    moving_label=moving_study_id,
                    initialization="com",
                    interpolation="linear",
                )
            else:
                result = NeuroLongitudinalCoregistrationTool().run(
                    baseline_image_path=fixed_path,
                    followup_image_path=moving_path,
                    output_dir=output_dir,
                    case_id=patient_id,
                    baseline_label=fixed_study_id,
                    followup_label=moving_study_id,
                    initialization="com",
                    interpolation="linear",
                )
            if result.get("status") not in {"ok", "completed"}:
                return _failed_alignment_job(payload, "Alignment processing did not complete for the selected studies.")

            transfer_result: dict[str, Any] | None = None
            if apply_to_segmentation and moving_seg_path:
                transfer_result = NeuroTransformApplicationTool().run(
                    source_image_path=moving_seg_path,
                    reference_image_path=fixed_path,
                    transform_path=str(result.get("transform_path") or ""),
                    output_image_path=str(Path(output_dir) / "transferred_segmentation_to_reference.nii.gz"),
                    interpolation="nearest",
                )

            qc = dict(result.get("qc") or {})
            warnings = list(qc.get("warnings") or [])
            clinical_warnings = []
            if "shape_mismatch" in warnings or "spacing_mismatch" in warnings:
                clinical_warnings.append("The selected scans use different grids or spacing; the moving study was resampled to the reference grid.")
            if qc.get("nonlinear_deformation_allowed") is False or workflow == "longitudinal_coregistration":
                clinical_warnings.append("Nonlinear deformation was not used, preserving true interval change for clinical review.")
            job_id = f"align_remote_{uuid.uuid4().hex[:10]}"
            job = {
                "job_id": job_id,
                "status": "completed",
                "mode": "remote",
                "workflow": workflow,
                "patient_id": patient_id,
                "fixed_study_id": fixed_study_id,
                "moving_study_id": moving_study_id,
                "apply_to_segmentation": apply_to_segmentation,
                "created_at": time.time(),
                "updated_at": time.time(),
                "stages": _alignment_stage_payload(),
                "clinical_summary": "Alignment completed for the selected studies.",
                "qc": {
                    **qc,
                    "resampled_to_reference_grid": True,
                    "clinical_warnings": clinical_warnings,
                },
                "outputs": {
                    "aligned_image_path": result.get("output_image_path"),
                    "transform_path": result.get("transform_path"),
                    "transferred_segmentation_path": transfer_result.get("output_image_path") if transfer_result else None,
                    "viewer_hint": "Use the viewer overlay to confirm anatomy before using the trend or report lanes.",
                },
            }
            alignment_jobs[job_id] = job
            return job
        except Exception as exc:
            return _failed_alignment_job(payload, "Alignment processing failed for this selection.")

    def _neuro_workspace_url(
        *,
        patient_id: str | None,
        study_id: str | None,
        case_id: str | None,
        mode: str | None = None,
        goal: str | None = None,
        from_chat: bool = False,
        source: str | None = None,
        source_path: str | None = None,
    ) -> str:
        params: dict[str, str] = {}
        if source:
            params["source"] = source
        if patient_id:
            params["patient_id"] = patient_id
        if study_id:
            params["study_id"] = study_id
        if case_id:
            params["case_id"] = case_id
        if mode:
            params["mode"] = mode
        if goal:
            params["goal"] = goal
        if source_path:
            params["source_path"] = source_path
        if from_chat:
            params["from"] = "chat"
        suffix = f"?{urlencode(params)}" if params else ""
        return f"/demo/analysis/neuro-report{suffix}"

    def _build_neuro_report_artifact_preview(
        message: str | None = None,
        *,
        ingest_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        try:
            _, neuro_report_demo_store = _get_neuro_report_demo_components()
            examples = neuro_report_demo_store.get_examples()
            patients_payload = neuro_report_demo_store.get_patients()
            if not examples:
                return None
            intake_context, capability_profile, analysis_plan = intake_plan_from_message(
                message or "",
                ingest_context=ingest_context,
            )
            example = next(
                (
                    item
                    for item in examples
                    if item.get("planning_result", {}).get("primary_goal") == analysis_plan.primary_goal
                ),
                examples[0],
            )
            use_curated_context = intake_context.source_kind == "curated_case" or analysis_plan.autorun
            chosen_mode = (
                example["default_mode"]
                if use_curated_context
                else analysis_plan.recommended_mode
            )
            viewer_type = (
                "nifti"
                if use_curated_context
                else ("dicomweb" if capability_profile.imaging_format == "dicom" else "png_fallback")
            )
            planning_result = build_planning_result(
                intake_context,
                capability_profile,
                analysis_plan,
                requested_mode=chosen_mode,
                executed_mode=chosen_mode,
                viewer_type=viewer_type,
            )
            runtime_bundle = build_workflow_runtime_bundle(
                "neuro_report",
                workflow_family=analysis_plan.workflow_family,
                primary_goal=planning_result.primary_goal,
                dashboard_profile=planning_result.dashboard_profile,
                track=analysis_plan.analysis_track,
                context_sources=capability_profile.context_sources,
                fallback_reason=capability_profile.blocked_reasons[0] if capability_profile.blocked_reasons else None,
                policy_mode=analysis_plan.runtime_mode,
            )
            return {
                "kind": "neuro_report",
                "module": "neuro_report",
                "title": "Neuro MRI Report Generator",
                "subtitle": example["title"] if use_curated_context else analysis_plan.requested_goal,
                "riskLevel": "moderate",
                "metrics": [
                    {"label": "Goal", "value": planning_result.primary_goal},
                    {"label": "Patient", "value": example["patient_id"] if use_curated_context else "Pending intake"},
                    {"label": "Study", "value": example["study_id"] if use_curated_context else capability_profile.imaging_format},
                    {"label": "Track", "value": analysis_plan.analysis_track},
                    {"label": "Dashboard", "value": analysis_plan.dashboard_profile},
                    {"label": "Mode", "value": chosen_mode or "intake"},
                ],
                "reportPreview": example["description"] if use_curated_context else analysis_plan.requested_goal,
                "qaStatus": {"privacy": True, "terminology": True, "completeness": True},
                "claimsSummary": analysis_plan.handoff_summary,
                "workspaceUrl": _neuro_workspace_url(
                    patient_id=example["patient_id"] if use_curated_context else None,
                    study_id=example["study_id"] if use_curated_context else None,
                    case_id=example["case_id"] if use_curated_context else None,
                    mode=chosen_mode,
                    goal=planning_result.primary_goal,
                    from_chat=True,
                    source="upload" if intake_context.source_kind == "upload" else "example",
                    source_path=str((ingest_context or {}).get("source_path") or "").strip() or None,
                ),
                "planSummary": analysis_plan.handoff_summary,
                "missingInputs": analysis_plan.missing_inputs,
                "allowedAnalyses": analysis_plan.allowed_analyses,
                "capabilityStatus": capability_profile.available_inputs,
                "intent": planning_result.intent,
                "recommendedNextAction": planning_result.recommended_next_action,
                "executionReadiness": "ready" if planning_result.can_execute else "intake_only",
                "viewerType": planning_result.viewer_type,
                "policyMode": runtime_bundle["tool_policy"]["mode"],
                "allowedTools": runtime_bundle["tool_policy"]["allowed_tools"],
                "blockedTools": runtime_bundle["tool_policy"]["blocked_tools"],
                "entities": planning_result.entities,
                "availableData": planning_result.available_data,
                "planningResult": planning_result.to_dict(),
                "analysisPlan": analysis_plan.to_dict(),
                "analysisPlanSummary": planning_result.analysis_plan_summary.to_dict(),
                "capabilityProfile": capability_profile.to_dict(),
                "capabilityProfileSummary": planning_result.capability_profile_summary.to_dict(),
            }
        except Exception:
            return None

    def _build_report_quality_artifact_preview(message: str | None = None) -> dict[str, Any] | None:
        try:
            snapshot = report_quality_demo_store.snapshot()
            workspace = snapshot["workspace"]
            _, capability_profile, analysis_plan = intake_plan_from_report_quality_message(message or "")
            case_planning = workspace.get("planning_result") or {}
            runtime_bundle = build_workflow_runtime_bundle(
                "report_quality_review",
                workflow_family=analysis_plan.workflow_family,
                primary_goal=analysis_plan.primary_goal,
                dashboard_profile=analysis_plan.dashboard_profile,
                track=analysis_plan.analysis_track,
                context_sources=capability_profile.context_sources,
                fallback_reason=capability_profile.blocked_reasons[0] if capability_profile.blocked_reasons else None,
                policy_mode=analysis_plan.runtime_mode,
            )
            return {
                "kind": "report_quality_review",
                "module": "report_quality",
                "title": "Report Quality Review",
                "subtitle": workspace["title"],
                "riskLevel": "moderate",
                "metrics": [
                    {"label": "Status", "value": workspace["status_label"]},
                    {"label": "Template", "value": workspace["template_id"]},
                    {"label": "Track", "value": analysis_plan.analysis_track},
                    {"label": "Dashboard", "value": analysis_plan.dashboard_profile},
                    {"label": "Mode", "value": analysis_plan.recommended_mode or "intake"},
                ],
                "reportPreview": workspace["summary"],
                "qaStatus": {"privacy": True, "terminology": True, "completeness": True},
                "claimsSummary": analysis_plan.handoff_summary,
                "workspaceUrl": f"/demo/functions/report-quality?case_id={workspace['id']}&from=chat",
                "planSummary": analysis_plan.handoff_summary,
                "missingInputs": analysis_plan.missing_inputs,
                "allowedAnalyses": analysis_plan.allowed_analyses,
                "capabilityStatus": capability_profile.available_inputs,
                "intent": analysis_plan.requested_goal,
                "recommendedNextAction": case_planning.get("recommended_next_action") or "Open the report quality workspace and inspect the selected draft.",
                "executionReadiness": "ready" if analysis_plan.can_execute else "intake_only",
                "viewerType": "workspace",
                "policyMode": runtime_bundle["tool_policy"]["mode"],
                "allowedTools": runtime_bundle["tool_policy"]["allowed_tools"],
                "blockedTools": runtime_bundle["tool_policy"]["blocked_tools"],
                "availableData": capability_profile.available_inputs,
            }
        except Exception:
            return None

    def _build_radonc_plan_artifact_preview(message: str | None = None) -> dict[str, Any] | None:
        try:
            snapshot = radonc_plan_demo_store.snapshot()
            session = snapshot.get("session") or {}
            intake_context = infer_radonc_context(message or "")
            _, capability_profile, analysis_plan = intake_plan_from_radonc_message(message or "")
            planning_result = build_radonc_planning_result(
                intake_context,
                capability_profile,
                analysis_plan,
            )
            runtime_bundle = build_workflow_runtime_bundle(
                "radonc_plan_optimization",
                workflow_family=analysis_plan.workflow_family,
                primary_goal=analysis_plan.primary_goal,
                dashboard_profile=analysis_plan.dashboard_profile,
                track=analysis_plan.analysis_track,
                context_sources=capability_profile.context_sources,
                fallback_reason=capability_profile.blocked_reasons[0] if capability_profile.blocked_reasons else None,
                policy_mode=analysis_plan.runtime_mode,
            )
            risk_tier = str(session.get("risk_tier") or "watch")
            session_id = str(session.get("id") or snapshot.get("default_session_id") or "radonc-plan-demo")
            patient_id = str(session.get("data_source_id") or snapshot.get("active_patient_id") or "Patient001")
            title = str(session.get("title") or "RadOnc Plan Optimization")
            subtitle = str(session.get("subtitle") or planning_result.analysis_plan_summary.summary)
            report_preview = (
                session.get("report_preview")
                or session.get("report_summary")
                or planning_result.analysis_plan_summary.summary
            )
            return {
                "kind": "radonc_plan",
                "module": "radonc_plan",
                "title": title,
                "subtitle": subtitle,
                "riskLevel": "high" if risk_tier in {"alert", "urgent"} else "moderate",
                "metrics": [
                    {"label": item["label"], "value": item["value"]}
                    for item in session.get("summary_cards", [])[:4]
                ],
                "reportPreview": report_preview,
                "qaStatus": {"privacy": True, "terminology": True, "completeness": True},
                "claimsSummary": analysis_plan.handoff_summary,
                "workspaceUrl": f"/demo/analysis/radonc-plan?patient_id={patient_id}&from=chat&autorun=1",
                "planSummary": analysis_plan.handoff_summary,
                "missingInputs": analysis_plan.missing_inputs,
                "allowedAnalyses": analysis_plan.allowed_analyses,
                "capabilityStatus": capability_profile.available_inputs,
                "intent": planning_result.intent,
                "recommendedNextAction": planning_result.recommended_next_action,
                "executionReadiness": "ready" if planning_result.can_execute else "intake_only",
                "viewerType": planning_result.viewer_type,
                "policyMode": runtime_bundle["tool_policy"]["mode"],
                "allowedTools": runtime_bundle["tool_policy"]["allowed_tools"],
                "blockedTools": runtime_bundle["tool_policy"]["blocked_tools"],
                "availableData": planning_result.available_data,
                "planningResult": planning_result.to_dict(),
                "analysisPlan": analysis_plan.to_dict(),
                "analysisPlanSummary": planning_result.analysis_plan_summary.to_dict(),
                "capabilityProfile": capability_profile.to_dict(),
                "capabilityProfileSummary": planning_result.capability_profile_summary.to_dict(),
            }
        except Exception:
            return None

    def _build_neuro_knowledge_client() -> MRRateKnowledgeServiceClient:
        return MRRateKnowledgeServiceClient(
            base_url=settings.mr_rate_base_url,
            timeout_s=settings.connector_timeout_s,
        )

    def _resolve_mr_rate_local_root(requested_local_root: str | None = None) -> Path:
        candidate = (requested_local_root or settings.mr_rate_local_root).strip()
        if candidate:
            return Path(candidate).expanduser().resolve()
        return (repo_root / ".clinagent" / "local" / "mr_rate_launches").resolve()

    def _prepare_mr_rate_launch(
        *,
        patient_uid: str,
        study_uid: str,
        requested_local_root: str | None,
        download_if_missing: bool,
        segmentation_preference: str,
        sequence_preference: str,
    ) -> dict[str, Any]:
        local_root = _resolve_mr_rate_local_root(requested_local_root)
        store = MRRateLocalLaunchStore(local_root)
        cached = store.get_ready_launch(patient_uid, study_uid)
        if cached is not None:
            return store.build_ready_payload(patient_uid, study_uid, cached)
        if not download_if_missing:
            return store.mark_missing(patient_uid, study_uid)

        client = _build_neuro_knowledge_client()
        remote_launch = client.create_analysis_launch(
            {
                "patient_uid": patient_uid,
                "study_uid": study_uid,
                "segmentation_preference": segmentation_preference,
                "sequence_preference": sequence_preference,
            }
        )
        launch_id = str(remote_launch.get("launch_id") or "").strip()
        if not launch_id:
            raise ValueError("MR-RATE knowledge service returned no launch_id.")

        try:
            remote_manifest = client.get_analysis_launch_manifest(launch_id)
            image_bytes = client.download_analysis_launch_file(launch_id, "image")
            seg_bytes = None
            if remote_manifest.get("has_segmentation"):
                seg_bytes = client.download_analysis_launch_file(launch_id, "seg")
            knowledge_context = remote_manifest.get("knowledge_context") or {}
            return store.write_launch(
                patient_uid=patient_uid,
                study_uid=study_uid,
                image_bytes=image_bytes,
                seg_bytes=seg_bytes,
                remote_manifest=remote_manifest,
                knowledge_context=knowledge_context if isinstance(knowledge_context, dict) else {},
            )
        except Exception:
            store.reset_study(patient_uid, study_uid)
            raise

    def _knowledge_launch_indication(payload: dict[str, Any]) -> str:
        knowledge_context = payload.get("knowledge_context")
        if not isinstance(knowledge_context, dict):
            return "Brain MRI from MR-RATE knowledge launch"
        report = knowledge_context.get("report")
        if isinstance(report, dict):
            clinical = str(report.get("clinical_information") or "").strip()
            if clinical:
                return clinical
            impression = str(report.get("impression") or "").strip()
            if impression:
                return impression
        summary = knowledge_context.get("study_summary")
        if isinstance(summary, dict):
            summary_text = str(summary.get("summary_text") or "").strip()
            if summary_text:
                return summary_text
        return "Brain MRI from MR-RATE knowledge launch"

    def _knowledge_launch_demographics(payload: dict[str, Any]) -> tuple[int | None, str | None]:
        local_bundle = payload.get("local_bundle")
        if isinstance(local_bundle, dict):
            age_value = local_bundle.get("age")
            sex_value = local_bundle.get("sex")
            try:
                age = int(age_value) if age_value is not None and str(age_value).strip() != "" else None
            except (TypeError, ValueError):
                age = None
            sex = str(sex_value).strip().upper()[:1] if sex_value else None
            if sex in {"M", "F"}:
                return age, sex
        knowledge_context = payload.get("knowledge_context")
        if not isinstance(knowledge_context, dict):
            return None, None
        study = knowledge_context.get("study")
        if not isinstance(study, dict):
            return None, None
        age_value = study.get("patient_age")
        sex_value = study.get("patient_sex")
        try:
            age = int(age_value) if age_value is not None and str(age_value).strip() != "" else None
        except (TypeError, ValueError):
            age = None
        sex = str(sex_value).strip().upper()[:1] if sex_value else None
        if sex not in {"M", "F"}:
            sex = None
        return age, sex

    def _neuro_report_session_response(session_id: str, session: dict[str, Any]) -> dict[str, Any]:
        response = {
            "ok": True,
            "session_id": session_id,
            "patient_id": session.get("patient_id"),
            "study_id": session.get("study_id"),
            "case_id": session.get("case_id"),
            "source": session.get("source"),
            "mode": session.get("mode"),
            "requested_mode": session.get("requested_mode"),
            "age": session.get("age"),
            "sex": session.get("sex"),
            "indication": session.get("indication"),
            "image_name": session.get("image_name"),
            "segmentation_name": session.get("segmentation_name"),
            "report": session.get("report"),
            "report_sections": session.get("report_sections"),
            "viewer_assets": session.get("viewer_assets"),
            "slice_manifest": session.get("slice_manifest"),
            "slice_source": session.get("slice_source"),
            "volumetrics": session.get("volumetrics"),
            "segmentation_regions": session.get("segmentation_regions"),
            "label_source": session.get("label_source"),
            "label_mapping_path": session.get("label_mapping_path"),
            "label_mapping_label_count": session.get("label_mapping_label_count"),
            "label_schema_version": session.get("label_schema_version"),
            "analysis_plan": session.get("analysis_plan"),
            "analysis_plan_summary": session.get("analysis_plan_summary"),
            "capability_profile": session.get("capability_profile"),
            "capability_profile_summary": session.get("capability_profile_summary"),
            "planning_result": session.get("planning_result"),
            "workspace_contract": session.get("workspace_contract"),
            "dashboard_payloads": session.get("dashboard_payloads"),
            "segmentation_backend": session.get("segmentation_backend"),
            "preprocessing_profile": session.get("preprocessing_profile"),
            "csv_export_url": session.get("csv_export_url"),
        }
        return response

    def _upstream_error_message(exc: httpx.HTTPStatusError) -> str:
        try:
            payload = exc.response.json()
        except ValueError:
            return exc.response.text or str(exc)
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("error") or payload.get("message")
            if isinstance(detail, str) and detail.strip():
                return detail
        return str(exc)

    def _proxy_neuro_knowledge(callable_: Any) -> JSONResponse:
        try:
            return JSONResponse(callable_())
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)
        except httpx.TimeoutException:
            return JSONResponse(
                {"ok": False, "error": "MR-RATE knowledge service timed out."},
                status_code=503,
            )
        except httpx.HTTPStatusError as exc:
            return JSONResponse(
                {"ok": False, "error": _upstream_error_message(exc)},
                status_code=exc.response.status_code,
            )
        except httpx.HTTPError as exc:
            return JSONResponse(
                {"ok": False, "error": f"MR-RATE knowledge service unavailable: {exc}"},
                status_code=502,
            )

    @app.get("/api/auth/config")
    async def auth_config():
        return {"ok": True, **_auth_config()}

    @app.get("/api/auth/me")
    async def auth_me(request: Request):
        user = getattr(request.state, "current_user", None)
        return {"ok": True, "user": user, **_auth_config()}

    @app.get("/api/auth/invitations/{token}")
    async def auth_invitation(token: str):
        try:
            invitation = auth_store.invitation_from_token(token)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
        return {"ok": True, "invitation": invitation, **_auth_config()}

    @app.post("/api/auth/invitations/accept")
    async def auth_invitation_accept(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "Invalid JSON."}, status_code=400)
        token = str(payload.get("token") or "")
        try:
            auth_store.enforce_request_rate_limit(
                request=request,
                scope="invitation_accept",
                ip_limit=10,
                email_limit=10,
                window_seconds=15 * 60,
            )
            user = auth_store.accept_invitation(
                token=token,
                password=str(payload.get("password") or ""),
                dua_accepted=bool(payload.get("dua_accepted")),
            )
        except RateLimitExceeded as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=429)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        session = auth_store.create_session(user["id"], request)
        response = JSONResponse({"ok": True, "user": user, **_auth_config()})
        auth_store.set_session_cookie(response, session)
        auth_store.record_audit(
            user_id=user["id"],
            action="invitation_accepted",
            resource="auth",
            status="200",
            request=request,
            metadata={"dua_version": user["dua_version"], "role": user["role"]},
        )
        return response

    @app.post("/api/auth/register")
    async def auth_register(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "Invalid JSON."}, status_code=400)
        try:
            user = auth_store.create_user(
                email=str(payload.get("email") or ""),
                password=str(payload.get("password") or ""),
                name=str(payload.get("name") or ""),
                organization=str(payload.get("organization") or ""),
                role=str(payload.get("role") or "radiologist"),
                dua_accepted=bool(payload.get("dua_accepted")),
            )
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        session = auth_store.create_session(user["id"], request)
        response = JSONResponse({"ok": True, "user": user, **_auth_config()})
        auth_store.set_session_cookie(response, session)
        auth_store.record_audit(
            user_id=user["id"],
            action="account_registered",
            resource="auth",
            status="200",
            request=request,
            metadata={"dua_version": user["dua_version"], "role": user["role"]},
        )
        return response

    @app.post("/api/auth/login")
    async def auth_login(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "Invalid JSON."}, status_code=400)
        email = str(payload.get("email") or "")
        try:
            auth_store.enforce_request_rate_limit(
                request=request,
                scope="login",
                email=email,
                ip_limit=20,
                email_limit=8,
                window_seconds=15 * 60,
            )
        except RateLimitExceeded as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=429)
        user = auth_store.verify_user(email=email, password=str(payload.get("password") or ""))
        if user is None:
            auth_store.record_audit(
                user_id=None,
                action="login_failed",
                resource="auth",
                status="401",
                request=request,
                metadata={},
            )
            return JSONResponse({"ok": False, "error": "Invalid email or password."}, status_code=401)
        session = auth_store.create_session(user["id"], request)
        response = JSONResponse({"ok": True, "user": user, **_auth_config()})
        auth_store.set_session_cookie(response, session)
        auth_store.record_audit(
            user_id=user["id"],
            action="login_succeeded",
            resource="auth",
            status="200",
            request=request,
            metadata={},
        )
        return response

    @app.post("/api/auth/account/setup")
    async def auth_account_setup(request: Request):
        user = getattr(request.state, "current_user", None)
        if not user:
            return JSONResponse({"ok": False, "error": "Authentication required."}, status_code=401)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("Invalid JSON object.")
            updated = auth_store.complete_account_setup(
                user_id=user["id"], current_password=str(payload.get("current_password") or ""),
                new_password=str(payload.get("new_password") or ""),
                dua_accepted=payload.get("dua_accepted") is True,
            )
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        session = auth_store.create_session(user["id"], request)
        response = JSONResponse({"ok": True, "user": updated, **_auth_config()})
        auth_store.set_session_cookie(response, session)
        auth_store.record_audit(user_id=user["id"], action="account_setup_completed",
                                resource="auth", status="200", request=request,
                                metadata={"dua_version": updated["dua_version"]})
        return response

    @app.post("/api/auth/password/forgot")
    async def auth_password_forgot(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "Invalid JSON."}, status_code=400)
        email = str(payload.get("email") or "")
        try:
            auth_store.enforce_request_rate_limit(
                request=request,
                scope="password_reset",
                email=email,
                ip_limit=10,
                email_limit=5,
                window_seconds=60 * 60,
            )
        except RateLimitExceeded as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=429)
        token = auth_store.create_password_reset_token(email, request)
        if token and email_sender.configured:
            recipient = auth_store.get_user_by_email(email)
            if recipient:
                try:
                    email_sender.send_password_reset(
                        email=recipient["email"],
                        name=recipient["name"],
                        token=token,
                    )
                except Exception:
                    auth_store.record_audit(
                        user_id=recipient["id"],
                        action="password_reset_delivery_failed",
                        resource="auth",
                        status="503",
                        request=request,
                        metadata={},
                    )
        auth_store.record_audit(
            user_id=None,
            action="password_reset_requested",
            resource="auth",
            status="200",
            request=request,
            metadata={},
        )
        response_payload: dict[str, Any] = {
            "ok": True,
            "user": None,
            "message": "If an active account exists for that email, password reset instructions are available.",
            **_auth_config(),
        }
        if token and auth_store.allow_local_password_reset:
            response_payload["reset_token"] = token
            response_payload["reset_url"] = f"/auth?reset_token={token}"
        return response_payload

    @app.post("/api/auth/password/reset")
    async def auth_password_reset(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "Invalid JSON."}, status_code=400)
        try:
            user = auth_store.reset_password_with_token(
                token=str(payload.get("token") or ""),
                new_password=str(payload.get("password") or ""),
            )
        except ValueError as exc:
            auth_store.record_audit(
                user_id=None,
                action="password_reset_failed",
                resource="auth",
                status="400",
                request=request,
                metadata={},
            )
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        session = auth_store.create_session(user["id"], request)
        response = JSONResponse({"ok": True, "user": auth_store.get_user(user["id"]), **_auth_config()})
        auth_store.set_session_cookie(response, session)
        auth_store.record_audit(
            user_id=user["id"],
            action="password_reset_completed",
            resource="auth",
            status="200",
            request=request,
            metadata={},
        )
        return response

    @app.post("/api/auth/password/change")
    async def auth_password_change(request: Request):
        user = getattr(request.state, "current_user", None)
        if user is None:
            return JSONResponse({"ok": False, "error": "Authentication required."}, status_code=401)
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "Invalid JSON."}, status_code=400)
        try:
            auth_store.change_password(
                user_id=user["id"],
                current_password=str(payload.get("current_password") or ""),
                new_password=str(payload.get("new_password") or ""),
            )
        except ValueError as exc:
            auth_store.record_audit(
                user_id=user["id"],
                action="password_change_failed",
                resource="auth",
                status="400",
                request=request,
                metadata={},
            )
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        session = auth_store.create_session(user["id"], request)
        response = JSONResponse({"ok": True, "user": user, **_auth_config()})
        auth_store.set_session_cookie(response, session)
        auth_store.record_audit(
            user_id=user["id"],
            action="password_changed",
            resource="auth",
            status="200",
            request=request,
            metadata={},
        )
        return response

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request):
        user = getattr(request.state, "current_user", None)
        auth_store.revoke_session(request.cookies.get(SESSION_COOKIE_NAME))
        response = JSONResponse({"ok": True, "user": None, **_auth_config()})
        auth_store.clear_session_cookie(response)
        if user:
            auth_store.record_audit(
                user_id=user["id"],
                action="logout",
                resource="auth",
                status="200",
                request=request,
                metadata={},
            )
        return response

    @app.get("/api/auth/audit/recent")
    async def auth_audit_recent(request: Request, limit: int = Query(default=50, ge=1, le=200)):
        user = getattr(request.state, "current_user", None)
        if user is None:
            return JSONResponse({"ok": False, "error": "Authentication required."}, status_code=401)
        return {"ok": True, "events": auth_store.recent_audit(user["id"], limit=limit)}

    @app.get("/api/version")
    async def version_info():
        return public_build_info(auth_schema_version=auth_store.schema_version)

    @app.get("/health")
    async def health():
        global_capability = get_model_capability(active_model)
        neuro_model_capability = get_model_capability(neuro_config.vlm_model)
        return {
            "status": "ok",
            "provider": llm.name,
            "model": active_model,
            "model_capabilities": global_capability.to_dict(),
            "neuro_report_provider": neuro_config.vlm_provider,
            "neuro_report_model": neuro_config.vlm_model,
            "neuro_report_model_capabilities": neuro_model_capability.to_dict(),
            "dicomweb_base_url": settings.dicomweb_base_url,
            "ohif_base_url": settings.ohif_base_url,
            "clinagent": {
                "scenario_count": len(clinagent.scenario_map),
            },
            "workflow_families": list_family_registry(),
            "workflow_registry": list_workflow_registry(),
            "mcp_servers": list_mcp_servers(),
        }

    @app.get("/api/neuro-knowledge/health")
    async def neuro_knowledge_health():
        return _proxy_neuro_knowledge(lambda: _build_neuro_knowledge_client().health())

    @app.get("/api/neuro-knowledge/cohorts/v1")
    async def neuro_knowledge_cohort():
        return _proxy_neuro_knowledge(lambda: _build_neuro_knowledge_client().get_cohort())

    @app.get("/api/neuro-knowledge/search")
    async def neuro_knowledge_search(q: str = Query(default="", min_length=1)):
        return _proxy_neuro_knowledge(lambda: _build_neuro_knowledge_client().search(q))

    @app.get("/api/neuro-knowledge/cases/{patient_uid}")
    async def neuro_knowledge_case(patient_uid: str):
        return _proxy_neuro_knowledge(lambda: _build_neuro_knowledge_client().get_case(patient_uid))

    @app.get("/api/neuro-knowledge/cases/{patient_uid}/assets")
    async def neuro_knowledge_case_assets(patient_uid: str):
        return _proxy_neuro_knowledge(lambda: _build_neuro_knowledge_client().get_case_assets(patient_uid))

    @app.get("/api/neuro-knowledge/studies/{study_uid}")
    async def neuro_knowledge_study(study_uid: str):
        return _proxy_neuro_knowledge(lambda: _build_neuro_knowledge_client().get_study(study_uid))

    @app.post("/api/neuro-knowledge/launch")
    async def neuro_knowledge_launch(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(
                {"ok": False, "error": 'Invalid JSON. Send { "patient_uid": "...", "study_uid": "..." }'},
                status_code=400,
            )
        patient_uid = str(payload.get("patient_uid") or "").strip()
        study_uid = str(payload.get("study_uid") or "").strip()
        if not patient_uid or not study_uid:
            return JSONResponse(
                {"ok": False, "error": "patient_uid and study_uid are required"},
                status_code=400,
            )
        requested_local_root = str(payload.get("local_root") or "").strip() or None
        download_if_missing = bool(payload.get("download_if_missing", True))
        segmentation_preference = str(payload.get("segmentation_preference") or "vista_then_nvseg").strip()
        sequence_preference = str(payload.get("sequence_preference") or "structural_default").strip()
        return _proxy_neuro_knowledge(
            lambda: _prepare_mr_rate_launch(
                patient_uid=patient_uid,
                study_uid=study_uid,
                requested_local_root=requested_local_root,
                download_if_missing=download_if_missing,
                segmentation_preference=segmentation_preference,
                sequence_preference=sequence_preference,
            )
        )

    @app.get("/api/chat/options")
    async def chat_options():
        return _build_chat_options(config, active_model)

    @app.get("/")
    async def root():
        return RedirectResponse(url="/demo", status_code=307)

    @app.get("/demo")
    async def demo_page():
        if demo_next_index.exists():
            return FileResponse(demo_next_index)
        if demo_index.exists():
            return FileResponse(demo_index)
        return Response(content="ClinAgent UI is not available.", status_code=404)

    @app.get("/demo/{path:path}")
    async def demo_spa_fallback(path: str):
        if demo_next_index.exists():
            return FileResponse(demo_next_index)
        if demo_index.exists():
            return FileResponse(demo_index)
        return Response(content="ClinAgent UI is not available.", status_code=404)

    @app.get("/auth")
    async def auth_page():
        if demo_next_index.exists():
            return FileResponse(demo_next_index)
        if demo_index.exists():
            return FileResponse(demo_index)
        return Response(content="ClinAgent UI is not available.", status_code=404)

    @app.get("/dev")
    async def dev_page():
        if demo_next_index.exists():
            return FileResponse(demo_next_index)
        if demo_index.exists():
            return FileResponse(demo_index)
        return Response(content="Developer UI is not available.", status_code=404)

    @app.get("/dev/{path:path}")
    async def dev_spa_fallback(path: str):
        if demo_next_index.exists():
            return FileResponse(demo_next_index)
        if demo_index.exists():
            return FileResponse(demo_index)
        return Response(content="Developer UI is not available.", status_code=404)

    @app.get("/api/demo/workspace")
    async def demo_workspace():
        return demo_workspace_store.snapshot()

    @app.get("/api/demo/console")
    async def demo_console():
        return console_snapshot()

    @app.get("/api/dev/console")
    async def developer_console():
        return dev_console_snapshot(recent_trace_summary=dev_runtime_state["recent_trace_summary"])

    @app.get("/api/dev/mcp-registry")
    async def dev_mcp_registry():
        return {"servers": list_mcp_servers()}

    @app.get("/api/demo/cases/{case_id}")
    async def demo_case(case_id: str):
        try:
            return demo_workspace_store.get_case(case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown demo case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.get("/api/demo/cases/{case_id}/report")
    async def demo_case_report(case_id: str):
        try:
            workspace = demo_workspace_store.get_case(case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown demo case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )
        return {"case_id": case_id, "report": workspace.get("report", {})}

    @app.get("/api/demo/cases/{case_id}/viewer")
    async def demo_case_viewer(case_id: str):
        try:
            workspace = demo_workspace_store.get_case(case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown demo case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )
        return {
            "case_id": case_id,
            "viewer": workspace.get("viewer") or workspace.get("imaging_preview", {}).get("viewer", {}),
            "imaging_preview": workspace.get("imaging_preview", {}),
        }

    @app.get("/api/demo/cases/{case_id}/evidence-board")
    async def demo_case_evidence_board(case_id: str):
        try:
            workspace = demo_workspace_store.get_case(case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown demo case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )
        return {"case_id": case_id, "evidence_review": workspace.get("evidence_review", {})}

    @app.post("/api/demo/evidence-board/verify")
    async def demo_evidence_board_verify(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps(
                    {
                        "error": (
                            'Invalid JSON. Send { "current_study": {...}, "draft_report": "...", '
                            '"prior_study": {...}, "prior_report": "..." }'
                        )
                    }
                ),
                status_code=400,
                media_type="application/json",
            )
        try:
            evidence_request = VerifyEvidenceBoardRequest.model_validate(payload)
        except Exception as exc:
            return Response(
                content=json.dumps({"error": f"Invalid evidence-board payload: {exc}"}),
                status_code=400,
                media_type="application/json",
            )
        return verify_evidence_board(evidence_request).model_dump()

    @app.post("/api/demo/chat")
    async def demo_chat(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "...", "message": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        message = (payload.get("message") or "").strip()
        if not case_id or not message:
            return Response(
                content=json.dumps({"error": "case_id and message are required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return demo_workspace_store.chat(case_id=case_id, message=message)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown demo case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/demo/command")
    async def demo_command(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "message": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        message = (payload.get("message") or "").strip()
        if not message:
            return Response(
                content=json.dumps({"error": "message is required"}),
                status_code=400,
                media_type="application/json",
            )
        return route_general_query(message)

    def _new_trace_summary(runtime: dict[str, Any], lane: str) -> dict[str, Any]:
        return {
            "status": "running",
            "lane": lane,
            "started_at": int(time.time() * 1000),
            "route": runtime["route"],
            "profile": runtime["profile"],
            "handoff": runtime["handoff"],
            "stages": runtime["stage_summary"],
            "tasks": runtime.get("task_summary", []),
            "tool_policy": runtime.get("tool_policy", {}),
            "mcp_servers": runtime.get("mcp_servers", []),
            "mcp_snapshot": runtime.get("mcp_snapshot", {}),
            "memory_context": runtime.get("memory_context", {}),
            "planner_defaults": runtime.get("planner_defaults", {}),
            "subagent_activity": runtime["subagent_activity"],
            "tool_calls": [],
            "errors": [],
            "final_outputs": [],
        }

    def _record_trace_event(trace_summary: dict[str, Any], kind: str, data: dict[str, Any]) -> None:
        if kind == "tool_call":
            trace_summary.setdefault("tool_calls", []).append(
                {
                    "name": data.get("name", "tool"),
                    "status": "running",
                    "preview": data.get("preview") or data.get("input_preview"),
                }
            )
            return
        if kind == "tool_result":
            tool_calls = trace_summary.setdefault("tool_calls", [])
            for entry in reversed(tool_calls):
                if entry.get("name") == data.get("name") and entry.get("status") == "running":
                    entry["status"] = "error" if data.get("success") is False else "done"
                    entry["preview"] = data.get("preview") or data.get("output") or entry.get("preview")
                    if data.get("error"):
                        entry["error"] = data.get("error")
                    break
            else:
                tool_calls.append(
                    {
                        "name": data.get("name", "tool"),
                        "status": "error" if data.get("success") is False else "done",
                        "preview": data.get("preview") or data.get("output"),
                        "error": data.get("error"),
                    }
                )

    async def _execute_stream(request: Request, *, developer_surface: bool):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "message": "...", "lane": "optional", "model": "optional", "reasoning_effort": "optional" }'}),
                status_code=400,
                media_type="application/json",
            )

        message = (payload.get("message") or "").strip()
        ingest_context = payload.get("ingest_context")
        lane = _resolve_lane(payload.get("lane"))
        requested_model = str(payload.get("model") or "").strip()
        requested_reasoning_effort = str(payload.get("reasoning_effort") or "").strip().lower()
        session_id = str(payload.get("session_id") or "").strip() or None
        if not message:
            return Response(
                content=json.dumps({"error": "message is required"}),
                status_code=400,
                media_type="application/json",
            )

        chat_options = _build_chat_options(config, active_model)
        available_model_ids = {entry["id"] for entry in chat_options["models"]}
        selected_model = requested_model or active_model
        if selected_model not in available_model_ids:
            return Response(
                content=json.dumps({"error": f"Unknown or unavailable model: {selected_model}"}),
                status_code=400,
                media_type="application/json",
            )

        if requested_reasoning_effort and requested_reasoning_effort not in VALID_REASONING_EFFORTS:
            return Response(
                content=json.dumps({"error": f"Invalid reasoning_effort: {requested_reasoning_effort}"}),
                status_code=400,
                media_type="application/json",
            )

        selected_model_capability = get_model_capability(selected_model)
        effective_reasoning_effort = (
            requested_reasoning_effort if requested_reasoning_effort and selected_model_capability.supports_reasoning_effort else ""
        )
        request_config = config.model_copy(deep=True)
        request_config.openai_reasoning_effort = effective_reasoning_effort
        try:
            request_llm = create_provider(selected_model, request_config)
        except Exception as exc:
            return Response(
                content=json.dumps({"error": f"Unable to initialize model {selected_model}: {exc}"}),
                status_code=400,
                media_type="application/json",
            )

        import asyncio

        event_queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _build_report_artifact_preview(workflow_id: str) -> dict[str, Any] | None:
            if workflow_id == "neuro_report":
                return _build_neuro_report_artifact_preview(message, ingest_context=ingest_context)
            if workflow_id == "report_quality_review":
                return _build_report_quality_artifact_preview(message)
            if workflow_id == "radonc_plan_optimization":
                return _build_radonc_plan_artifact_preview(message)
            if workflow_id != "neuro_longitudinal":
                return None
            try:
                snapshot = demo_workspace_store.snapshot()
                workspace = snapshot.get("workspace", {})
                report = workspace.get("report", {})
                quality = report.get("quality_review", {})
                return {
                    "kind": "neuro_report",
                    "module": "neuro",
                    "case_id": workspace.get("id"),
                    "title": report.get("title"),
                    "subtitle": report.get("subtitle"),
                    "patient_label": workspace.get("patient", {}).get("display_name"),
                    "risk_level": report.get("risk_level"),
                    "summary": report.get("summary"),
                    "qa_status": quality.get("status"),
                    "qa_counts": quality.get("counts", {}),
                }
            except Exception:
                return None

        def sse(event: str, data: Any):
            event_queue.put_nowait(f"event: {event}\ndata: {json.dumps(data)}\n\n")

        async def _call_route() -> dict[str, Any]:
            try:
                return await route_with_llm(
                    request_llm,
                    message,
                    ingest_context=ingest_context,
                    session_id=session_id,
                )
            except TypeError:
                if ingest_context:
                    return await route_with_llm(request_llm, message, ingest_context=ingest_context)
                return await route_with_llm(request_llm, message)

        async def _run():
            route = await _call_route()
            persist_session_intent_state(session_id, message, route)
            runtime_route = dict(route)
            if route["workflow_id"] == "neuro_report":
                intake_context, capability_profile, analysis_plan = intake_plan_from_message(
                    message,
                    ingest_context=ingest_context,
                )
                memory_context = build_reviewed_memory_context(
                    workflow_family=analysis_plan.workflow_family,
                    reviewed_pattern_ids=["response_default_bundle" if analysis_plan.primary_goal == "response_review" else "review_default_bundle" if analysis_plan.primary_goal == "report_review" else "structural_default_bundle"],
                    workflow_keys=[("neuro_report", "examples")],
                    user_id="default_demo_user",
                )
                runtime_route.update(
                    {
                        "workflow_family": analysis_plan.workflow_family,
                        "track": analysis_plan.analysis_track,
                        "primary_goal": analysis_plan.primary_goal,
                        "dashboard_profile": analysis_plan.dashboard_profile,
                        "context_sources": capability_profile.context_sources,
                        "fallback_reason": capability_profile.blocked_reasons[0] if capability_profile.blocked_reasons else None,
                        "memory_context": memory_context,
                        "planner_defaults": derive_reviewed_memory_defaults(memory_context),
                    }
                )
            elif route["workflow_id"] == "report_quality_review":
                intake_context, capability_profile, analysis_plan = intake_plan_from_report_quality_message(message)
                memory_context = build_reviewed_memory_context(
                    workflow_family=analysis_plan.workflow_family,
                    reviewed_pattern_ids=["report_quality_default_bundle"],
                    workflow_keys=[("report_quality_review", "default_snapshot")],
                    user_id="default_demo_user",
                )
                runtime_route.update(
                    {
                        "workflow_family": analysis_plan.workflow_family,
                        "track": analysis_plan.analysis_track,
                        "primary_goal": analysis_plan.primary_goal,
                        "dashboard_profile": analysis_plan.dashboard_profile,
                        "context_sources": capability_profile.context_sources,
                        "fallback_reason": capability_profile.blocked_reasons[0] if capability_profile.blocked_reasons else None,
                        "memory_context": memory_context,
                        "planner_defaults": derive_reviewed_memory_defaults(memory_context),
                    }
                )
            elif route["workflow_id"] == "radonc_plan_optimization":
                intake_context, capability_profile, analysis_plan = intake_plan_from_radonc_message(message)
                memory_context = build_reviewed_memory_context(
                    workflow_family=analysis_plan.workflow_family,
                    reviewed_pattern_ids=["plan_optimization_default_bundle"],
                    workflow_keys=[("radonc_plan_optimization", "default_snapshot")],
                    user_id="default_demo_user",
                    session_id=radonc_plan_demo_store.snapshot()["default_session_id"],
                )
                runtime_route.update(
                    {
                        "workflow_family": analysis_plan.workflow_family,
                        "track": analysis_plan.analysis_track,
                        "primary_goal": analysis_plan.primary_goal,
                        "dashboard_profile": analysis_plan.dashboard_profile,
                        "context_sources": capability_profile.context_sources,
                        "fallback_reason": capability_profile.blocked_reasons[0] if capability_profile.blocked_reasons else None,
                        "memory_context": memory_context,
                        "planner_defaults": derive_reviewed_memory_defaults(memory_context),
                    }
                )
            runtime = build_route_runtime(runtime_route)
            if developer_surface:
                dev_runtime_state["recent_trace_summary"] = _new_trace_summary(runtime, lane)
            routed_payload = {
                "session_id": session_id,
                "workflow_id": route["workflow_id"],
                "target_module": route["target_module"],
                "suggested_module": route.get("suggested_module"),
                "confidence": route["confidence"],
                "reason": route["reason"],
                "next_action": route["next_action"],
                "alternatives": route.get("alternatives", []),
                "intent_label": route.get("intent_label"),
                "needs_clarification": route.get("needs_clarification", False),
                "clarification_question": route.get("clarification_question"),
                "missing_slots": route.get("missing_slots", []),
                "fallback": route["fallback"],
            }
            if developer_surface:
                routed_payload.update(
                    {
                        "profile": runtime["profile"],
                        "handoff": runtime["handoff"],
                        "stage_summary": runtime["stage_summary"],
                        "task_summary": runtime.get("task_summary", []),
                        "tool_policy": runtime.get("tool_policy", {}),
                        "mcp_servers": runtime.get("mcp_servers", []),
                        "mcp_snapshot": runtime.get("mcp_snapshot", {}),
                        "memory_context": runtime.get("memory_context", {}),
                        "planner_defaults": runtime.get("planner_defaults", {}),
                        "subagent_activity": runtime["subagent_activity"],
                        "developer_explanation": runtime["developer_explanation"],
                        "user_explanation": route.get("clarification_question") or runtime["user_explanation"],
                    }
                )
            else:
                routed_payload.update(
                    {
                        "route_summary": route.get("clarification_question") or runtime["user_explanation"],
                        "user_explanation": route.get("clarification_question") or runtime["user_explanation"],
                        "stage_summary": [stage["label"] for stage in runtime["stage_summary"]],
                    }
                )
            sse("routed", routed_payload)
            sse("queued", {"lane": lane, "position": get_queue_size(lane)})

            if route.get("needs_clarification"):
                clarification_result = route.get("clarification_question") or "I need one more detail before I can continue."
                done_payload = {
                    "session_id": session_id,
                    "lane": lane,
                    "workflow_id": route["workflow_id"],
                    "target_module": route["target_module"],
                    "suggested_module": route.get("suggested_module"),
                    "status": "needs_clarification",
                    "result": clarification_result,
                    "iterations": 0,
                }
                if developer_surface:
                    done_payload.update({"profile": runtime["profile"], "handoff": runtime["handoff"]})
                    dev_runtime_state["recent_trace_summary"].update(
                        {
                            "status": "needs_clarification",
                            "completed_at": int(time.time() * 1000),
                            "final_outputs": [
                                {
                                    "kind": "clarification_request",
                                    "summary": clarification_result,
                                }
                            ],
                        }
                    )
                sse("done", done_payload)
                event_queue.put_nowait(None)
                return

            smalltalk_reply = None
            if route["workflow_id"] == "general_chat":
                smalltalk_reply = get_smalltalk_reply(message)
            if smalltalk_reply:
                sse("started", {"lane": lane, "workflow_id": route["workflow_id"]})
                done_payload = {
                    "session_id": session_id,
                    "lane": lane,
                    "workflow_id": route["workflow_id"],
                    "target_module": route["target_module"],
                    "suggested_module": route.get("suggested_module"),
                    "status": "ok",
                    "result": smalltalk_reply,
                    "iterations": 0,
                }
                if developer_surface:
                    done_payload.update({"profile": runtime["profile"], "handoff": runtime["handoff"]})
                    dev_runtime_state["recent_trace_summary"].update(
                        {
                            "status": "done",
                            "completed_at": int(time.time() * 1000),
                            "final_outputs": [
                                {
                                    "kind": "chat_reply",
                                    "summary": smalltalk_reply,
                                }
                            ],
                        }
                    )
                sse("done", done_payload)
                event_queue.put_nowait(None)
                return

            if route["workflow_id"] == "neuro_report":
                intake_context, capability_profile, analysis_plan = intake_plan_from_message(
                    message,
                    ingest_context=ingest_context,
                )
                planning_result = build_planning_result(
                    intake_context,
                    capability_profile,
                    analysis_plan,
                    requested_mode=analysis_plan.recommended_mode,
                    executed_mode=analysis_plan.recommended_mode,
                    viewer_type="dicomweb" if capability_profile.imaging_format == "dicom" else "png_fallback",
                )
                artifact = _build_report_artifact_preview("neuro_report")
                sse("started", {"lane": lane, "workflow_id": route["workflow_id"]})
                done_payload = {
                    "session_id": session_id,
                    "lane": lane,
                    "workflow_id": route["workflow_id"],
                    "target_module": route["target_module"],
                    "suggested_module": route.get("suggested_module"),
                    "status": "ok",
                    "result": analysis_plan.handoff_summary,
                    "artifact": artifact,
                    "analysis_plan": analysis_plan.to_dict(),
                    "capability_profile": capability_profile.to_dict(),
                    "planning_result": planning_result.to_dict(),
                    "iterations": 0,
                }
                if developer_surface:
                    done_payload.update({"profile": runtime["profile"], "handoff": runtime["handoff"]})
                    dev_runtime_state["recent_trace_summary"].update(
                        {
                            "status": "done",
                            "completed_at": int(time.time() * 1000),
                            "final_outputs": [
                                {
                                    "kind": "neuro_report_handoff",
                                    "summary": analysis_plan.handoff_summary,
                                }
                            ],
                        }
                    )
                sse("done", done_payload)
                event_queue.put_nowait(None)
                return

            if route["workflow_id"] == "report_quality_review":
                intake_context, capability_profile, analysis_plan = intake_plan_from_report_quality_message(message)
                planning_result = build_report_quality_planning_result(
                    intake_context,
                    capability_profile,
                    analysis_plan,
                )
                artifact = _build_report_artifact_preview("report_quality_review")
                sse("started", {"lane": lane, "workflow_id": route["workflow_id"]})
                done_payload = {
                    "session_id": session_id,
                    "lane": lane,
                    "workflow_id": route["workflow_id"],
                    "target_module": route["target_module"],
                    "suggested_module": route.get("suggested_module"),
                    "status": "ok",
                    "result": analysis_plan.handoff_summary,
                    "artifact": artifact,
                    "analysis_plan": analysis_plan.to_dict(),
                    "capability_profile": capability_profile.to_dict(),
                    "planning_result": planning_result.to_dict(),
                    "iterations": 0,
                }
                if developer_surface:
                    done_payload.update({"profile": runtime["profile"], "handoff": runtime["handoff"]})
                    dev_runtime_state["recent_trace_summary"].update(
                        {
                            "status": "done",
                            "completed_at": int(time.time() * 1000),
                            "final_outputs": [
                                {
                                    "kind": "report_quality_handoff",
                                    "summary": analysis_plan.handoff_summary,
                                }
                            ],
                        }
                    )
                sse("done", done_payload)
                event_queue.put_nowait(None)
                return

            if route["workflow_id"] == "radonc_plan_optimization":
                intake_context, capability_profile, analysis_plan = intake_plan_from_radonc_message(message)
                planning_result = build_radonc_planning_result(
                    intake_context,
                    capability_profile,
                    analysis_plan,
                )
                artifact = _build_radonc_plan_artifact_preview(message)
                sse("started", {"lane": lane, "workflow_id": route["workflow_id"]})
                done_payload = {
                    "session_id": session_id,
                    "lane": lane,
                    "workflow_id": route["workflow_id"],
                    "target_module": route["target_module"],
                    "suggested_module": route.get("suggested_module"),
                    "status": "ok",
                    "result": analysis_plan.handoff_summary,
                    "artifact": artifact,
                    "analysis_plan": analysis_plan.to_dict(),
                    "capability_profile": capability_profile.to_dict(),
                    "planning_result": planning_result.to_dict(),
                    "iterations": 0,
                }
                if developer_surface:
                    done_payload.update({"profile": runtime["profile"], "handoff": runtime["handoff"]})
                    dev_runtime_state["recent_trace_summary"].update(
                        {
                            "status": "done",
                            "completed_at": int(time.time() * 1000),
                            "final_outputs": [
                                {
                                    "kind": "radonc_plan_handoff",
                                    "summary": analysis_plan.handoff_summary,
                                }
                            ],
                        }
                    )
                sse("done", done_payload)
                event_queue.put_nowait(None)
                return

            async def _execute():
                sse("started", {"lane": lane, "workflow_id": route["workflow_id"]})
                agent = build_console_agent(request_llm, route["workflow_id"])

                def on_event(kind, data):
                    if developer_surface:
                        _record_trace_event(dev_runtime_state["recent_trace_summary"], kind, data)
                    sse("agent", {"kind": kind, "data": data})

                task = build_routed_task(route, message)
                return await agent.invoke(task, on_event=on_event)

            try:
                result = await enqueue_command_in_lane(lane, _execute)
                done_payload = {
                    "session_id": session_id,
                    "lane": lane,
                    "workflow_id": route["workflow_id"],
                    "target_module": route["target_module"],
                    "suggested_module": route.get("suggested_module"),
                    "status": result.status,
                    "result": result.result,
                    "artifact": _build_report_artifact_preview(route["workflow_id"]),
                    "iterations": result.iterations,
                }
                if developer_surface:
                    done_payload.update({"profile": runtime["profile"], "handoff": runtime["handoff"]})
                    dev_runtime_state["recent_trace_summary"].update(
                        {
                            "status": result.status,
                            "completed_at": int(time.time() * 1000),
                            "final_outputs": [
                                {
                                    "kind": runtime["profile"]["output_contract"]["kind"],
                                    "summary": result.result,
                                }
                            ],
                        }
                    )
                sse("done", done_payload)
            except Exception as e:
                if developer_surface:
                    dev_runtime_state["recent_trace_summary"].update(
                        {
                            "status": "error",
                            "completed_at": int(time.time() * 1000),
                            "errors": [str(e)],
                        }
                    )
                sse("error", {"lane": lane, "error": str(e)})
            finally:
                event_queue.put_nowait(None)

        asyncio.create_task(_run())

        async def _stream():
            while True:
                msg = await event_queue.get()
                if msg is None:
                    break
                yield msg

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    @app.post("/api/demo/execute-stream")
    async def demo_execute_stream(request: Request):
        return await _execute_stream(request, developer_surface=False)

    @app.post("/api/dev/execute-stream")
    async def developer_execute_stream(request: Request):
        return await _execute_stream(request, developer_surface=True)

    @app.get("/api/demo/radonc-plan/patients")
    async def radonc_plan_patients():
        return radonc_plan_demo_store.get_patients()

    @app.get("/api/demo/radonc-plan/session")
    async def radonc_plan_session(patient_id: str | None = Query(default=None), session_id: str | None = Query(default=None)):
        try:
            return radonc_plan_demo_store.snapshot(patient_id=patient_id, session_id=session_id)
        except KeyError:
            if patient_id:
                return JSONResponse({"error": f"Unknown radonc patient: {patient_id}"}, status_code=404)
            if session_id:
                return JSONResponse({"error": f"Unknown radonc plan session: {session_id}"}, status_code=404)
            return JSONResponse({"error": "No radonc patients are available."}, status_code=404)

    @app.get("/api/demo/radonc-plan/sessions/{session_id}")
    async def radonc_plan_session_detail(session_id: str):
        try:
            return radonc_plan_demo_store.get_session(session_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown radonc plan session: {session_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/demo/radonc-plan/sessions/{session_id}/reset")
    async def radonc_plan_reset(session_id: str):
        try:
            return radonc_plan_demo_store.reset_session(session_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown radonc plan session: {session_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.websocket("/api/demo/radonc-plan/ws/{session_id}")
    async def radonc_plan_ws(websocket: WebSocket, session_id: str):
        import asyncio

        if preview_scope == "brain_tumor":
            await websocket.close(code=4003, reason="Unavailable in this preview")
            return
        if auth_store.require_user_auth:
            user = auth_store.user_from_token(websocket.cookies.get(SESSION_COOKIE_NAME))
            if user is None:
                await websocket.close(code=4001, reason="Authentication required")
                return
            if user.get("role") != "admin" or user.get("account_setup_required") or not websocket_origin_allowed(websocket):
                await websocket.close(code=4003, reason="Operator access required")
                return
        await websocket.accept()
        loop_task: asyncio.Task[str] | None = None
        orchestrator: OptimizationOrchestrator | None = None

        def _find_command_entry(session_model, command_id: str) -> PlannerCommand | None:
            return next((item for item in session_model.command_history if item.id == command_id), None)

        def _describe_suggestion_change(objective_suggestion) -> str:
            objective = objective_suggestion.objective
            dose_text = f"{objective.dose:g} cGy"
            if objective.volume is not None:
                dose_text = f"{dose_text} @ {objective.volume:g}{objective.volume_unit or '%'}"
            return (
                f"{objective_suggestion.action.title()} {objective.roi} {objective.objective_type} "
                f"to {dose_text}, weight {objective.weight:g}."
            )

        def _apply_objective_table_updates(
            session_model,
            updates: list[dict[str, object]],
        ) -> tuple[list[str], list[PlanObjective]]:
            next_objectives = [item.model_copy(deep=True) for item in session_model.current_objectives]
            change_descriptions: list[str] = []
            for payload in updates:
                roi = str(payload.get("roi") or "").strip()
                objective_type = str(payload.get("objective_type") or "").strip()
                if not roi or not objective_type:
                    continue
                target = next(
                    (item for item in next_objectives if item.roi == roi and item.objective_type == objective_type),
                    None,
                )
                if target is None:
                    continue
                original_dose = target.dose
                original_weight = target.weight
                dose_value = payload.get("dose")
                weight_value = payload.get("weight")
                if isinstance(dose_value, (int, float)):
                    target.dose = max(0.0, round(float(dose_value), 2))
                if isinstance(weight_value, (int, float)):
                    target.weight = max(0.0, round(float(weight_value), 2))
                if target.dose != original_dose or target.weight != original_weight:
                    change_descriptions.append(
                        f"{roi} {objective_type}: dose {original_dose:g}→{target.dose:g} cGy, weight {original_weight:g}→{target.weight:g}."
                    )
            return change_descriptions, next_objectives

        def _build_orchestrator() -> OptimizationOrchestrator:
            session = radonc_plan_demo_store.get_session_model(session_id)

            async def _handle_event(event_type: str, data: dict[str, object]) -> None:
                active_session = radonc_plan_demo_store.get_session_model(session_id)
                if event_type == "thinking":
                    active_session.latest_thinking_log = str(data.get("content") or "")
                    radonc_plan_demo_store.update_session(active_session)
                elif event_type == "iteration_complete":
                    iteration = OptimizationIteration.model_validate(data["iteration"])
                    dvh_data = [DVHSnapshot.model_validate(item) for item in data.get("dvh_data", [])]
                    objective_results = [ObjectiveResult.model_validate(item) for item in data.get("objective_results", [])]
                    radonc_plan_demo_store.apply_iteration(
                        session_id=session_id,
                        iteration=iteration,
                        dvh_data=dvh_data,
                        suggestions=iteration.suggestions,
                        goal_status=iteration.goal_status,
                        objectives=iteration.objectives_snapshot,
                        objective_results=objective_results,
                        connector_state=data.get("connector_state") if isinstance(data.get("connector_state"), dict) else None,
                    )
                elif event_type == "session_complete":
                    reason = str(data.get("reason") or "completed")
                    active_session.status = "stopped" if reason == "stopped" else "completed"
                    active_session.messages.append(
                        {
                            "role": "assistant",
                            "content": f"Optimization loop finished with stop condition: {reason.replace('_', ' ')}.",
                        }
                    )
                    radonc_plan_demo_store.update_session(active_session)
                elif event_type == "iteration_start":
                    active_session.status = "running"
                    radonc_plan_demo_store.update_session(active_session)
                await websocket.send_json({"type": event_type, **data})

            connector = (
                AirtMockPlanningConnector(
                    patient_dir=radonc_plan_demo_store.get_patient_dir_for_session(session_id),
                    start_iteration=session.start_iteration_number,
                    current_objectives=session.current_objectives,
                    data_source_id=session.data_source_id,
                )
                if session.data_source_type == "airt_mock"
                else MockRTPlanningConnector(session)
            )

            return OptimizationOrchestrator(
                session_id=session.id,
                connector=connector,
                goals=session.goals,
                current_objectives=session.current_objectives,
                current_dvh_data=session.dvh_data,
                start_goal_status=session.start_goal_status or session.goal_status,
                start_dvh_data=session.start_dvh_data or session.dvh_data,
                reference_goal_status=session.reference_goal_status,
                reference_dvh_data=session.reference_dvh_data,
                max_iterations=session.simulation_max_iterations,
                plateau_threshold=session.plateau_threshold,
                history=session.iterations,
                command_history=[item.text for item in session.command_history if item.status == "queued"],
                start_iteration_number=session.start_iteration_number,
                reference_iteration_number=session.reference_iteration_number,
                on_event=_handle_event,
            )

        async def _send_snapshot() -> None:
            await websocket.send_json({"type": "session_snapshot", "session": radonc_plan_demo_store.get_session(session_id)})

        async def _run_single_iteration_preview(*, command_id: str | None = None) -> None:
            nonlocal orchestrator
            current_session = radonc_plan_demo_store.get_session_model(session_id)
            if current_session.status == "completed":
                await websocket.send_json(
                    {
                        "type": "agent_message",
                        "role": "assistant",
                        "content": "This simulation is complete. Reset the workspace to apply new planner instructions from the observed start bundle.",
                    }
                )
                return

            if orchestrator is None or (loop_task is not None and loop_task.done()):
                orchestrator = _build_orchestrator()

            orchestrator.resume()
            current_session.status = "running"
            radonc_plan_demo_store.update_session(current_session)
            await websocket.send_json({"type": "status_change", "status": "running"})
            await orchestrator.run_iteration()

            refreshed = radonc_plan_demo_store.get_session_model(session_id)
            latest_iteration = refreshed.iterations[-1] if refreshed.iterations else None
            simulation_complete = len(refreshed.iterations) >= refreshed.simulation_max_iterations

            if command_id and latest_iteration is not None:
                command_entry = _find_command_entry(refreshed, command_id)
                if command_entry is not None:
                    command_entry.status = "executed"
                    command_entry.applied_in_iteration = latest_iteration.number
                    command_entry.effect_summary = latest_iteration.improvement_summary

            if latest_iteration and latest_iteration.goals_fulfilled == latest_iteration.goals_total:
                refreshed.status = "completed"
                refreshed.messages.append(
                    {
                        "role": "assistant",
                        "content": "All protocol goals are met in the current simulated plan. Compare it with the observed Iteration002 reference bundle.",
                    }
                )
                radonc_plan_demo_store.update_session(refreshed)
                await websocket.send_json({"type": "session_complete", "reason": "all_goals_met"})
            elif simulation_complete:
                refreshed.status = "completed"
                refreshed.messages.append(
                    {
                        "role": "assistant",
                        "content": "Simulation reached the configured 20-step limit. Review the final DVH trajectory against the observed Iteration002 reference bundle.",
                    }
                )
                radonc_plan_demo_store.update_session(refreshed)
                await websocket.send_json({"type": "session_complete", "reason": "max_iterations"})
            elif refreshed.control_mode == "supervised":
                refreshed.status = "paused"
                refreshed.messages.append(
                    {
                        "role": "assistant",
                        "content": (
                            f"Simulated Iteration #{latest_iteration.number} is ready for review."
                            if latest_iteration is not None
                            else "Supervised mode paused after one simulated step. Review the dashboard, then resume when ready."
                        ),
                    }
                )
                radonc_plan_demo_store.update_session(refreshed)
                await websocket.send_json({"type": "status_change", "status": "paused"})
            else:
                refreshed.status = "ready"
                if command_id and latest_iteration is not None:
                    refreshed.messages.append(
                        {
                            "role": "assistant",
                            "content": (
                                f"Applied the planner update and simulated Iteration #{latest_iteration.number}. "
                                "Review the updated objective deck and DVH before the next step."
                            ),
                        }
                    )
                elif refreshed.control_mode == "manual":
                    refreshed.messages.append(
                        {
                            "role": "assistant",
                            "content": "Manual mode completed one simulated step. Use Run Iteration again for the next predicted DVH update.",
                        }
                    )
                radonc_plan_demo_store.update_session(refreshed)
                await websocket.send_json({"type": "status_change", "status": "ready"})

            await _send_snapshot()

        try:
            await _send_snapshot()
            while True:
                payload = await websocket.receive_json()
                if auth_store.require_user_auth and auth_store.user_from_token(websocket.cookies.get(SESSION_COOKIE_NAME)) is None:
                    await websocket.close(code=4001, reason="Session expired")
                    return
                message_type = str(payload.get("type") or "").strip().lower()
                session = radonc_plan_demo_store.get_session_model(session_id)

                if message_type == "command":
                    text = str(payload.get("text") or "").strip()
                    run_after_apply = bool(payload.get("run_after_apply", False))
                    if not text:
                        continue
                    command_entry = PlannerCommand(text=text, status="queued", run_after_apply=run_after_apply)
                    session.command_history.append(command_entry)
                    session.messages.append({"role": "user", "content": text})
                    if session.status != "running":
                        command_update = apply_planner_command_update(text, session.goals, session.current_objectives)
                        if command_update is not None:
                            next_goals, next_objectives, suggestions, response_text = command_update
                            session.goals = next_goals
                            session.current_objectives = next_objectives
                            session.goal_status = build_goal_statuses(session.goals, session.dvh_data)
                            session.start_goal_status = build_goal_statuses(session.goals, session.start_dvh_data)
                            session.reference_goal_status = build_goal_statuses(session.goals, session.reference_dvh_data)
                            session.objective_results = build_objective_results(session.current_objectives, session.dvh_data)
                            _, comparison_metrics, comparison_summary = build_reference_comparison(
                                goals=session.goals,
                                start_goal_status=session.start_goal_status,
                                current_goal_status=session.goal_status,
                                reference_goal_status=session.reference_goal_status,
                                current_dvh_data=session.dvh_data,
                                reference_dvh_data=session.reference_dvh_data,
                                current_label=f"Observed Iteration {session.start_iteration_number}",
                                reference_label=f"Observed Iteration {session.reference_iteration_number}",
                            )
                            session.comparison_metrics = comparison_metrics
                            session.comparison_summary = comparison_summary
                            session.latest_suggestions = suggestions
                            command_entry.status = "applied"
                            command_entry.response_text = response_text
                            command_entry.applied_changes = [_describe_suggestion_change(item) for item in suggestions]
                            command_entry.effect_summary = (
                                "Applied to the active objective deck. Running one predicted iteration now."
                                if run_after_apply
                                else "Applied to the active objective deck. Simulate the next iteration to measure the DVH effect."
                            )
                            assistant_copy = (
                                f"{response_text} Running one predicted iteration now."
                                if run_after_apply
                                else response_text
                            )
                            session.messages.append({"role": "assistant", "content": assistant_copy})
                            radonc_plan_demo_store.update_session(session)
                            if orchestrator is not None:
                                orchestrator.sync_workspace_state(goals=session.goals, current_objectives=session.current_objectives)
                            await websocket.send_json({"type": "agent_message", "role": "user", "content": text})
                            await websocket.send_json({"type": "agent_message", "role": "assistant", "content": assistant_copy})
                            await _send_snapshot()
                            if run_after_apply:
                                await _run_single_iteration_preview(command_id=command_entry.id)
                            continue
                        command_entry.status = "ignored"
                        command_entry.response_text = "The planner could not map that instruction to a supported dose or coverage objective."
                        command_entry.effect_summary = "No objective or clinical goal was changed."
                        session.messages.append(
                            {
                                "role": "assistant",
                                "content": "I could not map that instruction to a supported dose or coverage edit yet. Try an explicit ROI with Dmean, Dmax, or Vx target.",
                            }
                        )
                        radonc_plan_demo_store.update_session(session)
                        await websocket.send_json({"type": "agent_message", "role": "user", "content": text})
                        await websocket.send_json(
                            {
                                "type": "agent_message",
                                "role": "assistant",
                                "content": "I could not map that instruction to a supported dose or coverage edit yet. Try an explicit ROI with Dmean, Dmax, or Vx target.",
                            }
                        )
                        await _send_snapshot()
                        continue
                    command_entry.effect_summary = "Queued for the next simulated step while the optimizer is running."
                    command_entry.response_text = "Queued for the next simulated step."
                    radonc_plan_demo_store.update_session(session)
                    if orchestrator is not None:
                        orchestrator.add_user_command(text)
                    await websocket.send_json({"type": "agent_message", "role": "user", "content": text})
                    await _send_snapshot()
                    continue

                if message_type == "update_objectives":
                    updates = payload.get("updates")
                    run_after_apply = bool(payload.get("run_after_apply", False))
                    if not isinstance(updates, list):
                        continue
                    if session.status == "running":
                        await websocket.send_json(
                            {
                                "type": "agent_message",
                                "role": "assistant",
                                "content": "Pause the optimizer before editing dose or weight in the active objective deck.",
                            }
                        )
                        continue
                    change_descriptions, next_objectives = _apply_objective_table_updates(session, updates)
                    if not change_descriptions:
                        await websocket.send_json(
                            {
                                "type": "agent_message",
                                "role": "assistant",
                                "content": "No objective edits were detected. Change dose or weight first, then confirm the update.",
                            }
                        )
                        continue
                    session.current_objectives = next_objectives
                    session.objective_results = build_objective_results(session.current_objectives, session.dvh_data)
                    command_entry = PlannerCommand(
                        text=f"Manual objective edit: {'; '.join(change_descriptions)}",
                        status="applied",
                        response_text="Updated the active objective deck from manual table edits.",
                        effect_summary=(
                            "Manual edits applied. Running one predicted iteration now."
                            if run_after_apply
                            else "Manual edits applied to the active objective deck."
                        ),
                        applied_changes=change_descriptions,
                        run_after_apply=run_after_apply,
                    )
                    session.command_history.append(command_entry)
                    session.messages.append(
                        {
                            "role": "assistant",
                            "content": (
                                "Updated the active objective deck from manual edits. Running one predicted iteration now."
                                if run_after_apply
                                else "Updated the active objective deck from manual edits."
                            ),
                        }
                    )
                    radonc_plan_demo_store.update_session(session)
                    if orchestrator is not None:
                        orchestrator.sync_workspace_state(current_objectives=session.current_objectives)
                    await websocket.send_json(
                        {
                            "type": "agent_message",
                            "role": "assistant",
                            "content": (
                                "Updated the active objective deck from manual edits. Running one predicted iteration now."
                                if run_after_apply
                                else "Updated the active objective deck from manual edits."
                            ),
                        }
                    )
                    await _send_snapshot()
                    if run_after_apply:
                        await _run_single_iteration_preview(command_id=command_entry.id)
                    continue

                if message_type == "toggle_thinking":
                    session.show_thinking = bool(payload.get("visible", True))
                    radonc_plan_demo_store.update_session(session)
                    await _send_snapshot()
                    continue

                if message_type == "set_control_mode":
                    mode = str(payload.get("mode") or "").strip().lower()
                    if mode in {"auto", "supervised", "manual"}:
                        session.control_mode = mode
                        radonc_plan_demo_store.update_session(session)
                        await websocket.send_json({"type": "status_change", "status": session.status})
                        await _send_snapshot()
                    continue

                if message_type == "reset":
                    if loop_task is not None and not loop_task.done():
                        if orchestrator is not None:
                            orchestrator.stop()
                        loop_task.cancel()
                    radonc_plan_demo_store.reset_session(session_id)
                    orchestrator = None
                    loop_task = None
                    await _send_snapshot()
                    continue

                if message_type == "pause":
                    if session.status != "running":
                        continue
                    session.status = "paused"
                    radonc_plan_demo_store.update_session(session)
                    if orchestrator is not None:
                        orchestrator.pause()
                    await websocket.send_json({"type": "status_change", "status": "paused"})
                    await _send_snapshot()
                    continue

                if message_type == "stop":
                    session.status = "stopped"
                    radonc_plan_demo_store.update_session(session)
                    if orchestrator is not None:
                        orchestrator.stop()
                    await websocket.send_json({"type": "status_change", "status": "stopped"})
                    await _send_snapshot()
                    continue

                if message_type in {"start", "resume", "run_iteration"}:
                    if session.status == "completed":
                        await websocket.send_json(
                            {
                                "type": "agent_message",
                                "role": "assistant",
                                "content": "This simulation is complete. Reset the workspace to restart from the observed start bundle.",
                            }
                        )
                        continue
                    if session.control_mode == "manual" and message_type in {"start", "resume"}:
                        await websocket.send_json(
                            {
                                "type": "agent_message",
                                "role": "assistant",
                                "content": "Manual mode only advances one step at a time. Use Run Iteration for the next simulated update.",
                            }
                        )
                        continue
                    if session.status == "running":
                        continue
                    if orchestrator is None or (loop_task is not None and loop_task.done()):
                        orchestrator = _build_orchestrator()
                    if message_type in {"start", "resume"} and orchestrator is not None:
                        orchestrator.resume()
                    session.status = "running"
                    radonc_plan_demo_store.update_session(session)
                    await websocket.send_json({"type": "status_change", "status": "running"})
                    single_step = message_type == "run_iteration" or session.control_mode in {"supervised", "manual"}
                    if single_step:
                        await _run_single_iteration_preview()
                        continue
                    if loop_task is None or loop_task.done():
                        loop_task = asyncio.create_task(orchestrator.run_loop())
                    continue
        except WebSocketDisconnect:
            if orchestrator is not None:
                orchestrator.stop()
            if loop_task is not None and not loop_task.done():
                loop_task.cancel()

    @app.post("/api/demo/upload")
    async def demo_upload(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "...", "filename": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        filename = (payload.get("filename") or "").strip()
        if not case_id or not filename:
            return Response(
                content=json.dumps({"error": "case_id and filename are required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return demo_workspace_store.add_upload(case_id=case_id, filename=filename)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown demo case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/demo/review")
    async def demo_review(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "...", "action": "...", "comment": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        action = (payload.get("action") or "").strip()
        comment = (payload.get("comment") or "").strip() or None
        if not case_id or not action:
            return Response(
                content=json.dumps({"error": "case_id and action are required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return demo_workspace_store.review(case_id=case_id, action=action, comment=comment)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown demo case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    # --- Neuro Report Demo endpoints ---

    @app.get("/api/demo/neuro-report/examples")
    async def neuro_report_examples():
        _, neuro_report_demo_store = _get_neuro_report_demo_components()
        examples = neuro_report_demo_store.get_examples()
        preload_status = neuro_report_demo_store.get_preload_status()
        if auth_store.require_user_auth:
            examples = [neuro_access.publish_curated(str(item.get("patient_id")), item) for item in examples
                        if neuro_access.patient_allowed(str(item.get("patient_id")))]
            preload_status = {"available": bool(examples)}
        return {
            "default_case_id": examples[0]["case_id"] if examples else None,
            "examples": examples,
            "preload_status": preload_status,
        }

    @app.get("/api/demo/neuro-report/patients")
    async def neuro_report_patients():
        _, neuro_report_demo_store = _get_neuro_report_demo_components()
        payload = neuro_report_demo_store.get_patients()
        if auth_store.require_user_auth:
            patients = [item for item in payload.get("patients", []) if neuro_access.patient_allowed(str(item.get("id")))]
            return {"patients": patients, "default_patient_id": patients[0]["id"] if patients else None}
        return payload

    @app.get("/api/demo/neuro-report/patients/{patient_id}")
    async def neuro_report_patient(patient_id: str):
        try:
            _, neuro_report_demo_store = _get_neuro_report_demo_components()
            return neuro_access.publish_curated(patient_id, neuro_report_demo_store.get_patient_data(patient_id))
        except KeyError as exc:
            return Response(
                content=json.dumps({"error": str(exc)}),
                status_code=404,
                media_type="application/json",
            )

    @app.get("/api/demo/neuro-report/patients/{patient_id}/studies/{study_id}")
    async def neuro_report_study(patient_id: str, study_id: str):
        try:
            _, neuro_report_demo_store = _get_neuro_report_demo_components()
            return neuro_access.publish_curated(patient_id, neuro_report_demo_store.get_study_detail(patient_id, study_id))
        except KeyError as exc:
            return Response(
                content=json.dumps({"error": str(exc)}),
                status_code=404,
                media_type="application/json",
            )

    @app.get("/api/demo/neuro-report/patients/{patient_id}/volumetrics")
    async def neuro_report_volumetrics(patient_id: str, regions: str = ""):
        try:
            _, neuro_report_demo_store = _get_neuro_report_demo_components()
            region_list = [r.strip() for r in regions.split(",") if r.strip()] or None
            return neuro_access.publish_curated(patient_id, neuro_report_demo_store.get_longitudinal_volumetrics(patient_id, region_list))
        except KeyError as exc:
            return Response(
                content=json.dumps({"error": str(exc)}),
                status_code=404,
                media_type="application/json",
            )

    @app.get("/api/demo/neuro-report/patients/{patient_id}/heatmap")
    async def neuro_report_heatmap(patient_id: str, regions: str = ""):
        try:
            _, neuro_report_demo_store = _get_neuro_report_demo_components()
            region_list = [r.strip() for r in regions.split(",") if r.strip()] or None
            return neuro_access.publish_curated(patient_id, neuro_report_demo_store.get_heatmap_data(patient_id, region_list))
        except KeyError as exc:
            return Response(
                content=json.dumps({"error": str(exc)}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/demo/neuro-report/alignment-jobs")
    async def neuro_report_create_alignment_job(request: Request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        mode = str(payload.get("mode") or "demo").strip().lower()
        if auth_store.require_user_auth:
            if not neuro_access.patient_allowed(str(payload.get("patient_id") or "")):
                return JSONResponse({"error": "Patient not found."}, status_code=404)
            if mode != "remote":
                return JSONResponse({"error": "Simulated alignment is not available in physician preview."}, status_code=422)
            payload.pop("output_dir", None)
        if mode == "remote":
            job = _remote_alignment_job(payload)
        else:
            job = _demo_alignment_job({**payload, "mode": "demo"})
        if auth_store.require_user_auth:
            auth_store.register_job(job_id=job["job_id"], user_id=_current_user_id(request), job_type="neuro_alignment")
            return public_neuro_payload(job)
        return job

    @app.get("/api/demo/neuro-report/alignment-jobs/{job_id}")
    async def neuro_report_alignment_job(request: Request, job_id: str):
        if auth_store.require_user_auth and not auth_store.can_access_job(job_id=job_id, user_id=_current_user_id(request)):
            return JSONResponse({"error": "Job not found."}, status_code=404)
        job = alignment_jobs.get(job_id)
        if job is None:
            return Response(
                content=json.dumps({"error": f"Unknown alignment job: {job_id}"}),
                status_code=404,
                media_type="application/json",
            )
        return public_neuro_payload(job) if auth_store.require_user_auth else job

    def _mr_rate_studies(patient_uid: str) -> list[dict[str, Any]]:
        payload = _build_neuro_knowledge_client().get_case(patient_uid)
        studies = payload.get("studies") if isinstance(payload, dict) else None
        if not isinstance(studies, list):
            raise KeyError(patient_uid)
        return [dict(study) for study in studies if isinstance(study, dict)]

    def _mr_rate_longitudinal_builder() -> MRRateLongitudinalBuilder:
        def _launch_study(patient_uid: str, study_uid: str) -> dict[str, Any]:
            return _prepare_mr_rate_launch(
                patient_uid=patient_uid,
                study_uid=study_uid,
                requested_local_root=None,
                download_if_missing=True,
                segmentation_preference="vista_then_nvseg",
                sequence_preference="structural_default",
            )

        return MRRateLongitudinalBuilder(launch_study=_launch_study)

    mr_rate_longitudinal_cache: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}

    def _mr_rate_region_key(region_list: list[str] | None) -> tuple[str, ...]:
        return tuple(region_list or ())

    def _mr_rate_longitudinal(patient_uid: str, region_list: list[str] | None) -> dict[str, Any]:
        key = (patient_uid, _mr_rate_region_key(region_list))
        cached = mr_rate_longitudinal_cache.get(key)
        if cached is not None:
            return cached
        payload = _mr_rate_longitudinal_builder().build_volumetrics(
            patient_uid=patient_uid,
            studies=_mr_rate_studies(patient_uid),
            region_names=region_list,
        )
        mr_rate_longitudinal_cache[key] = payload
        return payload

    @app.get("/api/demo/neuro-report/knowledge/patients/{patient_uid}/volumetrics")
    async def neuro_report_knowledge_volumetrics(patient_uid: str, regions: str = ""):
        try:
            region_list = [r.strip() for r in regions.split(",") if r.strip()] or None
            return _mr_rate_longitudinal(patient_uid, region_list)
        except KeyError as exc:
            return Response(
                content=json.dumps({"error": str(exc)}),
                status_code=404,
                media_type="application/json",
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    @app.get("/api/demo/neuro-report/knowledge/patients/{patient_uid}/heatmap")
    async def neuro_report_knowledge_heatmap(patient_uid: str, regions: str = ""):
        try:
            region_list = [r.strip() for r in regions.split(",") if r.strip()] or None
            return MRRateLongitudinalBuilder.heatmap_from_longitudinal(
                patient_uid=patient_uid,
                longitudinal=_mr_rate_longitudinal(patient_uid, region_list),
            )
        except KeyError as exc:
            return Response(
                content=json.dumps({"error": str(exc)}),
                status_code=404,
                media_type="application/json",
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    @app.get("/api/demo/neuro-report/segmentation/service")
    async def neuro_report_segmentation_service():
        _, neuro_report_demo_store = _get_neuro_report_demo_components()
        return neuro_report_demo_store.structural_segmentation_service_status()

    @app.get("/api/demo/brain-tumor/service")
    async def brain_tumor_service():
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        return {
            **brain_tumor_demo_store.service_status(),
            "physician_curated_only": physician_curated_only,
        }

    @app.get("/api/demo/brain-tumor/dicom/studies")
    async def brain_tumor_dicom_studies(
        patient_id: str = Query(default=""),
        accession_number: str = Query(default=""),
    ):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        try:
            return await brain_tumor_demo_store.search_dicom_studies(
                patient_id=patient_id.strip() or None,
                accession_number=accession_number.strip() or None,
            )
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)

    @app.get("/api/demo/brain-tumor/dicom/studies/{study_instance_uid}/series")
    async def brain_tumor_dicom_series(study_instance_uid: str):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        try:
            return await brain_tumor_demo_store.search_dicom_series(study_instance_uid=study_instance_uid)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)

    @app.get("/api/demo/brain-tumor/dicom-mount/status")
    async def brain_tumor_dicom_mount_status():
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        return brain_tumor_demo_store.mounted_dicom_status()

    @app.get("/api/demo/brain-tumor/preload/examples")
    async def brain_tumor_preload_examples(request: Request):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        result = _filter_curated_preloads(brain_tumor_demo_store.get_preload_examples())
        if physician_curated_only:
            for example in result.get("examples", []):
                if not isinstance(example, dict):
                    continue
                example_id = str(example.get("id") or "").strip()
                if example_id:
                    _register_brain_tumor_sessions(
                        example,
                        user_id=_current_user_id(request),
                        source=f"curated_preload:{example_id}",
                        shared=True,
                    )
        else:
            _register_brain_tumor_sessions(result, user_id=_current_user_id(request), source="curated_preload", shared=True)
        return _brain_tumor_public_payload(result)

    @app.get("/api/demo/brain-tumor/registry/cases")
    async def brain_tumor_registry_cases():
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        try:
            return _filter_curated_cases(brain_tumor_demo_store.get_case_registry())
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)

    @app.post("/api/demo/brain-tumor/registry/load")
    async def brain_tumor_registry_load(request: Request):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        try:
            payload = await request.json()
            case_id = str(payload.get("case_id") or "").strip()
            if not case_id:
                raise ValueError("case_id is required.")
            if not _curated_case_allowed(case_id):
                raise KeyError(case_id)
            timepoint_ids = payload.get("timepoint_ids")
            if timepoint_ids is not None and not isinstance(timepoint_ids, list):
                raise ValueError("timepoint_ids must be a list when provided.")
            result = brain_tumor_demo_store.load_case_registry_case(
                case_id=case_id,
                timepoint_ids=[str(item) for item in timepoint_ids] if timepoint_ids else None,
                prefer_cached=physician_curated_only,
            )
            _register_brain_tumor_sessions(
                result,
                user_id=_current_user_id(request),
                source=f"curated_registry:{case_id}",
                shared=True,
            )
            return _brain_tumor_public_payload(result)
        except KeyError:
            return JSONResponse({"ok": False, "error": "Brain tumor registry case not found."}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)

    @app.post("/api/demo/brain-tumor/registry/run")
    async def brain_tumor_registry_run(request: Request):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        try:
            payload = await request.json()
            case_id = str(payload.get("case_id") or "").strip()
            if not case_id:
                raise ValueError("case_id is required.")
            if not _curated_case_allowed(case_id):
                raise KeyError(case_id)
            timepoint_ids = payload.get("timepoint_ids")
            if timepoint_ids is not None and not isinstance(timepoint_ids, list):
                raise ValueError("timepoint_ids must be a list when provided.")
            result = brain_tumor_demo_store.run_case_registry_case(
                case_id=case_id,
                timepoint_ids=[str(item) for item in timepoint_ids] if timepoint_ids else None,
            )
            _register_brain_tumor_sessions(
                result,
                user_id=_current_user_id(request),
                source=f"curated_registry:{case_id}",
                shared=True,
            )
            return _brain_tumor_public_payload(result)
        except KeyError:
            return JSONResponse({"ok": False, "error": "Brain tumor registry case not found."}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)

    @app.post("/api/demo/brain-tumor/registry/segment-jobs")
    async def brain_tumor_registry_segment_job_create(request: Request):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        try:
            payload = await request.json()
            case_id = str(payload.get("case_id") or "").strip()
            if not case_id:
                raise ValueError("case_id is required.")
            if not _curated_case_allowed(case_id):
                raise KeyError(case_id)
            timepoint_ids = payload.get("timepoint_ids")
            if timepoint_ids is not None and not isinstance(timepoint_ids, list):
                raise ValueError("timepoint_ids must be a list when provided.")
            normalized_timepoint_ids = [str(item) for item in timepoint_ids] if timepoint_ids else None
            force_rerun = bool(payload.get("force_rerun"))
            user_id = _current_user_id(request)
            if user_id and durable_brain_tumor_queue:
                job_id = f"gbmseg_{uuid.uuid4().hex[:12]}"
                initial_result = brain_tumor_demo_store.describe_registry_segment_job(
                    job_id=job_id,
                    case_id=case_id,
                    timepoint_ids=normalized_timepoint_ids,
                    force_rerun=force_rerun,
                )
                job, _created = auth_store.create_queued_job(
                    user_id=user_id,
                    job_type="brain_tumor_registry_segment",
                    job_id=job_id,
                    payload={
                        "case_id": case_id,
                        "timepoint_ids": normalized_timepoint_ids,
                        "force_rerun": force_rerun,
                    },
                    initial_result=initial_result,
                )
                return _brain_tumor_job_api_payload(job)
            result = brain_tumor_demo_store.create_registry_segment_job(
                case_id=case_id,
                timepoint_ids=normalized_timepoint_ids,
            )
            job_id = str(result.get("job_id") or "")
            if user_id and job_id:
                auth_store.register_job(job_id=job_id, user_id=user_id, job_type="brain_tumor_registry_segment")
            return result
        except KeyError:
            return JSONResponse({"ok": False, "error": "Brain tumor registry case not found."}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)

    @app.get("/api/demo/brain-tumor/registry/segment-jobs/active")
    async def brain_tumor_registry_segment_job_active(request: Request):
        user_id = _current_user_id(request)
        if not user_id:
            return {"ok": True, "job": None}
        job = auth_store.get_active_job(user_id=user_id, job_type="brain_tumor_registry_segment")
        return {"ok": True, "job": _brain_tumor_job_api_payload(job) if job else None}

    @app.get("/api/demo/brain-tumor/registry/segment-jobs/current")
    async def brain_tumor_registry_segment_job_current(request: Request):
        user_id = _current_user_id(request)
        if not user_id:
            return {"ok": True, "job": None}
        job = auth_store.get_active_job(user_id=user_id, job_type="brain_tumor_registry_segment")
        if job is None:
            job = auth_store.get_latest_job(user_id=user_id, job_type="brain_tumor_registry_segment")
        return {"ok": True, "job": _brain_tumor_job_api_payload(job) if job else None}

    @app.get("/api/demo/brain-tumor/registry/segment-jobs/{job_id}")
    async def brain_tumor_registry_segment_job_status(request: Request, job_id: str):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        if not _brain_tumor_job_allowed(request, job_id):
            return JSONResponse({"ok": False, "error": "Brain tumor registry segmentation job not found."}, status_code=404)
        try:
            durable_job = auth_store.get_job(job_id=job_id)
            if durable_job and durable_job.get("job_type") == "brain_tumor_registry_segment":
                return _brain_tumor_job_api_payload(durable_job)
            result = brain_tumor_demo_store.get_registry_segment_job(job_id)
            result_case_id = str(result.get("case_id") or "").strip()
            if result_case_id:
                _register_brain_tumor_sessions(
                    result,
                    user_id=_current_user_id(request),
                    source=f"curated_registry:{result_case_id}",
                    shared=True,
                )
            return result
        except KeyError:
            return JSONResponse({"ok": False, "error": "Brain tumor registry segmentation job not found."}, status_code=404)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)

    @app.get("/api/demo/brain-tumor/preload/artifact/{example_id}/{case_id}/{artifact_name}")
    async def brain_tumor_preload_artifact(example_id: str, case_id: str, artifact_name: str):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        if not _curated_case_allowed(example_id):
            return JSONResponse({"ok": False, "error": "Brain tumor preload artifact not found."}, status_code=404)
        try:
            path = brain_tumor_demo_store.get_preload_artifact_path(example_id, case_id, artifact_name)
            return FileResponse(path)
        except KeyError:
            return JSONResponse({"ok": False, "error": "Brain tumor preload artifact not found."}, status_code=404)

    @app.get("/api/demo/brain-tumor/upload-examples")
    async def brain_tumor_upload_examples(request: Request):
        from clinagent.gateway.preview_examples import example_archives

        if not _current_user_id(request):
            return JSONResponse({"ok": False, "error": "Authentication required."}, status_code=401)
        try:
            return {"ok": True, "examples": [row for row, _ in example_archives()]}
        except (ValueError, OSError, KeyError):
            return JSONResponse({"ok": False, "error": "Upload examples are temporarily unavailable."}, status_code=503)

    @app.get("/api/demo/brain-tumor/upload-examples/{example_id}/download")
    async def brain_tumor_upload_example_download(request: Request, example_id: str):
        from clinagent.gateway.preview_examples import example_archives

        if not _current_user_id(request):
            return JSONResponse({"ok": False, "error": "Authentication required."}, status_code=401)
        try:
            for row, path in example_archives():
                if row["id"] == example_id:
                    return FileResponse(path, media_type="application/zip", filename=f"{example_id}.zip",
                                        headers={"Cache-Control": "private, no-store"})
        except (ValueError, OSError, KeyError):
            return JSONResponse({"ok": False, "error": "Upload examples are temporarily unavailable."}, status_code=503)
        return JSONResponse({"ok": False, "error": "Example not found."}, status_code=404)

    @app.post("/api/demo/brain-tumor/feedback")
    async def brain_tumor_preview_feedback(request: Request, payload: dict[str, Any]):
        user_id = _current_user_id(request)
        if not user_id:
            return JSONResponse({"ok": False, "error": "Authentication required."}, status_code=401)
        category = payload.get("category")
        step = payload.get("workflow_step")
        comment = payload.get("comment")
        case_id = payload.get("case_id") or None
        if (set(payload) - {"category", "workflow_step", "comment", "case_id"}
            or not isinstance(category, str) or category not in {"issue", "suggestion", "question"}
            or not isinstance(step, str) or step not in {"upload", "review", "longitudinal", "report", "general"}
            or not isinstance(comment, str) or not 1 <= len(comment.strip()) <= 2000
            or (case_id is not None and not isinstance(case_id, str))):
            return JSONResponse({"ok": False, "error": "Choose a category and enter 1-2000 characters of feedback."}, status_code=422)
        if case_id and not auth_store.can_access_case(case_id=case_id, user_id=user_id):
            return JSONResponse({"ok": False, "error": "Case not found."}, status_code=404)
        feedback_id = auth_store.record_preview_feedback(user_id=user_id, case_id=case_id,
            category=category, workflow_step=step, comment=comment.strip())
        return {"ok": True, "feedback_id": feedback_id}

    @app.get("/api/demo/brain-tumor/uploads")
    async def brain_tumor_upload_cases(request: Request):
        from clinagent.gateway.brain_tumor_uploads import UPLOAD_JOB_TYPE

        user_id = _current_user_id(request)
        if not user_id:
            return JSONResponse({"ok": False, "error": "Authentication required."}, status_code=401)
        cases = auth_store.list_owned_cases(user_id=user_id, source="nifti_upload")
        return {
            "ok": True,
            "retention_days": 30,
            "cases": [
                _brain_tumor_upload_case_api_payload(
                    case,
                    auth_store.get_latest_job_for_case(
                        user_id=user_id,
                        case_id=str(case.get("id") or ""),
                        job_type=UPLOAD_JOB_TYPE,
                    ),
                )
                for case in cases
            ],
        }

    @app.post("/api/demo/brain-tumor/uploads")
    async def brain_tumor_upload_create(
        request: Request,
        deidentified_confirmed: bool = Form(...),
        t1n_file: UploadFile | None = File(None),
        t1c_file: UploadFile | None = File(None),
        t2w_file: UploadFile | None = File(None),
        t2f_file: UploadFile | None = File(None),
        files: list[UploadFile] = File(default=[]),
        visits_json: str | None = Form(None),
        target_case_id: str | None = Form(None),
        same_patient_confirmed: bool = Form(False),
    ):
        from clinagent.gateway.brain_tumor_uploads import create_upload_case
        from clinagent.gateway.brain_tumor_upload_visits import create_visit_upload_case, parse_visit_uploads

        user_id = _current_user_id(request)
        if not user_id:
            return JSONResponse({"ok": False, "error": "Authentication required."}, status_code=401)
        if not deidentified_confirmed:
            return JSONResponse(
                {"ok": False, "error": "Confirm that the uploaded images are de-identified before submission."},
                status_code=422,
            )
        try:
            if target_case_id:
                access = auth_store.get_case_access(case_id=target_case_id)
                if not access or access.get("owner_user_id") != user_id or access.get("source") != "nifti_upload":
                    raise LookupError("Uploaded case not found.")
            if visits_json is not None:
                if any((t1n_file, t1c_file, t2w_file, t2f_file)):
                    raise ValueError("Use one visit mapping format per upload.")
                visits = parse_visit_uploads(visits_json, files)
                if (len(visits) > 1 or target_case_id) and not same_patient_confirmed:
                    raise ValueError("Confirm that all visits belong to the same patient.")
                manifest, job = await create_visit_upload_case(auth_store=auth_store, user_id=user_id, visits=visits, target_case_id=target_case_id)
            else:
                if target_case_id or files:
                    raise ValueError("A visit mapping is required.")
                manifest, job = await create_upload_case(auth_store=auth_store, user_id=user_id,
                    uploads={key: value for key, value in {"t1n": t1n_file, "t1c": t1c_file, "t2w": t2w_file, "t2f": t2f_file}.items() if value})
            case = auth_store.get_case_access(case_id=str(manifest["case_id"])) or {}
            return {
                "ok": True,
                "case": _brain_tumor_upload_case_api_payload(case, job),
                "job": _brain_tumor_job_api_payload(job),
            }
        except LookupError:
            return JSONResponse({"ok": False, "error": "Uploaded case not found."}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)
        except Exception:
            return JSONResponse({"ok": False, "error": "The upload could not be prepared. Please retry."}, status_code=500)
        finally:
            for upload in [*files, t1n_file, t1c_file, t2w_file, t2f_file]:
                if upload:
                    await upload.close()

    @app.get("/api/demo/brain-tumor/uploads/jobs/current")
    async def brain_tumor_upload_job_current(request: Request):
        from clinagent.gateway.brain_tumor_uploads import UPLOAD_JOB_TYPE

        user_id = _current_user_id(request)
        if not user_id:
            return JSONResponse({"ok": False, "error": "Authentication required."}, status_code=401)
        job = auth_store.get_active_job(user_id=user_id, job_type=UPLOAD_JOB_TYPE)
        if job is None:
            job = auth_store.get_latest_job(user_id=user_id, job_type=UPLOAD_JOB_TYPE)
        return {"ok": True, "job": _brain_tumor_job_api_payload(job) if job else None}

    @app.get("/api/demo/brain-tumor/uploads/jobs/{job_id}")
    async def brain_tumor_upload_job_status(request: Request, job_id: str):
        from clinagent.gateway.brain_tumor_uploads import UPLOAD_JOB_TYPE

        if not _brain_tumor_job_allowed(request, job_id):
            return JSONResponse({"ok": False, "error": "Upload segmentation job not found."}, status_code=404)
        job = auth_store.get_job(job_id=job_id)
        if not job or job.get("job_type") != UPLOAD_JOB_TYPE:
            return JSONResponse({"ok": False, "error": "Upload segmentation job not found."}, status_code=404)
        return _brain_tumor_job_api_payload(job)

    @app.get("/api/demo/brain-tumor/uploads/{case_id}/modality/{modality}/{filename}")
    @app.get("/api/demo/brain-tumor/uploads/{case_id}/modality/{modality}")
    @app.get("/api/demo/brain-tumor/uploads/{case_id}/visits/{visit_id}/modality/{modality}/{filename}")
    async def brain_tumor_upload_modality(request: Request, case_id: str, modality: str, filename: str | None = None, visit_id: str = "visit_01"):
        from clinagent.gateway.brain_tumor_uploads import UPLOAD_MODALITIES, upload_root
        from clinagent.gateway.brain_tumor_upload_visits import visit_input_root

        user_id = _current_user_id(request)
        access = auth_store.get_case_access(case_id=case_id)
        if (
            not user_id
            or not access
            or access.get("owner_user_id") != user_id
            or access.get("source") != "nifti_upload"
            or modality not in UPLOAD_MODALITIES
            or (filename is not None and filename != f"{modality}.nii.gz")
        ):
            return JSONResponse({"ok": False, "error": "Uploaded modality not found."}, status_code=404)
        try:
            path = (visit_input_root(case_id, visit_id) / f"{modality}.nii.gz").resolve()
        except ValueError:
            return JSONResponse({"ok": False, "error": "Uploaded modality not found."}, status_code=404)
        if upload_root() not in path.parents or not path.is_file():
            return JSONResponse({"ok": False, "error": "Uploaded modality not found."}, status_code=404)
        return FileResponse(path)

    @app.post("/api/demo/brain-tumor/uploads/{case_id}/retry")
    async def brain_tumor_upload_retry(request: Request, case_id: str):
        from clinagent.gateway.brain_tumor_uploads import UPLOAD_JOB_TYPE, read_upload_manifest

        user_id = _current_user_id(request)
        access = auth_store.get_case_access(case_id=case_id)
        if not user_id or not access or access.get("owner_user_id") != user_id or access.get("source") != "nifti_upload":
            return JSONResponse({"ok": False, "error": "Uploaded case not found."}, status_code=404)
        manifest = read_upload_manifest(case_id)
        if manifest is None:
            return JSONResponse({"ok": False, "error": "Uploaded case files are no longer available."}, status_code=404)
        from clinagent.gateway.brain_tumor_upload_visits import upload_result

        job, created = auth_store.create_queued_job(
            user_id=user_id, job_type=UPLOAD_JOB_TYPE, case_id=case_id,
            payload={"case_id": case_id, "display_label": manifest.get("display_label"), "expires_at": access.get("expires_at")},
            initial_result=upload_result(manifest, status="queued", stage="queued"),
        )
        if not created and str(job.get("case_id") or "") != case_id:
            return JSONResponse({"ok": False, "error": "Another segmentation job is already active for this account."}, status_code=409)
        return _brain_tumor_job_api_payload(job)

    @app.delete("/api/demo/brain-tumor/uploads/{case_id}")
    async def brain_tumor_upload_delete(request: Request, case_id: str):
        from clinagent.gateway.brain_tumor_uploads import remove_upload_case

        user_id = _current_user_id(request)
        access = auth_store.get_case_access(case_id=case_id)
        if not user_id or not access or access.get("owner_user_id") != user_id or access.get("source") != "nifti_upload":
            return JSONResponse({"ok": False, "error": "Uploaded case not found."}, status_code=404)
        from clinagent.gateway.brain_tumor_upload_visits import remove_upload_sessions

        auth_store.mark_case_deleted(case_id=case_id, owner_user_id=user_id)
        await asyncio.to_thread(remove_upload_sessions, auth_store=auth_store,
            demo_store=_get_brain_tumor_demo_store(), case_id=case_id, owner_user_id=user_id)
        await asyncio.to_thread(remove_upload_case, case_id)
        return {"ok": True, "deleted": True, "case_id": case_id}

    @app.post("/api/demo/brain-tumor/report/draft")
    async def brain_tumor_report_draft(request: Request):
        payload = await request.json()
        session_id = str(payload.get("session_id") or "").strip()
        if auth_store.require_user_auth and (not session_id or not _brain_tumor_case_allowed(request, session_id)):
            return JSONResponse({"ok": False, "error": "Brain tumor session not found."}, status_code=404)
        local_draft = _build_brain_tumor_local_report_draft(payload)
        try:
            import asyncio

            prompt = _build_brain_tumor_report_prompt(payload)
            response = await asyncio.wait_for(llm.chat([
                LLMMessage(role="system", content=(
                    "You draft concise quantitative neuro-oncology imaging reports for research workflow handoff. "
                    "Do not diagnose. Do not invent measurements. Preserve QC limitations and state when a case is not cleared for final reporting."
                )),
                LLMMessage(role="user", content=prompt),
            ]), timeout=30.0)
            if response.partial or response.tool_calls or not str(response.content or "").strip():
                return _brain_tumor_report_local_fallback(local_draft, "Model draft was empty or incomplete; exported a deterministic local draft.")
            return {"ok": True, "generated": True, "report_text": response.content.strip(), "model": response.model}
        except Exception:
            return _brain_tumor_report_local_fallback(
                local_draft,
                "Model draft provider is unavailable; exported a deterministic local draft.",
            )

    @app.get("/api/demo/brain-tumor/dicom-mount/studies")
    async def brain_tumor_dicom_mount_studies(
        patient_id: str = Query(default=""),
        accession_number: str = Query(default=""),
    ):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        try:
            return brain_tumor_demo_store.search_mounted_dicom_studies(
                patient_id=patient_id.strip() or None,
                accession_number=accession_number.strip() or None,
            )
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)

    @app.get("/api/demo/brain-tumor/dicom-mount/studies/{study_ref}/series")
    async def brain_tumor_dicom_mount_series(study_ref: str):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        try:
            return brain_tumor_demo_store.search_mounted_dicom_series(study_ref=study_ref)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)

    @app.post("/api/demo/brain-tumor/analyze")
    async def brain_tumor_analyze(
        request: Request,
        input_mode: str = Form(default="nifti_upload"),
        patient_label: str = Form(default=""),
        study_instance_uid: str = Form(default=""),
        modality_mapping_json: str = Form(default=""),
        model_id: str = Form(default=""),
        t1n_path: str = Form(default=""),
        t1c_path: str = Form(default=""),
        t2w_path: str = Form(default=""),
        t2f_path: str = Form(default=""),
        precomputed_seg_path: str = Form(default=""),
        t1n_file: UploadFile | None = File(default=None),
        t1c_file: UploadFile | None = File(default=None),
        t2w_file: UploadFile | None = File(default=None),
        t2f_file: UploadFile | None = File(default=None),
        precomputed_seg_file: UploadFile | None = File(default=None),
        dicom_zip: UploadFile | None = File(default=None),
    ):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        try:
            mapping = json.loads(modality_mapping_json) if modality_mapping_json.strip() else {}
            if not isinstance(mapping, dict):
                raise ValueError("modality_mapping_json must be an object.")

            if input_mode == "dicomweb":
                if not study_instance_uid.strip():
                    raise ValueError("DICOMweb analysis requires study_instance_uid.")
                result = await brain_tumor_demo_store.analyze_dicomweb(
                    study_instance_uid=study_instance_uid.strip(),
                    modality_mapping={str(key): str(value) for key, value in mapping.items() if value},
                    patient_label=patient_label.strip(),
                    model_id=model_id.strip() or None,
                )
                _register_brain_tumor_sessions(result, user_id=_current_user_id(request), source="dicomweb", shared=False)
                return _brain_tumor_public_payload(result)

            if input_mode == "dicom_mount":
                if not study_instance_uid.strip():
                    raise ValueError("Mounted DICOM analysis requires study_instance_uid.")
                result = brain_tumor_demo_store.analyze_mounted_dicom(
                    study_ref=study_instance_uid.strip(),
                    modality_mapping={str(key): str(value) for key, value in mapping.items() if value},
                    patient_label=patient_label.strip(),
                    model_id=model_id.strip() or None,
                )
                _register_brain_tumor_sessions(result, user_id=_current_user_id(request), source="dicom_mount", shared=False)
                return _brain_tumor_public_payload(result)

            upload_root = brain_tumor_demo_store.asset_root / "_uploads" / uuid.uuid4().hex
            upload_root.mkdir(parents=True, exist_ok=True)
            modality_paths = {
                "t1n": t1n_path.strip(),
                "t1c": t1c_path.strip(),
                "t2w": t2w_path.strip(),
                "t2f": t2f_path.strip(),
            }
            for key, upload in {
                "t1n": t1n_file,
                "t1c": t1c_file,
                "t2w": t2w_file,
                "t2f": t2f_file,
            }.items():
                if upload and upload.filename:
                    target = upload_root / f"{key}_{Path(upload.filename).name}"
                    target.write_bytes(await upload.read())
                    modality_paths[key] = str(target.resolve())
            modality_paths = {key: value for key, value in modality_paths.items() if value}

            effective_precomputed_seg = precomputed_seg_path.strip()
            if precomputed_seg_file and precomputed_seg_file.filename:
                target = upload_root / f"precomputed_{Path(precomputed_seg_file.filename).name}"
                target.write_bytes(await precomputed_seg_file.read())
                effective_precomputed_seg = str(target.resolve())

            if dicom_zip and dicom_zip.filename and not modality_paths:
                target = upload_root / Path(dicom_zip.filename).name
                target.write_bytes(await dicom_zip.read())
                raise ValueError(
                    "DICOM archive upload is stored for intake, but v1 analysis still requires selected "
                    "DICOMweb series or direct NIfTI modality files."
                )

            result = brain_tumor_demo_store.analyze_nifti_paths(
                modality_paths=modality_paths,
                patient_label=patient_label.strip(),
                source={"type": input_mode},
                model_id=model_id.strip() or None,
                precomputed_seg_path=effective_precomputed_seg or None,
            )
            _register_brain_tumor_sessions(result, user_id=_current_user_id(request), source="nifti_upload", shared=False)
            return _brain_tumor_public_payload(result)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)
        except RuntimeError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @app.get("/api/demo/brain-tumor/sessions/{session_id}")
    async def brain_tumor_session(request: Request, session_id: str):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        if not _brain_tumor_case_allowed(request, session_id):
            return JSONResponse({"ok": False, "error": "Brain tumor session not found."}, status_code=404)
        try:
            return _brain_tumor_public_payload(brain_tumor_demo_store.get_session(session_id))
        except KeyError:
            return JSONResponse({"ok": False, "error": "Brain tumor session not found."}, status_code=404)

    @app.get("/api/demo/brain-tumor/sessions/{session_id}/artifact/{artifact_name}")
    async def brain_tumor_artifact(request: Request, session_id: str, artifact_name: str):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        if not _brain_tumor_case_allowed(request, session_id):
            return JSONResponse({"ok": False, "error": "Brain tumor artifact not found."}, status_code=404)
        try:
            path = brain_tumor_demo_store.get_artifact_path(session_id, artifact_name)
            return FileResponse(path)
        except KeyError:
            return JSONResponse({"ok": False, "error": "Brain tumor artifact not found."}, status_code=404)

    @app.get("/api/demo/brain-tumor/sessions/{session_id}/artifact/{artifact_name}/{filename:path}")
    async def brain_tumor_artifact_with_filename(request: Request, session_id: str, artifact_name: str, filename: str):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        if not _brain_tumor_case_allowed(request, session_id):
            return JSONResponse({"ok": False, "error": "Brain tumor artifact not found."}, status_code=404)
        try:
            path = brain_tumor_demo_store.get_artifact_path(session_id, artifact_name)
            return FileResponse(path)
        except KeyError:
            return JSONResponse({"ok": False, "error": "Brain tumor artifact not found."}, status_code=404)

    @app.post("/api/demo/brain-tumor/longitudinal/register")
    async def brain_tumor_longitudinal_register(request: Request):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        try:
            payload = await request.json()
            baseline_session_id = str(payload.get("baseline_session_id") or "").strip()
            followup_session_id = str(payload.get("followup_session_id") or "").strip()
            if not baseline_session_id or not followup_session_id:
                raise ValueError("baseline_session_id and followup_session_id are required.")
            if baseline_session_id == followup_session_id:
                raise ValueError("Choose a different follow-up session for longitudinal registration.")
            if not _brain_tumor_case_allowed(request, baseline_session_id) or not _brain_tumor_case_allowed(request, followup_session_id):
                return JSONResponse({"ok": False, "error": "Brain tumor session not found."}, status_code=404)
            from starlette.concurrency import run_in_threadpool
            return await run_in_threadpool(brain_tumor_demo_store.register_longitudinal_sessions,
                baseline_session_id=baseline_session_id,
                followup_session_id=followup_session_id,
            )
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)
        except KeyError:
            return JSONResponse({"ok": False, "error": "Brain tumor session not found."}, status_code=404)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Longitudinal alignment failed")
            return JSONResponse({"ok": False, "error": "Alignment could not complete. Check input geometry and image quality, then retry."}, status_code=503)

    @app.post("/api/demo/brain-tumor/longitudinal/align-jobs")
    async def brain_tumor_longitudinal_align_job_create(request: Request):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        try:
            payload = await request.json()
            baseline_session_id = str(payload.get("baseline_session_id") or "").strip()
            followup_session_ids = payload.get("followup_session_ids")
            if not isinstance(followup_session_ids, list):
                raise ValueError("followup_session_ids must be a list.")
            normalized_followups = [str(item).strip() for item in followup_session_ids]
            bias_correction = payload.get("bias_correction", False)
            if not isinstance(bias_correction, bool):
                raise ValueError("bias_correction must be a boolean.")
            if not _brain_tumor_case_allowed(request, baseline_session_id) or any(
                not _brain_tumor_case_allowed(request, item) for item in normalized_followups
            ):
                return JSONResponse({"ok": False, "error": "Brain tumor session not found."}, status_code=404)
            result = brain_tumor_demo_store.create_longitudinal_align_job(
                baseline_session_id=baseline_session_id,
                followup_session_ids=normalized_followups,
                bias_correction=bias_correction,
            )
            user_id = _current_user_id(request)
            job_id = str(result.get("job_id") or "")
            if user_id and job_id:
                auth_store.register_job(job_id=job_id, user_id=user_id, job_type="brain_tumor_alignment")
            return result
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)
        except KeyError:
            return JSONResponse({"ok": False, "error": "Brain tumor session not found."}, status_code=404)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)

    @app.get("/api/demo/brain-tumor/longitudinal/align-jobs/{job_id}")
    async def brain_tumor_longitudinal_align_job_status(request: Request, job_id: str):
        brain_tumor_demo_store = _get_brain_tumor_demo_store()
        if not _brain_tumor_job_allowed(request, job_id):
            return JSONResponse({"ok": False, "error": "Alignment job not found."}, status_code=404)
        try:
            return brain_tumor_demo_store.get_longitudinal_align_job(job_id)
        except KeyError:
            return JSONResponse({"ok": False, "error": "Alignment job not found."}, status_code=404)

    @app.get("/api/demo/brain-tumor/longitudinal/artifacts/{baseline_id}/{followup_id}/{variant}/{run_id}/{artifact_name}.nii.gz")
    async def brain_tumor_alignment_artifact(request: Request, baseline_id: str, followup_id: str,
                                            variant: str, run_id: str, artifact_name: str):
        if not _brain_tumor_case_allowed(request, baseline_id) or not _brain_tumor_case_allowed(request, followup_id):
            return JSONResponse({"ok": False, "error": "Alignment artifact not found."}, status_code=404)
        try:
            path = _get_brain_tumor_demo_store().get_registration_artifact(baseline_id, followup_id, variant, run_id, artifact_name)
            return FileResponse(path)
        except KeyError:
            return JSONResponse({"ok": False, "error": "Alignment artifact not found."}, status_code=404)

    @app.get("/api/demo/neuro-report/patients/{patient_id}/studies/{study_id}/slice")
    async def neuro_report_study_slice(
        patient_id: str,
        study_id: str,
        plane: str = Query(...),
        index: int = Query(..., ge=0),
        overlay: bool = Query(default=True),
    ):
        try:
            _, neuro_report_demo_store = _get_neuro_report_demo_components()
            return neuro_report_demo_store.get_structural_study_slice(
                patient_id,
                study_id,
                plane=plane,
                index=index,
                overlay=overlay,
            )
        except KeyError as exc:
            return Response(
                content=json.dumps({"error": str(exc)}),
                status_code=404,
                media_type="application/json",
            )

    @app.get("/api/demo/neuro-report/sessions/{session_id}/slice")
    async def neuro_report_session_slice(
        session_id: str,
        plane: str = Query(...),
        index: int = Query(..., ge=0),
        overlay: bool = Query(default=True),
    ):
        try:
            _, neuro_report_demo_store = _get_neuro_report_demo_components()
            return neuro_report_demo_store.get_structural_session_slice(
                session_id,
                plane=plane,
                index=index,
                overlay=overlay,
            )
        except KeyError as exc:
            return Response(
                content=json.dumps({"error": str(exc)}),
                status_code=404,
                media_type="application/json",
            )

    @app.get("/api/demo/neuro-report/sessions/{session_id}")
    async def neuro_report_session_detail(session_id: str):
        try:
            _, neuro_report_demo_store = _get_neuro_report_demo_components()
            session = neuro_report_demo_store.get_session(session_id)
            payload = _neuro_report_session_response(session_id, session)
            return public_neuro_payload(payload) if auth_store.require_user_auth else payload
        except KeyError as exc:
            return Response(
                content=json.dumps({"error": str(exc)}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/demo/neuro-report/knowledge-preview")
    async def neuro_report_knowledge_preview(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(
                {"ok": False, "error": 'Invalid JSON. Send { "patient_uid": "...", "study_uid": "..." }'},
                status_code=400,
            )
        patient_uid = str(payload.get("patient_uid") or "").strip()
        study_uid = str(payload.get("study_uid") or "").strip()
        if not patient_uid or not study_uid:
            return JSONResponse(
                {"ok": False, "error": "patient_uid and study_uid are required"},
                status_code=400,
            )

        requested_local_root = str(payload.get("local_root") or "").strip() or None
        sequence_preference = str(payload.get("sequence_preference") or "structural_default").strip()
        segmentation_preference = str(payload.get("segmentation_preference") or "vista_then_nvseg").strip()
        _, neuro_report_demo_store = _get_neuro_report_demo_components()
        try:
            launch_payload = _prepare_mr_rate_launch(
                patient_uid=patient_uid,
                study_uid=study_uid,
                requested_local_root=requested_local_root,
                download_if_missing=True,
                segmentation_preference=segmentation_preference,
                sequence_preference=sequence_preference,
            )
            local_bundle = launch_payload.get("local_bundle") or {}
            local_image_path = str(local_bundle.get("image_path") or "").strip()
            local_seg_path = str(local_bundle.get("seg_path") or "").strip() or None
            if not local_image_path:
                return JSONResponse(
                    {"ok": False, "error": "MR-RATE launch did not produce a local image bundle."},
                    status_code=502,
                )

            knowledge_context = launch_payload.get("knowledge_context")
            report = knowledge_context.get("report") if isinstance(knowledge_context, dict) else None
            report_sections = (
                {
                    "clinical_information": str(report.get("clinical_information") or ""),
                    "technique": str(report.get("technique") or ""),
                    "findings": str(report.get("findings") or ""),
                    "impression": str(report.get("impression") or ""),
                }
                if isinstance(report, dict)
                else None
            )
            report_text = str(report.get("report_text") or "").strip() if isinstance(report, dict) else ""
            launch_age, launch_sex = _knowledge_launch_demographics(launch_payload)
            preview = neuro_report_demo_store.prepare_workspace_preview(
                nifti_path=local_image_path,
                seg_path=local_seg_path,
                age=launch_age,
                sex=launch_sex,
                indication=_knowledge_launch_indication(launch_payload),
                patient_id=patient_uid,
                study_id=study_uid,
                source="knowledge",
                request_text="Review this MR-RATE study before running analysis.",
                report_text=report_text,
                report_sections=report_sections,
            )
            return {
                **preview,
                "ok": True,
                "local_status": launch_payload.get("local_status"),
            }
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @app.get("/api/demo/neuro-report/sessions/{session_id}/structural-regions.csv")
    async def neuro_report_structural_regions_csv(session_id: str):
        _, neuro_report_demo_store = _get_neuro_report_demo_components()
        try:
            session = neuro_report_demo_store.get_session(session_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown session: {session_id}"}),
                status_code=404,
                media_type="application/json",
            )
        export_path = (session.get("csv_export_path") or "").strip() if isinstance(session, dict) else ""
        if not export_path:
            return Response(
                content=json.dumps({"error": f"No structural region export is available for session {session_id}"}),
                status_code=404,
                media_type="application/json",
            )
        path = Path(export_path)
        if not path.exists():
            return Response(
                content=json.dumps({"error": f"Structural region export is missing for session {session_id}"}),
                status_code=404,
                media_type="application/json",
            )
        def _safe_filename_part(value: str | None) -> str:
            normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
            normalized = normalized.strip("-._")
            return normalized or "unknown"

        patient_id = _safe_filename_part(session.get("patient_id") if isinstance(session, dict) else None)
        study_id = _safe_filename_part(session.get("study_id") if isinstance(session, dict) else None)
        if isinstance(session, dict) and session.get("patient_id") and session.get("study_id"):
            download_name = f"structural-regions_{patient_id}_{study_id}.csv"
        else:
            download_name = f"structural-regions_upload_{_safe_filename_part(session_id)}.csv"
        return FileResponse(path, media_type="text/csv", filename=download_name)

    @app.get("/api/demo/neuro-report/patients/{patient_id}/studies/{study_id}/structural-regions.csv")
    async def neuro_report_study_structural_regions_csv(patient_id: str, study_id: str):
        _, neuro_report_demo_store = _get_neuro_report_demo_components()
        try:
            detail = neuro_report_demo_store.get_study_detail(patient_id, study_id)
        except KeyError as exc:
            return Response(
                content=json.dumps({"error": str(exc)}),
                status_code=404,
                media_type="application/json",
            )
        volumetrics = detail.get("volumetrics") if isinstance(detail, dict) else None
        export_path = (volumetrics.get("csv_export_path") or "").strip() if isinstance(volumetrics, dict) else ""
        if not export_path:
            return Response(
                content=json.dumps({"error": f"No structural region export is available for {patient_id}/{study_id}"}),
                status_code=404,
                media_type="application/json",
            )
        path = Path(export_path)
        if not path.exists():
            return Response(
                content=json.dumps({"error": f"Structural region export is missing for {patient_id}/{study_id}"}),
                status_code=404,
                media_type="application/json",
            )

        def _safe_filename_part(value: str | None) -> str:
            normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
            normalized = normalized.strip("-._")
            return normalized or "unknown"

        download_name = (
            f"structural-regions_{_safe_filename_part(patient_id)}_{_safe_filename_part(study_id)}.csv"
        )
        return FileResponse(path, media_type="text/csv", filename=download_name)

    @app.post("/api/demo/neuro-report/analyze")
    async def neuro_report_analyze(
        request: Request,
        case_id: str | None = Form(default=None),
        patient_id: str | None = Form(default=None),
        study_id: str | None = Form(default=None),
        session_id: str | None = Form(default=None),
        knowledge_launch_patient_uid: str | None = Form(default=None),
        knowledge_launch_study_uid: str | None = Form(default=None),
        source_path: str | None = Form(default=None),
        mode: str = Form(default="full_agent"),
        request_text: str | None = Form(default=None),
        age: int | None = Form(default=None),
        sex: str | None = Form(default=None),
        indication: str | None = Form(default=None),
        auto_segment: bool = Form(default=False),
        segmentation_backend: str | None = Form(default=None),
        nifti_file: UploadFile | None = File(default=None),
        seg_file: UploadFile | None = File(default=None),
    ):
        import asyncio

        if auth_store.require_user_auth:
            if source_path or knowledge_launch_patient_uid or knowledge_launch_study_uid:
                return JSONResponse({"error": "Use an approved case or upload files; server paths are not accepted."}, status_code=403)
            if session_id and not neuro_access.session_allowed(session_id, _current_user_id(request)):
                return JSONResponse({"error": "Session not found."}, status_code=404)
            if case_id or patient_id or study_id:
                _, store = _get_neuro_report_demo_components()
                try:
                    record = store.resolve_analysis_request(case_id=case_id, patient_id=patient_id, study_id=study_id)
                    resolved_patient = record.get("patient_id") if isinstance(record, dict) else record.patient_id
                except KeyError:
                    return JSONResponse({"error": "Patient not found."}, status_code=404)
                if not neuro_access.patient_allowed(str(resolved_patient)):
                    return JSONResponse({"error": "Patient not found."}, status_code=404)

        async def _stream():
            try:
                SUPPORTED_ANALYSIS_MODES, neuro_report_demo_store = _get_neuro_report_demo_components()
                auto_segmentation_requested = auto_segment and (segmentation_backend or "structural_segmenter") == "structural_segmenter"
                if knowledge_launch_patient_uid or knowledge_launch_study_uid:
                    if not knowledge_launch_patient_uid or not knowledge_launch_study_uid:
                        yield _format_sse(
                            "error",
                            {"error": "knowledge_launch_patient_uid and knowledge_launch_study_uid are required together."},
                        )
                        return
                    yield _format_sse(
                        "progress",
                        {"stage": "check_local_cache", "label": "Checking local MR-RATE mirror", "status": "running"},
                    )
                    launch_payload: dict[str, Any] | None = None
                    local_image_path = ""
                    local_seg_path: str | None = None
                    launch_age: int | None = None
                    launch_sex: str | None = None
                    launch_indication: str | None = None
                    matched_preview_session: tuple[str, dict[str, Any]] | None = None

                    if session_id:
                        try:
                            preview_session = neuro_report_demo_store.get_session(session_id)
                        except KeyError:
                            preview_session = None
                        if isinstance(preview_session, dict):
                            preview_patient_id = str(preview_session.get("patient_id") or "").strip()
                            preview_study_id = str(preview_session.get("study_id") or "").strip()
                            preview_source = str(preview_session.get("source") or "").strip()
                            preview_image_path = str(preview_session.get("_slice_image_path") or "").strip()
                            preview_seg_path = str(preview_session.get("_slice_seg_path") or "").strip()
                            if (
                                preview_source == "knowledge"
                                and preview_patient_id == knowledge_launch_patient_uid
                                and preview_study_id == knowledge_launch_study_uid
                                and preview_image_path
                            ):
                                local_image_path = preview_image_path
                                local_seg_path = preview_seg_path or None
                                launch_age = (
                                    int(preview_session["age"])
                                    if preview_session.get("age") not in (None, "")
                                    else None
                                )
                                launch_sex = str(preview_session.get("sex") or "").strip().upper() or None
                                launch_indication = str(preview_session.get("indication") or "").strip() or None

                    if not local_image_path:
                        matched_preview_session = neuro_report_demo_store.find_session(
                            source="knowledge",
                            patient_id=knowledge_launch_patient_uid,
                            study_id=knowledge_launch_study_uid,
                        )
                        if matched_preview_session is not None:
                            _, preview_session = matched_preview_session
                            local_image_path = str(preview_session.get("_slice_image_path") or "").strip()
                            local_seg_path = str(preview_session.get("_slice_seg_path") or "").strip() or None
                            launch_age = (
                                int(preview_session["age"])
                                if preview_session.get("age") not in (None, "")
                                else None
                            )
                            launch_sex = str(preview_session.get("sex") or "").strip().upper() or None
                            launch_indication = str(preview_session.get("indication") or "").strip() or None

                    if not local_image_path:
                        launch_payload = _prepare_mr_rate_launch(
                            patient_uid=knowledge_launch_patient_uid,
                            study_uid=knowledge_launch_study_uid,
                            requested_local_root=None,
                            download_if_missing=True,
                            segmentation_preference="vista_then_nvseg",
                            sequence_preference="structural_default",
                        )
                        local_bundle = launch_payload.get("local_bundle") or {}
                        local_image_path = str(local_bundle.get("image_path") or "").strip()
                        local_seg_path = str(local_bundle.get("seg_path") or "").strip() or None
                        launch_age, launch_sex = _knowledge_launch_demographics(launch_payload)
                        launch_indication = _knowledge_launch_indication(launch_payload)

                    yield _format_sse(
                        "progress",
                        {"stage": "check_local_cache", "label": "Checked local MR-RATE mirror", "status": "done"},
                    )
                    if launch_payload and launch_payload.get("local_status") == "downloaded":
                        yield _format_sse(
                            "progress",
                            {"stage": "download_mr_rate_assets", "label": "Downloaded MR-RATE assets", "status": "done"},
                        )
                    if not local_image_path:
                        yield _format_sse("error", {"error": "MR-RATE launch did not produce a local image bundle."})
                        return
                    chosen_mode = mode if mode in SUPPORTED_ANALYSIS_MODES else "full_agent"
                    if chosen_mode != "vanilla" and not local_seg_path and not auto_segmentation_requested:
                        chosen_mode = "vanilla"
                    yield _format_sse(
                        "progress",
                        {"stage": "resolve_case", "label": "Resolved MR-RATE study", "status": "done"},
                    )
                    yield _format_sse(
                        "progress",
                        {"stage": "load_images", "label": "Preparing MR-RATE MRI slices", "status": "running"},
                    )
                    if not local_seg_path and auto_segmentation_requested:
                        yield _format_sse(
                            "progress",
                            {"stage": "auto_segmentation", "label": "Warming auto segmentation", "status": "running"},
                        )
                    result = await neuro_report_demo_store.analyze(
                        nifti_path=local_image_path,
                        seg_path=local_seg_path,
                        age=age if age is not None else launch_age,
                        sex=(sex or "").upper() or launch_sex,
                        indication=indication or launch_indication or "Brain MRI from MR-RATE knowledge launch",
                        mode=chosen_mode,
                        patient_id=knowledge_launch_patient_uid,
                        study_id=knowledge_launch_study_uid,
                        case_id=None,
                        source="knowledge",
                        request_text=request_text or "Analyze this MR-RATE study from the knowledge explorer.",
                        auto_segment=auto_segment,
                        segmentation_backend=segmentation_backend,
                    )
                elif case_id or (patient_id and study_id):
                    record = neuro_report_demo_store.resolve_analysis_request(
                        case_id=case_id,
                        patient_id=patient_id,
                        study_id=study_id,
                    )
                    chosen_mode = mode if mode in SUPPORTED_ANALYSIS_MODES else "full_agent"
                    if isinstance(record, dict):
                        if chosen_mode not in {"vanilla", "seg_overlay"}:
                            chosen_mode = "seg_overlay"
                        if chosen_mode != "vanilla" and record["seg_path"] is None and not auto_segmentation_requested:
                            chosen_mode = "vanilla"
                    elif chosen_mode != "vanilla" and record.seg_path is None and not auto_segmentation_requested:
                        chosen_mode = "vanilla"
                    yield _format_sse(
                        "progress",
                        {"stage": "resolve_case", "label": "Resolved patient study", "status": "done"},
                    )
                    yield _format_sse(
                        "progress",
                        {"stage": "load_images", "label": "Preparing MRI slices", "status": "running"},
                    )
                    record_seg_path = (str(record["seg_path"]) if isinstance(record, dict) and record["seg_path"] else None) if isinstance(record, dict) else (str(record.seg_path) if record.seg_path else None)
                    if not record_seg_path and auto_segmentation_requested:
                        yield _format_sse(
                            "progress",
                            {"stage": "auto_segmentation", "label": "Warming auto segmentation", "status": "running"},
                        )
                    result = await neuro_report_demo_store.analyze(
                        nifti_path=str(record["analysis_image_path"]) if isinstance(record, dict) else str(record.analysis_image_path),
                        seg_path=record_seg_path,
                        age=record["age"] if isinstance(record, dict) else record.age,
                        sex=record["sex"] if isinstance(record, dict) else record.sex,
                        indication=indication or (record["indication"] if isinstance(record, dict) else record.indication),
                        mode=chosen_mode,
                        patient_id=record["patient_id"] if isinstance(record, dict) else record.patient_id,
                        study_id=record["study_id"] if isinstance(record, dict) else record.study_id,
                        case_id=record["case_id"] if isinstance(record, dict) else record.case_id,
                        source="example",
                        request_text=request_text or "",
                        auto_segment=auto_segment,
                        segmentation_backend=segmentation_backend,
                    )
                else:
                    resolved_source_path = str(source_path or "").strip()
                    if nifti_file is None and not resolved_source_path:
                        yield _format_sse("error", {"error": "Select a study from the patient library or upload a NIfTI file."})
                        return
                    if mode != "vanilla" and seg_file is None and not (
                        auto_segment and (segmentation_backend or "structural_segmenter") == "structural_segmenter"
                    ):
                        yield _format_sse(
                            "error",
                            {"error": "seg_file is required for the selected mode unless auto-segment structural anatomy is enabled."},
                        )
                        return
                    if nifti_file is not None:
                        nifti_bytes = await nifti_file.read()
                        seg_bytes = await seg_file.read() if seg_file else None
                        nifti_path, seg_path = neuro_report_demo_store.create_uploaded_source(
                            nifti_bytes=nifti_bytes,
                            nifti_filename=nifti_file.filename or "uploaded.nii.gz",
                            seg_bytes=seg_bytes,
                            seg_filename=seg_file.filename if seg_file else None,
                        )
                    else:
                        resolved_path = Path(resolved_source_path).expanduser().resolve()
                        if not resolved_path.exists() or not resolved_path.is_file():
                            yield _format_sse("error", {"error": f"Upload source is unavailable: {resolved_source_path}"})
                            return
                        nifti_path = str(resolved_path)
                        seg_path = None
                    yield _format_sse(
                        "progress",
                        {"stage": "resolve_upload", "label": "Stored uploaded files", "status": "done"},
                    )
                    yield _format_sse(
                        "progress",
                        {"stage": "load_images", "label": "Preparing uploaded MRI slices", "status": "running"},
                    )
                    if seg_path is None and auto_segmentation_requested:
                        yield _format_sse(
                            "progress",
                            {"stage": "auto_segmentation", "label": "Warming auto segmentation", "status": "running"},
                        )
                    result = await neuro_report_demo_store.analyze(
                        nifti_path=nifti_path,
                        seg_path=seg_path,
                        age=age,
                        sex=(sex or "").upper() or None,
                        indication=indication or "Brain MRI for clinical evaluation",
                        mode=mode,
                        patient_id=None,
                        study_id=None,
                        case_id=None,
                        source="upload",
                        request_text=request_text or "",
                        auto_segment=auto_segment,
                        segmentation_backend=segmentation_backend,
                    )

                neuro_access.register_result(result, _current_user_id(request))
                if auth_store.require_user_auth:
                    result = public_neuro_payload(result)
                yield _format_sse(
                    "progress",
                    {"stage": "load_images", "label": "Prepared MRI slices", "status": "done"},
                )
                if auto_segmentation_requested:
                    yield _format_sse(
                        "progress",
                        {
                            "stage": "auto_segmentation",
                            "label": "Auto segmentation ready" if result.get("segmentation_backend") == "structural_segmenter" else "Auto segmentation skipped",
                            "status": "done" if result.get("segmentation_backend") == "structural_segmenter" else "skipped",
                        },
                    )
                yield _format_sse(
                    "slices",
                    {
                        "raw": result["raw_slices"],
                        "overlay": result["overlay_slices"],
                        "active": result["slices"],
                        "manifest": result.get("slice_manifest"),
                        "source": result.get("slice_source"),
                    },
                )
                if result["volumetrics"]:
                    yield _format_sse(
                        "progress",
                        {"stage": "volumetrics", "label": "Computed volumetrics", "status": "done"},
                    )
                    yield _format_sse("volumetrics", result["volumetrics"])
                else:
                    yield _format_sse(
                        "progress",
                        {"stage": "volumetrics", "label": "No volumetrics for this mode", "status": "skipped"},
                    )

                accumulated = ""
                yield _format_sse(
                    "progress",
                    {"stage": "report", "label": "Generating report", "status": "running"},
                )
                for chunk in _chunk_text(result["report"]):
                    accumulated = f"{accumulated} {chunk}".strip()
                    yield _format_sse("report_chunk", {"delta": chunk, "content": accumulated})
                    await asyncio.sleep(0.03)
                yield _format_sse(
                    "progress",
                    {"stage": "report", "label": "Generated report", "status": "done"},
                )
                yield _format_sse(
                    "complete",
                    {
                        "session_id": result["session_id"],
                        "patient_id": result["patient_id"],
                        "study_id": result["study_id"],
                        "case_id": result["case_id"],
                        "mode": result["mode"],
                        "requested_mode": result["requested_mode"],
                        "report": result["report"],
                        "report_sections": result["report_sections"],
                        "viewer_assets": result["viewer_assets"],
                        "analysis_plan": result["analysis_plan"],
                        "analysis_plan_summary": result["analysis_plan_summary"],
                        "capability_profile": result["capability_profile"],
                        "capability_profile_summary": result["capability_profile_summary"],
                        "planning_result": result.get("planning_result"),
                        "dashboard_payloads": result.get("dashboard_payloads"),
                        "workspace_contract": result.get("workspace_contract"),
                        "slice_manifest": result.get("slice_manifest"),
                        "slice_source": result.get("slice_source"),
                    },
                )
            except Exception as exc:
                yield _format_sse("error", {"error": str(exc)})

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    @app.post("/api/demo/neuro-report/chat")
    async def neuro_report_chat(request: Request):
        import asyncio

        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "session_id": "...", "question": "..." }'}),
                status_code=400,
                media_type="application/json",
            )

        session_id = (payload.get("session_id") or "").strip()
        question = (payload.get("question") or "").strip()
        if auth_store.require_user_auth and not neuro_access.session_allowed(session_id, _current_user_id(request)):
            return JSONResponse({"error": "Session not found."}, status_code=404)
        if not session_id or not question:
            return Response(
                content=json.dumps({"error": "session_id and question are required"}),
                status_code=400,
                media_type="application/json",
            )

        async def _stream():
            try:
                _, neuro_report_demo_store = _get_neuro_report_demo_components()
                session = neuro_report_demo_store.get_session(session_id)
                context_sections = session.get("report_sections") or {}
                volumetrics = session.get("tool_outputs", {}).get("volumetrics")
                volumetric_summary = volumetrics.get("summary") if isinstance(volumetrics, dict) else ""
                analysis_plan = session.get("analysis_plan") or {}
                messages = [
                    LLMMessage(
                        role="system",
                        content=(
                            "You are the ClinAgent neuro MRI follow-up assistant. "
                            "Answer only from the supplied report and tool outputs. "
                            "Be concise, clear, and clinician-facing. "
                            "When useful, explain what the workflow could and could not safely do."
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=(
                            f"Patient context:\n"
                            f"- Patient ID: {session.get('patient_id') or 'uploaded case'}\n"
                            f"- Study ID: {session.get('study_id') or 'uploaded study'}\n"
                            f"- Mode: {session.get('mode')}\n"
                            f"- Clinical indication: {session.get('indication')}\n\n"
                            f"Analysis plan summary: {analysis_plan.get('handoff_summary', '')}\n"
                            f"Missing inputs: {', '.join(analysis_plan.get('missing_inputs', [])) or 'None'}\n\n"
                            f"Structured report sections:\n"
                            f"Clinical information: {context_sections.get('clinical_information', '')}\n"
                            f"Technique: {context_sections.get('technique', '')}\n"
                            f"Findings: {context_sections.get('findings', '')}\n"
                            f"Impression: {context_sections.get('impression', '')}\n\n"
                            f"Volumetric summary: {volumetric_summary}\n\n"
                            f"User question: {question}"
                        ),
                    ),
                ]
                response = await llm.chat(messages)
                accumulated = ""
                for chunk in _chunk_text(response.content):
                    accumulated = f"{accumulated} {chunk}".strip()
                    yield _format_sse("chat_chunk", {"delta": chunk, "content": accumulated})
                    await asyncio.sleep(0.02)
                yield _format_sse("chat_complete", {"content": accumulated or response.content.strip()})
            except Exception as exc:
                yield _format_sse("error", {"error": str(exc)})

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    @app.get("/safety-demo")
    async def safety_demo_page():
        if not safety_index.exists():
            return Response(content="Safety demo UI is not available.", status_code=404)
        return FileResponse(safety_index)

    @app.get("/findings-demo")
    async def findings_demo_page():
        if not findings_index.exists():
            return Response(content="Findings demo UI is not available.", status_code=404)
        return FileResponse(findings_index)

    @app.get("/queue-demo")
    async def queue_demo_page():
        if not queue_index.exists():
            return Response(content="Queue demo UI is not available.", status_code=404)
        return FileResponse(queue_index)

    @app.get("/report-quality-demo")
    async def report_quality_demo_page():
        if not report_quality_index.exists():
            return Response(content="Report quality demo UI is not available.", status_code=404)
        return FileResponse(report_quality_index)

    @app.get("/api/findings/workspace")
    async def findings_workspace():
        return findings_closure_store.snapshot()

    @app.get("/api/findings/cases/{case_id}")
    async def findings_case(case_id: str):
        try:
            return findings_closure_store.get_case(case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown findings case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/findings/rerun")
    async def findings_rerun(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        if not case_id:
            return Response(
                content=json.dumps({"error": "case_id is required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return findings_closure_store.rerun(case_id=case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown findings case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/findings/review")
    async def findings_review(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "...", "action": "...", "comment": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        action = (payload.get("action") or "").strip()
        comment = (payload.get("comment") or "").strip() or None
        if not case_id or not action:
            return Response(
                content=json.dumps({"error": "case_id and action are required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return findings_closure_store.review(case_id=case_id, action=action, comment=comment)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown findings case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/findings/explain")
    async def findings_explain(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "...", "question": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        question = (payload.get("question") or "").strip()
        if not case_id or not question:
            return Response(
                content=json.dumps({"error": "case_id and question are required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return findings_closure_store.explain(case_id=case_id, question=question)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown findings case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.get("/api/queue/workspace")
    async def queue_workspace():
        return queue_triage_store.snapshot()

    @app.get("/api/report-quality/workspace")
    async def report_quality_workspace():
        return report_quality_demo_store.snapshot()

    @app.get("/api/report-quality/cases/{case_id}")
    async def report_quality_case(case_id: str):
        try:
            return report_quality_demo_store.get_case(case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown report quality case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.get("/api/queue/cases/{case_id}")
    async def queue_case(case_id: str):
        try:
            return queue_triage_store.get_case(case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown queue case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/queue/rerun")
    async def queue_rerun(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        if not case_id:
            return Response(
                content=json.dumps({"error": "case_id is required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return queue_triage_store.rerun(case_id=case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown queue case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/queue/review")
    async def queue_review(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "...", "action": "...", "comment": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        action = (payload.get("action") or "").strip()
        comment = (payload.get("comment") or "").strip() or None
        if not case_id or not action:
            return Response(
                content=json.dumps({"error": "case_id and action are required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return queue_triage_store.review(case_id=case_id, action=action, comment=comment)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown queue case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/queue/explain")
    async def queue_explain(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "...", "question": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        question = (payload.get("question") or "").strip()
        if not case_id or not question:
            return Response(
                content=json.dumps({"error": "case_id and question are required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return queue_triage_store.explain(case_id=case_id, question=question)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown queue case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.get("/api/diagnosis/workspace")
    async def diagnosis_workspace():
        return missed_diagnosis_store.snapshot()

    @app.get("/api/diagnosis/cases/{case_id}")
    async def diagnosis_case(case_id: str):
        try:
            return missed_diagnosis_store.get_case(case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown diagnosis case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/diagnosis/rerun")
    async def diagnosis_rerun(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        if not case_id:
            return Response(
                content=json.dumps({"error": "case_id is required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return missed_diagnosis_store.rerun(case_id=case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown diagnosis case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/diagnosis/review")
    async def diagnosis_review(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "...", "action": "...", "comment": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        action = (payload.get("action") or "").strip()
        comment = (payload.get("comment") or "").strip() or None
        if not case_id or not action:
            return Response(
                content=json.dumps({"error": "case_id and action are required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return missed_diagnosis_store.review(case_id=case_id, action=action, comment=comment)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown diagnosis case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/diagnosis/explain")
    async def diagnosis_explain(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "...", "question": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        question = (payload.get("question") or "").strip()
        if not case_id or not question:
            return Response(
                content=json.dumps({"error": "case_id and question are required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return missed_diagnosis_store.explain(case_id=case_id, question=question)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown diagnosis case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.get("/api/screening/workspace")
    async def screening_workspace():
        return screening_gap_store.snapshot()

    @app.get("/api/screening/cases/{case_id}")
    async def screening_case(case_id: str):
        try:
            return screening_gap_store.get_case(case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown screening case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/screening/rerun")
    async def screening_rerun(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        if not case_id:
            return Response(
                content=json.dumps({"error": "case_id is required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return screening_gap_store.rerun(case_id=case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown screening case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/screening/review")
    async def screening_review(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "...", "action": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        action = payload.get("action")
        comment = payload.get("comment")
        if not case_id or not action:
            return Response(
                content=json.dumps({"error": "case_id and action are required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return screening_gap_store.review(case_id=case_id, action=action, comment=comment)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown screening case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/screening/explain")
    async def screening_explain(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "...", "question": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        question = (payload.get("question") or "").strip()
        if not case_id or not question:
            return Response(
                content=json.dumps({"error": "case_id and question are required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return screening_gap_store.explain(case_id=case_id, question=question)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown screening case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown diagnosis case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.get("/api/safety/workspace")
    async def safety_workspace():
        return safety_monitor_store.snapshot()

    @app.get("/api/safety/cases/{case_id}")
    async def safety_case(case_id: str):
        try:
            return safety_monitor_store.get_case(case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown safety case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/safety/rerun")
    async def safety_rerun(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        if not case_id:
            return Response(
                content=json.dumps({"error": "case_id is required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return safety_monitor_store.rerun(case_id=case_id)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown safety case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/safety/review")
    async def safety_review(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "...", "action": "...", "comment": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        action = (payload.get("action") or "").strip()
        comment = (payload.get("comment") or "").strip() or None
        if not case_id or not action:
            return Response(
                content=json.dumps({"error": "case_id and action are required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return safety_monitor_store.review(case_id=case_id, action=action, comment=comment)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown safety case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.post("/api/safety/explain")
    async def safety_explain(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "case_id": "...", "question": "..." }'}),
                status_code=400,
                media_type="application/json",
            )
        case_id = payload.get("case_id")
        question = (payload.get("question") or "").strip()
        if not case_id or not question:
            return Response(
                content=json.dumps({"error": "case_id and question are required"}),
                status_code=400,
                media_type="application/json",
            )
        try:
            return safety_monitor_store.explain(case_id=case_id, question=question)
        except KeyError:
            return Response(
                content=json.dumps({"error": f"Unknown safety case: {case_id}"}),
                status_code=404,
                media_type="application/json",
            )

    @app.get("/queue")
    async def queue_status():
        lanes = {lane: get_queue_size(lane) for lane in VALID_LANES}
        return {
            "lanes": lanes,
            "total": get_total_queue_size(),
            "active": get_active_task_count(),
        }

    @app.post("/chat")
    async def chat(request: Request):
        if not _check_auth(request):
            return Response(
                content=json.dumps({"error": "Unauthorized. Set Authorization: Bearer <GATEWAY_API_KEY>"}),
                status_code=401,
                media_type="application/json",
            )

        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "task": "...", "lane": "main|cron|subagent", "scenario_id": "optional" }'}),
                status_code=400,
                media_type="application/json",
            )

        task = payload.get("task", "Unknown task")
        lane = _resolve_lane(payload.get("lane"))
        scenario_id = payload.get("scenario_id")
        requested_by = payload.get("requested_by", "http-chat")
        case_id = payload.get("case_id")
        external_patient_id = payload.get("external_patient_id")
        note = payload.get("note")

        async def execute_graph():
            print(f"[Gateway] lane={lane} task: {task}")
            if scenario_id:
                if not clinagent.get_scenario(scenario_id):
                    raise ValueError(f"Unknown scenario_id: {scenario_id}")
                return await clinagent.invoke_scenario(
                    task=task,
                    scenario_id=scenario_id,
                    llm=llm,
                    requested_by=requested_by,
                    case_id=case_id,
                    external_patient_id=external_patient_id,
                    note=note,
                )
            agent = create_agent(model=llm)
            return await agent.invoke(task)

        try:
            result = await enqueue_command_in_lane(lane, execute_graph)
            if scenario_id:
                success = result.result.status != "reauth_required"
                return {
                    "success": success,
                    "lane": lane,
                    "scenario_id": result.scenario.id,
                    "task_run_id": result.task_run_id,
                    "review_required": result.review_required,
                    "artifact_ids": result.artifact_ids,
                    "access_event_ids": result.access_event_ids,
                    "status": result.result.status,
                    "result": result.result.result,
                    "iterations": result.result.iterations,
                }
            return {
                "success": True,
                "lane": lane,
                "status": result.status,
                "result": result.result,
                "iterations": result.iterations,
            }
        except Exception as e:
            return Response(
                content=json.dumps({"success": False, "lane": lane, "error": str(e)}),
                status_code=500,
                media_type="application/json",
            )

    @app.post("/chat/stream")
    async def chat_stream(request: Request):
        if not _check_auth(request):
            return Response(
                content=json.dumps({"error": "Unauthorized"}),
                status_code=401,
                media_type="application/json",
            )

        try:
            payload = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": 'Invalid JSON. Send { "task": "...", "lane": "main|cron|subagent", "scenario_id": "optional" }'}),
                status_code=400,
                media_type="application/json",
            )

        task = payload.get("task", "Unknown task")
        lane = _resolve_lane(payload.get("lane"))
        scenario_id = payload.get("scenario_id")
        requested_by = payload.get("requested_by", "http-stream")
        case_id = payload.get("case_id")
        external_patient_id = payload.get("external_patient_id")
        note = payload.get("note")

        import asyncio

        event_queue: asyncio.Queue[str | None] = asyncio.Queue()

        def sse(event: str, data: Any):
            event_queue.put_nowait(f"event: {event}\ndata: {json.dumps(data)}\n\n")

        async def _run():
            sse("queued", {"lane": lane, "position": get_queue_size(lane), "scenario_id": scenario_id})
            try:
                result = await enqueue_command_in_lane(lane, _execute)
                if scenario_id:
                    success = result.result.status != "reauth_required"
                    sse("done", {
                        "success": success,
                        "lane": lane,
                        "scenario_id": result.scenario.id,
                        "task_run_id": result.task_run_id,
                        "review_required": result.review_required,
                        "artifact_ids": result.artifact_ids,
                        "access_event_ids": result.access_event_ids,
                        "status": result.result.status,
                        "result": result.result.result,
                        "iterations": result.result.iterations,
                    })
                else:
                    sse("done", {
                        "lane": lane,
                        "status": result.status,
                        "result": result.result,
                        "iterations": result.iterations,
                    })
            except Exception as e:
                sse("error", {"lane": lane, "error": str(e)})
            finally:
                event_queue.put_nowait(None)

        async def _execute():
            sse("started", {"lane": lane, "scenario_id": scenario_id})
            if scenario_id:
                if not clinagent.get_scenario(scenario_id):
                    raise ValueError(f"Unknown scenario_id: {scenario_id}")

                def on_event(kind, data):
                    sse("agent", {"kind": kind, "data": data})

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

            def on_event(kind, data):
                sse("agent", {"kind": kind, "data": data})

            return await agent.invoke(task, on_event=on_event)

        asyncio.create_task(_run())

        async def _stream():
            while True:
                msg = await event_queue.get()
                if msg is None:
                    break
                yield msg

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    attach_websocket(app, llm, _GATEWAY_API_KEY, clinagent, auth_store=auth_store)

    return app, llm, active_model


def _gateway_bind_host(explicit_host: str | None = None) -> str:
    configured = explicit_host if explicit_host is not None else os.getenv("CLINAGENT_HOST", "0.0.0.0")
    return configured.strip() or "0.0.0.0"


def start_gateway(port: int = 3000, host: str | None = None):
    app, llm, active_model = create_app()
    bind_host = _gateway_bind_host(host)
    auth_status = "enabled" if _GATEWAY_API_KEY else "disabled (set GATEWAY_API_KEY to enable)"
    use_color = sys.stdout.isatty() and os.getenv("TERM", "dumb") != "dumb"
    if use_color:
        gold = "\033[38;2;210;146;70m"
        soft = "\033[38;2;235;205;166m"
        muted = "\033[38;2;142;125;102m"
        reset = "\033[0m"
        # Terminal approximation of the canonical brand mark from
        # frontend/public/clinagent-logo-mark.svg.
        logo_lines = (
            "                     ▗▄▄▖",
            "                  ▗██████▖",
            "               ▗██████████▖",
            "             ▗██████  █████▖",
            "            ▐█████      ████▌",
            "             ▜████▖  ▗█████▛",
            "               ▜██████████▛",
            "                 ▜██████▛",
        )
        print()
        for line in logo_lines:
            print(f"{gold}{line}{reset}")
        print(f"{gold}ClinAgent Gateway{reset} {soft}running on http://localhost:{port}{reset}")
        print(f"{muted}   Provider:{reset} {soft}{llm.name}{reset}")
        print(f"{muted}   Model:{reset} {soft}{active_model}{reset}")
        print(f"{muted}   Auth:{reset} {soft}{auth_status}{reset}")
        print(f"{muted}   Endpoints:{reset} {soft}POST /chat | POST /chat/stream | WS /ws | GET /queue | GET /health{reset}\n")
    else:
        print(f"\nClinAgent Gateway running on http://localhost:{port}")
        print(f"   Provider: {llm.name}")
        print(f"   Model: {active_model}")
        print(f"   Auth: {auth_status}")
        print("   Endpoints: POST /chat | POST /chat/stream | WS /ws | GET /queue | GET /health\n")

    uvicorn.run(app, host=bind_host, port=port, log_level="warning")
