import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react"
import { Pause, Play, RotateCcw, Send, Square, WandSparkles } from "lucide-react"
import Plotly from "plotly.js-basic-dist-min"
import { useNavigate, useSearchParams } from "react-router-dom"

import { RiskBadge, type RiskTier } from "@/components/RiskBadge"
import { SummaryMetric } from "@/components/SummaryMetric"
import { WorkspacePanel } from "@/components/WorkspacePanel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { useApi } from "@/hooks/useApi"
import { cn } from "@/lib/utils"

type GoalStatus = {
  roi: string
  metric: string
  operator: string
  target_value: number
  unit: string
  actual_value?: number | null
  passed: boolean
  priority: number
}

type PlanObjective = {
  roi: string
  objective_type: string
  dose: number
  volume?: number | null
  volume_unit?: string
  weight: number
  priority: number
}

type ObjectiveSuggestion = {
  action: string
  reason: string
  confidence: number
  source: string
  objective: PlanObjective
}

type ObjectiveResult = {
  objective: PlanObjective
  fulfilled: boolean
  actual_value?: number | null
  unit: string
}

type DVHSnapshot = {
  roi: string
  dose_points: number[]
  volume_points: number[]
}

type ReferenceGapSummary = {
  overall_percent: number
  dvh_gap_percent: number
  metric_gap_percent: number
  goal_agreement_percent: number
}

type ComparisonMetric = {
  roi: string
  metric: string
  unit: string
  start_value?: number | null
  current_value?: number | null
  reference_value?: number | null
  delta_to_reference?: number | null
  passed: boolean
  reference_passed: boolean
  agreement: boolean
}

type ComparisonSummary = {
  clinical_completion_percent: number
  reference_proximity_percent: number
  overall_completion_percent: number
  goal_agreement_percent: number
  dvh_gap_percent: number
  metric_gap_percent: number
  current_label: string
  reference_label: string
}

type BundleSummary = {
  label: string
  bundle_kind: "observed" | "simulated"
  iteration_number: number
  goals_fulfilled: number
  goals_total: number
  description: string
}

type OptimizationIteration = {
  number: number
  status: string
  bundle_kind: "observed" | "simulated"
  source_iteration_number?: number | null
  goals_fulfilled: number
  goals_total: number
  improvement_summary: string
  thinking_log: string
  user_commands: string[]
  created_at: string
  goal_status: GoalStatus[]
  objectives_snapshot: PlanObjective[]
  objective_results: ObjectiveResult[]
  dvh_data: DVHSnapshot[]
  suggestions: ObjectiveSuggestion[]
  reference_gap: ReferenceGapSummary
  comparison_metrics: ComparisonMetric[]
}

type PlannerCommand = {
  id: string
  text: string
  created_at: string
  status: string
  response_text?: string | null
  effect_summary?: string | null
  applied_changes: string[]
  applied_in_iteration?: number | null
  run_after_apply?: boolean
}

type ConnectorState = {
  bundle_kind?: "observed" | "simulated"
  current_iteration?: number
  reference_iteration?: number
  current_simulated_iteration?: number
  next_iteration_available?: boolean
  available_iterations?: number[]
  replay_exhausted?: boolean
}

type RadOncSession = {
  id: string
  title: string
  subtitle: string
  patient_label: string
  treatment_site: string
  protocol_name: string
  status: "ready" | "running" | "paused" | "stopped" | "completed" | "error"
  control_mode: "auto" | "supervised" | "manual"
  connector_type: string
  connector_writable: boolean
  show_thinking: boolean
  title_badge: string
  risk_tier: RiskTier
  risk_reason: string
  summary_cards: Array<{ label: string; value: string }>
  recommended_actions: string[]
  report_summary: string
  report_preview: string
  latest_thinking_log: string
  goals: Array<{ roi: string; metric: string; operator: string; value: number; unit: string }>
  goal_status: GoalStatus[]
  start_goal_status: GoalStatus[]
  reference_goal_status: GoalStatus[]
  current_objectives: PlanObjective[]
  start_objectives: PlanObjective[]
  reference_objectives: PlanObjective[]
  latest_suggestions: ObjectiveSuggestion[]
  objective_results: ObjectiveResult[]
  start_objective_results: ObjectiveResult[]
  reference_objective_results: ObjectiveResult[]
  dvh_data: DVHSnapshot[]
  start_dvh_data: DVHSnapshot[]
  reference_dvh_data: DVHSnapshot[]
  iterations: OptimizationIteration[]
  command_history: PlannerCommand[]
  messages: Array<{ role: string; content: string }>
  plan_metadata: Record<string, string | number>
  data_source_type: "synthetic_mock" | "airt_mock"
  data_source_id: string
  available_iterations: number[]
  start_iteration_number: number
  reference_iteration_number: number
  simulation_enabled: boolean
  simulation_max_iterations: number
  simulation_reference_mode: string
  connector_state: ConnectorState
  reference_bundle_summary?: BundleSummary | null
  comparison_summary: ComparisonSummary
  comparison_metrics: ComparisonMetric[]
}

type RadOncPatient = {
  id: string
  label: string
  source: string
  available_iterations: number[]
  default_session_id: string
  status: string
  risk_tier: RiskTier
}

type RadOncPatientsPayload = {
  default_patient_id: string
  default_session_id: string
  patients: RadOncPatient[]
}

type RadOncSnapshot = {
  default_patient_id: string
  default_session_id: string
  active_patient_id: string
  patients: RadOncPatient[]
  session: RadOncSession
}

type WsEvent =
  | { type: "session_snapshot"; session: RadOncSession }
  | { type: "thinking"; visible?: boolean; content?: string }
  | { type: "iteration_complete" }
  | { type: "status_change"; status: string }
  | { type: "session_complete"; reason?: string }
  | { type: "agent_message"; role?: string; content?: string }

type PlotFigure = {
  data: Array<Record<string, unknown>>
  layout: Record<string, unknown>
  config: Record<string, unknown>
}

type PlotlyClient = {
  Plots?: { resize?: (element: HTMLDivElement) => void }
  purge: (element: HTMLDivElement) => void
  react: (
    element: HTMLDivElement,
    data: PlotFigure["data"],
    layout: PlotFigure["layout"],
    config?: PlotFigure["config"],
  ) => void | Promise<void>
}

type CompareMode = "current" | "reference" | "overlay"
type TimelineFilter = "all" | "observed" | "simulated"
type SelectedBundle = {
  key: string
  label: string
  description: string
  bundleKind: "observed" | "simulated"
  goalStatus: GoalStatus[]
  objectives: PlanObjective[]
  objectiveResults: ObjectiveResult[]
  dvhData: DVHSnapshot[]
  thinkingLog: string
  suggestions: ObjectiveSuggestion[]
  goalsFulfilled: number
  goalsTotal: number
  referenceGap: ReferenceGapSummary
  comparisonMetrics: ComparisonMetric[]
  createdAt?: string
  userCommands?: string[]
}

type ObjectiveDraft = {
  dose: string
  weight: string
}

const plotlyClient = Plotly as unknown as PlotlyClient
const palette = ["#d4673b", "#3799b3", "#3f8a63", "#d0a42b", "#b4577d", "#8767c9", "#4a806f", "#c66f91"]

function formatNumber(value?: number | null, digits = 1) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "—"
  }
  return value.toFixed(digits)
}

function formatPercent(value?: number | null, digits = 1) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "—"
  }
  return `${value.toFixed(digits)}%`
}

