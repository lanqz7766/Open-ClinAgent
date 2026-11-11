from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import openpyxl

from clinagent.families.radonc.metrics import evaluate_objective
from clinagent.families.radonc.models import DVHSnapshot, GoalStatus, ObjectiveResult, PlanGoal, PlanObjective
from clinagent.platform.local_data import resolve_radonc_demo_root


GOAL_PATTERN = re.compile(
    r"^(?P<metric>Dmean|Dmax|D[\d.]+\s*(?:cm3|cm³|%)|V[\d.]+\s*cGy)\s*(?P<operator>≤|>=|>=|≤|<=)\s*(?P<value>[\d.]+)\s*(?P<unit>cGy|%|cm3|cm³)$",
    re.IGNORECASE,
)

RESULT_PATTERN = re.compile(r"^(?P<state>Fulfilled|Not fulfilled):\s*(?P<value>[\d.]+)\s*(?P<unit>cGy|%|cm3|cm³)?$", re.IGNORECASE)
EUD_PATTERN = re.compile(r"^(?:Max|Min) EUD\s+([\d.]+)\s*cGy(?:,\s*Parameter A\s*([\d.]+))?$", re.IGNORECASE)
DVH_PATTERN = re.compile(r"^(Max|Min)\s+DVH\s+([\d.]+)\s*cGy\s+to\s+([\d.]+)\s*(cm3|cm³|%)\s+volume$", re.IGNORECASE)
MIN_DOSE_PATTERN = re.compile(r"^Min dose\s+([\d.]+)\s*cGy$", re.IGNORECASE)
UNIFORM_DOSE_PATTERN = re.compile(r"^Uniform dose\s+([\d.]+)\s*cGy$", re.IGNORECASE)


@dataclass(slots=True)
class AirtIterationBundle:
    iteration_number: int
    goals: list[PlanGoal]
    goal_status: list[GoalStatus]
    input_objectives: list[PlanObjective]
    output_objectives: list[PlanObjective]
    objective_results: list[ObjectiveResult]
    dvh_data: list[DVHSnapshot]
    plan_metadata: dict[str, Any]


def default_airt_patient_dir() -> Path:
    resolved = resolve_radonc_demo_root("Patient001")
    if resolved is not None:
        return resolved
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root.parent / "AIRTPlanAgent-main" / "test_data" / "Patient001"


def discover_airt_iterations(patient_dir: Path | str) -> list[int]:
    patient_dir = Path(patient_dir)
    available: set[int] = set()
    for path in patient_dir.glob("Input_Iteration*.xlsx"):
        match = re.search(r"Iteration(\d+)", path.name)
        if match:
            available.add(int(match.group(1)))
    return sorted(available)


def load_airt_iteration_bundle(patient_dir: Path | str, iteration_number: int) -> AirtIterationBundle:
    patient_dir = Path(patient_dir)
    input_path = patient_dir / f"Input_Iteration{iteration_number:03d}.xlsx"
    output_path = patient_dir / f"Output_Iteration{iteration_number:03d}.xlsx"
    dvh_path = patient_dir / f"Output_Iteration{iteration_number:03d}_DVH.dvh"

    input_rows = _read_worksheet_rows(input_path)
    output_rows = _read_worksheet_rows(output_path)

    goals = _parse_clinical_goals(input_rows)
    goal_status = _parse_goal_status(output_rows)
    input_objectives = _parse_objectives(input_rows, include_weights=False)
    output_objectives = _parse_objectives(output_rows, include_weights=True)
    dvh_map = parse_dvh_file(dvh_path)
    display_rois = _build_display_roi_set(goals, output_objectives)
    dvh_data = [dvh_map[roi] for roi in display_rois if roi in dvh_map]
    objective_results = [
        ObjectiveResult(
            objective=objective,
            fulfilled=fulfilled,
            actual_value=None if actual is None else round(actual, 2),
            unit=unit,
        )
        for objective, fulfilled, actual, unit in (
            (objective, *evaluate_objective(objective, dvh_map[objective.roi]))
            for objective in output_objectives
            if objective.roi in dvh_map
        )
    ]

    protocol_name = _extract_protocol_name(input_rows) or "AIRT mock planning protocol"
    return AirtIterationBundle(
        iteration_number=iteration_number,
        goals=goals,
        goal_status=goal_status,
        input_objectives=input_objectives,
        output_objectives=output_objectives,
        objective_results=objective_results,
        dvh_data=dvh_data,
        plan_metadata={
            "protocol_name": protocol_name,
            "case_label": patient_dir.name,
            "iteration_number": iteration_number,
            "goal_count": len(goals),
            "objective_count": len(output_objectives),
        },
    )


