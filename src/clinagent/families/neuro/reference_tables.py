"""Utilities for maintaining research-use volumetric reference tables."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

REQUIRED_MASTER_FIELDS = (
    "roi_name",
    "roi_mapping_scope",
    "sex",
    "age_start",
    "age_end",
    "mean_mm3",
    "std_mm3",
    "n",
    "source_type",
    "source_citation",
    "source_url",
    "segmentation_protocol",
    "label_definition_match",
    "icv_adjustment",
    "scanner_scope",
    "field_strength",
    "population_notes",
    "evidence_tier",
    "fit_for_runtime",
    "review_status",
    "last_reviewed_on",
    "reviewer",
)

TIER_RANK = {"Tier A": 0, "Tier B": 1, "Tier C": 2}
SOURCE_TYPE_RANK = {"cohort": 0, "literature": 1, "derived": 2, "vendor_db": 3}
LABEL_MATCH_RANK = {"exact": 0, "approximate": 1, "group-only": 2, "mismatch": 3}

RUNTIME_NOTE = (
    "Research-use reference table generated from reviewed master records. "
    "Published entries are intended for comparative volumetry only and are not a clinical normative database."
)

NORMALIZATION_LIMITS = [
    "ROI volumetry does not require spatial normalization to template space when the segmentation pipeline is consistent.",
    "Age, sex, and intracranial-volume effects are incompletely modeled in literature-derived references unless explicitly noted.",
    "Cross-scanner and cross-site shifts can alter measured volumes; use cohort-specific harmonization before clinical deployment.",
]


@dataclass(frozen=True)
class MasterRecord:
    roi_name: str
    roi_mapping_scope: str
    sex: str
    age_start: int
    age_end: int
    mean_mm3: float
    std_mm3: float
    n: int
    source_type: str
    source_citation: str
    source_url: str
    segmentation_protocol: str
    label_definition_match: str
    icv_adjustment: str
    scanner_scope: str
    field_strength: str
    population_notes: str
    evidence_tier: str
    fit_for_runtime: bool
    review_status: str
    last_reviewed_on: str
    reviewer: str
    direction: str

    @property
    def age_bucket(self) -> str:
        return f"{self.age_start}-{self.age_end}"


def load_master_records(csv_path: str | Path) -> list[MasterRecord]:
    path = Path(csv_path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [field for field in REQUIRED_MASTER_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"Master reference table is missing required columns: {', '.join(missing)}")
        return [_record_from_row(row) for row in reader]


def build_runtime_reference_table(
    records: list[MasterRecord],
    *,
    generated_from: str,
    alignment_source: str,
) -> dict[str, Any]:
    published: dict[str, Any] = {
        "_meta": {
            "note": RUNTIME_NOTE,
            "source_alignment": alignment_source,
            "units": "mm3",
            "generated_from": generated_from,
            "generated_on": date.today().isoformat(),
            "selection_criteria": {
                "minimum_evidence_tier": "Tier A",
                "required_review_status": "approved",
                "minimum_sample_size": 100,
                "allowed_label_definition_match": ["exact", "approximate", "group-only"],
                "excluded_source_types": ["vendor_db"],
            },
            "normalization_limits": NORMALIZATION_LIMITS,
            "candidate_record_count": len(records),
            "published_record_count": 0,
            "published_region_count": 0,
        }
    }
    grouped: dict[tuple[str, str, str], list[MasterRecord]] = {}
    for record in records:
        grouped.setdefault((record.roi_name, record.sex, record.age_bucket), []).append(record)

    for (roi_name, sex, age_bucket), candidates in grouped.items():
        eligible = [candidate for candidate in candidates if _eligible_for_runtime(candidate)]
        if not eligible:
            continue
        selected = sorted(eligible, key=_runtime_sort_key)[0]
        roi_entry = published.setdefault(
            roi_name,
            {
                "_direction": selected.direction,
                "_note": (
                    "Research-use comparative reference. "
                    "Do not treat as a validated clinical normative database without cohort-specific verification."
                ),
                "_source_summary": selected.source_citation,
                "_evidence_tier": selected.evidence_tier,
                "_normalization_limits": NORMALIZATION_LIMITS,
            },
        )
        roi_entry.setdefault(sex, {})[age_bucket] = {
            "mean": selected.mean_mm3,
            "std": selected.std_mm3,
            "n": selected.n,
            "source_type": selected.source_type,
            "source_citation": selected.source_citation,
            "source_url": selected.source_url,
            "segmentation_protocol": selected.segmentation_protocol,
            "label_definition_match": selected.label_definition_match,
            "icv_adjustment": selected.icv_adjustment,
            "scanner_scope": selected.scanner_scope,
            "field_strength": selected.field_strength,
            "population_notes": selected.population_notes,
            "evidence_tier": selected.evidence_tier,
            "last_reviewed_on": selected.last_reviewed_on,
            "reviewer": selected.reviewer,
        }

    published_regions = [key for key in published if not key.startswith("_")]
    published["_meta"]["published_record_count"] = sum(
        len(roi_data[sex])
        for roi_name, roi_data in published.items()
        if not roi_name.startswith("_")
        for sex in ("M", "F")
        if sex in roi_data
    )
    published["_meta"]["published_region_count"] = len(published_regions)
    return published


def write_runtime_reference_table(
    records: list[MasterRecord],
    *,
    generated_from: str,
    alignment_source: str,
    destination: str | Path,
) -> dict[str, Any]:
    payload = build_runtime_reference_table(
        records,
        generated_from=generated_from,
        alignment_source=alignment_source,
    )
    Path(destination).write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return payload


def _record_from_row(row: dict[str, str]) -> MasterRecord:
    return MasterRecord(
        roi_name=row["roi_name"].strip(),
        roi_mapping_scope=row["roi_mapping_scope"].strip(),
        sex=row["sex"].strip().upper(),
        age_start=int(row["age_start"]),
        age_end=int(row["age_end"]),
        mean_mm3=float(row["mean_mm3"]),
        std_mm3=float(row["std_mm3"]),
        n=int(row["n"]),
        source_type=row["source_type"].strip(),
        source_citation=row["source_citation"].strip(),
        source_url=row["source_url"].strip(),
        segmentation_protocol=row["segmentation_protocol"].strip(),
        label_definition_match=row["label_definition_match"].strip(),
        icv_adjustment=row["icv_adjustment"].strip(),
        scanner_scope=row["scanner_scope"].strip(),
        field_strength=row["field_strength"].strip(),
        population_notes=row["population_notes"].strip(),
        evidence_tier=row["evidence_tier"].strip(),
        fit_for_runtime=row["fit_for_runtime"].strip().lower() == "true",
        review_status=row["review_status"].strip(),
        last_reviewed_on=row["last_reviewed_on"].strip(),
        reviewer=row["reviewer"].strip(),
        direction=_infer_direction(row["roi_name"].strip()),
    )


def _eligible_for_runtime(record: MasterRecord) -> bool:
    return (
        record.fit_for_runtime
        and record.review_status == "approved"
        and record.evidence_tier == "Tier A"
        and record.sex in {"M", "F"}
        and record.n >= 100
        and record.label_definition_match in {"exact", "approximate", "group-only"}
        and record.source_type != "vendor_db"
        and record.std_mm3 > 0.0
    )


def _runtime_sort_key(record: MasterRecord) -> tuple[int, int, int, int, str]:
    return (
        TIER_RANK.get(record.evidence_tier, 99),
        LABEL_MATCH_RANK.get(record.label_definition_match, 99),
        SOURCE_TYPE_RANK.get(record.source_type, 99),
        -record.n,
        record.source_citation,
    )


def _infer_direction(roi_name: str) -> str:
    return "high" if "ventricle" in roi_name else "low"
