export type StageStatus = "pending" | "active" | "done" | "error"

export interface DemoStage {
  id: string
  label: string
  description: string
  toolNames: string[]
  icon: string
}

export interface StageToolCall {
  name: string
  status: "pending" | "running" | "done" | "error"
  preview?: string
  durationMs?: number
}

export interface DemoStageState extends DemoStage {
  status: StageStatus
  durationMs?: number
  summary?: string
}

export const NEURO_STAGES: DemoStage[] = [
  {
    id: "data_retrieval",
    label: "Retrieving clinical data",
    description: "Querying imaging archive and patient chart",
    toolNames: ["pacs_series_query", "ehr_chart_pull", "prior_reports_fetch"],
    icon: "Database",
  },
  {
    id: "series_selection",
    label: "Selecting imaging series",
    description: "Identifying T1C contrast series across timepoints",
    toolNames: ["dicom_series_selector"],
    icon: "Layers",
  },
  {
    id: "segmentation",
    label: "Running lesion segmentation",
    description: "Analyzing tumor boundaries on each timepoint",
    toolNames: ["tumor_segmentation_runner"],
    icon: "Scan",
  },
  {
    id: "volumetrics",
    label: "Calculating longitudinal change",
    description: "Measuring lesion volume and computing interval trend",
    toolNames: ["lesion_volume_calculator", "brain_met_response_tracker"],
    icon: "TrendingDown",
  },
  {
    id: "synthesis",
    label: "Synthesizing evidence",
    description: "Aligning treatment timeline and building claim-level evidence",
    toolNames: ["rt_timeline_aligner", "evidence_board_builder", "risk_signal_renderer"],
    icon: "GitMerge",
  },
  {
    id: "report_generation",
    label: "Generating report",
    description: "Drafting structured radiology report with QA checks",
    toolNames: ["render_clinical_report", "report_quality_checker", "neuro_report_draft_generator"],
    icon: "FileText",
  },
  {
    id: "workspace_prep",
    label: "Preparing review workspace",
    description: "Rendering visualizations and assembling the review dashboard",
    toolNames: [
      "build_neuro_visualization_bundle",
      "lesion_trend_plotter",
      "treatment_event_timeline_renderer",
      "longitudinal_comparison_panel_builder",
      "get_neuro_longitudinal_viewer_manifest",
    ],
    icon: "LayoutDashboard",
  },
]

function latestCallByTool(calls: StageToolCall[]) {
  const latest = new Map<string, StageToolCall>()
  calls.forEach((call) => {
    latest.set(call.name, call)
  })
  return latest
}

function stageDuration(calls: StageToolCall[]) {
  const durations = calls
    .map((call) => call.durationMs)
    .filter((duration): duration is number => typeof duration === "number" && duration >= 0)

  if (!durations.length) {
    return undefined
  }

  return durations.reduce((sum, value) => sum + value, 0)
}

function stageSummary(calls: StageToolCall[]) {
  const completed = [...calls]
    .reverse()
    .find((call) => (call.status === "done" || call.status === "error") && call.preview?.trim())

  return completed?.preview
}

export function buildStageStates(
  calls: StageToolCall[],
  {
    stages = NEURO_STAGES,
    runComplete = false,
  }: { stages?: DemoStage[]; runComplete?: boolean } = {},
) {
  const stageCalls = stages.map((stage) =>
    calls.filter((call) => stage.toolNames.includes(call.name)),
  )

  const latestPerStage = stageCalls.map((items) => latestCallByTool(items))
  const furthestStartedStage = stageCalls.reduce((maxIndex, items, index) => {
    return items.length ? index : maxIndex
  }, -1)

  return stages.map<DemoStageState>((stage, index) => {
    const items = stageCalls[index]
    const latest = latestPerStage[index]
    const values = [...latest.values()]
    const seenStage = items.length > 0
    const hasError = values.some((call) => call.status === "error")
    const hasActive = values.some((call) => call.status === "running")
    const allDone =
      values.length > 0 &&
      stage.toolNames.every((toolName) => latest.get(toolName)?.status === "done")
    const laterStageStarted = furthestStartedStage > index

    let status: StageStatus = "pending"
    if (hasError) {
      status = "error"
    } else if (hasActive) {
      status = "active"
    } else if (allDone || (seenStage && (laterStageStarted || runComplete))) {
      status = "done"
    } else if (seenStage) {
      status = "active"
    }

    return {
      ...stage,
      status,
      durationMs: status === "done" || status === "error" ? stageDuration(items) : undefined,
      summary: status === "done" ? stageSummary(items) : undefined,
    }
  })
}
