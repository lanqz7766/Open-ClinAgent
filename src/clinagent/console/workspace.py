from __future__ import annotations

from typing import Any

from clinagent.console.demo import demo_workspace_store
from clinagent.families.findings.workspace import findings_closure_store
from clinagent.families.diagnosis.workspace import missed_diagnosis_store
from clinagent.platform.execution_profiles import (
    list_developer_actions,
    list_execution_profiles,
    list_subagent_roles,
)
from clinagent.platform.family_registry import (
    list_family_registry,
    list_workflow_registry,
    resolve_workflow_registry_id,
)
from clinagent.platform.mcp_registry import list_mcp_servers
from clinagent.families.queue.workspace import queue_triage_store
from clinagent.families.shared.report_quality_demo import report_quality_demo_store
from clinagent.families.screening.workspace import screening_gap_store
from clinagent.families.safety.workspace import safety_monitor_store
from clinagent.families.radonc import radonc_plan_demo_store
from clinagent.platform.runtime_bridge import get_active_task_count, get_queue_size, get_total_queue_size


WORKFLOWS = [
    {
        "id": "general_chat",
        "title": "General Clinical Command",
        "module": "home",
        "summary": "Natural-language intake that routes requests into the most relevant ClinAgent workflow.",
        "tools": ["workflow_router", "policy_guard", "tool_selector"],
        "tags": ["chat", "routing", "agent-entry"],
        "examples": [
            "Help me decide which workflow I should use.",
            "I have a new clinical task but I'm not sure where it belongs.",
        ],
    },
    {
        "id": "report_quality_review",
        "title": "Report Quality Review",
        "module": "report_quality",
        "summary": "Template-driven report QA with privacy, terminology, and compliance checks before sharing or sign-off.",
        "tools": ["deidentification_checker", "report_policy_checker", "clinical_language_checker", "report_template_registry"],
        "tags": ["report", "qa", "deidentification", "compliance", "terminology"],
        "examples": [
            "Check this report for identifiers and terminology issues.",
            "Show me whether this draft is ready for review.",
        ],
    },
    {
        "id": "findings_closure",
        "title": "Findings Closure",
        "module": "findings",
        "summary": "Actionable findings follow-up across labs, radiology reports, and other result-closure workflows.",
        "tools": ["finding_parser", "closure_checker", "action_recommender", "review_router"],
        "tags": ["findings", "follow-up", "lab", "report", "closure"],
        "examples": [
            "Does this critical lab need urgent escalation?",
            "Check whether this actionable report finding still needs follow-up.",
        ],
    },
    {
        "id": "queue_triage",
        "title": "Queue Triage",
        "module": "queue",
        "summary": "Reprioritize high-risk referrals and follow-up queues with compact review-first triage logic.",
        "tools": ["queue_reader", "priority_scorer", "review_router", "action_recommender"],
        "tags": ["queue", "referral", "triage", "follow-up"],
        "examples": [
            "Should this referral move to an urgent queue?",
            "Review this post-discharge case and suggest the next triage step.",
        ],
    },
    {
        "id": "missed_diagnosis_detection",
        "title": "Missed Diagnosis Review",
        "module": "diagnosis",
        "summary": "Detect likely diagnosis gaps from reports and chart follow-up signals, then prepare review-first workup guidance.",
        "tools": ["gap_reader", "evidence_bundle", "workup_recommender", "review_router"],
        "tags": ["diagnosis-gap", "fracture", "chart-review", "follow-up"],
        "examples": [
            "Does this report suggest a missed vertebral fracture workup gap?",
            "Review this case for a likely missed diagnosis and summarize the next step.",
        ],
    },
    {
        "id": "screening_gap_closure",
        "title": "Screening Gap Closure",
        "module": "screening",
        "summary": "Detect overdue or unresolved screening follow-up and prepare a concise review-first closure plan.",
        "tools": ["screening_reader", "gap_checker", "followup_recommender", "review_router"],
        "tags": ["screening", "gap", "follow-up", "population-health"],
        "examples": [
            "Does this positive FIT still need diagnostic follow-up?",
            "Review this screening result and tell me whether the gap is still open.",
        ],
    },
    {
        "id": "neuro_longitudinal",
        "title": "Neuro Longitudinal Review",
        "module": "neuro",
        "summary": "Legacy neuro-oncology response workspace retained as a compatibility data source while Neuro Report absorbs the flagship longitudinal response experience.",
        "tools": [
            "neuro_longitudinal_workspace",
            "dicom_series_selector",
            "neuro_longitudinal_visuals",
            "neuro_longitudinal_viewer_manifest",
            "neuro_longitudinal_report",
            "lesion_trend_plotter",
            "treatment_event_timeline_renderer",
            "key_slice_selector",
            "overlay_composer",
            "longitudinal_comparison_panel_builder",
            "risk_signal_renderer",
            "neuro_longitudinal_series_catalog",
            "brain_met_response_tracker",
            "rt_timeline_aligner",
            "slice_preview_renderer",
            "neuro_oncology_brief_presenter",
        ],
        "tags": ["brain", "mri", "brain-met", "response", "longitudinal", "legacy"],
        "examples": [
            "Compare this longitudinal brain MRI follow-up and draft a physician report.",
            "Does the latest follow-up suggest treatment response or concerning progression?",
        ],
    },
    {
        "id": "neuro_report",
        "title": "Neuro MRI Report Generator",
        "module": "neuro_report",
        "summary": "Flagship neuro workspace for structural volumetry, longitudinal response review, and embedded report-quality review across brain MRI cases.",
        "tools": [
            "slice_selector",
            "brain_segmentation",
            "volumetric_analysis",
            "vlm_report_generator",
        ],
        "tags": ["brain", "mri", "volumetric", "segmentation", "report", "longitudinal", "response", "review", "tumor", "lesion"],
        "examples": [
            "Analyze this brain MRI and generate a structured radiology report.",
            "Show me the longitudinal volume trends for this patient's hippocampus.",
            "Review longitudinal brain tumor response and summarize lesion burden change.",
            "Review this neuro MRI report draft for omissions or inconsistencies.",
        ],
    },
    {
        "id": "radonc_plan_optimization",
        "title": "RadOnc Plan Optimization",
        "module": "radonc_plan",
        "summary": "Flagship radiation oncology planning workspace for DVH review, objective trade-offs, and iterative auto-optimization.",
        "tools": [
            "rt_plan_context_loader",
            "dvh_constraint_analyzer",
            "objective_adjustment_engine",
            "plan_tradeoff_synthesizer",
        ],
        "tags": ["radonc", "plan", "optimization", "dvh", "coverage", "oar"],
        "examples": [
            "Optimize this lung SBRT plan and keep the spinal cord cooler.",
            "Review DVH trade-offs and auto-adjust the current planning objectives.",
        ],
    },
    {
        "id": "radiation_safety_monitor",
        "title": "Radiation Safety Monitor",
        "module": "safety",
        "summary": "Case-based failure pattern matching with watch/alert/urgent triage and mitigation playbooks.",
        "tools": ["case_parser", "failure_pattern_matcher", "risk_tier_engine", "mock_email_router"],
        "tags": ["qa", "radiation-oncology", "incident", "alert"],
        "examples": [
            "Does this radiation incident require an urgent alert?",
            "Match this QA case against historical failure patterns.",
        ],
    },
]


