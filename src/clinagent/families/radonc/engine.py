from __future__ import annotations

import asyncio
from copy import deepcopy
import math
import re
from statistics import fmean
from typing import Awaitable, Callable

from clinagent.families.radonc.connectors import RTPlanningConnector
from clinagent.families.radonc.metrics import (
    compute_dmax,
    compute_dmean,
    evaluate_goal,
    evaluate_objective,
    volume_at_dose,
)
from clinagent.families.radonc.models import (
    ComparisonMetric,
    ComparisonSummary,
    DVHSnapshot,
    GoalStatus,
    ObjectiveResult,
    ObjectiveSuggestion,
    OptimizationIteration,
    PlanGoal,
    PlanObjective,
    ReferenceGapSummary,
)


DEFAULT_OAR_TOLERANCES = (
    PlanGoal(roi="SpinalCord", metric="Dmax", operator="<=", value=1800.0, unit="cGy", priority=1, source="agent"),
    PlanGoal(roi="SpinalCanal", metric="Dmax", operator="<=", value=1800.0, unit="cGy", priority=1, source="agent"),
    PlanGoal(roi="Heart", metric="Dmean", operator="<=", value=900.0, unit="cGy", priority=2, source="agent"),
    PlanGoal(roi="Esophagus", metric="Dmean", operator="<=", value=1400.0, unit="cGy", priority=2, source="agent"),
)

ROI_ALIASES = {
    "cord": "SpinalCord",
    "spinal canal": "SpinalCanal",
    "spinal cord": "SpinalCord",
    "heart": "Heart",
    "esophagus": "Esophagus",
    "lung left": "Lung_L",
    "left lung": "Lung_L",
    "lung right": "Lung_R",
    "right lung": "Lung_R",
    "lung": "Lung_L",
    "breast": "Breast_L",
    "thyroid": "Glnd_Thyroid",
    "tumor bed": "TumorBed",
    "target": "PTV_Eval_APBI_2600",
    "ptv": "PTV_Eval_APBI_2600",
    "ctv": "CTV_APBI_2600",
    "coverage": "PTV_Eval_APBI_2600",
}

TARGET_ROIS = {"PTV_Eval_APBI_2600", "CTV_APBI_2600", "TumorBed"}


def _match_roi_alias(text: str) -> str | None:
    best_match: tuple[int, int, str] | None = None
    for token, value in ROI_ALIASES.items():
        index = text.find(token)
        if index < 0:
            continue
        candidate = (index, -len(token), value)
        if best_match is None or candidate < best_match:
            best_match = candidate
    return best_match[2] if best_match is not None else None


def _normalize_dose_to_cgy(value: float, unit: str | None) -> float:
    normalized_unit = (unit or "").lower()
    if normalized_unit == "gy" or (not normalized_unit and value <= 80):
        return round(value * 100.0, 2)
    return round(value, 2)


def _format_volume_metric(dose_cgy: float) -> str:
    return f"V{int(dose_cgy) if float(dose_cgy).is_integer() else f'{dose_cgy:g}'}cGy"


def _find_goal(goals: list[PlanGoal], *, roi: str, metric: str | None = None) -> PlanGoal | None:
    for goal in goals:
        if goal.roi != roi:
            continue
        if metric is None or goal.metric.lower() == metric.lower():
            return goal
    return None


def _find_objective(
    objectives: list[PlanObjective],
    *,
    roi: str,
    kind: str | None = None,
    fallback_to_any: bool = False,
) -> PlanObjective | None:
    for objective in objectives:
        if objective.roi != roi:
            continue
        if kind is None or objective.objective_type.lower() == kind.lower():
            return objective
    if fallback_to_any:
        return next((objective for objective in objectives if objective.roi == roi), None)
    return None


def _upsert_goal(goals: list[PlanGoal], next_goal: PlanGoal) -> None:
    for index, goal in enumerate(goals):
        if goal.roi == next_goal.roi and goal.metric.lower() == next_goal.metric.lower():
            goals[index] = next_goal
            return
    goals.append(next_goal)


def _upsert_objective(objectives: list[PlanObjective], next_objective: PlanObjective) -> None:
    for index, objective in enumerate(objectives):
        if objective.roi == next_objective.roi and objective.objective_type.lower() == next_objective.objective_type.lower():
            objectives[index] = next_objective
            return
    same_roi_indices = [index for index, objective in enumerate(objectives) if objective.roi == next_objective.roi]
    if len(same_roi_indices) == 1:
        objectives[same_roi_indices[0]] = next_objective
        return
    objectives.append(next_objective)


