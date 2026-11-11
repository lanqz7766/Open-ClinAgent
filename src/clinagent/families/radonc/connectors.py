from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
import math
from pathlib import Path
from typing import Any

from clinagent.families.radonc.airt import default_airt_patient_dir, discover_airt_iterations, load_airt_iteration_bundle
from clinagent.families.radonc.metrics import evaluate_goal, evaluate_objective
from clinagent.families.radonc.models import DVHSnapshot, GoalStatus, ObjectiveResult, PlanObjective, PlanOptimizationSession


class RTPlanningConnector(ABC):
    @abstractmethod
    async def get_dvh(self) -> list[DVHSnapshot]:
        ...

    @abstractmethod
    async def get_goal_status(self) -> list[GoalStatus]:
        ...

    @abstractmethod
    async def get_results(self) -> list[ObjectiveResult]:
        ...

    @abstractmethod
    async def get_objectives(self) -> list[PlanObjective]:
        ...

    @abstractmethod
    async def submit_objectives(self, objectives: list[PlanObjective]) -> None:
        ...

    @abstractmethod
    async def get_plan_metadata(self) -> dict[str, Any]:
        ...


class AirtMockPlanningConnector(RTPlanningConnector):
    def __init__(
        self,
        *,
        patient_dir: Path | str | None = None,
        start_iteration: int | None = None,
        current_objectives: list[PlanObjective] | None = None,
        data_source_id: str = "Patient001",
    ) -> None:
        self._patient_dir = Path(patient_dir or default_airt_patient_dir())
        self._available_iterations = discover_airt_iterations(self._patient_dir)
        if not self._available_iterations:
            raise ValueError(f"No AIRT mock iterations found under {self._patient_dir}")
        self._start_iteration_number = start_iteration if start_iteration in self._available_iterations else self._available_iterations[0]
        self._reference_iteration_number = self._available_iterations[-1]
        self._start_bundle = load_airt_iteration_bundle(self._patient_dir, self._start_iteration_number)
        self._reference_bundle = load_airt_iteration_bundle(self._patient_dir, self._reference_iteration_number)
        self._current_objectives = deepcopy(current_objectives or self._start_bundle.output_objectives or self._start_bundle.input_objectives)
        self._data_source_id = data_source_id
        self._last_submitted_objectives = deepcopy(self._current_objectives)
        self._simulation_iteration = 0

    async def get_dvh(self) -> list[DVHSnapshot]:
        return deepcopy(self._start_bundle.dvh_data)

    async def get_goal_status(self) -> list[GoalStatus]:
        return deepcopy(self._start_bundle.goal_status)

    async def get_results(self) -> list[ObjectiveResult]:
        dvh_map = {item.roi: item for item in self._start_bundle.dvh_data}
        results: list[ObjectiveResult] = []
        for objective in self._current_objectives:
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

    async def get_objectives(self) -> list[PlanObjective]:
        return deepcopy(self._current_objectives)

    async def submit_objectives(self, objectives: list[PlanObjective]) -> None:
        self._last_submitted_objectives = deepcopy(objectives)
        self._current_objectives = deepcopy(objectives)
        self._simulation_iteration += 1

    async def get_plan_metadata(self) -> dict[str, Any]:
        return {
            **self._start_bundle.plan_metadata,
            "connector_label": "AIRT mock connector",
            "data_source_id": self._data_source_id,
            "connector_state": {
                "bundle_kind": "observed",
                "current_iteration": self._start_iteration_number,
                "reference_iteration": self._reference_iteration_number,
                "available_iterations": deepcopy(self._available_iterations),
                "simulation_iteration": self._simulation_iteration,
                "next_iteration_available": True,
                "replay_exhausted": False,
                "can_run_current": True,
            },
        }

    async def get_reference_dvh(self) -> list[DVHSnapshot]:
        return deepcopy(self._reference_bundle.dvh_data)

    async def get_reference_goal_status(self) -> list[GoalStatus]:
        return deepcopy(self._reference_bundle.goal_status)

    async def get_reference_objectives(self) -> list[PlanObjective]:
        return deepcopy(self._reference_bundle.output_objectives)

    async def get_reference_results(self) -> list[ObjectiveResult]:
        return deepcopy(self._reference_bundle.objective_results)