ROUTING_KEYWORDS = {
    "report_quality": {
        "report quality",
        "report qa",
        "de-identification",
        "deidentification",
        "hipaa",
        "terminology",
        "abbreviation",
        "compliance",
        "redact",
        "redaction",
        "phi",
        "identifier",
        "report draft",
        "qa this report",
    },
    "findings": {
        "critical",
        "lab",
        "follow-up",
        "follow up",
        "result",
        "finding",
        "abnormal pap",
        "nodule",
        "potassium",
    },
    "queue": {
        "referral",
        "queue",
        "triage",
        "high-risk",
        "high risk",
        "post-discharge",
        "post discharge",
        "expedite",
        "same-day",
        "same day",
        "follow-up window",
        "follow up window",
        "outreach",
    },
    "diagnosis": {
        "missed diagnosis",
        "missed fracture",
        "vertebral",
        "compression fracture",
        "osteoporosis",
        "gap",
        "unrecognized",
        "undiagnosed",
        "atrial fibrillation",
        "hypertension",
    },
    "screening": {
        "screening",
        "positive fit",
        "fit",
        "colonoscopy",
        "cervical",
        "pap",
        "hpv",
        "lung cancer screening",
        "diabetic eye exam",
        "overdue screening",
        "care gap",
    },
    "neuro": {
        "mri",
        "brain",
        "brain metast",
        "metastasis",
        "brain met",
        "t1c",
        "flair",
        "response",
        "progression",
        "post-radiotherapy",
        "post radiotherapy",
        "longitudinal",
        "neuro",
        "evidence board",
        "claim verification",
        "verifier",
        "report",
        "volume",
        "trend",
        "tumor board",
    },
    "safety": {
        "incident",
        "safety",
        "radiation",
        "radiotherapy",
        "timeout",
        "error",
        "alert",
        "adaptive",
        "plan",
        "qa",
        "physics",
        "dosimetry",
        "beam",
    },
    "radonc_plan": {
        "plan optimization",
        "optimize plan",
        "treatment planning",
        "dvh",
        "dose volume histogram",
        "constraint",
        "coverage",
        "oar",
        "objective",
        "optimize objectives",
        "spinal cord",
        "lower heart dose",
        "too hot",
    },
}


