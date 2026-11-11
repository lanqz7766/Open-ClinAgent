from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from clinagent.bundled_resources import bundled_dir, source_tree_dir
from clinagent.platform.harness import build_workspace_contract
from clinagent.platform.execution_profiles import build_workflow_runtime_bundle
from clinagent.platform.memory_harness import (
    build_reviewed_memory_context,
    derive_reviewed_memory_defaults,
    save_entity_memory,
    save_reviewed_pattern_memory,
    save_user_memory,
    save_workflow_memory,
)
from clinagent.platform.mcp_registry import build_context_availability_summary
from clinagent.families.shared.report_quality import (
    build_quality_report_document,
    evaluate_report_quality,
    generate_report_template,
    load_text,
)
from clinagent.families.shared.report_quality_intake import (
    build_report_quality_analysis_plan,
    build_report_quality_capability_profile,
    build_report_quality_planning_result,
    normalize_report_quality_context,
)
from clinagent.families.shared.reporting import render_report_html


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sample_root() -> Path:
    relative_path = Path("examples") / "report_quality_samples"
    cwd_candidate = Path.cwd() / relative_path
    if cwd_candidate.exists():
        return cwd_candidate

    source_samples = source_tree_dir(str(relative_path))
    if source_samples is not None:
        return source_samples

    bundled_samples = bundled_dir(str(relative_path))
    if bundled_samples is not None:
        return bundled_samples

    return relative_path


REPORT_QUALITY_CASES = (
    {
        "id": "report_quality_privacy_radiology",
        "title": "Radiology report with direct identifiers",
        "sample_name": "privacy_flags_radiology",
        "template_id": "radiology",
        "compliance_profile": "radiology",
        "sample_file": "privacy_flags_radiology.md",
        "workflow_title": "Report QA",
        "focus": "De-identification guard",
        "summary": "Shows how the absorbed privacy checker flags names, MRN, dates, contact information, and address-level identifiers.",
    },
    {
        "id": "report_quality_terminology_followup",
        "title": "Follow-up note with terminology drift",
        "sample_name": "terminology_flags_followup",
        "template_id": "radiology",
        "compliance_profile": "radiology",
        "sample_file": "terminology_flags_followup.md",
        "workflow_title": "Report QA",
        "focus": "Terminology and clarity",
        "summary": "Highlights dangerous abbreviations, ambiguous shorthand, and a missing comparison section in a follow-up note.",
    },
    {
        "id": "report_quality_clean_neuro",
        "title": "Clean neuro follow-up report",
        "sample_name": "clean_neuro_followup",
        "template_id": "radiology",
        "compliance_profile": "radiology",
        "sample_file": "clean_neuro_followup.md",
        "workflow_title": "Report QA",
        "focus": "Ready-for-review radiology brief",
        "summary": "Demonstrates the desired end-state: compact structure, no obvious identifiers, and all required radiology sections present.",
    },
)


class ReportQualityDemoStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._template_preview = generate_report_template("radiology")
        self._cases = self._build_cases()

    def _score(self, status: str) -> int:
        return {
            "needs_redaction": 24,
            "needs_revision": 57,
            "needs_completion": 66,
            "ready_for_review": 92,
        }.get(status, 60)

    def _status_chip(self, status: str) -> dict[str, str]:
        mapping = {
            "needs_redaction": {"label": "Needs redaction", "tone": "danger"},
            "needs_revision": {"label": "Needs revision", "tone": "warn"},
            "needs_completion": {"label": "Needs completion", "tone": "warn"},
            "ready_for_review": {"label": "Ready for review", "tone": "good"},
        }
        return mapping.get(status, {"label": "In review", "tone": "neutral"})

    def _build_case(self, seed: dict[str, Any]) -> dict[str, Any]:
        text = load_text(_sample_root() / seed["sample_file"])
        quality = evaluate_report_quality(
            text,
            template_id=seed["template_id"],
            compliance_profile=seed["compliance_profile"],
        )
        document = build_quality_report_document(
            sample_name=seed["sample_name"],
            text=text,
            bundle=quality,
            template_preview=self._template_preview,
        )
        report_html = render_report_html(document)
        chip = self._status_chip(quality.status)
        deid = quality.deidentification
        terminology = quality.terminology
        compliance = quality.compliance
        missing = compliance.missing
        context = normalize_report_quality_context(
            request_text=seed["summary"],
            source_kind="curated_case",
            case_id=seed["id"],
            report_text=text,
            template_id=seed["template_id"],
            compliance_profile=seed["compliance_profile"],
        )
        capability_profile = build_report_quality_capability_profile(context)
        analysis_plan = build_report_quality_analysis_plan(context, capability_profile)
        planning_result = build_report_quality_planning_result(context, capability_profile, analysis_plan)
        memory_context = build_reviewed_memory_context(
            workflow_family=analysis_plan.workflow_family,
            reviewed_pattern_ids=["report_quality_default_bundle"],
            entity_keys=[("report_quality_case", seed["id"])],
            workflow_keys=[("report_quality_review", "default_snapshot")],
            user_id="default_demo_user",
        )
        planner_defaults = derive_reviewed_memory_defaults(memory_context)
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
        workspace_contract = build_workspace_contract(
            workflow_id="report_quality_review",
            workflow_family=analysis_plan.workflow_family,
            analysis_track=analysis_plan.analysis_track,
            dashboard_profile=analysis_plan.dashboard_profile,
            workspace_url=f"/demo/functions/report-quality?case_id={seed['id']}",
            module="report_quality",
            runtime_mode=analysis_plan.runtime_mode,
            viewer_type="workspace",
            can_autorun=planning_result.autorun,
            planning_result=planning_result,
            task_traces=runtime_bundle["task_summary"],
            tool_policy=runtime_bundle["tool_policy"],
            context_availability=build_context_availability_summary(
                workflow_id="report_quality_review",
                workflow_family=analysis_plan.workflow_family,
            ),
            memory_context=memory_context,
            planner_defaults=planner_defaults,
        )
        return {
            **seed,
            "status": quality.status,
            "status_label": chip["label"],
            "status_tone": chip["tone"],
            "score": self._score(quality.status),
            "input_text": text,
            "report_html": report_html,
            "document": document.model_dump(),
            "summary_cards": [
                {"label": "Privacy issues", "value": str(deid.total_findings), "tone": chip["tone"]},
                {"label": "Terminology", "value": str(terminology.total_findings), "tone": "neutral"},
                {"label": "Missing sections", "value": str(len(missing)), "tone": "neutral"},
                {"label": "Template", "value": seed["template_id"].replace("_", " ").title(), "tone": "neutral"},
            ],
            "findings_groups": [
                {
                    "title": "Privacy",
                    "empty": "No obvious HIPAA-style identifiers were detected.",
                    "items": [
                        {
                            "label": item.label,
                            "severity": item.severity,
                            "detail": item.recommendation,
                            "examples": list(item.examples),
                            "count": item.count,
                        }
                        for item in deid.findings
                    ],
                },
                {
                    "title": "Terminology",
                    "empty": "No high-risk abbreviations or ambiguous shorthand were detected.",
                    "items": [
                        {
                            "label": item.label,
                            "severity": item.severity,
                            "detail": item.recommendation,
                            "examples": list(item.examples),
                            "count": item.count,
                        }
                        for item in (*terminology.do_not_use, *terminology.ambiguous)
                    ],
                },
                {
                    "title": "Compliance",
                    "empty": "All required sections for the selected profile are present.",
                    "items": [
                        {
                            "label": item.label,
                            "severity": "warn",
                            "detail": item.recommendation,
                            "examples": [],
                            "count": 1,
                        }
                        for item in missing
                    ],
                },
            ],
            "timeline": [
                {
                    "title": "Template loaded",
                    "detail": f"Using the absorbed {seed['template_id']} template registry.",
                    "created_at": _now_iso(),
                },
                {
                    "title": "Validation completed",
                    "detail": f"Privacy, terminology, and compliance checks produced status '{chip['label']}'.",
                    "created_at": _now_iso(),
                },
                {
                    "title": "Clinician-facing report rendered",
                    "detail": "The output below is the formatted report surface built with the local ClinAgent report renderer.",
                    "created_at": _now_iso(),
                },
            ],
            "intake_context": context.to_dict(),
            "capability_profile": capability_profile.to_dict(),
            "capability_profile_summary": planning_result.capability_profile_summary.to_dict(),
            "analysis_plan": analysis_plan.to_dict(),
            "analysis_plan_summary": planning_result.analysis_plan_summary.to_dict(),
            "planning_result": planning_result.to_dict(),
            "workspace_contract": workspace_contract.to_dict(),
        }

    def _build_cases(self) -> dict[str, dict[str, Any]]:
        cases = {seed["id"]: self._build_case(seed) for seed in REPORT_QUALITY_CASES}
        for case_id, case in cases.items():
            save_entity_memory("report_quality_case", case_id, case)
        save_user_memory(
            "default_demo_user",
            {
                "preferred_workflow_family": "neuro",
                "preferred_dashboard_profile": "report_review",
                "autorun_examples": True,
                "output_style": "compact_clinical",
            },
        )
        save_workflow_memory(
            "report_quality_review",
            "default_snapshot",
            {
                "default_case_id": REPORT_QUALITY_CASES[0]["id"],
                "case_ids": [item["id"] for item in REPORT_QUALITY_CASES],
            },
        )
        save_reviewed_pattern_memory(
            "review",
            "report_quality_default_bundle",
            {
                "tool_bundle": [
                    "report_template_registry",
                    "report_policy_checker",
                    "clinical_language_checker",
                ],
                "review_focus": ["privacy", "terminology", "completeness"],
                "dashboard_profile": "report_review",
            },
        )
        return cases

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            default_case_id = REPORT_QUALITY_CASES[0]["id"]
            case = deepcopy(self._cases[default_case_id])
            return {
                "title": "Clinical Report Quality Demo",
                "tagline": "Absorbed template, privacy, compliance, and terminology checks from clinical-reports into local ClinAgent report QA tools.",
                "default_case_id": default_case_id,
                "cases": [
                    {
                        "id": item["id"],
                        "title": item["title"],
                        "status_label": item["status_label"],
                        "status_tone": item["status_tone"],
                        "focus": item["focus"],
                    }
                    for item in self._cases.values()
                ],
                "workspace": case,
            }

    def get_case(self, case_id: str) -> dict[str, Any]:
        with self._lock:
            case = self._cases.get(case_id)
            if not case:
                raise KeyError(case_id)
            return deepcopy(case)


report_quality_demo_store = ReportQualityDemoStore()