def parse_dvh_file(path: Path | str) -> dict[str, DVHSnapshot]:
    text = Path(path).read_text(encoding="utf-8")
    curves: dict[str, DVHSnapshot] = {}
    current_roi: str | None = None
    dose_points: list[float] = []
    volume_points: list[float] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#RoiName:"):
            if current_roi is not None:
                curves[current_roi] = DVHSnapshot(roi=current_roi, dose_points=dose_points, volume_points=volume_points)
            current_roi = line.split(":", 1)[1]
            dose_points = []
            volume_points = []
            continue
        if line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        dose_points.append(float(parts[0]))
        volume_points.append(float(parts[1]))

    if current_roi is not None:
        curves[current_roi] = DVHSnapshot(roi=current_roi, dose_points=dose_points, volume_points=volume_points)
    return curves


def _read_worksheet_rows(path: Path) -> list[list[Any]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        return [list(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def _parse_clinical_goals(rows: list[list[Any]]) -> list[PlanGoal]:
    goals: list[PlanGoal] = []
    in_goal_section = False
    for row in rows:
        if row and row[0] == "Prio" and len(row) >= 4 and row[2] == "ROI/POI":
            in_goal_section = True
            continue
        if in_goal_section and row and row[0] == "Function":
            break
        if not in_goal_section:
            continue
        roi = _get_cell(row, 2)
        goal_text = _get_cell(row, 3)
        if not roi or not goal_text:
            continue
        parsed = _parse_goal_string(goal_text)
        if parsed is None:
            continue
        goals.append(
            PlanGoal(
                roi=roi,
                metric=parsed["metric"],
                operator=parsed["operator"],
                value=parsed["value"],
                unit=parsed["unit"],
                priority=_infer_priority(roi, parsed["metric"]),
                source="protocol",
            )
        )
    return goals


def _parse_goal_status(rows: list[list[Any]]) -> list[GoalStatus]:
    items: list[GoalStatus] = []
    in_goal_section = False
    for row in rows:
        if row and row[0] == "Prio" and len(row) >= 6 and row[3] == "ROI/POI":
            in_goal_section = True
            continue
        if in_goal_section and row and row[0] == "Function":
            break
        if not in_goal_section:
            continue
        roi = _get_cell(row, 3)
        goal_text = _get_cell(row, 4)
        result_text = _get_cell(row, 5)
        if not roi or not goal_text or not result_text:
            continue
        parsed_goal = _parse_goal_string(goal_text)
        parsed_result = _parse_result_string(result_text)
        if parsed_goal is None or parsed_result is None:
            continue
        items.append(
            GoalStatus(
                roi=roi,
                metric=parsed_goal["metric"],
                operator=parsed_goal["operator"],
                target_value=parsed_goal["value"],
                unit=parsed_result["unit"] or parsed_goal["unit"],
                actual_value=parsed_result["value"],
                passed=parsed_result["fulfilled"],
                priority=_infer_priority(roi, parsed_goal["metric"]),
            )
        )
    return items


def _parse_objectives(rows: list[list[Any]], *, include_weights: bool) -> list[PlanObjective]:
    objectives: list[PlanObjective] = []
    in_objective_section = False
    for row in rows:
        if row and row[0] == "Function" and len(row) >= 5 and row[3] == "ROI":
            in_objective_section = True
            continue
        if not in_objective_section:
            continue
        function = _get_cell(row, 0)
        roi = _get_cell(row, 3)
        description = _get_cell(row, 4)
        if not function or not roi or not description or function == "Physical composite objective":
            continue
        parsed = _parse_objective_description(function, description)
        if parsed is None:
            continue
        weight = 1.0
        if include_weights:
            raw_weight = row[6] if len(row) > 6 else None
            if isinstance(raw_weight, (int, float)):
                weight = float(raw_weight)
        objectives.append(
            PlanObjective(
                roi=roi,
                objective_type=parsed["objective_type"],
                dose=parsed["dose"],
                volume=parsed.get("volume"),
                volume_unit=parsed.get("volume_unit", "%"),
                weight=weight,
                priority=_infer_priority(roi, parsed["objective_type"]),
            )
        )
    return objectives


def _extract_protocol_name(rows: list[list[Any]]) -> str | None:
    for row in rows:
        dose_label = _get_cell(row, 1)
        if dose_label and dose_label.startswith("Plan dose:"):
            return dose_label.replace("Plan dose:", "").strip()
    return None


def _build_display_roi_set(goals: list[PlanGoal], objectives: list[PlanObjective]) -> list[str]:
    preferred = {
        "Breast_L",
        "Breast_R",
        "CTV_APBI_2600",
        "PTV_Eval_APBI_2600",
        "TumorBed",
        "Tumorbed_Eval",
        "Heart",
        "Lung_L",
        "Lung_R",
        "fsBody",
    }
    roi_set = preferred | {goal.roi for goal in goals} | {objective.roi for objective in objectives}
    return sorted(roi_set)


def _parse_goal_string(value: str) -> dict[str, Any] | None:
    normalized = value.replace("≤", "<=").replace("≥", ">=").replace("cm³", "cm3")
    match = GOAL_PATTERN.match(normalized)
    if not match:
        return None
    metric = re.sub(r"\s+", "", match.group("metric"))
    operator = match.group("operator").replace("≤", "<=").replace("≥", ">=")
    unit = match.group("unit").replace("cm³", "cm3")
    return {
        "metric": metric,
        "operator": operator,
        "value": float(match.group("value")),
        "unit": unit,
    }


def _parse_result_string(value: str) -> dict[str, Any] | None:
    normalized = value.replace("cm³", "cm3")
    match = RESULT_PATTERN.match(normalized)
    if not match:
        return None
    return {
        "fulfilled": match.group("state").lower() == "fulfilled",
        "value": float(match.group("value")),
        "unit": (match.group("unit") or "").replace("cm³", "cm3") or None,
    }


def _parse_objective_description(function: str, description: str) -> dict[str, Any] | None:
    normalized = description.replace("cm³", "cm3")
    if match := EUD_PATTERN.match(normalized):
        return {
            "objective_type": function,
            "dose": float(match.group(1)),
            "volume": None,
            "volume_unit": "%",
        }
    if match := DVH_PATTERN.match(normalized):
        return {
            "objective_type": function,
            "dose": float(match.group(2)),
            "volume": float(match.group(3)),
            "volume_unit": match.group(4),
        }
    if match := MIN_DOSE_PATTERN.match(normalized):
        return {"objective_type": function, "dose": float(match.group(1))}
    if match := UNIFORM_DOSE_PATTERN.match(normalized):
        return {"objective_type": function, "dose": float(match.group(1))}
    return None


def _infer_priority(roi: str, metric: str) -> int:
    normalized_roi = roi.lower()
    normalized_metric = metric.lower()
    if "ptv" in normalized_roi or "ctv" in normalized_roi or "tumorbed" in normalized_roi or "tumorbed" in normalized_metric:
        return 1
    if "heart" in normalized_roi or "spinal" in normalized_roi or normalized_metric == "dmax":
        return 1
    if "lung" in normalized_roi or "body" in normalized_roi:
        return 2
    return 3


def _get_cell(row: list[Any], index: int) -> str | None:
    if index >= len(row):
        return None
    value = row[index]
    if value is None:
        return None
    return str(value).strip()