def console_snapshot() -> dict[str, Any]:
    neuro = demo_workspace_store.snapshot()
    safety = safety_monitor_store.snapshot()
    report_quality = report_quality_demo_store.snapshot()
    findings = findings_closure_store.snapshot()
    queue = queue_triage_store.snapshot()
    diagnosis = missed_diagnosis_store.snapshot()
    screening = screening_gap_store.snapshot()
    radonc = radonc_plan_demo_store.snapshot()
    return {
        "title": "ClinAgent Console",
        "tagline": "General clinical command center with workflow-specific modules.",
        "quick_prompts": [
            "Review this post-radiotherapy brain MRI trend and draft a physician summary.",
            "Should this referral move into an urgent queue today?",
            "Does this positive FIT still need colonoscopy follow-up?",
            "Check whether this radiotherapy case resembles a known failure pattern.",
            "Optimize this lung SBRT plan and summarize the DVH trade-offs.",
            "Route my request to the right workflow and show the next actions.",
        ],
        "workflows": WORKFLOWS,
        "workflow_families": list_family_registry(),
        "workflow_registry": list_workflow_registry(),
        "highlights": [
            {
                "label": "Workflow families",
                "value": f"{len(list_family_registry())} registered families",
            },
            {
                "label": "Available modules",
                "value": f"{len([item for item in WORKFLOWS if item['module'] != 'home'])} workflow workspaces",
            },
            {
                "label": "Report QA cases",
                "value": f"{len(report_quality['cases'])} validation examples",
            },
            {
                "label": "Active safety queue",
                "value": f"{len(safety['cases'])} incoming cases",
            },
            {
                "label": "Open findings queue",
                "value": f"{len(findings['cases'])} actionable cases",
            },
            {
                "label": "Queue triage lane",
                "value": f"{len(queue['cases'])} triage cases",
            },
            {
                "label": "Diagnosis gap review",
                "value": f"{len(diagnosis['cases'])} review cases",
            },
            {
                "label": "Screening gap queue",
                "value": f"{len(screening['cases'])} screening cases",
            },
            {
                "label": "Neuro report state",
                "value": neuro["workspace"]["review"]["status"].replace("_", " ").title(),
            },
            {
                "label": "RadOnc optimizer",
                "value": radonc["session"].get("status", "no_data").replace("_", " ").title(),
            },
        ],
        "modules": {
            "neuro": {
                "title": neuro["workspace"]["title"],
                "summary": neuro["workspace"]["patient"]["summary"],
                "risk": neuro["workspace"]["analysis"]["risk_level"],
                "default_case_id": neuro["default_case_id"],
            },
            "report_quality": {
                "title": report_quality["workspace"]["title"],
                "summary": report_quality["workspace"]["summary"],
                "risk": report_quality["workspace"]["status_label"],
                "default_case_id": report_quality["default_case_id"],
            },
            "findings": {
                "title": findings["workspace"]["title"],
                "summary": findings["workspace"]["risk_reason"],
                "risk": findings["workspace"]["risk_label"],
                "default_case_id": findings["default_case_id"],
            },
            "queue": {
                "title": queue["workspace"]["title"],
                "summary": queue["workspace"]["risk_reason"],
                "risk": queue["workspace"]["risk_label"],
                "default_case_id": queue["default_case_id"],
            },
            "diagnosis": {
                "title": diagnosis["workspace"]["title"],
                "summary": diagnosis["workspace"]["risk_reason"],
                "risk": diagnosis["workspace"]["risk_label"],
                "default_case_id": diagnosis["default_case_id"],
            },
            "screening": {
                "title": screening["workspace"]["title"],
                "summary": screening["workspace"]["risk_reason"],
                "risk": screening["workspace"]["risk_label"],
                "default_case_id": screening["default_case_id"],
            },
            "safety": {
                "title": safety["workspace"]["title"],
                "summary": safety["workspace"]["risk_reason"],
                "risk": safety["workspace"]["risk_label"],
                "default_case_id": safety["default_case_id"],
            },
            "radonc_plan": {
                "title": radonc["session"].get("title", "RadOnc Plan Optimization"),
                "summary": radonc["session"].get("subtitle", "No patient data loaded"),
                "risk": radonc["session"].get("risk_tier", "unknown"),
                "default_case_id": radonc["default_session_id"],
            },
        },
    }