def apply_planner_command_update(
    command: str,
    goals: list[PlanGoal],
    current_objectives: list[PlanObjective],
) -> tuple[list[PlanGoal], list[PlanObjective], list[ObjectiveSuggestion], str] | None:
    lowered = command.lower().strip()
    roi = _match_roi_alias(lowered)
    if roi is None:
        return None

    updated_goals = deepcopy(goals)
    updated_objectives = deepcopy(current_objectives)
    is_target_roi = roi in TARGET_ROIS

    weight_match = re.search(r"\bweight\b[^\d]*(\d+(?:\.\d+)?)", lowered)
    percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", lowered)
    volume_metric_match = re.search(r"\bv\s*(\d+(?:\.\d+)?)\s*(cgy|gy)?\b", lowered)
    dose_match = re.search(r"(\d+(?:\.\d+)?)\s*(cgy|gy)\b", lowered)

    explicit_dose_cgy = _normalize_dose_to_cgy(float(dose_match.group(1)), dose_match.group(2)) if dose_match else None
    explicit_weight = max(1.0, min(140.0, float(weight_match.group(1)))) if weight_match else None

    if volume_metric_match is not None or ("coverage" in lowered and (percent_match is not None or dose_match is not None)):
        dose_source = volume_metric_match or dose_match
        if dose_source is None:
            return None
        dose_cgy = _normalize_dose_to_cgy(float(dose_source.group(1)), dose_source.group(2))
        operator = ">=" if is_target_roi or any(token in lowered for token in ("cover", "coverage", "boost", "raise", "increase", ">=", "at least")) else "<="
        existing_goal = _find_goal(updated_goals, roi=roi, metric=_format_volume_metric(dose_cgy))
        existing_objective = _find_objective(updated_objectives, roi=roi, kind="Min DVH" if operator == ">=" else "Max DVH")
        volume_value = round(
            float(percent_match.group(1)) if percent_match else (
                existing_goal.value if existing_goal is not None else existing_objective.volume if existing_objective and existing_objective.volume is not None else (98.0 if operator == ">=" else 5.0)
            ),
            2,
        )
        priority = 1 if is_target_roi else 2
        next_goal = PlanGoal(
            roi=roi,
            metric=_format_volume_metric(dose_cgy),
            operator=operator,
            value=volume_value,
            unit="%",
            priority=priority,
            source="user",
        )
        next_objective = (existing_objective or PlanObjective(
            roi=roi,
            objective_type="Min DVH" if operator == ">=" else "Max DVH",
            dose=dose_cgy,
            volume=volume_value,
            volume_unit="%",
            weight=80.0 if is_target_roi else 18.0,
            priority=priority,
        )).model_copy(
            update={
                "objective_type": "Min DVH" if operator == ">=" else "Max DVH",
                "dose": dose_cgy,
                "volume": volume_value,
                "volume_unit": "%",
                "weight": explicit_weight if explicit_weight is not None else (existing_objective.weight if existing_objective else (80.0 if is_target_roi else 18.0)),
                "priority": priority,
            }
        )
        _upsert_goal(updated_goals, next_goal)
        _upsert_objective(updated_objectives, next_objective)
        suggestion = ObjectiveSuggestion(
            action="modify" if existing_objective else "add",
            objective=next_objective,
            reason=f"Planner chat updated {roi} coverage target to {next_goal.metric} {next_goal.operator} {next_goal.value:g}{next_goal.unit}.",
            confidence=0.93,
            source="planner_chat",
        )
        return updated_goals, updated_objectives, [suggestion], suggestion.reason

    metric_name = None
    objective_type = None
    default_dose_cgy = None
    if "dmax" in lowered or "max dose" in lowered:
        metric_name = "Dmax"
        objective_type = "Max Dose"
        default_dose_cgy = 1800.0 if roi in {"SpinalCord", "SpinalCanal"} else 1200.0
    elif "dmean" in lowered or "mean dose" in lowered:
        metric_name = "Dmean"
        objective_type = "Mean Dose"
        default_dose_cgy = 900.0 if roi == "Heart" else 1400.0
    elif explicit_dose_cgy is not None and any(
        token in lowered for token in ("dose", "limit", "constraint", "standard", "goal", "criteria", "threshold", "spare", "protect", "lower", "reduce", "tighten", "relax")
    ):
        existing_goal = _find_goal(updated_goals, roi=roi)
        metric_name = existing_goal.metric if existing_goal is not None else ("Dmean" if roi in {"Heart", "Esophagus"} else "Dmax")
        objective_type = "Mean Dose" if metric_name.lower() == "dmean" else "Max Dose"
        default_dose_cgy = existing_goal.value if existing_goal is not None else (900.0 if metric_name.lower() == "dmean" else 1800.0)

    if metric_name and objective_type:
        target_value = explicit_dose_cgy if explicit_dose_cgy is not None else default_dose_cgy
        existing_goal = _find_goal(updated_goals, roi=roi, metric=metric_name)
        existing_objective = _find_objective(updated_objectives, roi=roi, kind=objective_type)
        priority = existing_goal.priority if existing_goal is not None else (1 if roi in {"SpinalCord", "SpinalCanal"} else 2)
        next_goal = PlanGoal(
            roi=roi,
            metric=metric_name,
            operator="<=",
            value=target_value,
            unit="cGy",
            priority=priority,
            source="user",
        )
        next_objective = (existing_objective or PlanObjective(
            roi=roi,
            objective_type=objective_type,
            dose=target_value,
            weight=18.0 if priority == 1 else 10.0,
            priority=priority,
        )).model_copy(
            update={
                "objective_type": objective_type,
                "dose": target_value,
                "weight": explicit_weight if explicit_weight is not None else (existing_objective.weight if existing_objective else (18.0 if priority == 1 else 10.0)),
                "priority": priority,
            }
        )
        _upsert_goal(updated_goals, next_goal)
        _upsert_objective(updated_objectives, next_objective)
        suggestion = ObjectiveSuggestion(
            action="modify" if existing_objective else "add",
            objective=next_objective,
            reason=f"Planner chat updated {roi} {metric_name} limit to {target_value:g} cGy.",
            confidence=0.95,
            source="planner_chat",
        )
        return updated_goals, updated_objectives, [suggestion], suggestion.reason

    existing = _find_objective(updated_objectives, roi=roi, fallback_to_any=True)
    if existing is not None and explicit_weight is not None:
        next_objective = existing.model_copy(update={"weight": explicit_weight})
        _upsert_objective(updated_objectives, next_objective)
        suggestion = ObjectiveSuggestion(
            action="modify",
            objective=next_objective,
            reason=f"Planner chat set {roi} objective weight to {explicit_weight:g}.",
            confidence=0.9,
            source="planner_chat",
        )
        return updated_goals, updated_objectives, [suggestion], suggestion.reason

    if is_target_roi:
        next_objective = (existing or PlanObjective(roi=roi, objective_type="Min DVH", dose=2548.0, volume=98.0, weight=80.0, priority=1)).model_copy(
            update={"weight": min(140.0, (existing.weight if existing else 80.0) + 10.0)},
        )
        _upsert_objective(updated_objectives, next_objective)
        suggestion = ObjectiveSuggestion(
            action="modify" if existing else "add",
            objective=next_objective,
            reason=f"Planner chat increased coverage emphasis for {roi}.",
            confidence=0.74,
            source="planner_chat",
        )
        return updated_goals, updated_objectives, [suggestion], suggestion.reason

    next_objective = (existing or PlanObjective(roi=roi, objective_type="Max EUD", dose=900.0, weight=10.0, priority=2)).model_copy(
        update={"objective_type": "Max EUD", "weight": min(120.0, (existing.weight if existing else 10.0) + 8.0)},
    )
    _upsert_objective(updated_objectives, next_objective)
    suggestion = ObjectiveSuggestion(
        action="modify" if existing else "add",
        objective=next_objective,
        reason=f"Planner chat increased OAR sparing emphasis for {roi}.",
        confidence=0.77,
        source="planner_chat",
    )
    return updated_goals, updated_objectives, [suggestion], suggestion.reason


