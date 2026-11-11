from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clinagent.families.shared.reporting import ReportDocument, ReportMetric, ReportSection, build_report_document


@dataclass(frozen=True)
class ReportTemplate:
    template_id: str
    label: str
    audience: str
    sections: tuple[str, ...]
    starter_summary: str


@dataclass(frozen=True)
class Finding:
    code: str
    label: str
    severity: str
    count: int
    examples: tuple[str, ...] = ()
    recommendation: str = ""


@dataclass(frozen=True)
class RegulatoryCheck:
    code: str
    label: str
    passed: bool
    recommendation: str = ""


@dataclass(frozen=True)
class DeidentificationReport:
    status: str
    findings: tuple[Finding, ...]
    ages_over_89: tuple[int, ...]

    @property
    def total_findings(self) -> int:
        return sum(item.count for item in self.findings) + len(self.ages_over_89)


@dataclass(frozen=True)
class TerminologyReport:
    status: str
    do_not_use: tuple[Finding, ...]
    ambiguous: tuple[Finding, ...]
    icd10_codes: tuple[str, ...]

    @property
    def total_findings(self) -> int:
        return sum(item.count for item in self.do_not_use) + sum(item.count for item in self.ambiguous)


@dataclass(frozen=True)
class ComplianceReport:
    profile: str
    checks: tuple[RegulatoryCheck, ...]

    @property
    def missing(self) -> tuple[RegulatoryCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)


@dataclass(frozen=True)
class ReportQualityBundle:
    template_id: str | None
    deidentification: DeidentificationReport
    terminology: TerminologyReport
    compliance: ComplianceReport

    @property
    def status(self) -> str:
        if self.deidentification.status == "non_compliant":
            return "needs_redaction"
        if self.terminology.status == "needs_revision":
            return "needs_revision"
        if self.compliance.missing:
            return "needs_completion"
        return "ready_for_review"


TEMPLATES: dict[str, ReportTemplate] = {
    "radiology": ReportTemplate(
        template_id="radiology",
        label="Radiology Report",
        audience="Diagnostic imaging",
        sections=("Clinical Indication", "Technique", "Comparison", "Findings", "Impression"),
        starter_summary="Structured radiology report with concise findings and an actionable impression.",
    ),
    "consult_note": ReportTemplate(
        template_id="consult_note",
        label="Consult Note",
        audience="Clinical consultation",
        sections=("Reason for Consult", "History", "Exam", "Assessment", "Plan"),
        starter_summary="Focused consultant note emphasizing the assessment and next-step plan.",
    ),
    "case_report": ReportTemplate(
        template_id="case_report",
        label="Case Report",
        audience="Case publication",
        sections=(
            "Title",
            "Abstract",
            "Introduction",
            "Patient Information",
            "Timeline",
            "Diagnostic Assessment",
            "Intervention",
            "Outcome",
            "Discussion",
        ),
        starter_summary="CARE-style case report outline with patient timeline and diagnostic reasoning.",
    ),
}

