from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable

from clinagent.families.neuro.config import NeuroAgentConfig
from clinagent.families.neuro.resources import VISTA_LABEL_MAPPING_PATH
from clinagent.families.neuro.tools import StructuralSegmentationAdapter, VolumetricAnalysisTool


STRUCTURAL_SERIES_PRIORITY = [
    "left_hippocampus",
    "right_hippocampus",
    "left_lateral_ventricle",
    "right_lateral_ventricle",
    "hippocampus",
    "ventricles",
    "left_cerebral_cortex",
    "right_cerebral_cortex",
    "left_cerebral_white_matter",
    "right_cerebral_white_matter",
    "total_brain_volume",
]


def _display_name_from_series(series_name: str) -> str:
    return series_name.replace("_", " ").title()


def _study_time(study: dict[str, Any]) -> str:
    return str(study.get("anon_study_date") or study.get("study_date") or "")


def _series_meta(*, name: str, display_name: str | None = None, unit: str = "mm3", priority: int = 0) -> dict[str, Any]:
    return {
        "name": name,
        "display_name": display_name or _display_name_from_series(name),
        "unit": unit,
        "series_type": "anatomical_region",
        "priority": priority,
    }


def _default_structural_series(available_names: list[str]) -> list[str]:
    defaults = [name for name in STRUCTURAL_SERIES_PRIORITY if name in available_names][:4]
    return defaults or available_names[: min(4, len(available_names))]