class MockRTPlanningConnector(RTPlanningConnector):
    def __init__(self, session: PlanOptimizationSession):
        self._session = session

    async def get_dvh(self) -> list[DVHSnapshot]:
        return [self._build_dvh(roi, metrics) for roi, metrics in self._session.current_metrics.items()]

    async def get_goal_status(self) -> list[GoalStatus]:
        dvh_map = {item.roi: item for item in await self.get_dvh()}
        return [evaluate_goal(goal, dvh_map[goal.roi]) for goal in self._session.goals if goal.roi in dvh_map]

    async def get_results(self) -> list[ObjectiveResult]:
        dvh_map = {item.roi: item for item in await self.get_dvh()}
        results: list[ObjectiveResult] = []
        for objective in self._session.current_objectives:
            dvh = dvh_map.get(objective.roi)
            if dvh is None:
                continue
            fulfilled, actual, unit = evaluate_objective(objective, dvh)
            results.append(
                ObjectiveResult(
                    objective=objective,
                    fulfilled=fulfilled,
                    actual_value=None if actual is None else round(actual, 2),
                    unit=unit,
                )
            )
        return results

    async def get_objectives(self) -> list[PlanObjective]:
        return deepcopy(self._session.current_objectives)

    async def submit_objectives(self, objectives: list[PlanObjective]) -> None:
        self._session.current_objectives = deepcopy(objectives)
        self._session.current_metrics = self._derive_metrics(objectives)

    async def get_plan_metadata(self) -> dict[str, Any]:
        return deepcopy(self._session.plan_metadata)

    def _build_dvh(self, roi: str, metrics: dict[str, Any]) -> DVHSnapshot:
        max_grid = float(self._session.plan_metadata.get("dose_grid_max_cgy", 7000))
        doses = [float(index * 100) for index in range(int(max_grid / 100) + 1)]
        if metrics.get("kind") == "target":
            coverage = float(metrics.get("coverage_dose", 5600))
            sharpness = float(metrics.get("sharpness", 120))
            hotspot = float(metrics.get("max_dose", coverage + 450))
            volumes = [100.0 / (1.0 + math.exp((dose - coverage) / max(sharpness, 1.0))) for dose in doses]
            volumes = [max(0.0, min(100.0, value)) if dose <= hotspot else 0.0 for dose, value in zip(doses, volumes, strict=False)]
        else:
            mean_dose = float(metrics.get("mean_dose", 1000))
            max_dose = float(metrics.get("max_dose", mean_dose * 1.8))
            decay_power = float(metrics.get("decay_power", 1.28))
            volumes = []
            for dose in doses:
                if dose >= max_dose:
                    volumes.append(0.0)
                    continue
                normalized = max(dose / max(mean_dose, 1.0), 0.0)
                value = 100.0 * math.exp(-(normalized**decay_power))
                volumes.append(max(0.0, min(100.0, value)))
        return DVHSnapshot(roi=roi, dose_points=doses, volume_points=[round(value, 3) for value in volumes])

    def _derive_metrics(self, objectives: list[PlanObjective]) -> dict[str, dict[str, Any]]:
        metrics = deepcopy(self._session.base_metrics)
        target_pressure = 0.0
        oar_pressure = 0.0

        for objective in objectives:
            roi_metrics = metrics.get(objective.roi)
            if roi_metrics is None:
                continue
            if roi_metrics.get("kind") == "target":
                target_pressure += objective.weight
                current_coverage = float(roi_metrics.get("coverage_dose", objective.dose))
                desired_coverage = float(objective.dose)
                boost = min(110.0, 18.0 + objective.weight * 24.0)
                roi_metrics["coverage_dose"] = min(desired_coverage + 80.0, current_coverage + boost)
                roi_metrics["max_dose"] = max(float(roi_metrics.get("max_dose", desired_coverage + 500.0)), roi_metrics["coverage_dose"] + 350.0)
                continue

            oar_pressure += objective.weight
            metric_key = "mean_dose"
            if objective.objective_type.lower() == "max dose":
                metric_key = "max_dose"
            current_value = float(roi_metrics.get(metric_key, objective.dose))
            target_value = float(objective.dose if objective.objective_type.lower() != "volume at dose" else roi_metrics.get("mean_dose", objective.dose))
            reduction_factor = min(0.52, 0.12 + objective.weight * 0.08)
            roi_metrics[metric_key] = max(target_value * 0.88, current_value - (current_value - target_value) * reduction_factor if current_value > target_value else current_value * 0.96)
            if objective.objective_type.lower() == "volume at dose":
                roi_metrics["mean_dose"] = max(target_value * 0.82, float(roi_metrics.get("mean_dose", target_value)) * (0.93 - min(objective.weight * 0.015, 0.08)))
                roi_metrics["max_dose"] = max(target_value * 1.35, float(roi_metrics.get("max_dose", target_value * 1.6)) * (0.95 - min(objective.weight * 0.01, 0.05)))
            elif metric_key == "mean_dose":
                roi_metrics["max_dose"] = max(float(roi_metrics["mean_dose"]) * 1.45, float(roi_metrics.get("max_dose", target_value * 1.5)) * 0.97)

        pressure_gap = max(0.0, oar_pressure - target_pressure * 0.85)
        spillover = max(0.0, target_pressure - oar_pressure)
        iteration_bonus = max(0, len(self._session.iterations)) * 14.0

        for roi, roi_metrics in metrics.items():
            if roi_metrics.get("kind") == "target":
                roi_metrics["coverage_dose"] = max(5200.0, float(roi_metrics.get("coverage_dose", 5600.0)) - pressure_gap * 18.0 + iteration_bonus)
                roi_metrics["max_dose"] = max(float(roi_metrics["coverage_dose"]) + 320.0, float(roi_metrics.get("max_dose", 6500.0)) + spillover * 10.0)
            else:
                roi_metrics["mean_dose"] = max(150.0, float(roi_metrics.get("mean_dose", 1000.0)) + spillover * 12.0 - iteration_bonus * 0.65)
                roi_metrics["max_dose"] = max(float(roi_metrics["mean_dose"]) * 1.3, float(roi_metrics.get("max_dose", 1800.0)) + spillover * 18.0 - iteration_bonus)

        return metrics
