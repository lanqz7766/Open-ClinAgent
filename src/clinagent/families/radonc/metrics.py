from __future__ import annotations

import math

from clinagent.families.radonc.models import DVHSnapshot, GoalStatus, PlanGoal, PlanObjective


def _interpolate(x1: float, y1: float, x2: float, y2: float, x: float) -> float:
    if math.isclose(x1, x2):
        return y2
    ratio = (x - x1) / (x2 - x1)
    return y1 + ratio * (y2 - y1)


def volume_at_dose(dvh: DVHSnapshot, dose_threshold: float) -> float:
    doses = dvh.dose_points
    volumes = dvh.volume_points
    if not doses:
        return 0.0
    if dose_threshold <= doses[0]:
        return volumes[0]
    for index in range(1, len(doses)):
        if dose_threshold <= doses[index]:
            return max(0.0, _interpolate(doses[index - 1], volumes[index - 1], doses[index], volumes[index], dose_threshold))
    return max(0.0, volumes[-1])


def dose_at_volume(dvh: DVHSnapshot, volume_threshold: float) -> float:
    doses = dvh.dose_points
    volumes = dvh.volume_points
    if not doses:
        return 0.0
    if volume_threshold >= volumes[0]:
        return doses[0]
    for index in range(1, len(volumes)):
        if volume_threshold >= volumes[index]:
            return max(0.0, _interpolate(volumes[index - 1], doses[index - 1], volumes[index], doses[index], volume_threshold))
    return max(0.0, doses[-1])


def compute_dmax(dvh: DVHSnapshot) -> float:
    for dose, volume in reversed(list(zip(dvh.dose_points, dvh.volume_points, strict=False))):
        if volume > 0.01:
            return dose
    return dvh.dose_points[-1] if dvh.dose_points else 0.0


def compute_dmean(dvh: DVHSnapshot) -> float:
    doses = dvh.dose_points
    volumes = dvh.volume_points
    if len(doses) < 2:
        return doses[0] if doses else 0.0
    area = 0.0
    for index in range(1, len(doses)):
        delta_dose = doses[index] - doses[index - 1]
        mean_volume_fraction = ((volumes[index - 1] / 100.0) + (volumes[index] / 100.0)) / 2.0
        area += delta_dose * mean_volume_fraction
    return area


def evaluate_goal(goal: PlanGoal, dvh: DVHSnapshot) -> GoalStatus:
    metric = goal.metric.lower()
    actual_value = 0.0
    unit = goal.unit

    if metric == "dmax":
        actual_value = compute_dmax(dvh)
    elif metric == "dmean":
        actual_value = compute_dmean(dvh)
    elif metric.startswith("v") and metric.endswith("cgy"):
        actual_value = volume_at_dose(dvh, float(metric[1:-3]))
        unit = "%"
    elif metric.startswith("d"):
        try:
            volume_value = float(metric[1:])
        except ValueError:
            volume_value = goal.value
        actual_value = dose_at_volume(dvh, volume_value)
        unit = "cGy"

    passed = actual_value <= goal.value if goal.operator == "<=" else actual_value >= goal.value
    return GoalStatus(
        roi=goal.roi,
        metric=goal.metric,
        operator=goal.operator,
        target_value=goal.value,
        unit=unit,
        actual_value=round(actual_value, 2),
        passed=passed,
        priority=goal.priority,
    )


def evaluate_objective(objective: PlanObjective, dvh: DVHSnapshot) -> tuple[bool, float | None, str]:
    kind = objective.objective_type.lower()
    if kind == "max dose":
        actual = compute_dmax(dvh)
        return actual <= objective.dose, actual, "cGy"
    if kind == "mean dose":
        actual = compute_dmean(dvh)
        return actual <= objective.dose, actual, "cGy"
    if kind == "max eud":
        actual = compute_dmean(dvh)
        return actual <= objective.dose, actual, "cGy"
    if kind == "volume at dose":
        actual = volume_at_dose(dvh, objective.dose)
        target = objective.volume or 0.0
        return actual <= target, actual, "%"
    if kind == "min coverage":
        actual = volume_at_dose(dvh, objective.dose)
        target = objective.volume or 95.0
        return actual >= target, actual, "%"
    if kind == "max dvh":
        if (objective.volume_unit or "%").lower() != "%":
            return False, None, objective.volume_unit
        actual = volume_at_dose(dvh, objective.dose)
        target = objective.volume or 0.0
        return actual <= target, actual, "%"
    if kind == "min dvh":
        if (objective.volume_unit or "%").lower() != "%":
            return False, None, objective.volume_unit
        actual = volume_at_dose(dvh, objective.dose)
        target = objective.volume or 0.0
        return actual >= target, actual, "%"
    actual = compute_dmean(dvh)
    return actual <= objective.dose, actual, "cGy"