function formatTimestamp(value?: string) {
  if (!value) {
    return "Observed"
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
}

function formatStatusLabel(status: RadOncSession["status"]) {
  return status.replaceAll("_", " ")
}

function describeControlMode(mode: RadOncSession["control_mode"]) {
  if (mode === "auto") {
    return "Auto mode keeps iterating until goals are met, the loop is paused, or the simulation limit is reached."
  }
  if (mode === "supervised") {
    return "Supervised mode runs one simulated step, pauses, and waits for review before the next step."
  }
  return "Manual mode only advances when you explicitly run the next simulated iteration."
}

function describeControlState(session: RadOncSession, socketConnected: boolean) {
  if (!socketConnected) {
    return "Live controls are offline. Wait for the workspace socket before sending planner actions."
  }
  if (session.status === "completed") {
    return "Simulation is complete. Review the final DVH trajectory or reset to restart from the observed start bundle."
  }
  if (session.control_mode === "auto") {
    if (session.status === "running") {
      return "Auto mode is actively iterating. Pause to inspect the current step or Stop to freeze the loop."
    }
    if (session.status === "paused") {
      return "Auto mode is paused. Resume continues the continuous optimization loop."
    }
    return "Auto mode is idle. Start begins the continuous optimization loop from the current workspace state."
  }
  if (session.control_mode === "supervised") {
    if (session.status === "paused") {
      return "Supervised mode is paused after one reviewed step. Next Step runs one more simulated update."
    }
    return "Supervised mode is idle. Start Review runs a single step and then pauses for review."
  }
  return "Manual mode is idle. Run Iteration executes exactly one simulated step and then returns to ready."
}

function commandStatusTone(status: string): "default" | "secondary" | "outline" | "destructive" {
  if (status === "executed") {
    return "default"
  }
  if (status === "applied") {
    return "secondary"
  }
  if (status === "ignored") {
    return "destructive"
  }
  return "outline"
}

function formatCommandStatusLabel(status: string) {
  if (status === "executed") {
    return "executed"
  }
  if (status === "applied") {
    return "applied"
  }
  if (status === "ignored") {
    return "not mapped"
  }
  return "queued"
}

function objectiveKey(objective: Pick<PlanObjective, "roi" | "objective_type">) {
  return `${objective.roi}::${objective.objective_type}`
}

function buildDerivedComparisonMetrics({
  goals,
  startGoalStatus,
  currentGoalStatus,
  referenceGoalStatus,
}: {
  goals: RadOncSession["goals"]
  startGoalStatus: GoalStatus[]
  currentGoalStatus: GoalStatus[]
  referenceGoalStatus: GoalStatus[]
}): ComparisonMetric[] {
  const startMap = new Map(startGoalStatus.map((item) => [`${item.roi}::${item.metric}`, item]))
  const currentMap = new Map(currentGoalStatus.map((item) => [`${item.roi}::${item.metric}`, item]))
  const referenceMap = new Map(referenceGoalStatus.map((item) => [`${item.roi}::${item.metric}`, item]))
  const metrics: ComparisonMetric[] = []
  for (const goal of goals) {
    const key = `${goal.roi}::${goal.metric}`
    const start = startMap.get(key)
    const current = currentMap.get(key)
    const reference = referenceMap.get(key)
    if (!current || !reference) {
      continue
    }
    const delta =
      typeof current.actual_value === "number" && typeof reference.actual_value === "number"
        ? Number((current.actual_value - reference.actual_value).toFixed(2))
        : null
    metrics.push({
      roi: goal.roi,
      metric: goal.metric,
      unit: current.unit || reference.unit || goal.unit,
      start_value: start?.actual_value ?? null,
      current_value: current.actual_value ?? null,
      reference_value: reference.actual_value ?? null,
      delta_to_reference: delta,
      passed: current.passed,
      reference_passed: reference.passed,
      agreement: current.passed === reference.passed,
    })
  }
  return metrics
}

function buildDerivedComparisonSummary(metrics: ComparisonMetric[], currentGoalStatus: GoalStatus[]) {
  const metricGapSamples = metrics
    .filter((item) => typeof item.delta_to_reference === "number" && typeof item.reference_value === "number")
    .map((item) => Math.abs(item.delta_to_reference ?? 0) / Math.max(Math.abs(item.reference_value ?? 0), 1))
  const metricGapPercent = metricGapSamples.length
    ? Math.min(100, (metricGapSamples.reduce((sum, item) => sum + item, 0) / metricGapSamples.length) * 100)
    : 0
  const goalAgreementPercent = metrics.length
    ? (metrics.filter((item) => item.agreement).length / metrics.length) * 100
    : 100
  const clinicalCompletionPercent = currentGoalStatus.length
    ? (currentGoalStatus.filter((item) => item.passed).length / currentGoalStatus.length) * 100
    : 0
  const referenceProximityPercent = Math.max(0, 100 - metricGapPercent)
  return {
    clinical_completion_percent: clinicalCompletionPercent,
    reference_proximity_percent: referenceProximityPercent,
    overall_completion_percent: clinicalCompletionPercent * 0.65 + referenceProximityPercent * 0.2 + goalAgreementPercent * 0.15,
    goal_agreement_percent: goalAgreementPercent,
    dvh_gap_percent: 0,
    metric_gap_percent: metricGapPercent,
    current_label: "",
    reference_label: "",
  } satisfies ComparisonSummary
}

function deriveSelectedBundle(session: RadOncSession, selectedKey: string | null) {
  if (selectedKey === "reference") {
    return {
      key: "reference",
      label: `Reference bundle · Iteration ${session.reference_iteration_number.toString().padStart(3, "0")}`,
      description: "Observed AIRT optimization result used as the benchmark target.",
      bundleKind: "observed",
      goalStatus: session.reference_goal_status,
      objectives: session.reference_objectives,
      objectiveResults: session.reference_objective_results,
      dvhData: session.reference_dvh_data,
      thinkingLog: "Reference bundle is observed data, not a simulated reasoning step.",
      suggestions: [],
      goalsFulfilled: session.reference_goal_status.filter((item) => item.passed).length,
      goalsTotal: session.reference_goal_status.length,
      referenceGap: { overall_percent: 0, dvh_gap_percent: 0, metric_gap_percent: 0, goal_agreement_percent: 100 },
      comparisonMetrics: buildDerivedComparisonMetrics({
        goals: session.goals,
        startGoalStatus: session.start_goal_status,
        currentGoalStatus: session.reference_goal_status,
        referenceGoalStatus: session.reference_goal_status,
      }),
    } satisfies SelectedBundle
  }

  if (selectedKey && selectedKey.startsWith("sim-")) {
    const number = Number(selectedKey.replace("sim-", ""))
    const iteration = session.iterations.find((item) => item.number === number)
    if (iteration) {
      return {
        key: selectedKey,
        label: `Simulated Iteration ${iteration.number}`,
        description: iteration.improvement_summary,
        bundleKind: "simulated",
        goalStatus: iteration.goal_status,
        objectives: iteration.objectives_snapshot,
        objectiveResults: iteration.objective_results,
        dvhData: iteration.dvh_data,
        thinkingLog: iteration.thinking_log,
        suggestions: iteration.suggestions,
        goalsFulfilled: iteration.goals_fulfilled,
        goalsTotal: iteration.goals_total,
        referenceGap: iteration.reference_gap,
        comparisonMetrics: iteration.comparison_metrics,
        createdAt: iteration.created_at,
        userCommands: iteration.user_commands,
      } satisfies SelectedBundle
    }
  }

  return {
    key: "start",
    label: `Start bundle · Iteration ${session.start_iteration_number.toString().padStart(3, "0")}`,
    description: "Observed starting plan state before hybrid simulated optimization begins.",
    bundleKind: "observed",
    goalStatus: session.start_goal_status,
    objectives: session.start_objectives,
    objectiveResults: session.start_objective_results,
    dvhData: session.start_dvh_data,
    thinkingLog: "Observed start bundle loaded. Hybrid simulation will reason forward from this state.",
    suggestions: session.latest_suggestions,
    goalsFulfilled: session.start_goal_status.filter((item) => item.passed).length,
    goalsTotal: session.start_goal_status.length,
    referenceGap: {
      overall_percent: Math.max(0, 100 - buildDerivedComparisonSummary(
        buildDerivedComparisonMetrics({
          goals: session.goals,
          startGoalStatus: session.start_goal_status,
          currentGoalStatus: session.start_goal_status,
          referenceGoalStatus: session.reference_goal_status,
        }),
        session.start_goal_status,
      ).reference_proximity_percent),
      dvh_gap_percent: 0,
      metric_gap_percent: buildDerivedComparisonSummary(
        buildDerivedComparisonMetrics({
          goals: session.goals,
          startGoalStatus: session.start_goal_status,
          currentGoalStatus: session.start_goal_status,
          referenceGoalStatus: session.reference_goal_status,
        }),
        session.start_goal_status,
      ).metric_gap_percent,
      goal_agreement_percent: buildDerivedComparisonSummary(
        buildDerivedComparisonMetrics({
          goals: session.goals,
          startGoalStatus: session.start_goal_status,
          currentGoalStatus: session.start_goal_status,
          referenceGoalStatus: session.reference_goal_status,
        }),
        session.start_goal_status,
      ).goal_agreement_percent,
    },
    comparisonMetrics: buildDerivedComparisonMetrics({
      goals: session.goals,
      startGoalStatus: session.start_goal_status,
      currentGoalStatus: session.start_goal_status,
      referenceGoalStatus: session.reference_goal_status,
    }),
  } satisfies SelectedBundle
}

function pickOverlayRois({
  focusRoi,
  currentDvh,
}: {
  focusRoi: string
  currentDvh: DVHSnapshot[]
}) {
  if (focusRoi !== "all") {
    return [focusRoi]
  }
  const preferred = ["CTV_APBI_2600", "PTV_Eval_APBI_2600", "Heart", "Lung_R"]
  const currentRois = new Set(currentDvh.map((item) => item.roi))
  const picks = preferred.filter((item) => currentRois.has(item))
  return picks.length ? picks : currentDvh.slice(0, 4).map((item) => item.roi)
}

function buildDvhFigure({
  compareMode,
  focusRoi,
  currentLabel,
  currentDvh,
  startLabel,
  startDvh,
  referenceLabel,
  referenceDvh,
}: {
  compareMode: CompareMode
  focusRoi: string
  currentLabel: string
  currentDvh: DVHSnapshot[]
  startLabel: string
  startDvh: DVHSnapshot[]
  referenceLabel: string
  referenceDvh: DVHSnapshot[]
}): PlotFigure {
  const traceConfig: Array<{ label: string; data: DVHSnapshot[]; dash: "solid" | "dot" | "dash"; opacity: number }> =
    compareMode === "current"
      ? [{ label: currentLabel, data: currentDvh, dash: "solid", opacity: 1 }]
      : compareMode === "reference"
        ? [{ label: referenceLabel, data: referenceDvh, dash: "solid", opacity: 1 }]
        : [
            { label: startLabel, data: startDvh, dash: "dash", opacity: 0.45 },
            { label: currentLabel, data: currentDvh, dash: "solid", opacity: 1 },
            { label: referenceLabel, data: referenceDvh, dash: "dot", opacity: 0.85 },
          ]

  const rois =
    compareMode === "overlay"
      ? pickOverlayRois({ focusRoi, currentDvh })
      : focusRoi === "all"
        ? currentDvh.slice(0, 8).map((item) => item.roi)
        : [focusRoi]

  const data = traceConfig.flatMap((source) =>
    source.data
      .filter((item) => rois.includes(item.roi))
      .map((item, index) => ({
        x: item.dose_points,
        y: item.volume_points,
        type: "scatter",
        mode: "lines",
        name: compareMode === "overlay" ? `${item.roi} · ${source.label}` : item.roi,
        line: {
          width: source.label === currentLabel ? 2.8 : 2,
          dash: source.dash,
          color: palette[index % palette.length],
        },
        opacity: source.opacity,
        hovertemplate: `${item.roi}<br>Dose %{x:.0f} cGy<br>Volume %{y:.2f}%<extra>${source.label}</extra>`,
      })),
  )

  return {
    data,
    layout: {
      margin: { l: 50, r: 16, t: 24, b: 42 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "hsl(30 5% 28%)", family: "Inter Variable, sans-serif", size: 12 },
      legend: { orientation: "h", y: -0.28, x: 0, bgcolor: "rgba(0,0,0,0)" },
      xaxis: { title: "Dose (cGy)", gridcolor: "hsl(35 8% 85%)", zeroline: false },
      yaxis: { title: "Volume (%)", gridcolor: "hsl(35 8% 85%)", rangemode: "tozero" },
      hovermode: "closest",
    },
    config: { displayModeBar: false, responsive: true },
  }
}

function buildTrendFigure(session: RadOncSession): PlotFigure {
  const currentRows = [
    {
      label: "Start",
      goalsMetPercent: session.start_goal_status.length
        ? (session.start_goal_status.filter((item) => item.passed).length / session.start_goal_status.length) * 100
        : 0,
      targetValue:
        session.start_goal_status.find((item) => item.roi.includes("CTV") && item.operator === ">=")?.actual_value ??
        session.start_goal_status.find((item) => item.operator === ">=")?.actual_value ??
        0,
      heartValue:
        session.start_goal_status.find((item) => item.roi === "Heart")?.actual_value ??
        session.start_goal_status.find((item) => item.operator === "<=")?.actual_value ??
        0,
      referenceGap:
        100 -
        buildDerivedComparisonSummary(
          buildDerivedComparisonMetrics({
            goals: session.goals,
            startGoalStatus: session.start_goal_status,
            currentGoalStatus: session.start_goal_status,
            referenceGoalStatus: session.reference_goal_status,
          }),
          session.start_goal_status,
        ).reference_proximity_percent,
    },
    ...session.iterations.map((iteration) => ({
      label: `Sim ${iteration.number}`,
      goalsMetPercent: iteration.goals_total ? (iteration.goals_fulfilled / iteration.goals_total) * 100 : 0,
      targetValue:
        iteration.goal_status.find((item) => item.roi.includes("CTV") && item.operator === ">=")?.actual_value ??
        iteration.goal_status.find((item) => item.operator === ">=")?.actual_value ??
        0,
      heartValue:
        iteration.goal_status.find((item) => item.roi === "Heart")?.actual_value ??
        iteration.goal_status.find((item) => item.operator === "<=")?.actual_value ??
        0,
      referenceGap: iteration.reference_gap.overall_percent,
    })),
    {
      label: "Ref",
      goalsMetPercent: session.reference_goal_status.length
        ? (session.reference_goal_status.filter((item) => item.passed).length / session.reference_goal_status.length) * 100
        : 0,
      targetValue:
        session.reference_goal_status.find((item) => item.roi.includes("CTV") && item.operator === ">=")?.actual_value ??
        session.reference_goal_status.find((item) => item.operator === ">=")?.actual_value ??
        0,
      heartValue:
        session.reference_goal_status.find((item) => item.roi === "Heart")?.actual_value ??
        session.reference_goal_status.find((item) => item.operator === "<=")?.actual_value ??
        0,
      referenceGap: 0,
    },
  ]
  const x = currentRows.map((item) => item.label)
  return {
    data: [
      {
        x,
        y: currentRows.map((item) => item.goalsMetPercent),
        type: "scatter",
        mode: "lines+markers",
        name: "Goals met %",
        line: { width: 3, color: "#d4673b" },
        marker: { size: 8, color: "#d4673b" },
      },
      {
        x,
        y: currentRows.map((item) => item.targetValue),
        type: "scatter",
        mode: "lines+markers",
        name: "Target coverage metric",
        line: { width: 2.2, color: "#3799b3" },
        marker: { size: 6, color: "#3799b3" },
        yaxis: "y2",
      },
      {
        x,
        y: currentRows.map((item) => item.heartValue),
        type: "scatter",
        mode: "lines+markers",
        name: "Key OAR metric",
        line: { width: 2.2, color: "#3f8a63" },
        marker: { size: 6, color: "#3f8a63" },
        yaxis: "y2",
      },
      {
        x,
        y: currentRows.map((item) => item.referenceGap),
        type: "scatter",
        mode: "lines+markers",
        name: "Reference gap %",
        line: { width: 2.2, color: "#8767c9", dash: "dot" },
        marker: { size: 6, color: "#8767c9" },
      },
    ],
    layout: {
      margin: { l: 50, r: 56, t: 20, b: 42 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "hsl(30 5% 28%)", family: "Inter Variable, sans-serif", size: 12 },
      legend: { orientation: "h", y: -0.34, x: 0, bgcolor: "rgba(0,0,0,0)" },
      xaxis: { gridcolor: "hsl(35 8% 85%)" },
      yaxis: { title: "Completion / gap (%)", range: [0, 100], gridcolor: "hsl(35 8% 85%)" },
      yaxis2: {
        title: "Clinical metric",
        overlaying: "y",
        side: "right",
        gridcolor: "rgba(0,0,0,0)",
      },
      hovermode: "x unified",
    },
    config: { displayModeBar: false, responsive: true },
  }
}

function PlotSurface({ className, figure }: { className?: string; figure: PlotFigure }) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) {
      return
    }
    void plotlyClient.react(container, figure.data, figure.layout, figure.config)
    const handleResize = () => {
      if (containerRef.current) {
        plotlyClient.Plots?.resize?.(containerRef.current)
      }
    }
    window.addEventListener("resize", handleResize)
    return () => {
      window.removeEventListener("resize", handleResize)
      plotlyClient.purge(container)
    }
  }, [figure])

  return <div className={className} ref={containerRef} />
}

