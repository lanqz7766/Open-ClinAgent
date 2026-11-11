from __future__ import annotations

import re
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "with",
}

_TERM_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("hippocampal_atrophy", ("hippocamp", "atrophy")),
    ("atrophy", ("atrophy",)),
    ("hemorrhage", ("hemorrhage", "bleed")),
    ("ventricular_enlargement", ("ventric", "enlarg")),
    ("focal_lesion", ("lesion", "metast", "mass", "focus")),
    ("edema", ("edema", "oedema")),
    ("progression", ("progress", "regrowth", "increase", "enlarg")),
    ("stability", ("stable", "unchanged")),
    ("improvement", ("improv", "decrease", "reduc", "resolved")),
    ("comparison", ("prior", "compared", "interval", "follow-up")),
    ("uncertainty", ("uncertain", "indeterminate", "cannot exclude")),
]


def _slugify(value: str) -> str:
    lowered = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return lowered or "item"


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sentence_split(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [chunk.strip(" -\n\t") for chunk in chunks if chunk.strip(" -\n\t")]


def _extract_keywords(text: str) -> list[str]:
    lowered = text.lower()
    matched = [name for name, stems in _TERM_PATTERNS if any(stem in lowered for stem in stems)]
    if matched:
        return matched

    tokens = re.findall(r"[a-z0-9]+", lowered)
    return [token for token in tokens if token not in _STOPWORDS and len(token) > 3][:6]


def _keyword_matches_text(keyword: str, text: str) -> bool:
    normalized = keyword.replace("_", " ")
    if normalized in text or keyword in text:
        return True
    for name, stems in _TERM_PATTERNS:
        if name != keyword:
            continue
        return any(stem in text for stem in stems)
    return False


class ClaimCategory(str, Enum):
    finding = "finding"
    comparison = "comparison"
    uncertainty = "uncertainty"


class EvidenceSourceType(str, Enum):
    current_study = "current_study"
    prior_study = "prior_study"
    prior_report = "prior_report"
    structured_field = "structured_field"


class VerificationStatus(str, Enum):
    supported = "supported"
    conflicted = "conflicted"
    missing_evidence = "missing_evidence"


class WorkflowRunStatus(str, Enum):
    queued = "queued"
    running = "running"
    blocked = "blocked"
    ready_for_review = "ready_for_review"
    failed = "failed"
    needs_human_review = "needs_human_review"


class ComparisonChangeType(str, Enum):
    progression = "progression"
    stable_finding = "stable_finding"
    improvement = "improvement"
    uncertain_change = "uncertain_change"
    no_prior_available = "no_prior_available"


class StudyInput(BaseModel):
    study_id: str
    study_date: str | None = None
    modality: str = "MRI"
    sequence: str | None = None
    summary: str
    available_sequences: list[str] = Field(default_factory=list)
    structured_findings: dict[str, Any] = Field(default_factory=dict)


class Claim(BaseModel):
    id: str
    text: str
    sentence_index: int
    category: ClaimCategory
    normalized_label: str
    keywords: list[str] = Field(default_factory=list)
    requires_prior: bool = False


class EvidenceRef(BaseModel):
    id: str
    source_type: EvidenceSourceType
    label: str
    locator: str | None = None
    excerpt: str
    study_id: str | None = None
    study_date: str | None = None
    sequence: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    claim_id: str
    status: VerificationStatus
    summary: str
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    conflict_reason: str | None = None
    missing_requirements: list[str] = Field(default_factory=list)


class VerifiedClaim(BaseModel):
    claim: Claim
    verification: VerificationResult


class StopCondition(BaseModel):
    code: str
    reason: str
    what_is_missing: str
    radiologist_action: str


class ComparisonResult(BaseModel):
    status: ComparisonChangeType
    summary: str
    current_study_id: str
    prior_study_id: str | None = None
    delta_pct: float | None = None


class WorkflowStep(BaseModel):
    id: str
    title: str
    status: str
    detail: str


class WorkflowRun(BaseModel):
    id: str
    status: WorkflowRunStatus
    blocked_reason: str | None = None
    steps: list[WorkflowStep] = Field(default_factory=list)


class AgentGraphNode(BaseModel):
    id: str
    label: str
    kind: str
    responsibility: str


class AgentGraphEdge(BaseModel):
    source: str
    target: str


class AgentGraph(BaseModel):
    nodes: list[AgentGraphNode] = Field(default_factory=list)
    edges: list[AgentGraphEdge] = Field(default_factory=list)


class VerifyEvidenceBoardRequest(BaseModel):
    current_study: StudyInput
    draft_report: str
    prior_study: StudyInput | None = None
    prior_report: str | None = None
    require_comparison: bool = False
    required_sequences: list[str] = Field(default_factory=list)
    structured_fields: dict[str, Any] = Field(default_factory=dict)
    case_id: str | None = None


class EvidenceBoardResponse(BaseModel):
    case_id: str | None = None
    draft_report: str
    workflow_run: WorkflowRun
    claims: list[VerifiedClaim]
    stop_conditions: list[StopCondition] = Field(default_factory=list)
    comparison: ComparisonResult
    summary: dict[str, Any] = Field(default_factory=dict)
    agent_graph: AgentGraph


def extract_claims(draft_report: str) -> list[Claim]:
    sentences = _sentence_split(draft_report)
    claims: list[Claim] = []
    for index, sentence in enumerate(sentences, start=1):
        lowered = sentence.lower()
        if any(
            token in lowered
            for token in ("recommend", "question", "correlate clinically", "follow-up interval", "intended for physician review")
        ):
            continue
        category = ClaimCategory.finding
        requires_prior = False
        if any(token in lowered for token in ("stable", "unchanged", "prior", "interval", "compared", "increase", "decrease", "regrowth", "progress")):
            category = ClaimCategory.comparison
            requires_prior = True
        if any(token in lowered for token in ("uncertain", "indeterminate", "cannot exclude")):
            category = ClaimCategory.uncertainty
        keywords = _extract_keywords(sentence)
        normalized = keywords[0] if keywords else _slugify(" ".join(sentence.split()[:5]))
        claims.append(
            Claim(
                id=f"claim_{index:02d}",
                text=sentence,
                sentence_index=index,
                category=category,
                normalized_label=normalized,
                keywords=keywords,
                requires_prior=requires_prior,
            )
        )
    return claims


def _build_candidate_sources(request: VerifyEvidenceBoardRequest) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = [
        {
            "source_type": EvidenceSourceType.current_study,
            "label": "Current MRI",
            "excerpt": request.current_study.summary,
            "study_id": request.current_study.study_id,
            "study_date": request.current_study.study_date,
            "sequence": request.current_study.sequence,
            "locator": request.current_study.study_id,
            "metadata": request.current_study.structured_findings,
        }
    ]
    if request.prior_study is not None:
        candidates.append(
            {
                "source_type": EvidenceSourceType.prior_study,
                "label": "Prior MRI",
                "excerpt": request.prior_study.summary,
                "study_id": request.prior_study.study_id,
                "study_date": request.prior_study.study_date,
                "sequence": request.prior_study.sequence,
                "locator": request.prior_study.study_id,
                "metadata": request.prior_study.structured_findings,
            }
        )
    if request.prior_report:
        for index, sentence in enumerate(_sentence_split(request.prior_report), start=1):
            candidates.append(
                {
                    "source_type": EvidenceSourceType.prior_report,
                    "label": "Prior report",
                    "excerpt": sentence,
                    "study_id": request.prior_study.study_id if request.prior_study else None,
                    "study_date": request.prior_study.study_date if request.prior_study else None,
                    "sequence": request.prior_study.sequence if request.prior_study else None,
                    "locator": f"prior_report_sentence_{index}",
                    "metadata": {},
                }
            )
    for key, value in sorted(request.structured_fields.items()):
        candidates.append(
            {
                "source_type": EvidenceSourceType.structured_field,
                "label": key.replace("_", " ").title(),
                "excerpt": f"{key}: {value}",
                "study_id": None,
                "study_date": None,
                "sequence": None,
                "locator": key,
                "metadata": {"key": key, "value": value},
            }
        )
    return candidates


def _candidate_matches(claim: Claim, candidate: dict[str, Any]) -> bool:
    excerpt = str(candidate.get("excerpt") or "").lower()
    if claim.category == ClaimCategory.comparison and candidate["source_type"] in {
        EvidenceSourceType.current_study,
        EvidenceSourceType.prior_study,
        EvidenceSourceType.prior_report,
    }:
        return True
    return any(_keyword_matches_text(keyword, excerpt) for keyword in claim.keywords)


def _link_evidence(claim: Claim, request: VerifyEvidenceBoardRequest) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    for candidate in _build_candidate_sources(request):
        if not _candidate_matches(claim, candidate):
            continue
        refs.append(
            EvidenceRef(
                id=f"evidence_{uuid4().hex[:10]}",
                source_type=candidate["source_type"],
                label=candidate["label"],
                locator=candidate["locator"],
                excerpt=candidate["excerpt"],
                study_id=candidate["study_id"],
                study_date=candidate["study_date"],
                sequence=candidate["sequence"],
                metadata=candidate["metadata"],
            )
        )
    return refs


def _comparison_result(request: VerifyEvidenceBoardRequest) -> ComparisonResult:
    current_volume = _safe_float(
        request.current_study.structured_findings.get("lesion_volume_ml")
        or request.structured_fields.get("current_volume_ml")
    )
    prior_volume = _safe_float(
        (request.prior_study.structured_findings.get("lesion_volume_ml") if request.prior_study else None)
        or request.structured_fields.get("prior_volume_ml")
    )
    if request.prior_study is None or prior_volume is None or current_volume is None or prior_volume == 0:
        return ComparisonResult(
            status=ComparisonChangeType.no_prior_available,
            summary="No prior MRI volume was available for longitudinal comparison.",
            current_study_id=request.current_study.study_id,
            prior_study_id=request.prior_study.study_id if request.prior_study else None,
        )
    delta_pct = round(((current_volume - prior_volume) / prior_volume) * 100.0, 1)
    if delta_pct > 10:
        status = ComparisonChangeType.progression
        summary = f"Current lesion burden is {delta_pct:+.1f}% above the prior MRI."
    elif delta_pct < -10:
        status = ComparisonChangeType.improvement
        summary = f"Current lesion burden is {delta_pct:+.1f}% below the prior MRI."
    else:
        status = ComparisonChangeType.stable_finding
        summary = f"Current lesion burden is {delta_pct:+.1f}% from the prior MRI and sits in a stable range."
    return ComparisonResult(
        status=status,
        summary=summary,
        current_study_id=request.current_study.study_id,
        prior_study_id=request.prior_study.study_id if request.prior_study else None,
        delta_pct=delta_pct,
    )


def _expected_direction(claim: Claim) -> str | None:
    lowered = claim.text.lower()
    if any(token in lowered for token in ("stable", "unchanged", "no significant change")):
        return "stable"
    if any(token in lowered for token in ("progress", "regrowth", "increase", "enlarg")):
        return "progression"
    if any(token in lowered for token in ("improv", "decrease", "reduc", "resolved")):
        return "improvement"
    return None


def _conflict_reason(claim: Claim, comparison: ComparisonResult) -> str | None:
    expected = _expected_direction(claim)
    if expected is None:
        return None
    if comparison.status == ComparisonChangeType.no_prior_available:
        return None
    if expected == "stable" and comparison.status != ComparisonChangeType.stable_finding:
        return f"Claim says stable, but structured comparison resolved to {comparison.status.value}."
    if expected == "progression" and comparison.status != ComparisonChangeType.progression:
        return f"Claim says worsening, but structured comparison resolved to {comparison.status.value}."
    if expected == "improvement" and comparison.status != ComparisonChangeType.improvement:
        return f"Claim says improvement, but structured comparison resolved to {comparison.status.value}."
    return None


def _verify_claim(claim: Claim, request: VerifyEvidenceBoardRequest, comparison: ComparisonResult) -> VerificationResult:
    evidence_refs = _link_evidence(claim, request)
    missing_requirements: list[str] = []
    if claim.requires_prior and not (request.prior_study or request.prior_report):
        missing_requirements.append("Prior study/report required for this comparison claim.")
    if claim.requires_prior and not any(
        ref.source_type in {EvidenceSourceType.prior_study, EvidenceSourceType.prior_report} for ref in evidence_refs
    ):
        missing_requirements.append("No prior evidence link was found for the comparison claim.")
    conflict_reason = _conflict_reason(claim, comparison)
    if conflict_reason:
        return VerificationResult(
            claim_id=claim.id,
            status=VerificationStatus.conflicted,
            summary="Verifier found a conflict between the draft claim and the longitudinal comparison signal.",
            evidence_refs=evidence_refs,
            conflict_reason=conflict_reason,
            missing_requirements=missing_requirements,
        )
    if not evidence_refs or missing_requirements:
        return VerificationResult(
            claim_id=claim.id,
            status=VerificationStatus.missing_evidence,
            summary="Verifier could not assemble enough direct evidence for this claim.",
            evidence_refs=evidence_refs,
            missing_requirements=missing_requirements,
        )
    return VerificationResult(
        claim_id=claim.id,
        status=VerificationStatus.supported,
        summary="Claim is linked to current/prior evidence and passed the first-pass verifier.",
        evidence_refs=evidence_refs,
    )


def _stop_conditions(
    request: VerifyEvidenceBoardRequest,
    verified_claims: list[VerifiedClaim],
    comparison: ComparisonResult,
) -> list[StopCondition]:
    items: list[StopCondition] = []
    missing_sequences = [
        sequence
        for sequence in request.required_sequences
        if sequence not in set(request.current_study.available_sequences)
    ]
    if request.require_comparison and comparison.status == ComparisonChangeType.no_prior_available:
        items.append(
            StopCondition(
                code="no_prior_available",
                reason="Longitudinal comparison was required, but no prior MRI was available.",
                what_is_missing="Prior MRI and/or prior report context.",
                radiologist_action="Review the current MRI as a non-comparative read or retrieve priors before signing.",
            )
        )
    if missing_sequences:
        items.append(
            StopCondition(
                code="missing_required_sequence",
                reason="The current exam is missing one or more required sequences for this workflow.",
                what_is_missing=", ".join(missing_sequences),
                radiologist_action="Confirm whether the sequence is unavailable, mislabeled, or needs reacquisition.",
            )
        )
    if any(item.verification.status == VerificationStatus.missing_evidence for item in verified_claims):
        items.append(
            StopCondition(
                code="claim_missing_evidence",
                reason="At least one draft claim does not have enough direct evidence support.",
                what_is_missing="Linked imaging, prior-report, or structured evidence for every key claim.",
                radiologist_action="Edit or remove unsupported claims before finalizing the report.",
            )
        )
    if any(item.verification.status == VerificationStatus.conflicted for item in verified_claims):
        items.append(
            StopCondition(
                code="claim_conflict",
                reason="The verifier found a conflict between the draft narrative and the comparison signal.",
                what_is_missing="A reconciled interpretation across the draft, the current MRI, and the prior comparison.",
                radiologist_action="Resolve the discrepant claim before signing the report.",
            )
        )
    return items


def _workflow_run(stop_conditions: list[StopCondition], request: VerifyEvidenceBoardRequest) -> WorkflowRun:
    blocked_reason = stop_conditions[0].reason if stop_conditions else None
    status = WorkflowRunStatus.needs_human_review if stop_conditions else WorkflowRunStatus.ready_for_review
    prior_status = "completed" if request.prior_study or request.prior_report else "blocked" if request.require_comparison else "completed"
    verifier_status = "blocked" if stop_conditions else "completed"
    return WorkflowRun(
        id=f"run_{uuid4().hex[:10]}",
        status=status,
        blocked_reason=blocked_reason,
        steps=[
            WorkflowStep(id="study_ingest", title="Study intake", status="completed", detail="Current MRI payload loaded."),
            WorkflowStep(
                id="prior_retrieval",
                title="Prior retrieval",
                status=prior_status,
                detail="Collected the prior MRI summary and prior report when available.",
            ),
            WorkflowStep(
                id="claim_extraction",
                title="Claim extraction",
                status="completed",
                detail="Draft report was split into atomic claims for verification.",
            ),
            WorkflowStep(
                id="evidence_linking",
                title="Evidence linking",
                status="completed",
                detail="Each claim was linked to current MRI, prior MRI, prior report, and structured fields when relevant.",
            ),
            WorkflowStep(
                id="verifier_agent",
                title="Verifier agent",
                status=verifier_status,
                detail="Verifier assigned supported, conflicted, or missing evidence to every claim.",
            ),
            WorkflowStep(
                id="radiologist_review",
                title="Radiologist review",
                status="ready" if stop_conditions else "queued",
                detail="Case is ready for human review with claim-level traceability.",
            ),
        ],
    )


def default_agent_graph() -> AgentGraph:
    return AgentGraph(
        nodes=[
            AgentGraphNode(id="study_ingest", label="study_ingest", kind="system", responsibility="Register current study and required workflow context."),
            AgentGraphNode(id="prior_retrieval", label="prior_retrieval", kind="agent", responsibility="Retrieve prior MRI and prior report inputs."),
            AgentGraphNode(id="comparison_agent", label="comparison_agent", kind="agent", responsibility="Resolve longitudinal change before drafting."),
            AgentGraphNode(id="claim_extractor", label="claim_extractor", kind="agent", responsibility="Split the draft into atomic claims."),
            AgentGraphNode(id="evidence_linker", label="evidence_linker", kind="agent", responsibility="Attach current/prior evidence to each claim."),
            AgentGraphNode(id="verifier_agent", label="verifier_agent", kind="agent", responsibility="Assign supported, conflicted, or missing evidence."),
            AgentGraphNode(id="report_drafter", label="report_drafter", kind="agent", responsibility="Compose the final narrative only after verification."),
            AgentGraphNode(id="radiologist_review", label="radiologist_review", kind="human", responsibility="Review blocked claims and sign the report."),
        ],
        edges=[
            AgentGraphEdge(source="study_ingest", target="prior_retrieval"),
            AgentGraphEdge(source="prior_retrieval", target="comparison_agent"),
            AgentGraphEdge(source="comparison_agent", target="claim_extractor"),
            AgentGraphEdge(source="claim_extractor", target="evidence_linker"),
            AgentGraphEdge(source="evidence_linker", target="verifier_agent"),
            AgentGraphEdge(source="verifier_agent", target="report_drafter"),
            AgentGraphEdge(source="report_drafter", target="radiologist_review"),
        ],
    )


def verify_evidence_board(request: VerifyEvidenceBoardRequest) -> EvidenceBoardResponse:
    comparison = _comparison_result(request)
    claims = extract_claims(request.draft_report)
    verified_claims = [
        VerifiedClaim(claim=claim, verification=_verify_claim(claim, request, comparison))
        for claim in claims
    ]
    stop_conditions = _stop_conditions(request, verified_claims, comparison)
    workflow_run = _workflow_run(stop_conditions, request)
    status_counts = {
        status.value: sum(1 for item in verified_claims if item.verification.status == status)
        for status in VerificationStatus
    }
    return EvidenceBoardResponse(
        case_id=request.case_id,
        draft_report=request.draft_report,
        workflow_run=workflow_run,
        claims=verified_claims,
        stop_conditions=stop_conditions,
        comparison=comparison,
        summary={
            "claim_count": len(verified_claims),
            "status_counts": status_counts,
            "needs_human_review": bool(stop_conditions),
        },
        agent_graph=default_agent_graph(),
    )


def build_demo_evidence_request(workspace: dict[str, Any]) -> VerifyEvidenceBoardRequest:
    timeline = workspace.get("timeline") or []
    current_point = timeline[-1] if timeline else {}
    prior_point = timeline[-2] if len(timeline) > 1 else None
    analysis = workspace.get("analysis") or {}
    report = workspace.get("report") or {}
    sections = report.get("sections") or []
    current_volume = _safe_float(
        current_point.get("lesion_volume_ml")
        or analysis.get("latest_total_ml")
        or analysis.get("latest_volume_ml")
    )
    prior_volume = _safe_float(prior_point.get("lesion_volume_ml") if prior_point else analysis.get("previous_total_ml"))
    baseline_volume = _safe_float(
        timeline[0].get("lesion_volume_ml") if timeline else analysis.get("baseline_total_ml")
    )
    current_summary = (
        f"Current {current_point.get('sequence', 'MRI')} study dated {current_point.get('study_date', 'unknown date')} "
        f"shows lesion burden {current_volume:.2f} mL"
        if current_volume is not None
        else "Current MRI study summary is available."
    )
    if current_volume is not None and prior_volume is not None and prior_volume != 0:
        current_summary += f", compared with {prior_volume:.2f} mL on the prior MRI."
    if analysis.get("risk_level"):
        current_summary += f" Current workflow risk is {analysis.get('risk_level')}."

    prior_report = None
    if prior_point is not None and prior_volume is not None:
        prior_report = (
            f"Prior MRI from {prior_point.get('study_date', 'unknown date')} described lesion burden {prior_volume:.2f} mL "
            f"at {prior_point.get('timepoint', 'prior follow-up')}."
        )

    draft_sentences = [report.get("summary", "")]
    draft_sentences.extend(section.get("body", "") for section in sections[:3])
    draft_sentences.append("No acute hemorrhage identified on the available review.")
    draft_report = " ".join(sentence.strip() for sentence in draft_sentences if sentence and sentence.strip())

    available_sequences = []
    if current_point.get("sequence"):
        available_sequences.append(str(current_point["sequence"]))
    for sequence in workspace.get("imaging_preview", {}).get("secondary_modalities", []):
        available_sequences.append(str(sequence))

    return VerifyEvidenceBoardRequest(
        case_id=workspace.get("id"),
        current_study=StudyInput(
            study_id=str(current_point.get("study_id") or f"{workspace.get('id', 'case')}-current"),
            study_date=current_point.get("study_date"),
            sequence=current_point.get("sequence"),
            summary=current_summary,
            available_sequences=sorted({item for item in available_sequences if item}),
            structured_findings={
                "lesion_volume_ml": current_volume,
                "risk_level": analysis.get("risk_level"),
                "recent_change_pct": analysis.get("recent_segment_pct", analysis.get("recent_interval_change_pct")),
            },
        ),
        prior_study=(
            StudyInput(
                study_id=str(prior_point.get("study_id") or f"{workspace.get('id', 'case')}-prior"),
                study_date=prior_point.get("study_date"),
                sequence=prior_point.get("sequence"),
                summary=(
                    f"Prior {prior_point.get('sequence', 'MRI')} study dated {prior_point.get('study_date', 'unknown date')} "
                    f"showed lesion burden {prior_volume:.2f} mL."
                    if prior_volume is not None
                    else "Prior MRI summary is available."
                ),
                available_sequences=[str(prior_point.get("sequence"))] if prior_point.get("sequence") else [],
                structured_findings={
                    "lesion_volume_ml": prior_volume,
                    "timepoint": prior_point.get("timepoint"),
                },
            )
            if prior_point is not None
            else None
        ),
        prior_report=prior_report,
        draft_report=draft_report,
        require_comparison=True,
        required_sequences=["T1C"],
        structured_fields={
            "current_volume_ml": current_volume,
            "prior_volume_ml": prior_volume,
            "baseline_volume_ml": baseline_volume,
            "risk_level": analysis.get("risk_level"),
            "risk_reason": analysis.get("risk_reason"),
        },
    )


def build_demo_evidence_board(workspace: dict[str, Any]) -> dict[str, Any]:
    return verify_evidence_board(build_demo_evidence_request(workspace)).model_dump()