_DEIDENTIFICATION_PATTERNS: dict[str, dict[str, Any]] = {
    "name_honorific": {
        "label": "Possible names",
        "severity": "high",
        "flags": 0,
        "patterns": (
            r"\b(?:Dr|Mr|Mrs|Ms)\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?",
            r"\b[A-Z][a-z]+,\s*[A-Z][a-z]+\b",
        ),
        "recommendation": "Replace names with role-based descriptions such as 'the patient' or 'the treating physician'.",
    },
    "date_full": {
        "label": "Full dates",
        "severity": "high",
        "patterns": (
            r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12][0-9]|3[01])/\d{4}\b",
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b",
            r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b",
        ),
        "recommendation": "Use year-only or relative timing such as 'three months later'.",
    },
    "phone": {
        "label": "Phone numbers",
        "severity": "high",
        "patterns": (r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",),
        "recommendation": "Remove direct contact details from clinician-facing exports.",
    },
    "email": {
        "label": "Email addresses",
        "severity": "high",
        "patterns": (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",),
        "recommendation": "Remove direct email identifiers.",
    },
    "mrn": {
        "label": "Medical record identifiers",
        "severity": "high",
        "patterns": (
            r"(?i)\b(?:mrn|medical record(?: number| #)?|patient id)[:#]?\s*[A-Z0-9-]+\b",
            r"\bDEMO-\d{3,}\b",
        ),
        "recommendation": "Replace with an internal demo subject label.",
    },
    "address": {
        "label": "Street addresses",
        "severity": "high",
        "flags": 0,
        "patterns": (r"\b\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr)\b",),
        "recommendation": "Remove geographic details below the state level.",
    },
    "url": {
        "label": "URLs",
        "severity": "medium",
        "patterns": (r"https?://[^\s]+", r"\bwww\.[^\s]+\b"),
        "recommendation": "Avoid linking to patient-specific portals or documents.",
    },
}

_DO_NOT_USE = {
    "U": "unit",
    "IU": "international unit",
    "QD": "daily",
    "QOD": "every other day",
    "MS": "spell out the drug name",
    "MSO4": "morphine sulfate",
    "MgSO4": "magnesium sulfate",
}

_AMBIGUOUS = {
    "cc": "use mL instead",
    "hs": "spell out the intended timing",
    "TIW": "spell out the weekly schedule",
    "SC": "spell out subcutaneous",
    "SQ": "spell out subcutaneous",
    "D/C": "write discontinue or discharge explicitly",
    "OD": "can mean once daily or right eye",
    "OS": "can mean left eye",
    "OU": "can mean both eyes",
}

_COMPLIANCE_PROFILES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "case_report": (
        ("patient_consent", "Documented publication consent", r"(?i)(written|informed)\s+consent.*obtained"),
        ("deidentification", "Explicit de-identification statement", r"(?i)(de-identif|anonymi[sz])"),
        ("timeline", "Includes a timeline or longitudinal interval statement", r"(?i)\btimeline\b|month[s]?\s+later|week[s]?\s+later"),
    ),
    "radiology": (
        ("clinical_indication", "States a clinical indication", r"(?i)\bclinical\s+indication\b|\bindication\b"),
        ("technique", "Documents technique", r"(?i)\btechnique\b"),
        ("comparison", "Documents comparison imaging", r"(?i)\bcomparison\b|compared with"),
        ("impression", "Provides an impression", r"(?i)\bimpression\b"),
    ),
    "consult_note": (
        ("assessment", "Includes an assessment", r"(?i)\bassessment\b"),
        ("plan", "Includes a plan", r"(?i)\bplan\b"),
        ("history", "Includes relevant history", r"(?i)\bhistory\b"),
    ),
}


def list_report_templates() -> list[ReportTemplate]:
    return list(TEMPLATES.values())


def generate_report_template(template_id: str) -> str:
    template = TEMPLATES.get(template_id)
    if not template:
        raise KeyError(f"Unknown template: {template_id}")
    lines = [
        f"# {template.label}",
        "",
        f"Audience: {template.audience}",
        "",
        template.starter_summary,
        "",
    ]
    for section in template.sections:
        lines.extend([f"## {section}", "", "[Fill in concise, clinically relevant content here.]", ""])
    return "\n".join(lines).strip() + "\n"


def scan_deidentification(text: str) -> DeidentificationReport:
    findings: list[Finding] = []
    for code, config in _DEIDENTIFICATION_PATTERNS.items():
        matches: list[str] = []
        flags = int(config.get("flags", re.IGNORECASE))
        for pattern in config["patterns"]:
            matches.extend(match.group(0) for match in re.finditer(pattern, text, flags))
        unique_examples = tuple(dict.fromkeys(match.strip() for match in matches if match.strip()).keys())[:3]
        if matches:
            findings.append(
                Finding(
                    code=code,
                    label=config["label"],
                    severity=config["severity"],
                    count=len(matches),
                    examples=unique_examples,
                    recommendation=config["recommendation"],
                )
            )

    ages = [int(value) for value in re.findall(r"\b(\d{2,3})\s*(?:year|yr)s?[-\s]?old\b", text, re.IGNORECASE)]
    over_89 = tuple(age for age in ages if age > 89)
    if over_89:
        findings.append(
            Finding(
                code="age_over_89",
                label="Age above 89",
                severity="medium",
                count=len(over_89),
                examples=tuple(str(age) for age in over_89[:3]),
                recommendation="Aggregate ages above 89 into '90 or older'.",
            )
        )

    critical_or_high = [item for item in findings if item.severity in {"critical", "high"}]
    if critical_or_high:
        status = "non_compliant"
    elif findings:
        status = "needs_review"
    else:
        status = "compliant"
    return DeidentificationReport(status=status, findings=tuple(findings), ages_over_89=over_89)


def validate_terminology(text: str) -> TerminologyReport:
    do_not_use: list[Finding] = []
    ambiguous: list[Finding] = []
    for abbrev, replacement in _DO_NOT_USE.items():
        if abbrev == "U":
            matches = re.findall(r"\b\d+\s*U\b|\bU\b", text)
        else:
            matches = re.findall(rf"\b{re.escape(abbrev)}\b", text)
        if matches:
            do_not_use.append(
                Finding(
                    code=f"dnu_{abbrev.lower()}",
                    label=abbrev,
                    severity="high",
                    count=len(matches),
                    recommendation=f"Replace '{abbrev}' with '{replacement}'.",
                )
            )
    for abbrev, recommendation in _AMBIGUOUS.items():
        matches = re.findall(rf"\b{re.escape(abbrev)}\b", text, re.IGNORECASE)
        if matches:
            ambiguous.append(
                Finding(
                    code=f"amb_{abbrev.lower()}",
                    label=abbrev,
                    severity="medium",
                    count=len(matches),
                    recommendation=recommendation,
                )
            )
    icd10_codes = tuple(sorted(set(re.findall(r"\b[A-Z]\d{2}\.?\d{0,4}\b", text))))
    status = "needs_revision" if do_not_use else ("review_for_clarity" if ambiguous else "clean")
    return TerminologyReport(
        status=status,
        do_not_use=tuple(do_not_use),
        ambiguous=tuple(ambiguous),
        icd10_codes=icd10_codes,
    )


