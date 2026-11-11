"""Volumetric analysis tool with research-use comparative references."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scipy.stats import norm

from clinagent.families.neuro.tools.base_tool import BaseTool


class VolumetricAnalysisTool(BaseTool):
    """Compare observed region volumes against age/sex research-use references."""

    def __init__(self, normative_table_path: str):
        self.normative_table_path = str(normative_table_path)
        self._normative_table = json.loads(Path(normative_table_path).read_text())

    @property
    def name(self) -> str:
        return "volumetric_analysis"

    @property
    def description(self) -> str:
        return "Compare brain region volumes against age- and sex-adjusted research-use references"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "segmentation_result": {
                    "type": "object",
                    "description": "Output returned by BrainSegmentationTool.run()",
                },
                "patient_age": {
                    "type": "integer",
                    "description": "Patient age in years",
                },
                "patient_sex": {
                    "type": "string",
                    "enum": ["M", "F"],
                    "description": "Patient sex used for reference lookup",
                },
            },
            "required": ["segmentation_result", "patient_age", "patient_sex"],
            "additionalProperties": False,
        }

    def run(self, segmentation_result: dict, patient_age: int, patient_sex: str) -> dict:
        """Compute z-scores, percentiles, and human-readable comparative findings."""
        patient_sex = patient_sex.upper()
        decade_bucket = self._age_bucket(patient_age)

        interpreted_regions: list[dict[str, Any]] = []
        abnormal_summaries: list[str] = []
        normalization_limits: list[str] = list(self._normative_table.get("_meta", {}).get("normalization_limits", []))
        available_regions = self._normative_table_regions()
        full_regions = [dict(region) for region in segmentation_result.get("regions", [])]
        grouped_regions = [dict(region) for region in segmentation_result.get("grouped_regions", [])]

        for region in self._iter_regions(segmentation_result):
            region_name = region["name"]
            if region_name not in available_regions:
                continue
            reference = self._lookup_reference(region_name, patient_sex, decade_bucket)
            if reference is None:
                continue
            observed = float(region["volume_mm3"])
            z_score = (observed - float(reference["mean"])) / float(reference["std"])
            percentile = float(norm.cdf(z_score) * 100.0)
            direction = reference.get("_direction", "low")
            interpretation = self._interpret_z_score(z_score, direction)
            result = {
                "name": region_name,
                "display_name": region.get("display_name", region_name.replace("_", " ")),
                "volume_mm3": observed,
                "normative_mean": float(reference["mean"]),
                "normative_std": float(reference["std"]),
                "z_score": float(z_score),
                "percentile": percentile,
                "direction": direction,
                "interpretation": interpretation,
                "reference_source": reference.get("source_citation"),
                "reference_url": reference.get("source_url"),
                "reference_evidence_tier": reference.get("evidence_tier"),
                "reference_icv_adjustment": reference.get("icv_adjustment"),
                "reference_n": reference.get("n"),
            }
            interpreted_regions.append(result)
            normalization_limits = _merge_unique(normalization_limits, reference.get("normalization_limits", []))
            if interpretation != "within normal limits":
                abnormal_summaries.append(
                    f"{result['display_name']} is {interpretation} (z={z_score:.2f}, {observed:.1f} mm3)"
                )

        total_reference = self._lookup_reference("total_brain_volume", patient_sex, decade_bucket)
        total_brain_volume = float(segmentation_result.get("total_brain_volume_mm3", 0.0))
        brain_volume_percentile = None
        total_brain_interpretation = None
        if total_reference is not None:
            total_z = (total_brain_volume - float(total_reference["mean"])) / float(total_reference["std"])
            brain_volume_percentile = float(norm.cdf(total_z) * 100.0)
            total_direction = total_reference.get("_direction", "low")
            total_brain_interpretation = self._interpret_z_score(total_z, total_direction)
            interpreted_regions.append(
                {
                    "name": "total_brain_volume",
                    "display_name": "total brain volume",
                    "volume_mm3": total_brain_volume,
                    "normative_mean": float(total_reference["mean"]),
                    "normative_std": float(total_reference["std"]),
                    "z_score": float(total_z),
                    "percentile": brain_volume_percentile,
                    "direction": total_direction,
                    "interpretation": total_brain_interpretation,
                    "reference_source": total_reference.get("source_citation"),
                    "reference_url": total_reference.get("source_url"),
                    "reference_evidence_tier": total_reference.get("evidence_tier"),
                    "reference_icv_adjustment": total_reference.get("icv_adjustment"),
                    "reference_n": total_reference.get("n"),
                }
            )
            normalization_limits = _merge_unique(normalization_limits, total_reference.get("normalization_limits", []))
            if total_brain_interpretation != "within normal limits":
                abnormal_summaries.insert(
                    0,
                    f"overall brain volume is {total_brain_interpretation} (percentile {brain_volume_percentile:.1f})",
                )

        if abnormal_summaries:
            summary = "Reference-based comparative volumetry flagged: " + "; ".join(abnormal_summaries) + "."
        elif total_brain_interpretation:
            summary = (
                f"Overall brain volume is {total_brain_interpretation} for the selected research-use reference bucket "
                f"(percentile {brain_volume_percentile:.1f})."
            )
        elif available_regions:
            summary = "No abnormal findings identified within the published research-use reference coverage."
        else:
            summary = "No approved research-use reference values are available for the referenced regions."

        return {
            "regions": full_regions,
            "interpreted_regions": interpreted_regions,
            "grouped_regions": grouped_regions,
            "total_brain_volume_mm3": total_brain_volume,
            "brain_volume_percentile": brain_volume_percentile,
            "summary": summary,
            "reference_bucket": {
                "age_decade": decade_bucket,
                "sex": patient_sex,
            },
            "normative_reference_bucket": {
                "age_decade": decade_bucket,
                "sex": patient_sex,
            },
            "reference_table_meta": self._normative_table.get("_meta", {}),
            "normalization_limits": normalization_limits,
        }

    def _normative_table_regions(self) -> set[str]:
        return {key for key in self._normative_table if not key.startswith("_")}

    def _lookup_reference(self, region_name: str, patient_sex: str, decade_bucket: str) -> dict | None:
        region_data = self._normative_table.get(region_name, {})
        sex_data = region_data.get(patient_sex)
        if not sex_data:
            return None
        available = sorted(sex_data)
        if not available:
            return None
        reference = sex_data[decade_bucket] if decade_bucket in sex_data else sex_data[available[-1]]
        return {
            **reference,
            "_direction": region_data.get("_direction", "low"),
            "_note": region_data.get("_note"),
            "normalization_limits": region_data.get("_normalization_limits", []),
        }

    @staticmethod
    def _iter_regions(segmentation_result: dict) -> list[dict]:
        combined: dict[str, dict] = {}
        for collection_name in ("regions", "grouped_regions"):
            for region in segmentation_result.get(collection_name, []):
                combined.setdefault(region["name"], region)
        return list(combined.values())

    @staticmethod
    def _age_bucket(age: int) -> str:
        lower = max(50, min((age // 10) * 10, 80))
        upper = lower + 9
        return f"{lower}-{upper}"

    @staticmethod
    def _interpret_z_score(z_score: float, direction: str) -> str:
        if direction == "high":
            if z_score < 1.0:
                return "within normal limits"
            if z_score < 1.5:
                return "mildly enlarged"
            if z_score < 2.0:
                return "moderately enlarged"
            return "severely enlarged"
        if z_score > -1.0:
            return "within normal limits"
        if z_score > -1.5:
            return "mildly reduced"
        if z_score > -2.0:
            return "moderately reduced"
        return "severely reduced"


def _merge_unique(existing: list[str], new_values: list[str]) -> list[str]:
    merged = list(existing)
    for value in new_values:
        if value and value not in merged:
            merged.append(value)
    return merged