function TonePill({
  children,
  tone = "default",
}: {
  children: ReactNode
  tone?: "default" | "positive" | "warning" | "danger"
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[11px]",
        tone === "positive" && "border-[hsl(var(--status-ok)/0.2)] bg-[hsl(var(--status-ok)/0.08)] text-[hsl(var(--status-ok))]",
        tone === "warning" && "border-[hsl(var(--status-alert)/0.25)] bg-[hsl(var(--status-alert)/0.08)] text-[hsl(var(--status-alert))]",
        tone === "danger" && "border-[hsl(var(--destructive)/0.2)] bg-[hsl(var(--destructive)/0.08)] text-[hsl(var(--destructive))]",
        tone === "default" && "border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[hsl(var(--muted-foreground))]",
      )}
    >
      {children}
    </span>
  )
}

export function RadOncPlanPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const patients = useApi<RadOncPatientsPayload>("/api/demo/radonc-plan/patients")
  const [patientId, setPatientId] = useState("")
  const snapshot = useApi<RadOncSnapshot>(
    patientId ? `/api/demo/radonc-plan/session?patient_id=${encodeURIComponent(patientId)}` : null,
  )
  const [sessionId, setSessionId] = useState("")
  const [session, setSession] = useState<RadOncSession | null>(null)
  const [sessionError, setSessionError] = useState<string | null>(null)
  const [commandText, setCommandText] = useState("")
  const [objectiveDrafts, setObjectiveDrafts] = useState<Record<string, ObjectiveDraft>>({})
  const [socketConnected, setSocketConnected] = useState(false)
  const [selectedBundleKey, setSelectedBundleKey] = useState<string>("start")
  const [compareMode, setCompareMode] = useState<CompareMode>("overlay")
  const [focusRoi, setFocusRoi] = useState("all")
  const [timelineFilter, setTimelineFilter] = useState<TimelineFilter>("all")
  const socketRef = useRef<WebSocket | null>(null)
  const autorunRef = useRef(false)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!patients.data) {
      return
    }
    const allPatients = patients.data.patients
    if (!allPatients.length) {
      setPatientId("")
      return
    }
    const explicitPatientId = searchParams.get("patient_id")?.trim() || ""
    const compatSessionId = searchParams.get("session_id")?.trim() || ""
    const validPatientId = allPatients.some((item) => item.id === explicitPatientId) ? explicitPatientId : ""
    const compatPatientId =
      compatSessionId ? allPatients.find((item) => item.default_session_id === compatSessionId)?.id ?? "" : ""
    const nextPatientId = validPatientId || compatPatientId || patients.data.default_patient_id || allPatients[0]?.id || ""
    if (!nextPatientId) {
      return
    }
    setPatientId(nextPatientId)

    const params = new URLSearchParams(searchParams)
    const needsNavigation = params.get("patient_id") !== nextPatientId || params.has("session_id")
    if (needsNavigation) {
      params.set("patient_id", nextPatientId)
      params.delete("session_id")
      const nextSearch = params.toString()
      navigate({ search: nextSearch ? `?${nextSearch}` : "" }, { replace: true })
    }
  }, [navigate, patients.data, searchParams])

  useEffect(() => {
    if (!patientId) {
      return
    }
    setSessionId("")
    setSession(null)
    setSessionError(null)
  }, [patientId])

  useEffect(() => {
    if (!snapshot.data) {
      return
    }
    const initialSnapshot = snapshot.data
    setPatientId(initialSnapshot.active_patient_id || patientId)
    setSessionId(initialSnapshot.session.id)
    setSession(initialSnapshot.session)
    setSessionError(null)
    setSelectedBundleKey(initialSnapshot.session.iterations.length ? `sim-${initialSnapshot.session.iterations.at(-1)?.number}` : "start")
  }, [patientId, snapshot.data])

  const loadSession = useCallback(async (activeSessionId: string) => {
    const response = await fetch(`/api/demo/radonc-plan/sessions/${activeSessionId}`)
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { error?: string } | null
      throw new Error(payload?.error || `Session request failed with status ${response.status}`)
    }
    const payload = (await response.json()) as RadOncSession
    setSession(payload)
    setSessionError(null)
    setSelectedBundleKey((current) => {
      if (current === "reference") {
        return current
      }
      if (current === "start") {
        return payload.iterations.length ? `sim-${payload.iterations.at(-1)?.number}` : "start"
      }
      if (current.startsWith("sim-")) {
        const number = Number(current.replace("sim-", ""))
        if (payload.iterations.some((item) => item.number === number)) {
          return current
        }
      }
      return payload.iterations.length ? `sim-${payload.iterations.at(-1)?.number}` : "start"
    })
  }, [])

  useEffect(() => {
    if (!sessionId) {
      return
    }
    void loadSession(sessionId).catch((error: unknown) => {
      setSessionError(error instanceof Error ? error.message : "Failed to load session")
    })
  }, [loadSession, sessionId])

  useEffect(() => {
    if (!sessionId) {
      return
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
    const socket = new WebSocket(`${protocol}//${window.location.host}/api/demo/radonc-plan/ws/${sessionId}`)
    socketRef.current = socket

    socket.onopen = () => {
      setSocketConnected(true)
      if (searchParams.get("autorun") === "1" && !autorunRef.current) {
        autorunRef.current = true
        socket.send(JSON.stringify({ type: "start" }))
      }
    }

    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as WsEvent
      if (payload.type === "session_snapshot") {
        setSession(payload.session)
        return
      }
      if (payload.type === "thinking") {
        setSession((current) => (current ? { ...current, latest_thinking_log: payload.content ?? current.latest_thinking_log } : current))
        return
      }
      if (payload.type === "agent_message" && payload.content) {
        setSession((current) =>
          current
            ? {
                ...current,
                messages: [...current.messages, { role: payload.role ?? "assistant", content: payload.content ?? "" }],
              }
            : current,
        )
        return
      }
      if (payload.type === "status_change" || payload.type === "iteration_complete" || payload.type === "session_complete") {
        void loadSession(sessionId).catch(() => undefined)
      }
    }

    socket.onclose = () => {
      setSocketConnected(false)
    }

    return () => {
      socket.close()
      socketRef.current = null
      setSocketConnected(false)
    }
  }, [loadSession, searchParams, sessionId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [session?.messages.length])

  useEffect(() => {
    if (!session) {
      setObjectiveDrafts({})
      return
    }
    setObjectiveDrafts(
      Object.fromEntries(
        session.current_objectives.map((item) => [
          objectiveKey(item),
          {
            dose: String(item.dose),
            weight: String(item.weight),
          },
        ]),
      ),
    )
  }, [session?.id, session?.current_objectives])

  const sendSocketMessage = useCallback((payload: Record<string, unknown>) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(payload))
    }
  }, [])

  const sendPlannerCommand = useCallback(
    (runAfterApply: boolean) => {
      const text = commandText.trim()
      if (!text) {
        return
      }
      if (runAfterApply) {
        setSelectedBundleKey("start")
      }
      sendSocketMessage({ type: "command", text, run_after_apply: runAfterApply })
      setCommandText("")
    },
    [commandText, sendSocketMessage],
  )

  const handleCommandSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      sendPlannerCommand(session?.status !== "running")
    },
    [sendPlannerCommand, session?.status],
  )

  const handleCommandKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key !== "Enter" || event.shiftKey) {
        return
      }
      event.preventDefault()
      sendPlannerCommand(session?.status !== "running")
    },
    [sendPlannerCommand, session?.status],
  )

  const handleReset = useCallback(async () => {
    if (!sessionId) {
      return
    }
    await fetch(`/api/demo/radonc-plan/sessions/${sessionId}/reset`, { method: "POST" })
    autorunRef.current = false
    sendSocketMessage({ type: "reset" })
    await loadSession(sessionId)
    setSelectedBundleKey("start")
  }, [loadSession, sendSocketMessage, sessionId])

  const selectedBundle = useMemo(
    () => (session ? deriveSelectedBundle(session, selectedBundleKey) : null),
    [selectedBundleKey, session],
  )

  const objectiveUpdates = useMemo(() => {
    if (!session) {
      return []
    }
    return session.current_objectives.flatMap((item) => {
      const draft = objectiveDrafts[objectiveKey(item)]
      if (!draft) {
        return []
      }
      const nextDose = Number(draft.dose)
      const nextWeight = Number(draft.weight)
      if (!Number.isFinite(nextDose) || !Number.isFinite(nextWeight)) {
        return []
      }
      if (nextDose === item.dose && nextWeight === item.weight) {
        return []
      }
      return [
        {
          roi: item.roi,
          objective_type: item.objective_type,
          dose: nextDose,
          weight: nextWeight,
        },
      ]
    })
  }, [objectiveDrafts, session])

  const allRois = useMemo(() => {
    if (!session) {
      return []
    }
    return Array.from(
      new Set(
        [...session.start_dvh_data, ...session.reference_dvh_data, ...(selectedBundle?.dvhData ?? [])].map((item) => item.roi),
      ),
    )
  }, [selectedBundle?.dvhData, session])

  useEffect(() => {
    if (focusRoi === "all") {
      return
    }
    if (!allRois.includes(focusRoi)) {
      setFocusRoi("all")
    }
  }, [allRois, focusRoi])

  const visibleTimelineItems = useMemo(() => {
    if (!session) {
      return []
    }
    const items = [
      { key: "start", label: "Start bundle", kind: "observed" as const },
      ...session.iterations.map((item) => ({ key: `sim-${item.number}`, label: `Simulated ${item.number}`, kind: "simulated" as const })),
      { key: "reference", label: "Reference bundle", kind: "observed" as const },
    ]
    return timelineFilter === "all" ? items : items.filter((item) => item.kind === timelineFilter)
  }, [session, timelineFilter])

  const dvhFigure = useMemo(() => {
    if (!session || !selectedBundle) {
      return { data: [], layout: {}, config: {} } satisfies PlotFigure
    }
    return buildDvhFigure({
      compareMode,
      focusRoi,
      currentLabel: selectedBundle.label,
      currentDvh: selectedBundle.dvhData,
      startLabel: `Observed Iteration ${session.start_iteration_number}`,
      startDvh: session.start_dvh_data,
      referenceLabel: `Observed Iteration ${session.reference_iteration_number}`,
      referenceDvh: session.reference_dvh_data,
    })
  }, [compareMode, focusRoi, selectedBundle, session])

  const trendFigure = useMemo(
    () => (session ? buildTrendFigure(session) : ({ data: [], layout: {}, config: {} } satisfies PlotFigure)),
    [session],
  )

  const activeComparisonMetrics = useMemo(() => {
    if (!session || !selectedBundle) {
      return []
    }
    return selectedBundle.comparisonMetrics.length
      ? selectedBundle.comparisonMetrics
      : buildDerivedComparisonMetrics({
          goals: session.goals,
          startGoalStatus: session.start_goal_status,
          currentGoalStatus: selectedBundle.goalStatus,
          referenceGoalStatus: session.reference_goal_status,
        })
  }, [selectedBundle, session])

  const activeComparisonSummary = useMemo(() => {
    if (!session || !selectedBundle) {
      return null
    }
    if (selectedBundle.key === "reference") {
      return {
        ...buildDerivedComparisonSummary(activeComparisonMetrics, selectedBundle.goalStatus),
        current_label: selectedBundle.label,
        reference_label: selectedBundle.label,
      }
    }
    if (selectedBundle.key === "start") {
      return {
        ...buildDerivedComparisonSummary(activeComparisonMetrics, selectedBundle.goalStatus),
        current_label: selectedBundle.label,
        reference_label: `Observed Iteration ${session.reference_iteration_number}`,
      }
    }
    return {
      clinical_completion_percent: selectedBundle.goalsTotal
        ? (selectedBundle.goalsFulfilled / selectedBundle.goalsTotal) * 100
        : 0,
      reference_proximity_percent: 100 - selectedBundle.referenceGap.overall_percent,
      overall_completion_percent:
        (selectedBundle.goalsTotal ? (selectedBundle.goalsFulfilled / selectedBundle.goalsTotal) * 100 : 0) * 0.6 +
        (100 - selectedBundle.referenceGap.overall_percent) * 0.25 +
        selectedBundle.referenceGap.goal_agreement_percent * 0.15,
      goal_agreement_percent: selectedBundle.referenceGap.goal_agreement_percent,
      dvh_gap_percent: selectedBundle.referenceGap.dvh_gap_percent,
      metric_gap_percent: selectedBundle.referenceGap.metric_gap_percent,
      current_label: selectedBundle.label,
      reference_label: `Observed Iteration ${session.reference_iteration_number}`,
    } satisfies ComparisonSummary
  }, [activeComparisonMetrics, selectedBundle, session])

  if (!session) {
    const noPatients = !patients.loading && (patients.data?.patients.length ?? 0) === 0
    const visibleError = patients.error ?? snapshot.error ?? sessionError
    return (
      <WorkspacePanel subtitle="Loading the RadOnc planning workspace." title="RadOnc Plan Optimization">
        <div className="space-y-2 text-[13px] text-[hsl(var(--muted-foreground))]">
          <div>
            {patients.loading || snapshot.loading
              ? "Loading patient and session data…"
              : noPatients
                ? "No RadOnc patients were discovered. Check the local AIRT demo roots or CLINAGENT_RADONC_DEMO_ROOT."
                : "Waiting for session data."}
          </div>
          {visibleError ? <div className="text-[hsl(var(--destructive))]">{visibleError}</div> : null}
        </div>
      </WorkspacePanel>
    )
  }

  const isRunning = session.status === "running"
  const isPaused = session.status === "paused"
  const hasControlError = session.status === "error"
  const isCompleted = session.status === "completed"
  const canStart = socketConnected && !isRunning && !isPaused && !isCompleted && !hasControlError && session.control_mode !== "manual"
  const canResume = socketConnected && isPaused && session.control_mode !== "manual"
  const canPause = socketConnected && isRunning && session.control_mode === "auto"
  const canStop = socketConnected && (isRunning || isPaused)
  const canRunIteration = socketConnected && !isRunning && !isCompleted && !hasControlError && session.control_mode === "manual"
  const canEditObjectives = socketConnected && !isRunning && !isCompleted && !hasControlError
  const hasObjectiveEdits = objectiveUpdates.length > 0
  const modeTone = session.control_mode === "auto" ? "positive" : session.control_mode === "supervised" ? "warning" : "default"
  const startLabel = session.control_mode === "supervised" ? "Start Review" : "Start"
  const resumeLabel = session.control_mode === "supervised" ? "Next Step" : "Resume"
  const controlModeDescription = describeControlMode(session.control_mode)
  const controlStateDescription = describeControlState(session, socketConnected)
  const canSendCommand = socketConnected && commandText.trim().length > 0
  const recentCommands = session.command_history.slice(-6).reverse()
  const latestCommand = session.command_history.at(-1) ?? null
  const queuedCommandCount = session.command_history.filter((item) => item.status === "queued").length
  const executedCommandCount = session.command_history.filter((item) => item.status === "executed").length
  const visibleMessages = session.messages.slice(-12)
  const plannerActionLabel = isRunning ? "Queue for next step" : "Apply + iterate"
  const plannerActionHint = isRunning
    ? "The optimizer is running, so this instruction will queue for the next simulated step."
    : "This will update the active objective deck and immediately simulate one predicted iteration."
  const plannerQuickPrompts = [
    "Set Heart mean dose limit to 8 Gy.",
    "Set Spinal cord Dmax limit to 18 Gy.",
    "Increase target coverage to V26Gy >= 98%.",
  ]
  const activeObjectiveResults = session.objective_results
  const activeGoalsMet = session.goal_status.filter((item) => item.passed).length

  const handleObjectiveDraftChange = useCallback((key: string, field: keyof ObjectiveDraft, value: string) => {
    setObjectiveDrafts((current) => ({
      ...current,
      [key]: {
        dose: current[key]?.dose ?? "",
        weight: current[key]?.weight ?? "",
        [field]: value,
      },
    }))
  }, [])

  const handleObjectiveUpdate = useCallback(
    (runAfterApply: boolean) => {
      if (!objectiveUpdates.length) {
        return
      }
      if (runAfterApply) {
        setSelectedBundleKey("start")
      }
      sendSocketMessage({ type: "update_objectives", updates: objectiveUpdates, run_after_apply: runAfterApply })
    },
    [objectiveUpdates, sendSocketMessage],
  )

  return (
    <div className="space-y-4">
      <WorkspacePanel
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2 py-1">
              <label className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]" htmlFor="radonc-patient">
                Patient
              </label>
              <select
                className="max-w-[12rem] bg-transparent text-[12px] text-[hsl(var(--foreground))] outline-none"
                id="radonc-patient"
                onChange={(event) => {
                  const nextPatientId = event.target.value
                  const params = new URLSearchParams(searchParams)
                  params.set("patient_id", nextPatientId)
                  params.delete("session_id")
                  const nextSearch = params.toString()
                  navigate({ search: nextSearch ? `?${nextSearch}` : "" }, { replace: false })
                }}
                value={patientId}
              >
                {(patients.data?.patients ?? []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2 py-1">
              <label className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]" htmlFor="radonc-control-mode">
                Mode
              </label>
              <select
                className="bg-transparent text-[12px] text-[hsl(var(--foreground))] outline-none"
                disabled={!socketConnected}
                id="radonc-control-mode"
                onChange={(event) => sendSocketMessage({ type: "set_control_mode", mode: event.target.value })}
                value={session.control_mode}
              >
                <option value="auto">auto</option>
                <option value="supervised">supervised</option>
                <option value="manual">manual</option>
              </select>
            </div>
            {session.control_mode !== "manual" ? (
              <Button disabled={!canStart} onClick={() => sendSocketMessage({ type: "start" })} size="sm" variant="default">
                <Play data-icon="inline-start" />
                {startLabel}
              </Button>
            ) : null}
            {session.control_mode === "auto" ? (
              <Button disabled={!canPause} onClick={() => sendSocketMessage({ type: "pause" })} size="sm" variant="outline">
                <Pause data-icon="inline-start" />
                Pause
              </Button>
            ) : null}
            {session.control_mode !== "manual" ? (
              <Button disabled={!canResume} onClick={() => sendSocketMessage({ type: "resume" })} size="sm" variant="outline">
                <Play data-icon="inline-start" />
                {resumeLabel}
              </Button>
            ) : null}
            {session.control_mode === "manual" ? (
              <Button disabled={!canRunIteration} onClick={() => sendSocketMessage({ type: "run_iteration" })} size="sm" variant="default">
                <WandSparkles data-icon="inline-start" />
                Run Iteration
              </Button>
            ) : null}
            <Button disabled={!canStop} onClick={() => sendSocketMessage({ type: "stop" })} size="sm" variant="outline">
              <Square data-icon="inline-start" />
              Stop
            </Button>
            <Button onClick={handleReset} size="sm" variant="outline">
              <RotateCcw data-icon="inline-start" />
              Reset
            </Button>
          </div>
        }
        riskTier={session.risk_tier}
        subtitle={session.subtitle}
        title={session.title}
      >
        <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Patient</div>
                <div className="mt-2 text-[16px] font-medium text-[hsl(var(--foreground))]">{session.patient_label}</div>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Protocol</div>
                <div className="mt-2 text-[14px] leading-6 text-[hsl(var(--foreground))]">{session.protocol_name}</div>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Site</div>
                <div className="mt-2 text-[14px] text-[hsl(var(--foreground))]">{session.treatment_site}</div>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Data source</div>
                <div className="mt-2 text-[14px] text-[hsl(var(--foreground))]">
                  {session.data_source_type} · {session.data_source_id}
                </div>
                <div className="mt-1 text-[12px] text-[hsl(var(--muted-foreground))]">
                  Source {(patients.data?.patients ?? []).find((item) => item.id === patientId)?.source ?? "unknown"}
                </div>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <RiskBadge tier={session.risk_tier} />
              <TonePill>{session.title_badge}</TonePill>
              <TonePill>{socketConnected ? `${session.connector_type} · live` : `${session.connector_type} · offline`}</TonePill>
              <TonePill tone={modeTone}>{session.control_mode}</TonePill>
              <TonePill tone="warning">Observed start {session.start_iteration_number.toString().padStart(3, "0")}</TonePill>
              <TonePill tone="positive">Reference {session.reference_iteration_number.toString().padStart(3, "0")}</TonePill>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <SummaryMetric label="Status" value={formatStatusLabel(session.status)} />
            <SummaryMetric label="Simulation" value={`${session.iterations.length}/${session.simulation_max_iterations}`} />
            <SummaryMetric label="Clinical completion" value={formatPercent(activeComparisonSummary?.clinical_completion_percent)} />
            <SummaryMetric label="Reference proximity" value={formatPercent(activeComparisonSummary?.reference_proximity_percent)} />
          </div>
        </div>
        <p className="mt-4 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">{session.risk_reason}</p>
        <div className="mt-4 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-4 py-3">
          <div className="text-[12px] font-medium text-[hsl(var(--foreground))]">{controlModeDescription}</div>
          <div className="mt-1 text-[12px] leading-6 text-[hsl(var(--muted-foreground))]">{controlStateDescription}</div>
        </div>
      </WorkspacePanel>

      <div className="grid gap-4 xl:grid-cols-[1.35fr_0.95fr]">
        <WorkspacePanel subtitle="Keep the optimization objective deck front and center while reviewing the active bundle." title="Optimization Objectives">
          <div className="grid gap-4">
            <div className="grid gap-3 md:grid-cols-4">
              <SummaryMetric label="Active deck" value={session.iterations.length ? `Sim ${session.iterations.at(-1)?.number}` : "Start state"} />
              <SummaryMetric label="Objectives" value={`${activeObjectiveResults.length}`} />
              <SummaryMetric label="Goals met" value={`${activeGoalsMet}/${session.goal_status.length}`} />
              <SummaryMetric label="Reference proximity" value={formatPercent(session.comparison_summary.reference_proximity_percent)} />
            </div>

            <div className="rounded-xl border border-[hsl(var(--border)/0.75)] bg-[linear-gradient(135deg,hsl(var(--accent))_0%,hsl(var(--background))_52%,hsl(var(--background))_100%)] p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">Active objective deck</Badge>
                <Badge variant="outline">{session.iterations.length ? "simulated current" : "observed start"}</Badge>
                <Badge variant="outline">{activeComparisonSummary?.current_label || "Current planner state"}</Badge>
              </div>
              <p className="mt-3 max-w-4xl text-[13px] leading-6 text-[hsl(var(--foreground))]">
                ROI / Objective / Dose / Weight / Result is the primary control surface for plan tuning. You can edit dose and weight directly in this active deck, confirm the change set, and then run the next predicted optimization step.
              </p>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--background))] px-4 py-3">
              <div className="text-[12px] leading-6 text-[hsl(var(--muted-foreground))]">
                {canEditObjectives
                  ? hasObjectiveEdits
                    ? `${objectiveUpdates.length} objective row${objectiveUpdates.length === 1 ? "" : "s"} edited. Confirm to apply them to the active deck.`
                    : "Edit Dose or Weight in the active objective deck, then confirm the update."
                  : "Pause or reset the optimizer before editing the active objective deck."}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  disabled={!hasObjectiveEdits}
                  onClick={() =>
                    setObjectiveDrafts(
                      Object.fromEntries(
                        session.current_objectives.map((item) => [
                          objectiveKey(item),
                          { dose: String(item.dose), weight: String(item.weight) },
                        ]),
                      ),
                    )
                  }
                  size="sm"
                  variant="outline"
                >
                  Reset draft
                </Button>
                <Button disabled={!hasObjectiveEdits || !canEditObjectives} onClick={() => handleObjectiveUpdate(false)} size="sm" variant="outline">
                  Confirm only
                </Button>
                <Button disabled={!hasObjectiveEdits || !canEditObjectives} onClick={() => handleObjectiveUpdate(true)} size="sm" variant="default">
                  Confirm + iterate
                </Button>
              </div>
            </div>

            <ScrollArea className="h-[31rem] rounded-xl border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--background))]">
              <div className="p-1">
                <Table>
                  <TableHeader className="sticky top-0 z-10 bg-[hsl(var(--background))]">
                    <TableRow>
                      <TableHead className="pl-3">ROI</TableHead>
                      <TableHead>Objective</TableHead>
                      <TableHead>Dose</TableHead>
                      <TableHead>Weight</TableHead>
                      <TableHead className="pr-3">Result</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {activeObjectiveResults.map((item, index) => {
                      const key = objectiveKey(item.objective)
                      const draft = objectiveDrafts[key] ?? { dose: String(item.objective.dose), weight: String(item.objective.weight) }
                      return (
                      <TableRow key={`${item.objective.roi}-${index}`}>
                        <TableCell className="pl-3 font-medium">{item.objective.roi}</TableCell>
                        <TableCell>
                          <div className="flex flex-col gap-1">
                            <span>{item.objective.objective_type}</span>
                            <span className="text-[11px] text-[hsl(var(--muted-foreground))]">priority {item.objective.priority}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col gap-1">
                            <Input
                              className="h-8 w-[8.5rem]"
                              disabled={!canEditObjectives}
                              inputMode="decimal"
                              onChange={(event) => handleObjectiveDraftChange(key, "dose", event.target.value)}
                              value={draft.dose}
                            />
                            {typeof item.objective.volume === "number" ? (
                              <span className="text-[11px] text-[hsl(var(--muted-foreground))]">
                                @ {formatNumber(item.objective.volume)} {item.objective.volume_unit ?? "%"}
                              </span>
                            ) : null}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Input
                            className="h-8 w-[6.5rem]"
                            disabled={!canEditObjectives}
                            inputMode="decimal"
                            onChange={(event) => handleObjectiveDraftChange(key, "weight", event.target.value)}
                            value={draft.weight}
                          />
                        </TableCell>
                        <TableCell className="pr-3">
                          <div className="flex flex-col gap-1">
                            <Badge variant={item.fulfilled ? "default" : "secondary"}>{item.fulfilled ? "Met" : "Not met"}</Badge>
                            <span className="text-[11px] text-[hsl(var(--muted-foreground))]">
                              {formatNumber(item.actual_value)} {item.unit}
                            </span>
                          </div>
                        </TableCell>
                      </TableRow>
                    )})}
                  </TableBody>
                </Table>
              </div>
            </ScrollArea>
          </div>
        </WorkspacePanel>

        <WorkspacePanel subtitle="Planner instructions should change the active objective deck and drive the next predicted step, not just sit in a chat shell." title="Planner Chat">
          <div className="grid gap-4">
            <div className="rounded-xl border border-[hsl(var(--border)/0.75)] bg-[linear-gradient(160deg,hsl(var(--primary)/0.10)_0%,hsl(var(--background))_58%)] p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="default">Live planner</Badge>
                <Badge variant="outline">{session.control_mode}</Badge>
                <Badge variant="outline">{socketConnected ? "socket connected" : "socket offline"}</Badge>
                <Badge variant="secondary">{queuedCommandCount} queued</Badge>
                <Badge variant="secondary">{executedCommandCount} executed</Badge>
              </div>
              <p className="mt-3 text-[13px] leading-6 text-[hsl(var(--foreground))]">
                Use planner chat to edit dose limits or coverage goals. By default, the command updates the active objective deck and runs one predicted iteration immediately so the DVH surface can move, not just the text log.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {plannerQuickPrompts.map((prompt) => (
                  <button
                    className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-1.5 text-left text-[12px] text-[hsl(var(--foreground))] transition-colors hover:bg-[hsl(var(--accent))]"
                    key={prompt}
                    onClick={() => setCommandText(prompt)}
                    type="button"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>

            <form className="space-y-2" onSubmit={handleCommandSubmit}>
              <label className="text-[12px] font-medium text-[hsl(var(--muted-foreground))]" htmlFor="radonc-command">
                Planner input
              </label>
              <div className="rounded-[1.4rem] border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
                <Textarea
                  className="min-h-[118px] resize-none border-0 bg-transparent px-0 py-0 text-[13px] leading-6 shadow-none focus-visible:ring-0"
                  id="radonc-command"
                  onChange={(event) => setCommandText(event.target.value)}
                  onKeyDown={handleCommandKeyDown}
                  placeholder="For example: Set Heart mean dose limit to 8 Gy while keeping target coverage at V26Gy >= 98%."
                  value={commandText}
                />
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                  <div className="text-[11px] leading-5 text-[hsl(var(--muted-foreground))]">
                    {plannerActionHint} Enter uses the primary action. Shift+Enter adds a new line.
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button disabled={!canSendCommand} onClick={() => sendPlannerCommand(false)} size="sm" type="button" variant="outline">
                      Queue only
                    </Button>
                    <Button disabled={!canSendCommand} size="sm" type="submit" variant="default">
                      <Send data-icon="inline-start" />
                      {plannerActionLabel}
                    </Button>
                  </div>
                </div>
              </div>
            </form>

            <div className="grid gap-3 md:grid-cols-4">
              <SummaryMetric label="Last command" value={latestCommand ? formatCommandStatusLabel(latestCommand.status) : "none"} />
              <SummaryMetric label="Applied changes" value={`${latestCommand?.applied_changes.length ?? 0}`} />
              <SummaryMetric label="Executed in iteration" value={latestCommand?.applied_in_iteration ? `#${latestCommand.applied_in_iteration}` : "pending"} />
              <SummaryMetric label="Planner state" value={isRunning ? "running" : session.status} />
            </div>

            <div className="grid gap-3 xl:grid-cols-[1.15fr_0.85fr]">
              <div className="rounded-xl border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--background))] p-3">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <div className="text-[12px] font-medium text-[hsl(var(--foreground))]">Conversation feed</div>
                    <div className="text-[11px] text-[hsl(var(--muted-foreground))]">Planner decisions and operator instructions in one stream</div>
                  </div>
                  <Badge variant="secondary">{visibleMessages.length} messages</Badge>
                </div>
                <Separator className="my-3" />
                <ScrollArea className="h-[18rem] pr-3">
                  <div className="flex flex-col gap-3">
                    {!visibleMessages.length ? (
                      <div className="rounded-lg border border-dashed border-[hsl(var(--border))] px-4 py-5 text-[12px] leading-6 text-[hsl(var(--muted-foreground))]">
                        Start with an explicit instruction such as “Set Heart mean dose limit to 8 Gy” or “Increase target coverage to V26Gy &gt;= 98%.”
                      </div>
                    ) : null}
                    {visibleMessages.map((message, index) => (
                      <div className={cn("flex", message.role === "user" ? "justify-end" : "justify-start")} key={`${message.role}-${index}-${message.content.slice(0, 24)}`}>
                        <div
                          className={cn(
                            "max-w-[92%] rounded-2xl px-4 py-3 text-[13px] leading-6 shadow-sm",
                            message.role === "user"
                              ? "rounded-br-md bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                              : "rounded-bl-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[hsl(var(--foreground))]",
                          )}
                        >
                          <div
                            className={cn(
                              "text-[10px] uppercase tracking-[0.14em]",
                              message.role === "user"
                                ? "text-[hsl(var(--primary-foreground)/0.72)]"
                                : "text-[hsl(var(--muted-foreground))]",
                            )}
                          >
                            {message.role}
                          </div>
                          <p className="mt-2 whitespace-pre-wrap [overflow-wrap:anywhere]">{message.content}</p>
                        </div>
                      </div>
                    ))}
                    <div ref={messagesEndRef} />
                  </div>
                </ScrollArea>
              </div>

              <div className="grid gap-3">
                <div className="rounded-xl border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--background))] p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <div className="text-[12px] font-medium text-[hsl(var(--foreground))]">Latest plan impact</div>
                      <div className="text-[11px] text-[hsl(var(--muted-foreground))]">What the last planner instruction actually changed</div>
                    </div>
                    <Badge variant={commandStatusTone(latestCommand?.status ?? "queued")}>
                      {latestCommand ? formatCommandStatusLabel(latestCommand.status) : "none"}
                    </Badge>
                  </div>
                  <Separator className="my-3" />
                  {!latestCommand ? (
                    <div className="rounded-lg border border-dashed border-[hsl(var(--border))] px-3 py-4 text-[12px] leading-6 text-[hsl(var(--muted-foreground))]">
                      No planner command has been applied yet.
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--accent)/0.38)] px-3 py-3">
                        <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Instruction</div>
                        <p className="mt-2 text-[13px] leading-6 text-[hsl(var(--foreground))]">{latestCommand.text}</p>
                      </div>
                      {latestCommand.response_text ? (
                        <div>
                          <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Planner response</div>
                          <p className="mt-2 text-[12px] leading-6 text-[hsl(var(--foreground))]">{latestCommand.response_text}</p>
                        </div>
                      ) : null}
                      {latestCommand.applied_changes.length ? (
                        <div>
                          <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Objective changes</div>
                          <div className="mt-2 space-y-2">
                            {latestCommand.applied_changes.map((change) => (
                              <div className="rounded-lg border border-[hsl(var(--border))] px-3 py-2 text-[12px] leading-6 text-[hsl(var(--foreground))]" key={change}>
                                {change}
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      {latestCommand.effect_summary ? (
                        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-3 text-[12px] leading-6 text-[hsl(var(--foreground))]">
                          {latestCommand.effect_summary}
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>

                <div className="rounded-xl border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--background))] p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <div className="text-[12px] font-medium text-[hsl(var(--foreground))]">Planner activity</div>
                      <div className="text-[11px] text-[hsl(var(--muted-foreground))]">Recent command execution status</div>
                    </div>
                    <Badge variant="secondary">{recentCommands.length} recent</Badge>
                  </div>
                  <Separator className="my-3" />
                  <ScrollArea className="h-[18rem] pr-3">
                    <div className="flex flex-col gap-2">
                      {!recentCommands.length ? (
                        <div className="rounded-lg border border-dashed border-[hsl(var(--border))] px-3 py-4 text-[12px] leading-6 text-[hsl(var(--muted-foreground))]">
                          No commands yet.
                        </div>
                      ) : null}
                      {recentCommands.map((item) => (
                        <div className="rounded-lg border border-[hsl(var(--border))] px-3 py-3" key={item.id}>
                          <div className="flex items-center justify-between gap-2">
                            <Badge variant={commandStatusTone(item.status)}>{formatCommandStatusLabel(item.status)}</Badge>
                            <span className="text-[11px] text-[hsl(var(--muted-foreground))]">{formatTimestamp(item.created_at)}</span>
                          </div>
                          <p className="mt-2 text-[12px] leading-6 text-[hsl(var(--foreground))]">{item.text}</p>
                          {item.applied_in_iteration ? (
                            <div className="mt-2 text-[11px] text-[hsl(var(--muted-foreground))]">Predicted iteration #{item.applied_in_iteration}</div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </ScrollArea>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--background))] p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div>
                  <div className="text-[12px] font-medium text-[hsl(var(--foreground))]">Planner reasoning</div>
                  <div className="text-[11px] text-[hsl(var(--muted-foreground))]">Latest simulated rationale and suggestion merge log</div>
                </div>
                <Button onClick={() => sendSocketMessage({ type: "toggle_thinking", visible: !session.show_thinking })} size="sm" variant="outline">
                  {session.show_thinking ? "Hide" : "Show"}
                </Button>
              </div>
              <Separator className="my-3" />
              <pre className="max-h-[16rem] overflow-auto whitespace-pre-wrap text-[12px] leading-6 text-[hsl(var(--muted-foreground))]">
                {session.show_thinking
                  ? selectedBundle?.thinkingLog || session.latest_thinking_log || "Thinking output will appear during optimization."
                  : "Thinking is hidden for this session."}
              </pre>
            </div>
          </div>
        </WorkspacePanel>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.3fr_0.7fr]">
        <WorkspacePanel subtitle="Structured comparison of current, observed reference, and overlayed DVH trajectories." title="Planning Surface">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-2">
              {(["current", "reference", "overlay"] as CompareMode[]).map((item) => (
                <Button key={item} onClick={() => setCompareMode(item)} size="sm" variant={compareMode === item ? "default" : "outline"}>
                  {item === "overlay" ? "Overlay Compare" : item[0].toUpperCase() + item.slice(1)}
                </Button>
              ))}
            </div>
            <div className="flex items-center gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2 py-1">
              <label className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]" htmlFor="radonc-roi-focus">
                ROI
              </label>
              <select
                className="bg-transparent text-[12px] text-[hsl(var(--foreground))] outline-none"
                id="radonc-roi-focus"
                onChange={(event) => setFocusRoi(event.target.value)}
                value={focusRoi}
              >
                <option value="all">all</option>
                {allRois.map((roi) => (
                  <option key={roi} value={roi}>
                    {roi}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid gap-4">
            <div className="overflow-hidden rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
              <PlotSurface className="h-[360px] w-full" figure={dvhFigure} />
            </div>

            <div className="grid gap-3 md:grid-cols-4">
              <SummaryMetric label="Clinical completion" value={formatPercent(activeComparisonSummary?.clinical_completion_percent)} />
              <SummaryMetric label="Reference proximity" value={formatPercent(activeComparisonSummary?.reference_proximity_percent)} />
              <SummaryMetric label="Agreement" value={formatPercent(activeComparisonSummary?.goal_agreement_percent)} />
              <SummaryMetric label="Overall completion" value={formatPercent(activeComparisonSummary?.overall_completion_percent)} />
            </div>

            <div className="overflow-hidden rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
              <PlotSurface className="h-[260px] w-full" figure={trendFigure} />
            </div>
          </div>
        </WorkspacePanel>

        <WorkspacePanel subtitle="Observed bundles anchor the timeline. Simulated iterations fill the space between start and reference." title="Iteration Timeline">
          <div className="mb-3 flex flex-wrap gap-2">
            {(["all", "observed", "simulated"] as TimelineFilter[]).map((item) => (
              <Button key={item} onClick={() => setTimelineFilter(item)} size="sm" variant={timelineFilter === item ? "default" : "outline"}>
                {item}
              </Button>
            ))}
          </div>
          <ScrollArea className="h-[36rem] pr-3">
            <div className="flex flex-col gap-3">
              {visibleTimelineItems.map((item) => {
                const selected = selectedBundleKey === item.key
                const bundle =
                  item.key === "start"
                    ? deriveSelectedBundle(session, "start")
                    : item.key === "reference"
                      ? deriveSelectedBundle(session, "reference")
                      : deriveSelectedBundle(session, item.key)

                return (
                  <button
                    className={cn(
                      "w-full rounded-xl border px-3 py-3 text-left transition-colors",
                      selected
                        ? "border-[hsl(var(--primary))] bg-[hsl(var(--accent))]"
                        : "border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:bg-[hsl(var(--accent))]",
                    )}
                    key={item.key}
                    onClick={() => setSelectedBundleKey(item.key)}
                    type="button"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[13px] font-medium text-[hsl(var(--foreground))]">{bundle.label}</div>
                      <Badge variant={bundle.bundleKind === "simulated" ? "secondary" : "outline"}>{bundle.bundleKind}</Badge>
                    </div>
                    <div className="mt-2 text-[12px] text-[hsl(var(--muted-foreground))]">
                      {bundle.goalsFulfilled}/{bundle.goalsTotal} goals met
                    </div>
                    <p className="mt-2 text-[13px] leading-6 text-[hsl(var(--foreground))]">{bundle.description}</p>
                    {bundle.createdAt ? <div className="mt-2 text-[11px] text-[hsl(var(--muted-foreground))]">{formatTimestamp(bundle.createdAt)}</div> : null}
                  </button>
                )
              })}
            </div>
          </ScrollArea>
        </WorkspacePanel>
      </div>

      <WorkspacePanel subtitle="Completion and reference proximity remain visible while switching between simulated and observed states." title="Optimization Summary">
        <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
          <div className="space-y-4">
            <div className="grid gap-3 md:grid-cols-3">
              <SummaryMetric label="Clinical completion" value={formatPercent(activeComparisonSummary?.clinical_completion_percent)} />
              <SummaryMetric label="Reference proximity" value={formatPercent(activeComparisonSummary?.reference_proximity_percent)} />
              <SummaryMetric label="Overall completion" value={formatPercent(activeComparisonSummary?.overall_completion_percent)} />
            </div>
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
              <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Summary</div>
              <p className="mt-3 text-[13px] leading-7 text-[hsl(var(--foreground))]">
                {selectedBundle?.description || session.report_summary}
              </p>
              <p className="mt-3 text-[12px] leading-6 text-[hsl(var(--muted-foreground))]">
                Current view: {activeComparisonSummary?.current_label || selectedBundle?.label}. Reference: {activeComparisonSummary?.reference_label || `Observed Iteration ${session.reference_iteration_number}`}.
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {session.recommended_actions.map((item) => (
                <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3 text-[13px] leading-6 text-[hsl(var(--foreground))]" key={item}>
                  {item}
                </div>
              ))}
            </div>
          </div>

          <div className="grid gap-4">
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
              <div className="mb-3 flex items-center justify-between gap-2">
                <div>
                  <div className="text-[12px] font-medium text-[hsl(var(--foreground))]">Clinical goal review</div>
                  <div className="text-[11px] text-[hsl(var(--muted-foreground))]">This table is secondary to the objective deck above and is kept here for reference review.</div>
                </div>
                <Badge variant="secondary">{selectedBundle?.goalStatus.length ?? 0} goals</Badge>
              </div>
              <ScrollArea className="h-[14rem]">
                <Table>
                  <TableHeader className="sticky top-0 z-10 bg-[hsl(var(--background))]">
                    <TableRow>
                      <TableHead className="pl-3">ROI</TableHead>
                      <TableHead>Metric</TableHead>
                      <TableHead>Target</TableHead>
                      <TableHead>Actual</TableHead>
                      <TableHead className="pr-3">Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(selectedBundle?.goalStatus ?? []).map((item) => (
                      <TableRow key={`${item.roi}-${item.metric}`}>
                        <TableCell className="pl-3 font-medium">{item.roi}</TableCell>
                        <TableCell>{item.metric}</TableCell>
                        <TableCell>
                          {item.operator} {formatNumber(item.target_value)} {item.unit}
                        </TableCell>
                        <TableCell>
                          {formatNumber(item.actual_value)} {item.unit}
                        </TableCell>
                        <TableCell className="pr-3">
                          <Badge variant={item.passed ? "default" : "secondary"}>{item.passed ? "Pass" : "Fail"}</Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </ScrollArea>
            </div>

            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
              <div className="mb-3 flex items-center justify-between gap-2">
                <div>
                  <div className="text-[12px] font-medium text-[hsl(var(--foreground))]">Reference comparison</div>
                  <div className="text-[11px] text-[hsl(var(--muted-foreground))]">Start / current / reference values for the active bundle.</div>
                </div>
                <Badge variant="outline">{activeComparisonMetrics.length} rows</Badge>
              </div>
              <ScrollArea className="h-[18rem]">
                <Table>
                  <TableHeader className="sticky top-0 z-10 bg-[hsl(var(--background))]">
                    <TableRow>
                      <TableHead className="pl-3">ROI</TableHead>
                      <TableHead>Metric</TableHead>
                      <TableHead>Start</TableHead>
                      <TableHead>Current</TableHead>
                      <TableHead>Reference</TableHead>
                      <TableHead>Delta</TableHead>
                      <TableHead className="pr-3">Pass</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {activeComparisonMetrics.map((item) => (
                      <TableRow key={`${item.roi}-${item.metric}`}>
                        <TableCell className="pl-3 font-medium">{item.roi}</TableCell>
                        <TableCell>{item.metric}</TableCell>
                        <TableCell>
                          {formatNumber(item.start_value)} {item.unit}
                        </TableCell>
                        <TableCell>
                          {formatNumber(item.current_value)} {item.unit}
                        </TableCell>
                        <TableCell>
                          {formatNumber(item.reference_value)} {item.unit}
                        </TableCell>
                        <TableCell>
                          {typeof item.delta_to_reference === "number" ? `${item.delta_to_reference > 0 ? "+" : ""}${formatNumber(item.delta_to_reference)}` : "—"}
                        </TableCell>
                        <TableCell className="pr-3">
                          <div className="flex flex-col gap-1">
                            <Badge variant={item.passed ? "default" : "secondary"}>{item.passed ? "Pass" : "Fail"}</Badge>
                            <span className="text-[11px] text-[hsl(var(--muted-foreground))]">
                              {item.agreement ? "ref aligned" : item.reference_passed ? "below ref" : "above ref"}
                            </span>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </ScrollArea>
            </div>
          </div>
        </div>
      </WorkspacePanel>
    </div>
  )
}