def check_compliance(text: str, profile: str = "radiology") -> ComplianceReport:
    profile_checks = _COMPLIANCE_PROFILES.get(profile)
    if not profile_checks:
        raise KeyError(f"Unknown compliance profile: {profile}")
    checks = []
    for code, label, pattern in profile_checks:
        passed = bool(re.search(pattern, text))
        recommendation = "" if passed else f"Add a concise {label.lower()} section."
        checks.append(RegulatoryCheck(code=code, label=label, passed=passed, recommendation=recommendation))
    return ComplianceReport(profile=profile, checks=tuple(checks))


def evaluate_report_quality(text: str, *, template_id: str | None = None, compliance_profile: str = "radiology") -> ReportQualityBundle:
    return ReportQualityBundle(
        template_id=template_id,
        deidentification=scan_deidentification(text),
        terminology=validate_terminology(text),
        compliance=check_compliance(text, profile=compliance_profile),
    )


def build_quality_report_document(
    *,
    sample_name: str,
    text: str,
    bundle: ReportQualityBundle,
    template_preview: str | None = None,
) -> ReportDocument:
    deid = bundle.deidentification
    term = bundle.terminology
    compliance = bundle.compliance
    badge_map = {
        "ready_for_review": ("Ready for review", "good"),
        "needs_completion": ("Needs completion", "warn"),
        "needs_revision": ("Needs revision", "warn"),
        "needs_redaction": ("Needs redaction", "danger"),
    }
    badge_label, badge_tone = badge_map[bundle.status]

    sections: list[dict[str, Any]] = []
    if deid.findings:
        sections.append(
            {
                "title": "De-identification",
                "body": f"{len(deid.findings)} privacy issue types were detected.",
                "bullets": [
                    f"{item.label}: {item.count} hit(s). {item.recommendation}"
                    + (f" Example: {', '.join(item.examples)}" if item.examples else "")
                    for item in deid.findings[:4]
                ],
            }
        )
    else:
        sections.append({"title": "De-identification", "body": "No obvious HIPAA-style identifier patterns were detected."})

    terminology_bullets = [
        f"Avoid {item.label}: {item.recommendation}" for item in (*term.do_not_use[:3], *term.ambiguous[:2])
    ]
    sections.append(
        {
            "title": "Terminology",
            "body": (
                "Terminology looks clean." if not terminology_bullets
                else f"{term.total_findings} terminology issue(s) were flagged."
            ),
            "bullets": terminology_bullets,
        }
    )

    missing = compliance.missing
    sections.append(
        {
            "title": "Compliance",
            "body": (
                f"Profile '{compliance.profile}' is complete."
                if not missing
                else f"{len(missing)} required section(s) are missing for the '{compliance.profile}' profile."
            ),
            "bullets": [f"{item.label}: {item.recommendation}" for item in missing[:4]],
        }
    )

    if template_preview:
        preview_lines = [line.strip() for line in template_preview.splitlines() if line.strip()][:5]
        sections.append(
            {
                "title": "Template Preview",
                "body": "Starter structure generated from the absorbed report template library.",
                "bullets": preview_lines,
            }
        )

    payload = {
        "title": f"Clinical report quality review: {sample_name}",
        "subtitle": "Absorbed from clinical-reports into local ClinAgent validation tools.",
        "audience": "Clinical report QA",
        "summary": f"Quick validation of privacy, terminology, and completeness for a local demo report. Input length: {len(text.split())} words.",
        "highlight": f"Overall status: {badge_label}.",
        "badge_label": badge_label,
        "badge_tone": badge_tone,
        "metrics": [
            {"label": "Privacy issues", "value": str(deid.total_findings)},
            {"label": "Terminology issues", "value": str(term.total_findings)},
            {"label": "Missing compliance items", "value": str(len(missing))},
            {"label": "ICD-10 codes", "value": str(len(term.icd10_codes))},
        ],
        "sections": sections,
        "footer": "Use this QA summary before sharing clinician-facing reports or demo artifacts.",
        "metadata": {
            "status": bundle.status,
            "template_id": bundle.template_id,
            "compliance_profile": compliance.profile,
        },
    }
    return build_report_document(payload)


def load_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")