def _goal_key(goal: PlanGoal | GoalStatus) -> tuple[str, str]:
    return (goal.roi, goal.metric)


def _dvh_map(dvh_data: list[DVHSnapshot]) -> dict[str, DVHSnapshot]:
    return {item.roi: item for item in dvh_data}


def _status_map(goal_status: list[GoalStatus]) -> dict[tuple[str, str], GoalStatus]:
    return {_goal_key(item): item for item in goal_status}


def build_goal_statuses(goals: list[PlanGoal], dvh_data: list[DVHSnapshot]) -> list[GoalStatus]:
    dvh_map = _dvh_map(dvh_data)
    return [evaluate_goal(goal, dvh_map[goal.roi]) for goal in goals if goal.roi in dvh_map]


def build_objective_results(objectives: list[PlanObjective], dvh_data: list[DVHSnapshot]) -> list[ObjectiveResult]:
    dvh_map = _dvh_map(dvh_data)
    results: list[ObjectiveResult] = []
    for objective in objectives:
        dvh = dvh_map.get(objective.roi)
        if dvh is None:
            continue
        fulfilled, actual, unit = evaluate_objective(objective, dvh)
        if actual is None and (objective.volume_unit or "").lower() != "%":
            continue
        results.append(
            ObjectiveResult(
                objective=deepcopy(objective),
                fulfilled=fulfilled,
                actual_value=None if actual is None else round(actual, 2),
                unit=unit,
            )
        )
    return results