def _merged_structural_regions(volumetrics_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not volumetrics_payload:
        return []
    regions = [dict(region) for region in volumetrics_payload.get("regions", []) if isinstance(region, dict)]
    interpreted_lookup = {
        str(region.get("name")): dict(region)
        for region in volumetrics_payload.get("interpreted_regions", [])
        if isinstance(region, dict) and region.get("name")
    }
    merged_regions: list[dict[str, Any]] = []
    for region in regions:
        interpreted = interpreted_lookup.get(str(region.get("name")))
        merged_regions.append({**region, **interpreted} if interpreted else region)
    for name, interpreted in interpreted_lookup.items():
        if not any(str(region.get("name")) == name for region in merged_regions):
            merged_regions.append(interpreted)
    return merged_regions


def _structural_series_registry(volumetrics_payload: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[str]]:
    if not volumetrics_payload:
        return [], []
    regions = _merged_structural_regions(volumetrics_payload)
    available_names = [str(region.get("name", "")) for region in regions if region.get("name")]
    available_series = [
        _series_meta(
            name=str(region.get("name")),
            display_name=str(region.get("display_name") or _display_name_from_series(str(region.get("name")))),
            priority=STRUCTURAL_SERIES_PRIORITY.index(str(region.get("name")))
            if str(region.get("name")) in STRUCTURAL_SERIES_PRIORITY
            else 100,
        )
        for region in regions
        if region.get("name")
    ]
    available_series.sort(key=lambda item: (item["priority"], item["display_name"]))
    return available_series, _default_structural_series(available_names)


@dataclass
class MRRateLongitudinalBuilder:
    launch_study: Callable[[str, str], dict[str, Any]]
    segmentation_adapter: StructuralSegmentationAdapter | None = None
    volumetrics_tool: VolumetricAnalysisTool | None = None

    def __post_init__(self) -> None:
        if self.segmentation_adapter is None:
            self.segmentation_adapter = StructuralSegmentationAdapter()
        if self.volumetrics_tool is None:
            self.volumetrics_tool = VolumetricAnalysisTool(NeuroAgentConfig().normative_table_path)

    def build_volumetrics(
        self,
        *,
        patient_uid: str,
        studies: list[dict[str, Any]],
        region_names: list[str] | None = None,
    ) -> dict[str, Any]:
        ordered_studies = sorted(studies, key=_study_time)
        study_payloads = [self._study_volumetrics(patient_uid, study) for study in ordered_studies]
        available_series, default_series = self._series_registry_from_payloads(study_payloads)
        selected_region_names = region_names or default_series
        series: list[dict[str, Any]] = []

        for item in study_payloads:
            study = item["study"]
            volumetrics = item.get("volumetrics")
            regions_by_name = {
                str(region["name"]): region
                for region in _merged_structural_regions(volumetrics)
                if region.get("name")
            }
            data_point: dict[str, Any] = {
                "study_id": str(study.get("study_uid") or ""),
                "study_date": _study_time(study),
                "age_at_study": int(study.get("patient_age") or item.get("age") or 0),
            }
            for region_name in selected_region_names:
                region = regions_by_name.get(region_name)
                data_point[f"{region_name}_volume_mm3"] = region.get("volume_mm3") if region else None
                data_point[f"{region_name}_z_score"] = region.get("z_score") if region else None
                if region and region.get("z_score") is not None:
                    data_point[f"{region_name}_z_score_basis"] = "reference_table"
            series.append(data_point)

        self._fill_longitudinal_z_scores(series, selected_region_names)
        highlights = self._series_highlights(series, selected_region_names, available_series)

        return {
            "patient_id": patient_uid,
            "patient_name": f"Patient {patient_uid}",
            "region_names": selected_region_names,
            "available_series": available_series,
            "default_series": default_series,
            "series": series,
            "highlights": highlights[:10],
            "source": "mr_rate_knowledge",
            "z_score_basis": "reference_table_when_available_else_patient_longitudinal",
        }

    def build_heatmap(
        self,
        *,
        patient_uid: str,
        studies: list[dict[str, Any]],
        region_names: list[str] | None = None,
    ) -> dict[str, Any]:
        longitudinal = self.build_volumetrics(
            patient_uid=patient_uid,
            studies=studies,
            region_names=region_names,
        )
        return self.heatmap_from_longitudinal(patient_uid=patient_uid, longitudinal=longitudinal)

    @staticmethod
    def heatmap_from_longitudinal(*, patient_uid: str, longitudinal: dict[str, Any]) -> dict[str, Any]:
        selected_region_names = list(longitudinal.get("region_names") or [])
        matrix: dict[str, list[dict[str, Any]]] = {name: [] for name in selected_region_names}
        dates: list[str] = []
        for point in longitudinal["series"]:
            dates.append(point["study_date"])
            for region_name in selected_region_names:
                matrix[region_name].append(
                    {
                        "z_score": point.get(f"{region_name}_z_score"),
                        "volume_mm3": point.get(f"{region_name}_volume_mm3"),
                    }
                )
        return {
            "patient_id": patient_uid,
            "region_names": selected_region_names,
            "available_series": longitudinal.get("available_series", []),
            "default_series": longitudinal.get("default_series", []),
            "dates": dates,
            "matrix": matrix,
            "source": "mr_rate_knowledge",
            "z_score_basis": longitudinal.get("z_score_basis"),
        }

    def _study_volumetrics(self, patient_uid: str, study: dict[str, Any]) -> dict[str, Any]:
        study_uid = str(study.get("study_uid") or "").strip()
        if not study_uid:
            return {"study": study, "volumetrics": None}
        launch_payload = self.launch_study(patient_uid, study_uid)
        local_bundle = launch_payload.get("local_bundle") if isinstance(launch_payload, dict) else None
        if not isinstance(local_bundle, dict):
            return {"study": study, "volumetrics": None}
        seg_path = str(local_bundle.get("seg_path") or "").strip()
        if not seg_path:
            return {"study": study, "volumetrics": None}
        knowledge_context = launch_payload.get("knowledge_context") if isinstance(launch_payload, dict) else None
        context_study = knowledge_context.get("study") if isinstance(knowledge_context, dict) else None
        age = self._age_from_context(context_study if isinstance(context_study, dict) else study)
        sex = self._sex_from_context(context_study if isinstance(context_study, dict) else study)
        segmentation = self.segmentation_adapter.run(
            seg_nifti_path=seg_path,
            label_mapping_path=str(VISTA_LABEL_MAPPING_PATH),
            label_source="vista_tsv",
        )
        volumetrics = self.volumetrics_tool.run(
            segmentation_result=segmentation,
            patient_age=age,
            patient_sex=sex,
        )
        return {
            "study": context_study if isinstance(context_study, dict) else study,
            "volumetrics": volumetrics,
            "segmentation": segmentation,
            "age": age,
            "sex": sex,
        }

    @staticmethod
    def _age_from_context(study: dict[str, Any]) -> int:
        try:
            return int(study.get("patient_age") or 65)
        except (TypeError, ValueError):
            return 65

    @staticmethod
    def _sex_from_context(study: dict[str, Any]) -> str:
        sex = str(study.get("patient_sex") or "M").strip().upper()[:1]
        return sex if sex in {"M", "F"} else "M"

    @staticmethod
    def _series_registry_from_payloads(study_payloads: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        for item in study_payloads:
            available_series, default_series = _structural_series_registry(item.get("volumetrics"))
            if available_series:
                return available_series, default_series
        return [], []

    @staticmethod
    def _fill_longitudinal_z_scores(series: list[dict[str, Any]], region_names: list[str]) -> None:
        """Backfill display z-scores from this patient's time-series when references are unavailable."""
        for region_name in region_names:
            value_key = f"{region_name}_volume_mm3"
            z_key = f"{region_name}_z_score"
            numeric_values = [
                float(point[value_key])
                for point in series
                if isinstance(point.get(value_key), int | float)
            ]
            if len(numeric_values) < 2:
                continue
            mean = sum(numeric_values) / len(numeric_values)
            variance = sum((value - mean) ** 2 for value in numeric_values) / len(numeric_values)
            std = math.sqrt(variance)
            if std <= 0:
                continue
            for point in series:
                if point.get(z_key) is not None or not isinstance(point.get(value_key), int | float):
                    continue
                point[z_key] = (float(point[value_key]) - mean) / std
                point[f"{region_name}_z_score_basis"] = "patient_longitudinal"

    @staticmethod
    def _series_highlights(
        series: list[dict[str, Any]],
        region_names: list[str],
        available_series: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        display_by_name = {str(item.get("name")): str(item.get("display_name") or item.get("name")) for item in available_series}
        highlights: list[dict[str, Any]] = []
        for point in series:
            for region_name in region_names:
                z_score = point.get(f"{region_name}_z_score")
                if z_score is None or abs(float(z_score)) < 1.0:
                    continue
                basis = str(point.get(f"{region_name}_z_score_basis") or "reference_table")
                if basis == "patient_longitudinal":
                    direction = "above" if float(z_score) > 0 else "below"
                    interpretation = f"{direction} this patient's longitudinal mean"
                else:
                    interpretation = "outside expected reference range"
                highlights.append(
                    {
                        "study_id": str(point.get("study_id") or ""),
                        "study_date": str(point.get("study_date") or ""),
                        "display_name": display_by_name.get(region_name, _display_name_from_series(region_name)),
                        "z_score": float(z_score),
                        "interpretation": interpretation,
                    }
                )
        highlights.sort(key=lambda item: abs(float(item["z_score"])), reverse=True)
        return highlights[:10]

    @staticmethod
    def _key_findings(volumetrics_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not volumetrics_payload:
            return []
        region_lookup = {
            region["name"]: region
            for region in (
                volumetrics_payload.get("interpreted_regions")
                or volumetrics_payload.get("regions", [])
            )
            if isinstance(region, dict) and region.get("name")
        }
        findings: list[dict[str, Any]] = []
        for name in STRUCTURAL_SERIES_PRIORITY:
            region = region_lookup.get(name)
            if not region:
                continue
            z_score = region.get("z_score")
            if z_score is None:
                continue
            findings.append(
                {
                    "name": region["name"],
                    "display_name": region.get("display_name") or _display_name_from_series(region["name"]),
                    "z_score": z_score,
                    "percentile": region.get("percentile"),
                    "volume_mm3": region.get("volume_mm3"),
                    "direction": region.get("direction"),
                    "interpretation": region.get("interpretation", "outside expected range"),
                }
            )
        findings.sort(key=lambda item: abs(float(item["z_score"])), reverse=True)
        return findings[:8]
