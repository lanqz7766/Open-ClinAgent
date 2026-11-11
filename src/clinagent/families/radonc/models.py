from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


SuggestionAction = Literal["add", "modify", "remove"]
ControlMode = Literal["auto", "supervised", "manual"]
SessionStatus = Literal["ready", "running", "paused", "stopped", "completed", "error"]
GoalSource = Literal["protocol", "user", "agent"]
BundleKind = Literal["observed", "simulated"]


class PlanGoal(BaseModel):
    roi: str
    metric: str
    operator: Literal["<=", ">="]
    value: float
    unit: str
    priority: int = 2
    source: GoalSource = "protocol"


class PlanObjective(BaseModel):
    roi: str
    objective_type: str
    dose: float
    volume: float | None = None
    volume_unit: str = "%"
    weight: float = 1.0
    priority: int = 2


class ObjectiveSuggestion(BaseModel):
    action: SuggestionAction
    objective: PlanObjective
    reason: str
    confidence: float
    source: str


class DVHSnapshot(BaseModel):
    roi: str
    dose_points: list[float]
    volume_points: list[float]


class GoalStatus(BaseModel):
    roi: str
    metric: str
    operator: str
    target_value: float
    unit: str
    actual_value: float | None = None
    passed: bool = False
    priority: int = 2


class ObjectiveResult(BaseModel):
    objective: PlanObjective
    fulfilled: bool
    actual_value: float | None = None
    unit: str


class PlannerCommand(BaseModel):
    id: str = Field(default_factory=lambda: f"cmd_{uuid4().hex[:10]}")
    text: str
    created_at: str = Field(default_factory=utc_now_iso)
    status: str = "queued"
    response_text: str | None = None
    effect_summary: str | None = None
    applied_changes: list[str] = Field(default_factory=list)
    applied_in_iteration: int | None = None
    run_after_apply: bool = False


class ReferenceGapSummary(BaseModel):
    overall_percent: float = 0.0
    dvh_gap_percent: float = 0.0
    metric_gap_percent: float = 0.0
    goal_agreement_percent: float = 100.0


class ComparisonMetric(BaseModel):
    roi: str
    metric: str
    unit: str
    start_value: float | None = None
    current_value: float | None = None
    reference_value: float | None = None
    delta_to_reference: float | None = None
    passed: bool = False
    reference_passed: bool = False
    agreement: bool = True


class BundleSummary(BaseModel):
    label: str
    bundle_kind: BundleKind
    iteration_number: int
    goals_fulfilled: int
    goals_total: int
    description: str = ""


class ComparisonSummary(BaseModel):
    clinical_completion_percent: float = 0.0
    reference_proximity_percent: float = 100.0
    overall_completion_percent: float = 0.0
    goal_agreement_percent: float = 100.0
    dvh_gap_percent: float = 0.0
    metric_gap_percent: float = 0.0
    current_label: str = ""
    reference_label: str = ""


class OptimizationIteration(BaseModel):
    number: int
    status: str
    bundle_kind: BundleKind = "simulated"
    source_iteration_number: int | None = None
    goals_fulfilled: int
    goals_total: int
    improvement_summary: str
    goal_status: list[GoalStatus] = Field(default_factory=list)
    suggestions: list[ObjectiveSuggestion] = Field(default_factory=list)
    objectives_snapshot: list[PlanObjective] = Field(default_factory=list)
    objective_results: list[ObjectiveResult] = Field(default_factory=list)
    dvh_data: list[DVHSnapshot] = Field(default_factory=list)
    user_commands: list[str] = Field(default_factory=list)
    thinking_log: str = ""
    reference_gap: ReferenceGapSummary = Field(default_factory=ReferenceGapSummary)
    comparison_metrics: list[ComparisonMetric] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)


class StopCondition(BaseModel):
    reason: str
    reached: bool = False


class PlanOptimizationSession(BaseModel):
    id: str
    title: str
    subtitle: str
    patient_label: str
    treatment_site: str
    protocol_name: str
    status: SessionStatus = "ready"
    control_mode: ControlMode = "auto"
    show_thinking: bool = True
    connector_type: str = "mock"
    connector_writable: bool = True
    data_source_type: Literal["synthetic_mock", "airt_mock"] = "synthetic_mock"
    data_source_id: str = "default"
    available_iterations: list[int] = Field(default_factory=list)
    start_iteration_number: int = 1
    reference_iteration_number: int = 2
    simulation_enabled: bool = False
    simulation_max_iterations: int = 20
    simulation_reference_mode: str = "iter1_iter2_reference"
    connector_state: dict[str, Any] = Field(default_factory=dict)
    max_iterations: int = 8
    plateau_threshold: int = 2
    title_badge: str = "RadOnc flagship"
    risk_tier: str = "watch"
    risk_reason: str = ""
    summary_cards: list[dict[str, str]] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    report_summary: str = ""
    report_preview: str = ""
    latest_thinking_log: str = ""
    goals: list[PlanGoal] = Field(default_factory=list)
    goal_status: list[GoalStatus] = Field(default_factory=list)
    start_goal_status: list[GoalStatus] = Field(default_factory=list)
    reference_goal_status: list[GoalStatus] = Field(default_factory=list)
    current_objectives: list[PlanObjective] = Field(default_factory=list)
    start_objectives: list[PlanObjective] = Field(default_factory=list)
    reference_objectives: list[PlanObjective] = Field(default_factory=list)
    latest_suggestions: list[ObjectiveSuggestion] = Field(default_factory=list)
    dvh_data: list[DVHSnapshot] = Field(default_factory=list)
    start_dvh_data: list[DVHSnapshot] = Field(default_factory=list)
    reference_dvh_data: list[DVHSnapshot] = Field(default_factory=list)
    objective_results: list[ObjectiveResult] = Field(default_factory=list)
    start_objective_results: list[ObjectiveResult] = Field(default_factory=list)
    reference_objective_results: list[ObjectiveResult] = Field(default_factory=list)
    iterations: list[OptimizationIteration] = Field(default_factory=list)
    command_history: list[PlannerCommand] = Field(default_factory=list)
    messages: list[dict[str, str]] = Field(default_factory=list)
    plan_metadata: dict[str, Any] = Field(default_factory=dict)
    reference_bundle_summary: BundleSummary | None = None
    comparison_summary: ComparisonSummary = Field(default_factory=ComparisonSummary)
    comparison_metrics: list[ComparisonMetric] = Field(default_factory=list)
    base_metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    current_metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    planning_result: dict[str, Any] | None = None
    workspace_contract: dict[str, Any] | None = None
    analysis_plan: dict[str, Any] | None = None
    capability_profile: dict[str, Any] | None = None
    updated_at: str = Field(default_factory=utc_now_iso)