def build_reference_comparison(
    *,
    goals: list[PlanGoal],
    start_goal_status: list[GoalStatus],
    current_goal_status: list[GoalStatus],
    reference_goal_status: list[GoalStatus],
    current_dvh_data: list[DVHSnapshot],
    reference_dvh_data: list[DVHSnapshot],
    current_label: str,
    reference_label: str,
) -> tuple[ReferenceGapSummary, list[ComparisonMetric], ComparisonSummary]:
    start_map = _status_map(start_goal_status)
    current_map = _status_map(current_goal_status)
    reference_map = _status_map(reference_goal_status)

    comparison_metrics: list[ComparisonMetric] = []
    metric_gap_samples: list[float] = []
    goal_agreement_samples: list[float] = []

    for goal in goals:
        key = _goal_key(goal)
        start_item = start_map.get(key)
        current_item = current_map.get(key)
        reference_item = reference_map.get(key)
        if current_item is None or reference_item is None:
            continue

        delta_to_reference = None
        if current_item.actual_value is not None and reference_item.actual_value is not None:
            delta_to_reference = round(current_item.actual_value - reference_item.actual_value, 2)
            scale = max(abs(reference_item.actual_value), abs(goal.value), 1.0)
            metric_gap_samples.append(abs(delta_to_reference) / scale)

        agreement = current_item.passed == reference_item.passed
        goal_agreement_samples.append(1.0 if agreement else 0.0)
        comparison_metrics.append(
            ComparisonMetric(
                roi=goal.roi,
                metric=goal.metric,
                unit=current_item.unit or reference_item.unit or goal.unit,
                start_value=start_item.actual_value if start_item is not None else None,
                current_value=current_item.actual_value,
                reference_value=reference_item.actual_value,
                delta_to_reference=delta_to_reference,
                passed=current_item.passed,
                reference_passed=reference_item.passed,
                agreement=agreement,
            )
        )

    current_dvh_map = _dvh_map(current_dvh_data)
    reference_dvh_map = _dvh_map(reference_dvh_data)
    dvh_gap_samples: list[float] = []
    for roi, current in current_dvh_map.items():
        reference = reference_dvh_map.get(roi)
        if reference is None:
            continue
        sample_points = current.dose_points[:: max(1, len(current.dose_points) // 30)] or current.dose_points
        if not sample_points:
            continue
        point_diffs = [
            abs(volume_at_dose(current, dose) - volume_at_dose(reference, dose)) / 100.0 for dose in sample_points
        ]
        dvh_gap_samples.append(fmean(point_diffs))

    metric_gap_percent = round(min(100.0, fmean(metric_gap_samples) * 100.0), 2) if metric_gap_samples else 0.0
    dvh_gap_percent = round(min(100.0, fmean(dvh_gap_samples) * 100.0), 2) if dvh_gap_samples else 0.0
    goal_agreement_percent = round(fmean(goal_agreement_samples) * 100.0, 2) if goal_agreement_samples else 100.0
    clinical_completion_percent = round(
        (sum(1 for item in current_goal_status if item.passed) / len(current_goal_status)) * 100.0,
        2,
    ) if current_goal_status else 0.0
    reference_proximity_percent = round(
        max(0.0, 100.0 - (metric_gap_percent * 0.55 + dvh_gap_percent * 0.45)),
        2,
    )
    overall_completion_percent = round(
        clinical_completion_percent * 0.6 + reference_proximity_percent * 0.25 + goal_agreement_percent * 0.15,
        2,
    )

    reference_gap = ReferenceGapSummary(
        overall_percent=round(100.0 - reference_proximity_percent, 2),
        dvh_gap_percent=dvh_gap_percent,
        metric_gap_percent=metric_gap_percent,
        goal_agreement_percent=goal_agreement_percent,
    )
    comparison_summary = ComparisonSummary(
        clinical_completion_percent=clinical_completion_percent,
        reference_proximity_percent=reference_proximity_percent,
        overall_completion_percent=overall_completion_percent,
        goal_agreement_percent=goal_agreement_percent,
        dvh_gap_percent=dvh_gap_percent,
        metric_gap_percent=metric_gap_percent,
        current_label=current_label,
        reference_label=reference_label,
    )
    return reference_gap, comparison_metrics, comparison_summary


class RuleEngine:
    def __init__(self, tolerances: tuple[PlanGoal, ...] = DEFAULT_OAR_TOLERANCES):
        self._tolerances = tolerances

    def analyze(
        self,
        *,
        goals: list[PlanGoal],
        goal_status: list[GoalStatus],
        current_objectives: list[PlanObjective],
        dvh_map: dict[str, object],
    ) -> tuple[list[GoalStatus], list[ObjectiveSuggestion]]:
        resolved_status: list[GoalStatus] = list(goal_status)
        if not resolved_status:
            resolved_status = [evaluate_goal(goal, dvh_map[goal.roi]) for goal in goals if goal.roi in dvh_map]

        suggestions: list[ObjectiveSuggestion] = []
        objective_rois = {item.roi for item in current_objectives}

        for goal in goals:
            status = next((item for item in resolved_status if item.roi == goal.roi and item.metric == goal.metric), None)
            if status is None or status.passed:
                continue
            existing = self._find_matching_objective(goal=goal, objectives=current_objectives)
            proposed = self._build_objective(goal=goal, status=status, existing=existing)
            suggestions.append(
                ObjectiveSuggestion(
                    action="modify" if existing else "add",
                    objective=proposed,
                    reason=f"{goal.roi} {goal.metric} remains outside target ({status.actual_value:.2f} vs {goal.value:.2f} {status.unit}).",
                    confidence=0.95 if goal.priority == 1 else 0.84 if goal.priority == 2 else 0.72,
                    source="rule_engine",
                )
            )

        for tolerance in self._tolerances:
            if tolerance.roi not in dvh_map or tolerance.roi in objective_rois:
                continue
            actual = compute_dmax(dvh_map[tolerance.roi]) if tolerance.metric.lower() == "dmax" else compute_dmean(dvh_map[tolerance.roi])
            if actual <= tolerance.value:
                continue
            suggestions.append(
                ObjectiveSuggestion(
                    action="add",
                    objective=PlanObjective(
                        roi=tolerance.roi,
                        objective_type="Max EUD",
                        dose=tolerance.value,
                        weight=18.0 if tolerance.priority == 1 else 10.0,
                        priority=tolerance.priority,
                    ),
                    reason=f"Unmonitored OAR {tolerance.roi} exceeds default tolerance ({actual:.1f} cGy).",
                    confidence=0.9,
                    source="rule_engine",
                )
            )

        return resolved_status, suggestions

    def _find_matching_objective(self, *, goal: PlanGoal, objectives: list[PlanObjective]) -> PlanObjective | None:
        same_roi = [item for item in objectives if item.roi == goal.roi]
        if not same_roi:
            return None
        metric = goal.metric.lower()
        if metric.startswith("v"):
            return next((item for item in same_roi if item.objective_type.lower().endswith("dvh")), same_roi[0])
        if metric.startswith("d"):
            return next((item for item in same_roi if item.objective_type.lower() == "max eud"), same_roi[0])
        return same_roi[0]

    def _build_objective(self, *, goal: PlanGoal, status: GoalStatus, existing: PlanObjective | None) -> PlanObjective:
        severity = 0.0
        if status.actual_value is not None and goal.value > 0:
            if goal.operator == "<=":
                severity = max(0.0, (status.actual_value - goal.value) / goal.value)
            else:
                severity = max(0.0, (goal.value - status.actual_value) / goal.value)
        weight_bump = 10.0 if goal.priority == 1 else 6.0 if goal.priority == 2 else 3.5
        adaptive_weight = min(140.0, (existing.weight if existing else 8.0) + weight_bump * (1.0 + min(severity, 0.5)))

        metric = goal.metric.lower()
        if metric.startswith("v"):
            dose_match = re.search(r"([\d.]+)", goal.metric)
            dose = float(dose_match.group(1)) if dose_match else goal.value
            objective_type = "Min DVH" if goal.operator == ">=" else "Max DVH"
            return PlanObjective(
                roi=goal.roi,
                objective_type=objective_type,
                dose=dose,
                volume=goal.value,
                volume_unit=goal.unit,
                weight=adaptive_weight,
                priority=goal.priority,
            )
        return PlanObjective(
            roi=goal.roi,
            objective_type="Max EUD" if goal.operator == "<=" else "Min Dose",
            dose=goal.value,
            volume=existing.volume if existing else None,
            volume_unit=existing.volume_unit if existing else "%",
            weight=adaptive_weight,
            priority=goal.priority,
        )


class LLMAdvisor:
    async def analyze_async(
        self,
        *,
        goals: list[PlanGoal],
        goal_status: list[GoalStatus],
        current_objectives: list[PlanObjective],
        history_count: int,
    ) -> list[ObjectiveSuggestion]:
        target_failures = [item for item in goal_status if not item.passed and item.operator == ">="]
        oar_failures = [item for item in goal_status if not item.passed and item.operator == "<="]
        if history_count < 1 or not target_failures or not oar_failures:
            return []

        lowest_priority_oar = sorted(oar_failures, key=lambda item: item.priority, reverse=True)[0]
        existing = next((item for item in current_objectives if item.roi == lowest_priority_oar.roi), None)
        if existing is None:
            return []

        return [
            ObjectiveSuggestion(
                action="modify",
                objective=existing.model_copy(update={"weight": max(5.0, existing.weight - 4.0)}),
                reason=f"Trade-off adjustment: ease {lowest_priority_oar.roi} pressure slightly to recover target coverage.",
                confidence=0.58,
                source="llm_advisor",
            )
        ]

    async def interpret_command(
        self,
        command: str,
        goals: list[PlanGoal],
        current_objectives: list[PlanObjective],
    ) -> list[ObjectiveSuggestion]:
        update = apply_planner_command_update(command, goals, current_objectives)
        if update is None:
            return []
        _, _, suggestions, _ = update
        return suggestions


class HybridSimulationEngine:
    def __init__(
        self,
        *,
        goals: list[PlanGoal],
        start_dvh_data: list[DVHSnapshot],
        reference_dvh_data: list[DVHSnapshot],
    ) -> None:
        self._goals = deepcopy(goals)
        self._start_dvh_map = _dvh_map(start_dvh_data)
        self._reference_dvh_map = _dvh_map(reference_dvh_data)

    def simulate_next(
        self,
        *,
        iteration_number: int,
        current_dvh_data: list[DVHSnapshot],
        current_objectives: list[PlanObjective],
        suggestions: list[ObjectiveSuggestion],
        current_goal_status: list[GoalStatus],
    ) -> list[DVHSnapshot]:
        current_map = _dvh_map(current_dvh_data)
        objective_weight_by_roi: dict[str, float] = {}
        for objective in current_objectives:
            objective_weight_by_roi[objective.roi] = objective_weight_by_roi.get(objective.roi, 0.0) + objective.weight
        suggestion_weight_by_roi: dict[str, float] = {}
        for suggestion in suggestions:
            suggestion_weight_by_roi[suggestion.objective.roi] = suggestion_weight_by_roi.get(suggestion.objective.roi, 0.0) + suggestion.confidence * 12.0

        failed_goals_by_roi: dict[str, list[GoalStatus]] = {}
        for status in current_goal_status:
            if not status.passed:
                failed_goals_by_roi.setdefault(status.roi, []).append(status)

        next_dvh_data: list[DVHSnapshot] = []
        for roi, current in current_map.items():
            reference = self._reference_dvh_map.get(roi, current)
            start = self._start_dvh_map.get(roi, current)
            objective_pressure = min(1.0, objective_weight_by_roi.get(roi, 0.0) / 120.0)
            suggestion_pressure = min(1.0, suggestion_weight_by_roi.get(roi, 0.0) / 16.0)
            failure_pressure = min(1.0, len(failed_goals_by_roi.get(roi, [])) * 0.32)
            alpha = min(0.24, 0.065 + objective_pressure * 0.04 + suggestion_pressure * 0.05 + failure_pressure * 0.06 + iteration_number * 0.004)

            next_volumes: list[float] = []
            for index, dose in enumerate(current.dose_points):
                current_volume = current.volume_points[index]
                reference_volume = volume_at_dose(reference, dose)
                start_volume = volume_at_dose(start, dose)
                value = current_volume + alpha * (reference_volume - current_volume)

                if self._is_target_roi(roi):
                    if failed_goals_by_roi.get(roi):
                        normalized_dose = dose / max(1.0, reference.dose_points[-1] if reference.dose_points else dose or 1.0)
                        if 0.45 <= normalized_dose <= 0.98:
                            value += 1.1 * failure_pressure * (1.0 - abs(0.72 - normalized_dose))
                else:
                    normalized_dose = dose / max(1.0, reference.dose_points[-1] if reference.dose_points else dose or 1.0)
                    if normalized_dose >= 0.35:
                        value -= 1.4 * (objective_pressure + suggestion_pressure * 0.6) * normalized_dose

                value = min(100.0, max(0.0, value))
                if index == 0:
                    value = max(value, min(100.0, max(start_volume, current_volume)))
                next_volumes.append(value)

            next_volumes = self._enforce_monotonic_descending(next_volumes)
            next_dvh_data.append(
                DVHSnapshot(
                    roi=roi,
                    dose_points=deepcopy(current.dose_points),
                    volume_points=[round(item, 3) for item in next_volumes],
                )
            )

        return next_dvh_data

    @staticmethod
    def _is_target_roi(roi: str) -> bool:
        lowered = roi.lower()
        return "ptv" in lowered or "ctv" in lowered or "tumor" in lowered

    @staticmethod
    def _enforce_monotonic_descending(volumes: list[float]) -> list[float]:
        if not volumes:
            return volumes
        adjusted = [max(0.0, min(100.0, volumes[0]))]
        for value in volumes[1:]:
            adjusted.append(max(0.0, min(adjusted[-1], value)))
        return adjusted


class OptimizationOrchestrator:
    def __init__(
        self,
        *,
        session_id: str,
        connector: RTPlanningConnector | None,
        goals: list[PlanGoal],
        current_objectives: list[PlanObjective],
        current_dvh_data: list[DVHSnapshot],
        start_goal_status: list[GoalStatus],
        start_dvh_data: list[DVHSnapshot],
        reference_goal_status: list[GoalStatus],
        reference_dvh_data: list[DVHSnapshot],
        max_iterations: int,
        plateau_threshold: int,
        history: list[OptimizationIteration] | None = None,
        command_history: list[str] | None = None,
        start_iteration_number: int = 1,
        reference_iteration_number: int = 2,
        on_event: Callable[[str, dict[str, object]], Awaitable[None]] | None = None,
    ):
        self.session_id = session_id
        self.connector = connector
        self.goals = deepcopy(goals)
        self.current_objectives = deepcopy(current_objectives)
        self.current_dvh_data = deepcopy(current_dvh_data)
        self.start_goal_status = deepcopy(start_goal_status)
        self.start_dvh_data = deepcopy(start_dvh_data)
        self.reference_goal_status = deepcopy(reference_goal_status)
        self.reference_dvh_data = deepcopy(reference_dvh_data)
        self.max_iterations = max_iterations
        self.plateau_threshold = plateau_threshold
        self.history = list(history or [])
        self.pending_commands = list(command_history or [])
        self.start_iteration_number = start_iteration_number
        self.reference_iteration_number = reference_iteration_number
        self.on_event = on_event
        self.iteration_number = len(self.history)
        self.paused = False
        self.stopped = False
        self.rule_engine = RuleEngine()
        self.llm_advisor = LLMAdvisor()
        self.simulation_engine = HybridSimulationEngine(
            goals=self.goals,
            start_dvh_data=self.start_dvh_data,
            reference_dvh_data=self.reference_dvh_data,
        )

    def add_user_command(self, command: str) -> None:
        if command.strip():
            self.pending_commands.append(command.strip())

    def sync_workspace_state(
        self,
        *,
        goals: list[PlanGoal] | None = None,
        current_objectives: list[PlanObjective] | None = None,
    ) -> None:
        if goals is not None:
            self.goals = deepcopy(goals)
            self.simulation_engine = HybridSimulationEngine(
                goals=self.goals,
                start_dvh_data=self.start_dvh_data,
                reference_dvh_data=self.reference_dvh_data,
            )
        if current_objectives is not None:
            self.current_objectives = deepcopy(current_objectives)

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def stop(self) -> None:
        self.stopped = True

    async def _emit(self, event_type: str, data: dict[str, object]) -> None:
        if self.on_event is not None:
            await self.on_event(event_type, data)

    async def _connector_state(self) -> dict[str, object]:
        base: dict[str, object] = {}
        if self.connector is not None:
            metadata = await self.connector.get_plan_metadata()
            state = metadata.get("connector_state")
            if isinstance(state, dict):
                base.update(state)
        base.update(
            {
                "bundle_kind": "simulated" if self.history else "observed",
                "observed_start_iteration": self.start_iteration_number,
                "reference_iteration": self.reference_iteration_number,
                "current_iteration": self.start_iteration_number,
                "current_simulated_iteration": self.iteration_number,
                "next_iteration_available": self.iteration_number < self.max_iterations,
                "replay_exhausted": self.iteration_number >= self.max_iterations,
                "can_run_current": self.iteration_number < self.max_iterations and not self.stopped,
            }
        )
        return base

    async def run_iteration(self) -> OptimizationIteration:
        self.iteration_number += 1
        await self._emit("iteration_start", {"number": self.iteration_number, "bundle_kind": "simulated"})
        await self._emit("iteration_progress", {"step": "evaluate_current"})

        current_goal_status = build_goal_statuses(self.goals, self.current_dvh_data)
        dvh_map = _dvh_map(self.current_dvh_data)

        await self._emit("iteration_progress", {"step": "rule_analysis"})
        _, rule_suggestions = self.rule_engine.analyze(
            goals=self.goals,
            goal_status=current_goal_status,
            current_objectives=self.current_objectives,
            dvh_map=dvh_map,
        )

        await self._emit("iteration_progress", {"step": "tradeoff_analysis"})
        llm_suggestions = await self.llm_advisor.analyze_async(
            goals=self.goals,
            goal_status=current_goal_status,
            current_objectives=self.current_objectives,
            history_count=len(self.history),
        )

        commands = list(self.pending_commands)
        self.pending_commands.clear()
        command_suggestions: list[ObjectiveSuggestion] = []
        for command in commands:
            command_suggestions.extend(await self.llm_advisor.interpret_command(command, self.goals, self.current_objectives))

        all_suggestions = rule_suggestions + llm_suggestions + command_suggestions
        next_objectives = self._apply_suggestions(self.current_objectives, all_suggestions)

        await self._emit("iteration_progress", {"step": "simulate_dvh"})
        next_dvh_data = self.simulation_engine.simulate_next(
            iteration_number=self.iteration_number,
            current_dvh_data=self.current_dvh_data,
            current_objectives=next_objectives,
            suggestions=all_suggestions,
            current_goal_status=current_goal_status,
        )
        next_goal_status = build_goal_statuses(self.goals, next_dvh_data)
        next_results = build_objective_results(next_objectives, next_dvh_data)
        reference_gap, comparison_metrics, comparison_summary = build_reference_comparison(
            goals=self.goals,
            start_goal_status=self.start_goal_status,
            current_goal_status=next_goal_status,
            reference_goal_status=self.reference_goal_status,
            current_dvh_data=next_dvh_data,
            reference_dvh_data=self.reference_dvh_data,
            current_label=f"Simulated Iteration {self.iteration_number}",
            reference_label=f"Observed Iteration {self.reference_iteration_number}",
        )

        thinking_log = self._build_thinking_log(
            current_goal_status=current_goal_status,
            next_goal_status=next_goal_status,
            suggestions=all_suggestions,
            commands=commands,
            reference_gap=reference_gap,
        )
        await self._emit("thinking", {"visible": True, "content": thinking_log})
        await self._emit("suggestion_preview", {"suggestions": [item.model_dump() for item in all_suggestions]})

        previous_goals_fulfilled = sum(1 for item in current_goal_status if item.passed)
        goals_fulfilled = sum(1 for item in next_goal_status if item.passed)
        goal_delta = goals_fulfilled - previous_goals_fulfilled

        self.current_objectives = next_objectives
        self.current_dvh_data = next_dvh_data
        connector_state = await self._connector_state()
        iteration = OptimizationIteration(
            number=self.iteration_number,
            status="completed",
            bundle_kind="simulated",
            source_iteration_number=self.start_iteration_number,
            goals_fulfilled=goals_fulfilled,
            goals_total=len(next_goal_status),
            improvement_summary=(
                f"Simulated Iteration #{self.iteration_number}: {goals_fulfilled}/{len(next_goal_status)} planning goals fulfilled. "
                f"Reference gap {reference_gap.overall_percent:.1f}%."
            ),
            goal_status=next_goal_status,
            suggestions=all_suggestions,
            objectives_snapshot=deepcopy(self.current_objectives),
            objective_results=deepcopy(next_results),
            dvh_data=deepcopy(next_dvh_data),
            user_commands=commands,
            thinking_log=thinking_log,
            reference_gap=reference_gap,
            comparison_metrics=comparison_metrics,
        )
        self.history.append(iteration)
        await self._emit(
            "iteration_complete",
            {
                "iteration": iteration.model_dump(),
                "objective_results": [item.model_dump() for item in next_results],
                "dvh_data": [item.model_dump() for item in next_dvh_data],
                "connector_state": connector_state,
                "bundle_kind": "simulated",
                "reference_gap": reference_gap.model_dump(),
                "goal_delta": goal_delta,
                "comparison_metrics": [item.model_dump() for item in comparison_metrics],
                "comparison_summary": comparison_summary.model_dump(),
            },
        )
        return iteration

    async def run_loop(self) -> str:
        plateau_count = 0
        previous_fulfilled = self.history[-1].goals_fulfilled if self.history else sum(
            1 for item in self.start_goal_status if item.passed
        )
        previous_gap = self.history[-1].reference_gap.overall_percent if self.history else None

        while not self.stopped and self.iteration_number < self.max_iterations:
            while self.paused and not self.stopped:
                await asyncio.sleep(0.2)
            if self.stopped:
                await self._emit("session_complete", {"reason": "stopped"})
                return "stopped"

            iteration = await self.run_iteration()
            if iteration.goals_fulfilled == iteration.goals_total and iteration.goals_total > 0:
                await self._emit("session_complete", {"reason": "all_goals_met"})
                return "all_goals_met"

            current_gap = iteration.reference_gap.overall_percent
            if previous_gap is not None and abs(previous_gap - current_gap) < 0.12:
                plateau_count += 1
            elif iteration.goals_fulfilled <= previous_fulfilled:
                plateau_count += 1
            else:
                plateau_count = 0

            if self.iteration_number >= 10 and plateau_count >= self.plateau_threshold:
                await self._emit("session_complete", {"reason": "plateau"})
                return "plateau"

            previous_fulfilled = iteration.goals_fulfilled
            previous_gap = current_gap

        reason = "stopped" if self.stopped else "max_iterations"
        await self._emit("session_complete", {"reason": reason})
        return reason

    def _build_thinking_log(
        self,
        *,
        current_goal_status: list[GoalStatus],
        next_goal_status: list[GoalStatus],
        suggestions: list[ObjectiveSuggestion],
        commands: list[str],
        reference_gap: ReferenceGapSummary,
    ) -> str:
        lines = [f"Simulated iteration #{self.iteration_number}", ""]
        lines.append("Current goal status:")
        for status in current_goal_status:
            actual = "n/a" if status.actual_value is None else f"{status.actual_value:.2f}"
            lines.append(f"  [{'PASS' if status.passed else 'FAIL'}] {status.roi} {status.metric} -> {actual} {status.unit}")
        if commands:
            lines.append("")
            lines.append("Planner commands:")
            lines.extend([f"  - {command}" for command in commands])
        if suggestions:
            lines.append("")
            lines.append("Merged suggestions:")
            lines.extend([f"  - {item.action} {item.objective.roi}: {item.reason}" for item in suggestions])
        lines.append("")
        lines.append("Predicted next status:")
        for status in next_goal_status:
            actual = "n/a" if status.actual_value is None else f"{status.actual_value:.2f}"
            lines.append(f"  [{'PASS' if status.passed else 'FAIL'}] {status.roi} {status.metric} -> {actual} {status.unit}")
        lines.append("")
        lines.append(
            f"Reference gap: overall {reference_gap.overall_percent:.2f}%, "
            f"DVH {reference_gap.dvh_gap_percent:.2f}%, metric {reference_gap.metric_gap_percent:.2f}%, "
            f"agreement {reference_gap.goal_agreement_percent:.2f}%."
        )
        return "\n".join(lines)

    @staticmethod
    def _apply_suggestions(objectives: list[PlanObjective], suggestions: list[ObjectiveSuggestion]) -> list[PlanObjective]:
        updated = deepcopy(objectives)
        for suggestion in suggestions:
            key = (suggestion.objective.roi, suggestion.objective.objective_type)
            index = next((position for position, objective in enumerate(updated) if (objective.roi, objective.objective_type) == key), None)
            if suggestion.action == "remove":
                updated = [objective for objective in updated if (objective.roi, objective.objective_type) != key]
                continue
            if index is None:
                updated.append(suggestion.objective)
            else:
                updated[index] = suggestion.objective
        return updated