def dev_console_snapshot(*, recent_trace_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot = console_snapshot()
    return {
        **snapshot,
        "surface": "developer",
        "profiles": list_execution_profiles(),
        "lane_status": {
            "lanes": [
                {"id": lane, "queued": get_queue_size(lane)}
                for lane in ("main", "cron", "subagent", "nested")
            ],
            "total_queued": get_total_queue_size(),
            "active_tasks": get_active_task_count(),
        },
        "subagent_roles": list_subagent_roles(),
        "developer_actions": list_developer_actions(),
        "mcp_servers": list_mcp_servers(),
        "recent_trace_summary": recent_trace_summary
        or {
            "status": "idle",
            "message": "No developer trace has been captured yet.",
            "tool_calls": [],
            "errors": [],
        },
    }


def _normalize_ingest_context(ingest_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(ingest_context, dict):
        return {}
    raw_inventory = ingest_context.get("raw_inventory")
    suggested_workflows = ingest_context.get("suggested_workflows")
    return {
        "detected_type": str(ingest_context.get("detected_type") or "").strip().lower(),
        "has_imaging": bool(ingest_context.get("has_imaging")),
        "has_longitudinal_data": bool(ingest_context.get("has_longitudinal_data")),
        "has_segmentation": bool(ingest_context.get("has_segmentation")),
        "patient_count": int(ingest_context.get("patient_count") or 0),
        "raw_inventory": raw_inventory if isinstance(raw_inventory, dict) else {},
        "suggested_workflows": [str(item).strip().lower() for item in suggested_workflows or [] if str(item).strip()],
    }


def augment_message_with_ingest_context(message: str, ingest_context: dict[str, Any] | None = None) -> str:
    normalized = _normalize_ingest_context(ingest_context)
    if not normalized:
        return message
    raw_inventory = normalized["raw_inventory"]
    has_nifti = any(raw_inventory.get(ext, 0) for ext in ("nii", "nii.gz"))
    has_dicom = any(raw_inventory.get(ext, 0) for ext in ("dcm", "dicom"))
    hints: list[str] = []
    if normalized["has_imaging"]:
        hints.append("uploaded brain mri")
    if has_nifti:
        hints.append("uploaded nifti")
    if has_dicom:
        hints.append("uploaded dicom")
    if normalized["has_segmentation"]:
        hints.append("segmentation available")
    else:
        hints.append("no segmentation uploaded")
    if normalized["has_longitudinal_data"] or normalized["detected_type"] == "longitudinal":
        hints.append("longitudinal follow-up imaging")
    if any(
        token in normalized["suggested_workflows"]
        for token in ("single_study_neuro_review", "longitudinal_neuro_review", "report_aware_longitudinal_review")
    ):
        hints.append("neuro report workflow suggested")
    if not hints:
        return message
    return f"{message}\n\nUpload context: {', '.join(hints)}."


def rank_workflows(message: str, ingest_context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    lowered = augment_message_with_ingest_context(message, ingest_context).lower()
    report_quality_score = sum(1 for token in ROUTING_KEYWORDS["report_quality"] if token in lowered)
    findings_score = sum(1 for token in ROUTING_KEYWORDS["findings"] if token in lowered)
    queue_score = sum(1 for token in ROUTING_KEYWORDS["queue"] if token in lowered)
    diagnosis_score = sum(1 for token in ROUTING_KEYWORDS["diagnosis"] if token in lowered)
    screening_score = sum(1 for token in ROUTING_KEYWORDS["screening"] if token in lowered)
    neuro_score = sum(1 for token in ROUTING_KEYWORDS["neuro"] if token in lowered)
    safety_score = sum(1 for token in ROUTING_KEYWORDS["safety"] if token in lowered)
    radonc_score = sum(1 for token in ROUTING_KEYWORDS["radonc_plan"] if token in lowered)
    ranked = [
        {
            "module": "report_quality",
            "workflow": next(item for item in WORKFLOWS if item["module"] == "report_quality"),
            "score": report_quality_score,
        },
        {
            "module": "findings",
            "workflow": next(item for item in WORKFLOWS if item["module"] == "findings"),
            "score": findings_score,
        },
        {
            "module": "queue",
            "workflow": next(item for item in WORKFLOWS if item["module"] == "queue"),
            "score": queue_score,
        },
        {
            "module": "diagnosis",
            "workflow": next(item for item in WORKFLOWS if item["module"] == "diagnosis"),
            "score": diagnosis_score,
        },
        {
            "module": "screening",
            "workflow": next(item for item in WORKFLOWS if item["module"] == "screening"),
            "score": screening_score,
        },
        {
            "module": "neuro_report",
            "workflow": next(item for item in WORKFLOWS if item["module"] == "neuro_report"),
            "score": neuro_score,
        },
        {
            "module": "safety",
            "workflow": next(item for item in WORKFLOWS if item["module"] == "safety"),
            "score": safety_score,
        },
        {
            "module": "radonc_plan",
            "workflow": next(item for item in WORKFLOWS if item["module"] == "radonc_plan"),
            "score": radonc_score,
        },
    ]
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked


def route_general_query(message: str, ingest_context: dict[str, Any] | None = None) -> dict[str, Any]:
    lowered = augment_message_with_ingest_context(message, ingest_context).lower()
    ranked = rank_workflows(message, ingest_context=ingest_context)
    best = ranked[0]
    alternatives = [
        {"module": item["module"], "title": item["workflow"]["title"], "score": item["score"]}
        for item in ranked
        if item["score"] > 0
    ]
    report_quality_score = next(item["score"] for item in ranked if item["module"] == "report_quality")
    findings_score = next(item["score"] for item in ranked if item["module"] == "findings")
    queue_score = next(item["score"] for item in ranked if item["module"] == "queue")
    diagnosis_score = next(item["score"] for item in ranked if item["module"] == "diagnosis")
    screening_score = next(item["score"] for item in ranked if item["module"] == "screening")
    neuro_score = next(item["score"] for item in ranked if item["module"] == "neuro_report")
    safety_score = next(item["score"] for item in ranked if item["module"] == "safety")
    radonc_score = next(item["score"] for item in ranked if item["module"] == "radonc_plan")

    if report_quality_score >= findings_score and report_quality_score >= queue_score and report_quality_score >= diagnosis_score and report_quality_score >= screening_score and report_quality_score >= neuro_score and report_quality_score >= safety_score and report_quality_score >= radonc_score and report_quality_score > 0:
        workflow = best["workflow"]
        return {
            "assistant": {
                "content": (
                    "I routed this request to Report Quality Review. The next step is to check for identifiers, risky abbreviations, "
                    "and missing core sections before sharing the draft."
                )
            },
            "workflow": workflow,
            "target_module": "report_quality",
            "target_view": "report_quality",
            "suggested_steps": workflow["tools"],
            "alternatives": alternatives,
            "confidence": min(0.55 + report_quality_score * 0.12, 0.9),
        }

    if screening_score >= findings_score and screening_score >= queue_score and screening_score >= diagnosis_score and screening_score >= neuro_score and screening_score >= safety_score and screening_score >= radonc_score and screening_score > 0:
        workflow = best["workflow"]
        return {
            "assistant": {
                "content": (
                    "I routed this request to Screening Gap Closure. The next step is to verify whether the screening follow-up "
                    "is still open, summarize the missing step, and prepare a review-first closure recommendation."
                )
            },
            "workflow": workflow,
            "target_module": "screening",
            "target_view": "screening",
            "suggested_steps": workflow["tools"],
            "alternatives": alternatives,
            "confidence": min(0.55 + screening_score * 0.12, 0.9),
        }

    if findings_score >= queue_score and findings_score >= diagnosis_score and findings_score >= neuro_score and findings_score >= safety_score and findings_score >= radonc_score and findings_score > 0:
        workflow = best["workflow"]
        return {
            "assistant": {
                "content": (
                    "I routed this request to Findings Closure. The next step is to inspect the incoming finding, "
                    "check whether follow-up is already closed, and prepare the safest next action for review."
                )
            },
            "workflow": workflow,
            "target_module": "findings",
            "target_view": "findings",
            "suggested_steps": workflow["tools"],
            "alternatives": alternatives,
            "confidence": min(0.55 + findings_score * 0.12, 0.9),
        }

    if queue_score >= diagnosis_score and queue_score >= screening_score and queue_score >= neuro_score and queue_score >= safety_score and queue_score >= radonc_score and queue_score > 0:
        workflow = best["workflow"]
        return {
            "assistant": {
                "content": (
                    "I routed this request to Queue Triage. The next step is to inspect the queue item, "
                    "score urgency, and prepare the safest queue move for review."
                )
            },
            "workflow": workflow,
            "target_module": "queue",
            "target_view": "queue",
            "suggested_steps": workflow["tools"],
            "alternatives": alternatives,
            "confidence": min(0.55 + queue_score * 0.12, 0.9),
        }

    if diagnosis_score >= screening_score and diagnosis_score >= neuro_score and diagnosis_score >= safety_score and diagnosis_score >= radonc_score and diagnosis_score > 0:
        workflow = best["workflow"]
        return {
            "assistant": {
                "content": (
                    "I routed this request to Missed Diagnosis Review. The next step is to inspect the signal, "
                    "check whether follow-up is already documented, and prepare a review-first workup recommendation."
                )
            },
            "workflow": workflow,
            "target_module": "diagnosis",
            "target_view": "diagnosis",
            "suggested_steps": workflow["tools"],
            "alternatives": alternatives,
            "confidence": min(0.55 + diagnosis_score * 0.12, 0.9),
        }

    longitudinal_neuro_tokens = {
        "metastasis",
        "metastases",
        "brain metast",
        "progression",
        "response",
        "tumor board",
        "post-radiotherapy",
        "post radiotherapy",
    }
    if neuro_score > 0 and any(token in lowered for token in longitudinal_neuro_tokens):
        workflow = next(item for item in WORKFLOWS if item["id"] == "neuro_report")
        return {
            "assistant": {
                "content": (
                    "I routed this request to the Neuro MRI Report Generator. The best next step is to "
                    "open the response-focused neuro workspace, inspect serial MRI burden change, and prepare a review-first physician brief inside the flagship family."
                )
            },
            "workflow": workflow,
            "target_module": "neuro_report",
            "target_view": "neuro-report",
            "suggested_steps": workflow["tools"],
            "alternatives": alternatives,
            "confidence": min(0.58 + neuro_score * 0.1, 0.92),
            "workflow_family": "neuro",
            "workflow_task_id": resolve_workflow_registry_id(
                runtime_workflow_id="neuro_report",
                workflow_family="neuro",
                primary_goal="response_review",
            ),
        }

    if neuro_score > safety_score and neuro_score > radonc_score and neuro_score > 0:
        workflow = best["workflow"]
        return {
            "assistant": {
                "content": (
                    "I routed this request to the Neuro MRI Report Generator. The best next step is to "
                    "open the MRI report workspace, choose a curated study or upload a scan, and review slices, volumetrics, and the structured report together."
                )
            },
            "workflow": workflow,
            "target_module": "neuro_report",
            "target_view": "neuro-report",
            "suggested_steps": workflow["tools"],
            "alternatives": alternatives,
            "confidence": min(0.55 + neuro_score * 0.12, 0.9),
            "workflow_family": "neuro",
            "workflow_task_id": resolve_workflow_registry_id(
                runtime_workflow_id="neuro_report",
                workflow_family="neuro",
                primary_goal="structural_report",
            ),
        }

    if radonc_score >= safety_score and radonc_score > 0:
        workflow = next(item for item in WORKFLOWS if item["id"] == "radonc_plan_optimization")
        return {
            "assistant": {
                "content": (
                    "I routed this request to RadOnc Plan Optimization. The next step is to open the DVH planning workspace, "
                    "evaluate the current goals and OAR trade-offs, and run the controlled optimization loop inside the radonc family shell."
                )
            },
            "workflow": workflow,
            "target_module": "radonc_plan",
            "target_view": "radonc-plan",
            "suggested_steps": workflow["tools"],
            "alternatives": alternatives,
            "confidence": min(0.58 + radonc_score * 0.1, 0.93),
            "workflow_family": "radonc",
            "primary_goal": "plan_optimization",
            "dashboard_profile": "plan_optimization",
            "workflow_task_id": resolve_workflow_registry_id(
                runtime_workflow_id="radonc_plan_optimization",
                workflow_family="radonc",
                primary_goal="plan_optimization",
            ),
        }

    if safety_score >= neuro_score and safety_score > 0:
        workflow = best["workflow"]
        return {
            "assistant": {
                "content": (
                    "I routed this request to the Radiation Safety Monitor. The next step is to parse the case "
                    "text, compare it against the local failure library, assign a watch/alert/urgent tier, and prepare mitigation guidance."
                )
            },
            "workflow": workflow,
            "target_module": "safety",
            "target_view": "safety",
            "suggested_steps": workflow["tools"],
            "alternatives": alternatives,
            "confidence": min(0.55 + safety_score * 0.12, 0.9),
        }

    workflow = next(item for item in WORKFLOWS if item["module"] == "home")
    return {
        "assistant": {
            "content": "No strong workflow match. Continue in general chat unless the user asks for a specific analysis workflow."
        },
        "workflow": workflow,
        "target_module": "home",
        "target_view": "home",
        "suggested_steps": workflow["tools"],
        "alternatives": alternatives,
        "confidence": 0.0,
    }
