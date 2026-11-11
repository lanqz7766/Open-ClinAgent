import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react"
import { useOutletContext, useSearchParams } from "react-router-dom"
import {
  Activity,
  Brain,
  ChartNoAxesCombined,
  CheckCircle2,
  CircleAlert,
  ChevronDown,
  Copy,
  Database,
  FileText,
  GitCompareArrows,
  LayoutDashboard,
  Loader2,
  MessageSquare,
  ScanLine,
  Search,
  Send,
  Upload,
  type LucideIcon,
} from "lucide-react"
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { useApi } from "@/hooks/useApi"
import type { ChatMessage } from "@/lib/chatTypes"
import type { DemoLayoutContext } from "@/lib/ingestTypes"
import { cn } from "@/lib/utils"
import {
  buildSegmentationOverlayModel,
  defaultExpandedGroups,
  type SegmentationOverlayModel,
  type ViewerMode,
} from "@/lib/segmentationOverlay"
import {
  HybridImagingViewer,
  type SliceManifest,
  type SlicePlaneSet,
  type StructuralSliceRequestContext,
  type ViewerAssets,
} from "@/components/HybridImagingViewer"
import { MarkdownContent } from "@/components/MarkdownContent"
import { SummaryMetric } from "@/components/SummaryMetric"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select"
import type {
  NeuroKnowledgeAsset,
  NeuroKnowledgeAssetsResponse,
  NeuroKnowledgeCase,
  NeuroKnowledgeCaseStudy,
  NeuroKnowledgeCohortEntry,
  NeuroKnowledgeCohortResponse,
  NeuroKnowledgeLaunchResponse,
  NeuroKnowledgeSearchResponse,
  NeuroKnowledgeStudy,
} from "@/types/api"

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`)
  }
  return (await response.json()) as T
}

async function postJson<T>(url: string, body: object): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`)
  }
  return (await response.json()) as T
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function buildDemoProgressPlan(source: AnalysisSource): DemoProgressStep[] {
  if (source === "upload") {
    return [
      { stage: "attach_source", label: "Attach source", status: "pending", durationMs: 1000 },
      { stage: "capture_intake", label: "Capture intake", status: "pending", durationMs: 1000 },
      { stage: "auto_segmentation", label: "Run segmentation", status: "pending", durationMs: 2000 },
      { stage: "prepare_viewer", label: "Prepare viewer", status: "pending", durationMs: 1000 },
      { stage: "hydrate_workspace", label: "Hydrate workspace", status: "pending", durationMs: 800 },
    ]
  }
  return [
    { stage: "resolve_patient", label: "Resolve patient", status: "pending", durationMs: 1000 },
    { stage: "load_timeline", label: "Load timeline", status: "pending", durationMs: 1000 },
    { stage: "auto_segmentation", label: "Run segmentation", status: "pending", durationMs: 2000 },
    { stage: "prepare_viewer", label: "Prepare viewer", status: "pending", durationMs: 1000 },
    { stage: "hydrate_workspace", label: "Hydrate workspace", status: "pending", durationMs: 800 },
  ]
}

type ExampleCase = {
  case_id: string
  patient_id: string
  study_id: string
  study_date: string
  title: string
  description: string
  thumbnail_base64: string
  age: number
  sex: string
  default_mode: AnalysisMode
  supported_modes: AnalysisMode[]
  case_type?: "structural" | "response"
  viewer_assets?: ViewerAssets | null
  capability_profile: CapabilityProfile
  capability_profile_summary?: CapabilityProfileSummary | null
  analysis_plan: AnalysisPlan
  analysis_plan_summary?: AnalysisPlanSummary | null
  planning_result?: PlanningResult | null
  workspace_contract?: WorkspaceContract | null
  dashboard_payloads?: DashboardPayloads | null
  report?: {
    full_text: string
    sections: ReportSections | null
  } | null
}

type CuratedPatientGroup = {
  patientId: string
  representative: ExampleCase
  studies: ExampleCase[]
}

type ExamplesResponse = {
  default_case_id: string | null
  examples: ExampleCase[]
  preload_status?: {
    structural_ready: boolean
    response_ready: boolean
    structural_patient_count: number
    response_case_count: number
    example_count: number
    warnings: string[]
  } | null
}

type PatientSummary = {
  id: string
  name: string
  age: number
  sex: string
  study_count: number
  diagnosis: string
  default_study_id: string
  date_range: { start: string; end: string }
}

type PatientsResponse = {
  default_patient_id: string | null
  patients: PatientSummary[]
}

type PatientStudy = {
  study_id: string
  study_date: string
  age_at_study: number
  thumbnail_base64: string
  indication: string
  has_segmentation: boolean
  supported_modes: AnalysisMode[]
}

type PatientDataResponse = {
  patient: PatientSummary
  default_study_id: string
  studies: PatientStudy[]
  highlights: Array<{
    study_id: string
    study_date: string
    display_name: string
    z_score: number
    interpretation: string
  }>
}

type ReportSections = {
  clinical_information: string
  technique: string
  findings: string
  impression: string
}

type Region = {
  label_id?: number
  name: string
  label_name?: string
  display_name: string
  group?: string | null
  hemisphere?: string | null
  voxel_count?: number
  volume_mm3: number
  z_score?: number
  percentile?: number
  direction?: "high" | "low"
  interpretation?: string
}

type TrendSeriesMeta = {
  name: string
  display_name: string
  unit: string
  series_type: "anatomical_region" | "lesion_burden"
  priority?: number
}

type VolumetricsResponse = {
  regions: Region[]
  interpreted_regions?: Region[]
  grouped_regions?: Array<{
    name: string
    display_name: string
    group?: string | null
    voxel_count: number
    volume_mm3: number
    member_regions?: string[]
  }>
  total_brain_volume_mm3?: number | null
  summary: string
  kind?: "anatomical_region" | "lesion_burden"
  series_type?: "anatomical_region" | "lesion_burden"
  available_series?: TrendSeriesMeta[]
  default_series?: string[]
  csv_export_path?: string | null
  csv_export_url?: string | null
  label_source?: "vista_tsv" | "remote_schema" | string | null
  label_mapping_path?: string | null
  label_mapping_label_count?: number | null
  label_schema_path?: string | null
  label_schema_version?: string | null
  segmentation_backend?: string | null
  preprocessing_profile?: string | null
  lesion_count?: number | null
  total_lesion_volume_mm3?: number | null
  enhancing_burden_mm3?: number | null
  delta_vs_baseline?: number | null
  delta_vs_prior?: number | null
  confidence_or_coverage_note?: string | null
  response_category?: string | null
  active_study_id?: string | null
  baseline_study_id?: string | null
  prior_study_id?: string | null
}

type RightPanelTab = "report" | "review"

const RIGHT_PANEL_TAB_STORAGE_KEY = "neuro-report:right-panel-tab"

type SegmentationServiceStatus = {
  ok: boolean
  service_ready: boolean
  status?: "ready" | "not_configured" | "tunnel_down" | "remote_unhealthy" | "service_unavailable" | string
  service_url?: string | null
  error?: string | null
  model?: {
    model_id?: string | null
    label_count?: number | null
    input_modalities?: string[] | null
  } | null
}

type CapabilityProfile = {
  workflow_family?: string
  has_demographics: boolean
  has_single_study_mri: boolean
  imaging_format: string
  has_segmentation: boolean
  has_longitudinal_priors: boolean
  has_report_context: boolean
  has_ehr_context: boolean
  available_inputs: string[]
  missing_inputs: string[]
  blocked_reasons: string[]
}

type AnalysisPlan = {
  workflow_family: string
  analysis_track: "structural" | "response" | "review"
  primary_goal: "structural_report" | "response_review" | "report_review"
  dashboard_profile: "volumetry" | "longitudinal_response" | "report_review"
  secondary_lanes: string[]
  requested_goal: string
  recommended_workflow: string
  recommended_goal: string
  recommended_mode: AnalysisMode | null
  can_execute: boolean
  autorun: boolean
  allowed_analyses: string[]
  blocked_analyses: string[]
  missing_inputs: string[]
  rationale: string[]
  safe_fallback_mode: AnalysisMode | null
  stages: string[]
  handoff_summary: string
}

type AnalysisPlanSummary = {
  family: string
  track: "structural" | "response" | "review"
  primary_goal: "structural_report" | "response_review" | "report_review"
  dashboard_profile: "volumetry" | "longitudinal_response" | "report_review"
  secondary_lanes: string[]
  detected_inputs: string[]
  chosen_mode: AnalysisMode | null
  requested_mode: AnalysisMode | null
  recommended_mode: AnalysisMode | null
  missing_info: string[]
  viewer_type: ViewerAssets["viewer_type"]
  can_execute: boolean
  safety_fallback: string | null
  summary: string
  runtime_mode: string
}

type PlanningResult = {
  intent: string
  family: string
  track: "structural" | "response" | "review"
  primary_goal: "structural_report" | "response_review" | "report_review"
  dashboard_profile: "volumetry" | "longitudinal_response" | "report_review"
  secondary_lanes: string[]
  goal_confidence: number
  available_data: string[]
  recommended_workflow: string
  requested_goal: string
  recommended_goal: string
  reason_for_track_selection: string
  user_override_allowed: boolean
  context_sources: string[]
  can_execute: boolean
  missing_inputs: string[]
  recommended_next_action: string
  viewer_type: ViewerAssets["viewer_type"]
  blocked_claims?: string[]
}

type WorkspaceContract = {
  workflow_id: string
  workflow_family: string
  analysis_track: "structural" | "response" | "review"
  primary_goal: "structural_report" | "response_review" | "report_review"
  dashboard_profile: "volumetry" | "longitudinal_response" | "report_review"
  secondary_lanes: string[]
  workspace_url: string
  runtime_mode: string
  viewer_type: ViewerAssets["viewer_type"]
  can_autorun: boolean
}

type CapabilityProfileSummary = {
  detected_inputs: string[]
  missing_info: string[]
  blocked_reasons: string[]
  imaging_format: string
  has_segmentation: boolean
  has_demographics: boolean
  context_sources?: string[]
}

type DashboardPayloads = {
  active_profile: "volumetry" | "longitudinal_response" | "report_review"
  structural: {
    dashboard_profile: "volumetry"
    summary: string
    volumetrics_summary?: string | null
  }
  response: {
    dashboard_profile: "longitudinal_response"
    status: "ready" | "intake_only"
    summary: string
    requirements: string[]
    available_inputs: string[]
    recommended_tools: string[]
    source_label?: string
    baseline_total_ml?: number | null
    latest_total_ml?: number | null
    previous_total_ml?: number | null
    delta_pct?: number | null
    recent_segment_pct?: number | null
    annual_change_pct?: number | null
    lesion_count?: number | null
    risk_level?: string | null
    risk_reason?: string | null
    response_category?: string | null
    confidence_note?: string | null
    coverage_note?: string | null
    next_checks?: string[]
    timeline?: Array<{
      study_id: string
      study_date: string
      timepoint: string
      lesion_volume_ml: number
      percent_change_from_baseline?: number | null
      percent_change_from_prior?: number | null
    }>
    key_slice_compare?: {
      title?: string
      caption?: string
      image_url?: string | null
    } | null
    report_summary?: string | null
    report_sections?: Array<{ title?: string; body?: string }>
  }
  review: {
    dashboard_profile: "report_review"
    summary: string
    recommended_tools: string[]
    status?: string
    finding_groups?: Array<{
      label: string
      status: string
      items: Array<{
        label: string
        severity: string
        count: number
        recommendation?: string
      }>
    }>
    revision_suggestions?: string[]
    source_report_sections?: ReportSections | null
  }
}

type StudyDetailResponse = {
  patient_id: string
  study_id: string
  study_date: string
  age_at_study: number
  sex: string
  indication: string
  image_name: string
  segmentation_name: string | null
  thumbnail_base64: string
  viewer_assets: ViewerAssets
  slices?: SlicePlaneSet | null
  raw_slices?: SlicePlaneSet | null
  overlay_slices?: SlicePlaneSet | null
  slice_manifest?: SliceManifest | null
  slice_source?: "on_demand" | "sampled" | null
  report: { full_text: string; sections: ReportSections }
  volumetrics: VolumetricsResponse | null
  segmentation_regions?: Region[] | null
  label_source?: "vista_tsv" | "remote_schema" | string | null
  label_mapping_path?: string | null
  label_mapping_label_count?: number | null
  label_schema_path?: string | null
  label_schema_version?: string | null
  key_findings: Region[]
  supported_modes: AnalysisMode[]
  capability_profile: CapabilityProfile
  capability_profile_summary?: CapabilityProfileSummary | null
  analysis_plan: AnalysisPlan
  analysis_plan_summary?: AnalysisPlanSummary | null
  dashboard_payloads?: DashboardPayloads | null
  planning_result?: PlanningResult | null
  workspace_contract?: WorkspaceContract | null
}

type AnalysisSessionResponse = {
  ok: boolean
  session_id: string
  patient_id: string | null
  study_id: string | null
  case_id: string | null
  source: AnalysisSource | null
  mode: AnalysisMode | null
  requested_mode: AnalysisMode | null
  age: number | null
  sex: string | null
  indication: string | null
  image_name: string | null
  segmentation_name: string | null
  report: string
  report_sections: ReportSections | null
  viewer_assets: ViewerAssets | null
  slice_manifest?: SliceManifest | null
  slice_source?: "on_demand" | "sampled" | null
  volumetrics: VolumetricsResponse | null
  segmentation_regions?: Region[] | null
  label_source?: "vista_tsv" | "remote_schema" | string | null
  label_mapping_path?: string | null
  label_mapping_label_count?: number | null
  label_schema_version?: string | null
  analysis_plan: AnalysisPlan | null
  analysis_plan_summary?: AnalysisPlanSummary | null
  capability_profile: CapabilityProfile | null
  capability_profile_summary?: CapabilityProfileSummary | null
  dashboard_payloads?: DashboardPayloads | null
  planning_result?: PlanningResult | null
  workspace_contract?: WorkspaceContract | null
  segmentation_backend?: string | null
  preprocessing_profile?: string | null
  csv_export_url?: string | null
}

type KnowledgeWorkspaceHydrationResponse = AnalysisSessionResponse & {
  local_status: KnowledgeLocalStatus
}

type ViewerStudySummary = {
  study_id: string
  study_date: string
  has_segmentation: boolean
}

type LongitudinalResponse = {
  patient_id: string
  patient_name: string
  region_names: string[]
  available_series?: TrendSeriesMeta[]
  default_series?: string[]
  series: Array<Record<string, string | number | null>>
  highlights: Array<{
    study_id: string
    study_date: string
    display_name: string
    z_score: number
    interpretation: string
  }>
}

type HeatmapResponse = {
  patient_id: string
  region_names: string[]
  available_series?: TrendSeriesMeta[]
  default_series?: string[]
  dates: string[]
  matrix: Record<string, Array<{ z_score: number | null; volume_mm3: number | null }>>
}

type AnalysisSource = "example" | "upload" | "knowledge"
type AnalysisMode = "vanilla" | "seg_overlay" | "tool_output" | "full_agent"
type NeuroWorkspaceTab = "overview" | "segmentation" | "alignment" | "trend" | "report"
type AlignmentWorkflow = "longitudinal_coregistration" | "sequence_coregistration"

type KnowledgeLocalStatus = NeuroKnowledgeLaunchResponse["local_status"] | "checking"
type KnowledgeCaseFilter = "all" | "longitudinal" | "single"

type AlignmentJobResponse = {
  job_id: string
  status: "completed" | "failed" | "running" | "queued" | string
  mode: "demo" | "remote" | string
  workflow: AlignmentWorkflow | string
  patient_id?: string | null
  fixed_study_id?: string | null
  moving_study_id?: string | null
  apply_to_segmentation?: boolean
  clinical_summary?: string
  error?: string
  stages?: Array<{ stage: string; label: string; status: string }>
  qc?: {
    translation_mm?: number[]
    translation_norm_mm?: number
    ncc_before?: number
    ncc_after?: number
    ncc_delta?: number
    resampled_to_reference_grid?: boolean
    nonlinear_deformation_allowed?: boolean
    warnings?: string[]
    clinical_warnings?: string[]
  }
  outputs?: {
    aligned_image_label?: string | null
    transferred_segmentation_label?: string | null
    aligned_image_path?: string | null
    transform_path?: string | null
    transferred_segmentation_path?: string | null
    viewer_hint?: string | null
  }
}

type AnalysisState = {
  running: boolean
  error: string | null
  progress: Array<{ stage: string; label: string; status: "pending" | "running" | "done" | "skipped" }>
  report: string
  reportSections: ReportSections | null
  rawSlices: SlicePlaneSet | null
  overlaySlices: SlicePlaneSet | null
  sliceManifest: SliceManifest | null
  sliceSource: "on_demand" | "sampled" | null
  viewerAssets: ViewerAssets | null
  volumetrics: VolumetricsResponse | null
  segmentationRegions: Region[] | null
  sessionId: string | null
  analysisPlan: AnalysisPlan | null
  analysisPlanSummary: AnalysisPlanSummary | null
  capabilityProfile: CapabilityProfile | null
  capabilityProfileSummary: CapabilityProfileSummary | null
  planningResult: PlanningResult | null
  workspaceContract: WorkspaceContract | null
  requestedMode: AnalysisMode | null
  executedMode: AnalysisMode | null
  dashboardPayloads: DashboardPayloads | null
  segmentationBackend: string | null
  preprocessingProfile: string | null
  csvExportUrl: string | null
  labelSource: "vista_tsv" | "remote_schema" | string | null
  labelMappingPath: string | null
  labelMappingLabelCount: number | null
  labelSchemaVersion: string | null
  source: AnalysisSource | null
}

type DemoProgressStep = {
  stage: string
  label: string
  status: "pending" | "running" | "done" | "skipped"
  durationMs: number
}

type HydrationStage = {
  stage: string
  label: string
  hint: string
  status: "pending" | "running" | "done"
}

type HydrationMetric = {
  label: string
  value: string
}

const MODE_META: Record<
  AnalysisMode,
  { label: string; description: string }
> = {
  vanilla: {
    label: "Vanilla",
    description: "Image-only read for a fast structured report.",
  },
  seg_overlay: {
    label: "Overlay",
    description: "MRI slices with segmentation overlays for visual grounding.",
  },
  tool_output: {
    label: "Tool Output",
    description: "Inject segmentation and volumetric outputs directly into the report step.",
  },
  full_agent: {
    label: "Full Agent",
    description: "Three-step reasoning with slices, tools, and synthesized reporting.",
  },
}

const TREND_COLORS = ["#5dd39e", "#3cae74", "#64b5f6", "#2d8cf0", "#ef6c57", "#9c6bff", "#f6b44b", "#ef476f"]
const KNOWLEDGE_STUDY_THUMBNAIL_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAGElEQVR4nGNkYGBgYGBgYGBgYGBgAAAANQABJzQnCgAAAABJRU5ErkJggg=="
const NEURO_WORKSPACE_TABS: Array<{
  id: NeuroWorkspaceTab
  label: string
  description: string
  icon: LucideIcon
}> = [
  { id: "overview", label: "Overview", description: "Case context and recommended next step", icon: LayoutDashboard },
  { id: "segmentation", label: "Segmentation", description: "Viewer, labels, and structural measurements", icon: ScanLine },
  { id: "alignment", label: "Alignment", description: "Sequence and longitudinal co-registration", icon: GitCompareArrows },
  { id: "trend", label: "Trend", description: "Longitudinal volumetric change", icon: ChartNoAxesCombined },
  { id: "report", label: "Report", description: "Draft findings and review lane", icon: FileText },
]

function normalizeWorkspaceTab(value: string | null): NeuroWorkspaceTab {
  return NEURO_WORKSPACE_TABS.some((tab) => tab.id === value) ? (value as NeuroWorkspaceTab) : "overview"
}

function readSseChunk(buffer: string) {
  const chunks = buffer.split("\n\n")
  return {
    complete: chunks.slice(0, -1),
    remainder: chunks[chunks.length - 1] ?? "",
  }
}

async function consumeSse(
  response: Response,
  onEvent: (eventName: string, payload: Record<string, unknown>) => void,
) {
  if (!response.ok || !response.body) {
    throw new Error(`Request failed with status ${response.status}`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      break
    }
    buffer += decoder.decode(value, { stream: true })
    const { complete, remainder } = readSseChunk(buffer)
    buffer = remainder

    for (const chunk of complete) {
      const lines = chunk.split("\n")
      const eventLine = lines.find((line) => line.startsWith("event: "))
      const dataLine = lines.find((line) => line.startsWith("data: "))
      if (!eventLine || !dataLine) {
        continue
      }
      onEvent(eventLine.slice(7).trim(), JSON.parse(dataLine.slice(6)) as Record<string, unknown>)
    }
  }
}

function formatShortDate(value: string) {
  if (!value) {
    return "Unknown date"
  }
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) {
    return value
  }
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" })
}

function studyTime(value: string) {
  const timestamp = new Date(value).getTime()
  return Number.isFinite(timestamp) ? timestamp : 0
}

function sortStudiesByDate<T extends { study_date: string }>(studies: T[]) {
  return [...studies].sort((left, right) => studyTime(left.study_date) - studyTime(right.study_date))
}

function formatCompareValue(value: number, unit: string) {
  if (unit === "count") {
    return `${Math.round(value).toLocaleString()} ${unit}`
  }
  return `${Math.round(value).toLocaleString()} ${unit}`
}

function formatPercentDelta(value: number | null) {
  if (value == null || !Number.isFinite(value)) {
    return "—"
  }
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`
}

function zColor(zScore: number | null | undefined) {
  if (zScore == null) {
    return "bg-[hsl(var(--muted))]"
  }
  const magnitude = Math.abs(zScore)
  if (magnitude >= 2) {
    return zScore > 0 ? "bg-rose-500/80" : "bg-amber-500/80"
  }
  if (magnitude >= 1.2) {
    return zScore > 0 ? "bg-sky-500/75" : "bg-emerald-500/75"
  }
  return "bg-[hsl(var(--muted))]"
}

function summarizeRisk(volumetrics: VolumetricsResponse | null) {
  const interpreted = volumetrics?.interpreted_regions ?? volumetrics?.regions ?? []
  if (!interpreted.length) {
    return "low" as const
  }
  const maxAbs = Math.max(...interpreted.map((region) => Math.abs(region.z_score ?? 0)))
  if (maxAbs >= 2) {
    return "critical" as const
  }
  if (maxAbs >= 1.6) {
    return "high" as const
  }
  if (maxAbs >= 1.0) {
    return "moderate" as const
  }
  return "low" as const
}

function reportPreviewText(reportSections: ReportSections | null, report: string) {
  return reportSections?.impression || reportSections?.findings || report || "MRI analysis report ready."
}

function knowledgeLocalStatusLabel(status: KnowledgeLocalStatus | null) {
  switch (status) {
    case "checking":
      return "Checking local mirror"
    case "ready_local":
      return "Available locally"
    case "downloaded":
      return "Downloaded for this session"
    case "missing":
      return "Will download on analyze"
    case "failed":
      return "Download failed"
    default:
      return "Status unavailable"
  }
}

function isKnowledgeSegmentationAsset(asset: NeuroKnowledgeAsset) {
  const kind = asset.asset_kind.toLowerCase()
  const family = asset.segmentation_family?.toLowerCase() ?? ""
  return kind === "vista_zip" || kind === "nvseg_zip" || kind.includes("seg") || family === "vista" || family === "nvseg"
}

function hasKnowledgeAsset(value: number | boolean | undefined) {
  return value === true || value === 1
}

function isLongitudinalKnowledgeCase(entry: NeuroKnowledgeCohortEntry) {
  const shape = entry.cohort_shape?.toLowerCase() ?? ""
  return entry.study_count > 1 || shape.includes("multi") || shape.includes("longitudinal")
}

function knowledgeCohortRankScore(entry: NeuroKnowledgeCohortEntry) {
  const demoPriority = entry.patient_uid === "2016" ? 1000 : 0
  const longitudinalPriority = isLongitudinalKnowledgeCase(entry) ? 220 : 0
  const reportPriority = Math.min(entry.report_count ?? 0, 8) * 18
  const studyPriority = Math.min(entry.study_count ?? 0, 8) * 14
  const assetPriority =
    (hasKnowledgeAsset(entry.has_mri_zip) ? 28 : 0) +
    (hasKnowledgeAsset(entry.has_nvseg) ? 24 : 0) +
    (hasKnowledgeAsset(entry.has_vista_seg) ? 18 : 0)
  const richnessPriority = Math.min(entry.richness_score ?? 0, 100)
  const rankPenalty = entry.cohort_rank != null ? entry.cohort_rank * 0.01 : 0
  return demoPriority + longitudinalPriority + reportPriority + studyPriority + assetPriority + richnessPriority - rankPenalty
}

function knowledgeCohortMatches(entry: NeuroKnowledgeCohortEntry, query: string) {
  const tokens = query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
  if (!tokens.length) {
    return true
  }
  const haystack = [
    entry.patient_uid,
    entry.case_label,
    entry.cohort_shape,
    entry.cohort_tag,
    entry.summary_text,
    entry.selection_reason,
    ...(entry.study_uids ?? []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
  return tokens.every((token) => haystack.includes(token))
}

function knowledgeCohortFilterMatches(entry: NeuroKnowledgeCohortEntry, filter: KnowledgeCaseFilter) {
  if (filter === "longitudinal") {
    return isLongitudinalKnowledgeCase(entry)
  }
  if (filter === "single") {
    return !isLongitudinalKnowledgeCase(entry)
  }
  return true
}

function knowledgeStudyAssetFlags(assets: NeuroKnowledgeAsset[], studyUid: string) {
  const studyAssets = assets.filter((asset) => asset.study_uid === studyUid)
  return {
    mri: studyAssets.some((asset) => asset.asset_kind.toLowerCase() === "mri_zip" && hasKnowledgeAsset(asset.available)),
    nvseg: studyAssets.some((asset) => asset.asset_kind.toLowerCase() === "nvseg_zip" && hasKnowledgeAsset(asset.available)),
    vista: studyAssets.some((asset) => asset.asset_kind.toLowerCase() === "vista_zip" && hasKnowledgeAsset(asset.available)),
    segmentation: studyAssets.some((asset) => hasKnowledgeAsset(asset.available) && isKnowledgeSegmentationAsset(asset)),
  }
}

function uploadHydrationTitle(uploadDisplayName: string, hasUploadFile: boolean, uploadSourcePath: string) {
  if (hasUploadFile || uploadSourcePath) {
    return `Upload intake for ${uploadDisplayName}`
  }
  return "Upload intake"
}

function trendValueKeys(seriesName: string) {
  if (seriesName === "total_lesion_volume_mm3") {
    return {
      valueKey: "total_lesion_volume_mm3",
      deltaKey: "total_lesion_volume_mm3_delta",
    }
  }
  if (seriesName === "enhancing_burden_mm3") {
    return {
      valueKey: "enhancing_burden_mm3",
      deltaKey: "enhancing_burden_mm3_delta",
    }
  }
  if (seriesName === "lesion_count") {
    return {
      valueKey: "lesion_count",
      deltaKey: "lesion_count_delta",
    }
  }
  return {
    valueKey: `${seriesName}_volume_mm3`,
    deltaKey: `${seriesName}_z_score`,
  }
}

function formatTrendUnit(meta: TrendSeriesMeta | undefined) {
  if (!meta) {
    return "value"
  }
  if (meta.unit === "count") {
    return "count"
  }
  if (meta.unit.toLowerCase() === "mm3") {
    return "mm³"
  }
  return meta.unit
}

function humanizeGroupLabel(value: string) {
  return value
    .replaceAll("_", " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

function buildTrendSeriesGroups(trendSeries: TrendSeriesMeta[], segmentationRegions: Region[] | null) {
  const regionGroupByName = new Map<string, string>()
  for (const region of segmentationRegions ?? []) {
    if (region.name && region.group) {
      regionGroupByName.set(region.name, region.group)
    }
  }

  const grouped = new Map<string, { id: string; displayName: string; series: TrendSeriesMeta[] }>()
  for (const series of trendSeries) {
    const groupId =
      series.series_type === "lesion_burden"
        ? "lesion_burden"
        : regionGroupByName.get(series.name) || "ungrouped"
    const displayName = groupId === "lesion_burden" ? "Lesion burden" : humanizeGroupLabel(groupId)
    const group = grouped.get(groupId) ?? { id: groupId, displayName, series: [] }
    group.series.push(series)
    grouped.set(groupId, group)
  }

  return [...grouped.values()]
    .map((group) => ({
      ...group,
      series: [...group.series].sort((left, right) => (left.priority ?? 100) - (right.priority ?? 100) || left.display_name.localeCompare(right.display_name)),
    }))
    .sort((left, right) => left.displayName.localeCompare(right.displayName))
}

function toggleTrendSeriesSelection(current: string[], seriesName: string) {
  if (current.includes(seriesName)) {
    return current.length > 1 ? current.filter((item) => item !== seriesName) : current
  }
  return [...current, seriesName].slice(-4)
}

function copyText(value: string) {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    void navigator.clipboard.writeText(value)
  }
}

function extractExampleStudyDate(example: ExampleCase) {
  if (example.study_date) {
    return example.study_date
  }
  const match = example.title.match(/\b\d{4}-\d{2}-\d{2}\b/)
  return match?.[0] ?? ""
}

function CaseCard({
  group,
  selected,
  onSelect,
}: {
  group: CuratedPatientGroup
  selected: boolean
  onSelect: () => void
}) {
  const { representative, studies, patientId } = group
  const representativeDate = extractExampleStudyDate(representative)
  const primaryGoal =
    representative.planning_result?.primary_goal ?? representative.analysis_plan_summary?.primary_goal ?? "structural_report"

  return (
    <button
      className={cn(
        "group flex h-full flex-col overflow-hidden rounded-[1.25rem] border text-left transition-all",
        selected
          ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.06)] shadow-[0_18px_60px_-32px_hsl(var(--primary)/0.45)]"
          : "border-[hsl(var(--border))] bg-[hsl(var(--card))] hover:border-[hsl(var(--primary)/0.35)] hover:bg-[hsl(var(--accent)/0.4)]",
      )}
      onClick={onSelect}
      type="button"
    >
      <div className="relative h-32 overflow-hidden bg-black">
        <img
          alt={representative.title}
          className="h-full w-full object-cover opacity-90 transition-transform duration-300 group-hover:scale-[1.02]"
          src={`data:image/png;base64,${representative.thumbnail_base64}`}
        />
        <div className="absolute inset-0 bg-[linear-gradient(180deg,transparent,rgba(0,0,0,0.55))]" />
        <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between text-white">
          <div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-white/60">
              {representative.case_type === "response" ? "Response review" : "Structural review"} patient
            </div>
            <div className="mt-1 text-[15px] font-medium">{patientId}</div>
          </div>
          <div className="rounded-full border border-white/20 bg-white/10 px-2.5 py-1 text-[11px]">
            {MODE_META[representative.default_mode].label}
          </div>
        </div>
      </div>
      <div className="flex h-[12.5rem] flex-1 flex-col gap-3 p-4">
        <div>
          <div className="line-clamp-2 text-[14px] font-medium text-[hsl(var(--foreground))]">
            Patient {patientId}{representativeDate ? ` · ${representativeDate}` : ""}
          </div>
          <div className="mt-1 line-clamp-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
            {studies.length > 1
              ? `${studies.length} studies available. Opens the patient timeline with the latest study selected.`
              : representative.description}
          </div>
        </div>
        <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">
          {primaryGoal.replaceAll("_", " ")}
        </div>
        <div className="mt-auto flex flex-wrap gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
          <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1">
            {(representative.case_type || "structural").replaceAll("_", " ")}
          </span>
          <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1">{representative.sex}</span>
          <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1">{representative.age}y</span>
          <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1">
            {studies.length} {studies.length === 1 ? "study" : "studies"}
          </span>
        </div>
      </div>
    </button>
  )
}

function KnowledgeAssetChip({
  label,
  available,
  className,
}: {
  label: string
  available: boolean
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-medium",
        available
          ? "border-emerald-500/24 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
          : "border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[hsl(var(--muted-foreground))]",
        className,
      )}
    >
      {available ? <CheckCircle2 className="size-3 shrink-0" /> : <CircleAlert className="size-3 shrink-0" />}
      {label}
    </span>
  )
}

function KnowledgeDemoCasePicker({
  cohort,
  filteredCohort,
  query,
  filter,
  selectedPatientUid,
  selectedStudyUid,
  selectedEntry,
  selectedSummary,
  studies,
  assets,
  caseLoading,
  studyLoading,
  cohortLoading,
  cohortError,
  caseError,
  studyError,
  localStatus,
  localStatusError,
  segmentationStatus,
  onQueryChange,
  onFilterChange,
  onSelectCase,
  onUseStudy,
}: {
  cohort: NeuroKnowledgeCohortEntry[]
  filteredCohort: NeuroKnowledgeCohortEntry[]
  query: string
  filter: KnowledgeCaseFilter
  selectedPatientUid: string
  selectedStudyUid: string
  selectedEntry: NeuroKnowledgeCohortEntry | null
  selectedSummary: NeuroKnowledgeCase["summary"] | null
  studies: NeuroKnowledgeCaseStudy[]
  assets: NeuroKnowledgeAsset[]
  caseLoading: boolean
  studyLoading: boolean
  cohortLoading: boolean
  cohortError: string | null
  caseError: string | null
  studyError: string | null
  localStatus: KnowledgeLocalStatus | null
  localStatusError: string | null
  segmentationStatus: {
    label: string
    tone: "ready" | "warming" | "neutral" | "unavailable"
    loading: boolean
  }
  onQueryChange: (value: string) => void
  onFilterChange: (value: KnowledgeCaseFilter) => void
  onSelectCase: (patientUid: string) => void
  onUseStudy: (studyUid: string) => void
}) {
  const selectedCaseSummary =
    selectedSummary?.summary_text ||
    selectedEntry?.summary_text ||
    selectedEntry?.selection_reason ||
    "MR-RATE metadata is ready for this case."
  const sortedStudies = useMemo(
    () => [...studies].sort((left, right) => studyTime(right.anon_study_date ?? "") - studyTime(left.anon_study_date ?? "")),
    [studies],
  )
  const selectedStudy = studies.find((study) => study.study_uid === selectedStudyUid) ?? null
  const selectedStudyFlags = selectedStudyUid
    ? knowledgeStudyAssetFlags(assets, selectedStudyUid)
    : { mri: false, nvseg: false, vista: false, segmentation: false }
  const filterItems: Array<{ value: KnowledgeCaseFilter; label: string }> = [
    { value: "all", label: "All" },
    { value: "longitudinal", label: "Longitudinal" },
    { value: "single", label: "Single" },
  ]

  return (
    <section className="min-w-0 overflow-hidden rounded-[1.5rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <div className="border-b border-[hsl(var(--border)/0.72)] px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">
              <Database className="size-3.5" />
              MR-RATE case picker
            </div>
            <div className="mt-1 text-[17px] font-medium text-[hsl(var(--foreground))]">Choose a case, then choose a study</div>
          </div>
          <div className="flex flex-wrap gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
            <span className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2.5 py-1">
              {cohort.length} cases
            </span>
            <span className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2.5 py-1">
              {cohort.reduce((total, entry) => total + (entry.study_count ?? 0), 0)} studies
            </span>
            <span className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2.5 py-1">
              {cohort.filter(isLongitudinalKnowledgeCase).length} longitudinal
            </span>
          </div>
        </div>
      </div>

      <div className="grid min-w-0 gap-0 xl:grid-cols-[minmax(20rem,0.9fr)_minmax(0,1.35fr)]">
        <div className="min-w-0 border-b border-[hsl(var(--border)/0.72)] p-4 xl:border-b-0 xl:border-r">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
            <input
              className="h-11 w-full rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] pl-9 pr-3 text-[13px] outline-none transition-colors placeholder:text-[hsl(var(--muted-foreground))] focus:border-[hsl(var(--primary)/0.45)]"
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="Search case, report, study UID"
              value={query}
            />
          </div>

          <div className="mt-3 grid grid-cols-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-1">
            {filterItems.map((item) => (
              <button
                className={cn(
                  "h-8 rounded-lg text-[12px] font-medium transition-colors",
                  filter === item.value
                    ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                    : "text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]",
                )}
                key={item.value}
                onClick={() => onFilterChange(item.value)}
                type="button"
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="mt-4 max-h-[34rem] space-y-2 overflow-y-auto pr-1">
            {cohortLoading ? (
              <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-4 text-[13px] text-[hsl(var(--muted-foreground))]">
                <Loader2 className="mr-2 inline size-3.5 animate-spin" />
                Loading MR-RATE cohort
              </div>
            ) : null}
            {cohortError ? (
              <div className="rounded-xl border border-destructive/25 bg-destructive/10 px-3 py-4 text-[13px] text-destructive">
                {cohortError}
              </div>
            ) : null}
            {!cohortLoading && !filteredCohort.length ? (
              <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-4 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
                No matching cases.
              </div>
            ) : null}
            {filteredCohort.map((entry) => {
              const selected = entry.patient_uid === selectedPatientUid
              const longitudinal = isLongitudinalKnowledgeCase(entry)
              return (
                <button
                  className={cn(
                    "group w-full rounded-[1rem] border px-3 py-3 text-left transition-all",
                    selected
                      ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.07)] shadow-[0_18px_44px_-34px_hsl(var(--primary)/0.52)]"
                      : "border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:border-[hsl(var(--primary)/0.35)] hover:bg-[hsl(var(--accent)/0.35)]",
                  )}
                  key={entry.patient_uid}
                  onClick={() => onSelectCase(entry.patient_uid)}
                  type="button"
                >
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <div className="truncate text-[15px] font-medium text-[hsl(var(--foreground))]">Case {entry.patient_uid}</div>
                        <span
                          className={cn(
                            "shrink-0 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.12em]",
                            longitudinal
                              ? "border-sky-500/25 bg-sky-500/10 text-sky-700 dark:text-sky-300"
                              : "border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))]",
                          )}
                        >
                          {longitudinal ? "Longitudinal" : "Single"}
                        </span>
                      </div>
                      <div className="mt-1 text-[12px] text-[hsl(var(--muted-foreground))]">
                        {entry.study_count} studies · {entry.report_count} reports
                      </div>
                    </div>
                    <div className="shrink-0 text-[11px] text-[hsl(var(--muted-foreground))]">#{entry.cohort_rank ?? "—"}</div>
                  </div>
                  <div className="mt-2 line-clamp-2 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">
                    {entry.summary_text || entry.selection_reason || entry.case_label || "MR-RATE case metadata available."}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    <KnowledgeAssetChip available={hasKnowledgeAsset(entry.has_mri_zip)} label="MRI" />
                    <KnowledgeAssetChip available={hasKnowledgeAsset(entry.has_nvseg)} label="NVSeg" />
                    <KnowledgeAssetChip available={hasKnowledgeAsset(entry.has_vista_seg)} label="Vista" />
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        <div className="min-w-0 p-5">
          {!selectedPatientUid ? (
            <div className="flex min-h-[26rem] items-center justify-center rounded-[1.25rem] border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--background)/0.55)] px-6 text-center">
              <div className="max-w-[24rem]">
                <div className="mx-auto flex size-12 items-center justify-center rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--background))]">
                  <Database className="size-5 text-[hsl(var(--muted-foreground))]" />
                </div>
                <div className="mt-4 text-[16px] font-medium text-[hsl(var(--foreground))]">No case loaded</div>
                <div className="mt-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
                  Pick a case from the MR-RATE registry to inspect its studies.
                </div>
              </div>
            </div>
          ) : (
            <div className="min-w-0 space-y-4">
              <div className="rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Selected case</div>
                    <div className="mt-1 truncate text-[19px] font-medium text-[hsl(var(--foreground))]">Case {selectedPatientUid}</div>
                  </div>
                  <Badge className="rounded-full px-3 py-1 text-[11px] font-medium" variant="outline">
                    {selectedEntry && isLongitudinalKnowledgeCase(selectedEntry) ? "Longitudinal" : "Study set"}
                  </Badge>
                </div>
                <div className="mt-3 line-clamp-3 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">{selectedCaseSummary}</div>
                <div className="mt-4 grid gap-2 sm:grid-cols-3">
                  <div className="rounded-xl border border-[hsl(var(--border))] px-3 py-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Studies</div>
                    <div className="mt-1 text-[15px] font-medium text-[hsl(var(--foreground))]">{studies.length || selectedEntry?.study_count || "—"}</div>
                  </div>
                  <div className="rounded-xl border border-[hsl(var(--border))] px-3 py-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Reports</div>
                    <div className="mt-1 text-[15px] font-medium text-[hsl(var(--foreground))]">{selectedEntry?.report_count ?? selectedSummary?.report_count ?? "—"}</div>
                  </div>
                  <div className="rounded-xl border border-[hsl(var(--border))] px-3 py-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Mirror</div>
                    <div className="mt-1 text-[15px] font-medium text-[hsl(var(--foreground))]">
                      {selectedStudyUid ? knowledgeLocalStatusLabel(localStatus) : "Not loaded"}
                    </div>
                  </div>
                </div>
                {caseError ? (
                  <div className="mt-3 rounded-xl border border-destructive/25 bg-destructive/10 px-3 py-3 text-[12px] text-destructive">
                    {caseError}
                  </div>
                ) : null}
              </div>

              <div className="rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Selected study</div>
                    <div className="mt-1 truncate text-[16px] font-medium text-[hsl(var(--foreground))]">
                      {selectedStudyUid || "No study selected"}
                    </div>
                  </div>
                  {selectedStudyUid ? (
                    <SegmentationReadyPill
                      className="h-8 px-2.5 text-[11px]"
                      label={segmentationStatus.label}
                      loading={segmentationStatus.loading}
                      tone={segmentationStatus.tone}
                    />
                  ) : null}
                </div>

                {!selectedStudyUid ? (
                  <div className="mt-3 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
                    Select a study card below to prepare the preview workspace.
                  </div>
                ) : (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] text-[hsl(var(--muted-foreground))]">
                      {selectedStudy ? formatShortDate(selectedStudy.anon_study_date ?? "") : "Unknown date"}
                    </span>
                    <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] text-[hsl(var(--muted-foreground))]">
                      {studyLoading || localStatus === "checking" ? "Checking mirror" : knowledgeLocalStatusLabel(localStatus)}
                    </span>
                    <KnowledgeAssetChip available={selectedStudyFlags.mri} label="MRI" />
                    <KnowledgeAssetChip available={selectedStudyFlags.nvseg} label="NVSeg" />
                    <KnowledgeAssetChip available={selectedStudyFlags.vista} label="Vista" />
                  </div>
                )}

                {studyLoading ? (
                  <div className="mt-3 rounded-xl border border-[hsl(var(--border))] px-3 py-3 text-[12px] text-[hsl(var(--muted-foreground))]">
                    <Loader2 className="mr-2 inline size-3.5 animate-spin" />
                    Loading study context
                  </div>
                ) : null}
                {studyError ? (
                  <div className="mt-3 rounded-xl border border-destructive/25 bg-destructive/10 px-3 py-3 text-[12px] text-destructive">
                    {studyError}
                  </div>
                ) : null}
                {localStatusError ? (
                  <div className="mt-3 rounded-xl border border-amber-500/25 bg-amber-500/10 px-3 py-3 text-[12px] text-amber-700 dark:text-amber-300">
                    {localStatusError}
                  </div>
                ) : null}
              </div>

              <div className="min-w-0">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Studies</div>
                  {caseLoading ? <Loader2 className="size-4 animate-spin text-[hsl(var(--muted-foreground))]" /> : null}
                </div>
                <div className="grid max-h-[22rem] gap-2 overflow-y-auto pr-1 md:grid-cols-2">
                  {!caseLoading && !sortedStudies.length ? (
                    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-4 text-[13px] text-[hsl(var(--muted-foreground))]">
                      No studies indexed for this case.
                    </div>
                  ) : null}
                  {sortedStudies.map((study) => {
                    const flags = knowledgeStudyAssetFlags(assets, study.study_uid)
                    const selected = study.study_uid === selectedStudyUid
                    return (
                      <button
                        className={cn(
                          "w-full rounded-[1rem] border px-3 py-3 text-left transition-all",
                          selected
                            ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.07)]"
                            : "border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:border-[hsl(var(--primary)/0.35)]",
                        )}
                        key={study.study_uid}
                        onClick={() => onUseStudy(study.study_uid)}
                        type="button"
                      >
                        <div className="flex min-w-0 items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-[13px] font-medium text-[hsl(var(--foreground))]">{formatShortDate(study.anon_study_date ?? "")}</div>
                            <div className="mt-1 truncate text-[12px] text-[hsl(var(--muted-foreground))]">{study.study_uid}</div>
                          </div>
                          <span
                            className={cn(
                              "shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium",
                              selected
                                ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                                : "border border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))]",
                            )}
                          >
                            {selected ? "Selected" : "Use study"}
                          </span>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-1.5">
                          <KnowledgeAssetChip available={Boolean(study.report_available)} label="Report" />
                          <KnowledgeAssetChip available={flags.mri} label="MRI" />
                          <KnowledgeAssetChip available={flags.segmentation} label={flags.nvseg ? "NVSeg" : "Seg"} />
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function SelectedCaseDetailStrip({
  example,
}: {
  example: ExampleCase
}) {
  const primaryGoal =
    example.planning_result?.primary_goal ?? example.analysis_plan_summary?.primary_goal ?? example.analysis_plan?.primary_goal ?? "structural_report"
  return (
    <div className="rounded-[1.25rem] border border-[hsl(var(--primary)/0.22)] bg-[hsl(var(--primary)/0.05)] px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Selected case</div>
          <div className="text-[16px] font-medium text-[hsl(var(--foreground))]">{example.title}</div>
          <div className="max-w-3xl text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">{example.description}</div>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px]">
          <span className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2.5 py-1">
            Goal {primaryGoal.replaceAll("_", " ")}
          </span>
          <span className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2.5 py-1">
            {example.case_type === "response" ? "Tumor / lesion" : "Structural"} case
          </span>
          <span className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2.5 py-1">
            Case {example.case_id}
          </span>
        </div>
      </div>
    </div>
  )
}

function ViewerStudySelector({
  caseId,
  patientLabel,
  selectedStudyId,
  selectedStudySummary,
  patientStudies,
  onSelectStudy,
}: {
  caseId: string | null
  patientLabel: string | null
  selectedStudyId: string | null
  selectedStudySummary: ViewerStudySummary | null
  patientStudies: PatientStudy[]
  onSelectStudy: (study: PatientStudy) => void
}) {
  if (!caseId && !patientLabel && !patientStudies.length) {
    return null
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-[1rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {patientLabel ? (
            <Badge className="rounded-full px-2 py-0.5 text-[10px] font-medium" variant="outline">
              {patientLabel}
            </Badge>
          ) : null}
          {caseId ? (
            <Badge className="rounded-full px-2 py-0.5 text-[10px] font-medium" variant="secondary">
              Case {caseId}
            </Badge>
          ) : null}
          {selectedStudySummary?.has_segmentation ? (
            <Badge className="rounded-full px-2 py-0.5 text-[10px] font-medium" variant="outline">
              Segmentation
            </Badge>
          ) : null}
        </div>
        <div className="mt-2 text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Viewer study</div>
        <div className="mt-1 text-[13px] font-medium text-[hsl(var(--foreground))]">
          {selectedStudySummary ? formatShortDate(selectedStudySummary.study_date) : "No study selected"}
        </div>
      </div>
      {patientStudies.length ? (
        <div className="w-full sm:w-auto sm:min-w-[11rem]">
          <Select
            onValueChange={(value) => {
              const study = patientStudies.find((item) => item.study_id === value)
              if (study) {
                onSelectStudy(study)
              }
            }}
            value={selectedStudyId ?? ""}
          >
            <SelectTrigger className="h-9 rounded-full bg-[hsl(var(--background))] text-[12px] shadow-none">
              <SelectValue placeholder="Select study date" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>Studies</SelectLabel>
                {patientStudies.map((study) => (
                  <SelectItem key={study.study_id} value={study.study_id}>
                    {formatShortDate(study.study_date)}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
      ) : null}
    </div>
  )
}

function ProgressRail({
  steps,
}: {
  steps: AnalysisState["progress"]
}) {
  const fallback = [
    { stage: "resolve_case", label: "Resolve case", status: "pending" as const },
    { stage: "load_images", label: "Prepare slices", status: "pending" as const },
    { stage: "volumetrics", label: "Volumetrics", status: "pending" as const },
    { stage: "report", label: "Report", status: "pending" as const },
  ]
  const resolvedSteps = steps.length ? steps : fallback

  return (
    <div className="rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
      <div className="flex flex-wrap gap-3">
        {resolvedSteps.map((step) => (
          <div
            className={cn(
              "min-w-[10rem] flex-1 rounded-xl border px-3 py-3",
              step.status === "done" && "border-emerald-500/30 bg-emerald-500/10",
              step.status === "running" && "border-[hsl(var(--primary)/0.35)] bg-[hsl(var(--primary)/0.08)]",
              step.status === "skipped" && "border-[hsl(var(--border))] bg-[hsl(var(--muted)/0.45)]",
              step.status === "pending" && "border-[hsl(var(--border))] bg-[hsl(var(--background))]",
            )}
            key={step.stage}
          >
            <div className="flex items-center gap-2 text-[12px] font-medium text-[hsl(var(--foreground))]">
              {step.status === "done" ? (
                <CheckCircle2 className="size-4 text-emerald-500" />
              ) : step.status === "running" ? (
                <Loader2 className="size-4 animate-spin text-[hsl(var(--primary))]" />
              ) : (
                <Activity className="size-4 text-[hsl(var(--muted-foreground))]" />
              )}
              {step.label}
            </div>
            <div className="mt-2 text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">
              {step.status}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function WorkspaceHydrationPanel({
  eyebrow,
  title,
  summary,
  metrics,
  steps,
}: {
  eyebrow: string
  title: string
  summary: string
  metrics: HydrationMetric[]
  steps: HydrationStage[]
}) {
  const [replayActiveIndex, setReplayActiveIndex] = useState<number | null>(null)
  const playbackTimersRef = useRef<number[]>([])
  const allDone = steps.length > 0 && steps.every((step) => step.status === "done")

  useEffect(() => {
    playbackTimersRef.current.forEach((timer) => window.clearTimeout(timer))
    playbackTimersRef.current = []

    if (!allDone) {
      setReplayActiveIndex(null)
      return () => {
        playbackTimersRef.current.forEach((timer) => window.clearTimeout(timer))
        playbackTimersRef.current = []
      }
    }

    const totalPlaybackMs = 1250
    const perStepMs = Math.max(180, Math.floor(totalPlaybackMs / Math.max(steps.length, 1)))

    setReplayActiveIndex(0)

    steps.forEach((_, index) => {
      const timer = window.setTimeout(() => {
        setReplayActiveIndex(index)
      }, index * perStepMs)
      playbackTimersRef.current.push(timer)
    })

    const finalTimer = window.setTimeout(() => {
      setReplayActiveIndex(null)
    }, steps.length * perStepMs)
    playbackTimersRef.current.push(finalTimer)

    return () => {
      playbackTimersRef.current.forEach((timer) => window.clearTimeout(timer))
      playbackTimersRef.current = []
    }
  }, [allDone, steps, title])

  return (
    <div className="rounded-[1.4rem] border border-[hsl(var(--border))] bg-[linear-gradient(180deg,hsl(var(--card)),hsl(var(--background)))] p-4 shadow-[0_20px_50px_-34px_rgba(15,23,42,0.28)]">
      <div className="flex flex-col gap-4">
        <div className="space-y-2">
          <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">{eyebrow}</div>
          <div className="text-[18px] font-medium tracking-[-0.03em] text-[hsl(var(--foreground))]">{title}</div>
          <p className="max-w-4xl text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">{summary}</p>
        </div>

        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {metrics.map((metric) => (
            <div
              className="rounded-[1rem] border border-[hsl(var(--border)/0.8)] bg-[hsl(var(--background)/0.82)] px-3 py-3"
              key={`${metric.label}-${metric.value}`}
            >
              <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">{metric.label}</div>
              <div className="mt-1 text-[15px] font-medium text-[hsl(var(--foreground))]">{metric.value}</div>
            </div>
          ))}
        </div>

        <div className="grid gap-2 xl:grid-cols-5">
          {steps.map((step, index) => {
            const visualStatus = allDone && replayActiveIndex === index ? "running" : step.status
            return (
              <div
                className={cn(
                  "rounded-[1rem] border px-3 py-3 transition-colors",
                  visualStatus === "done" && "border-emerald-500/25 bg-emerald-500/10",
                  visualStatus === "running" && "border-[hsl(var(--primary)/0.35)] bg-[hsl(var(--primary)/0.08)]",
                  visualStatus === "pending" && "border-[hsl(var(--border))] bg-[hsl(var(--background)/0.78)]",
                )}
                key={step.stage}
              >
                <div className="flex items-center gap-2 text-[12px] font-medium text-[hsl(var(--foreground))]">
                  {visualStatus === "running" ? (
                    <Loader2 className="size-4 animate-spin text-[hsl(var(--primary))]" />
                  ) : step.status === "done" ? (
                    <CheckCircle2 className="size-4 text-emerald-500" />
                  ) : step.status === "pending" ? (
                    <Activity className="size-4 text-[hsl(var(--muted-foreground))]" />
                  ) : (
                    <Loader2 className="size-4 animate-spin text-[hsl(var(--primary))]" />
                  )}
                  {step.label}
                </div>
                <div className="mt-2 text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">{step.status}</div>
                <div className="mt-2 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">{step.hint}</div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function SegmentationReadyPill({
  label,
  tone,
  loading = false,
  className,
}: {
  label: string
  tone: "ready" | "warming" | "neutral" | "unavailable"
  loading?: boolean
  className?: string
}) {
  const toneClassName =
    tone === "ready"
      ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : tone === "warming"
        ? "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300"
        : tone === "unavailable"
          ? "border-destructive/20 bg-destructive/10 text-destructive"
          : "border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[hsl(var(--muted-foreground))]"
  const Icon = loading ? Loader2 : tone === "ready" ? CheckCircle2 : tone === "unavailable" ? CircleAlert : Activity

  return (
    <div
      className={cn(
        "inline-flex h-10 items-center gap-2 rounded-full border px-3 text-[12px] font-medium",
        toneClassName,
        className,
      )}
    >
      <Icon className={cn("size-3.5 shrink-0", loading && "animate-spin")} />
      <span>{label}</span>
    </div>
  )
}

function ReportPanel({
  report,
  reportSections,
  volumetrics,
}: {
  report: string
  reportSections: ReportSections | null
  volumetrics?: VolumetricsResponse | null
}) {
  return (
    <div className="min-w-0 overflow-hidden rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <div className="flex items-center justify-between border-b border-[hsl(var(--border)/0.7)] px-5 py-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Report</div>
          <div className="mt-1 text-[16px] font-medium text-[hsl(var(--foreground))]">Structured neuroradiology draft</div>
        </div>
        <Button onClick={() => copyText(report)} size="sm" type="button" variant="outline">
          <Copy data-icon="inline-start" />
          Copy
        </Button>
      </div>
      <div className="max-h-[34rem] overflow-y-auto px-5 py-5">
        <ReportPanelContent reportSections={reportSections} volumetrics={volumetrics ?? null} />
      </div>
    </div>
  )
}

function ReportPanelContent({
  reportSections,
  volumetrics,
}: {
  reportSections: ReportSections | null
  volumetrics?: VolumetricsResponse | null
}) {
  const sections = useMemo(() => {
    if (!reportSections) {
      return null
    }
    const items = [
      { label: "Clinical Information", value: reportSections.clinical_information },
      { label: "Technique", value: reportSections.technique },
      { label: "Findings", value: reportSections.findings },
    ]
    if (volumetrics?.summary) {
      items.push({ label: "Quantitative Findings", value: volumetrics.summary })
    }
    items.push({ label: "Impression", value: reportSections.impression })
    return items
  }, [reportSections, volumetrics?.summary])

  return (
    <div className="flex flex-col gap-4">
      {sections ? (
        sections.map((section) => (
          <div className="rounded-xl border border-[hsl(var(--border)/0.75)] bg-[hsl(var(--background))] p-4" key={section.label}>
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">
              {section.label}
            </div>
            <div className="mt-2 whitespace-pre-wrap text-[13px] leading-6 text-[hsl(var(--foreground))]">
              {section.value || "Pending…"}
            </div>
          </div>
        ))
      ) : (
        <div className="rounded-xl border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
          The streamed report will appear here section by section after analysis starts.
        </div>
      )}
    </div>
  )
}

function ReviewLaneContent({
  review,
}: {
  review: DashboardPayloads["review"] | null
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
        {review?.summary || "No structured critique is available yet for this track."}
      </div>
      {(review?.recommended_tools ?? []).length ? (
        <div className="flex flex-wrap gap-2">
          {review?.recommended_tools?.map((tool) => (
            <Badge className="font-medium" key={tool} variant="outline">
              {tool.replaceAll("_", " ")}
            </Badge>
          ))}
        </div>
      ) : null}
      <div className="flex flex-col gap-3">
        {(review?.finding_groups ?? []).length ? (
          review?.finding_groups?.map((group) => (
            <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4" key={group.label}>
              <div className="flex items-center justify-between gap-3">
                <div className="text-[13px] font-medium text-[hsl(var(--foreground))]">{group.label}</div>
                <Badge variant="outline">{group.status.replaceAll("_", " ")}</Badge>
              </div>
              <div className="mt-3 flex flex-col gap-2">
                {group.items.map((item, index) => (
                  <div className="rounded-lg border border-[hsl(var(--border)/0.8)] px-3 py-3" key={`${group.label}-${item.label}-${index}`}>
                    <div className="text-[12px] font-medium text-[hsl(var(--foreground))]">
                      {item.label} · {item.severity}
                    </div>
                    <div className="mt-1 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">
                      {item.count} finding(s). {item.recommendation || "Review this section for clarity."}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))
        ) : (
          <div className="rounded-xl border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4 text-[13px] text-[hsl(var(--muted-foreground))]">
            No structured critique is available yet for this track.
          </div>
        )}
      </div>
      {(review?.revision_suggestions ?? []).length ? (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
          <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Revision suggestions</div>
          <div className="mt-3 flex flex-col gap-2">
            {review?.revision_suggestions?.map((item, index) => (
              <div className="text-[13px] leading-6 text-[hsl(var(--foreground))]" key={`${item}-${index}`}>
                {item}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function ClinicalDraftPanel({
  report,
  reportSections,
  review,
  volumetrics,
}: {
  report: string
  reportSections: ReportSections | null
  review: DashboardPayloads["review"] | null
  volumetrics: VolumetricsResponse | null
}) {
  const [activeTab, setActiveTab] = useState<RightPanelTab>(() => {
    if (typeof window === "undefined") {
      return "report"
    }
    const stored = window.localStorage.getItem(RIGHT_PANEL_TAB_STORAGE_KEY)
    return stored === "review" ? "review" : "report"
  })

  useEffect(() => {
    window.localStorage.setItem(RIGHT_PANEL_TAB_STORAGE_KEY, activeTab)
  }, [activeTab])

  return (
    <div className="flex min-w-0 flex-col overflow-hidden rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] xl:h-full">
      <div className="border-b border-[hsl(var(--border)/0.7)] px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Draft</div>
            <div className="mt-1 text-[16px] font-medium text-[hsl(var(--foreground))]">Structured neuroradiology draft</div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {(["report", "review"] as RightPanelTab[]).map((tab) => (
              <Button
                className="rounded-full px-4 capitalize"
                key={tab}
                onClick={() => setActiveTab(tab)}
                size="lg"
                type="button"
                variant={activeTab === tab ? "default" : "outline"}
              >
                {tab}
              </Button>
            ))}
            {activeTab === "report" ? (
              <Button className="rounded-full px-4" onClick={() => copyText(report)} size="lg" type="button" variant="outline">
                <Copy data-icon="inline-start" />
                Copy
              </Button>
            ) : null}
          </div>
        </div>
      </div>
      <div className="min-h-[24rem] flex-1 overflow-y-auto px-5 py-5 xl:min-h-0">
        {activeTab === "report" ? <ReportPanelContent reportSections={reportSections} volumetrics={volumetrics} /> : null}
        {activeTab === "review" ? <ReviewLaneContent review={review} /> : null}
      </div>
    </div>
  )
}

function AnalysisSummaryBar({
  summary,
  plan,
  capabilitySummary,
  planningResult,
  workspaceContract,
  activePrimaryGoal,
  plannerPrimaryGoal,
  setActivePrimaryGoal,
}: {
  summary: AnalysisPlanSummary | null
  plan: AnalysisPlan | null
  capabilitySummary: CapabilityProfileSummary | null
  planningResult: PlanningResult | null
  workspaceContract: WorkspaceContract | null
  activePrimaryGoal: "structural_report" | "response_review" | "report_review"
  plannerPrimaryGoal: "structural_report" | "response_review" | "report_review"
  setActivePrimaryGoal: (goal: "structural_report" | "response_review" | "report_review" | null) => void
}) {
  const goals = [
    { id: "structural_report" as const, label: "Structural", title: "Show structural segmentation, regions, and volumetrics." },
    { id: "response_review" as const, label: "Trend / Response", title: "Show longitudinal trend and response review." },
    { id: "report_review" as const, label: "Report Review", title: "Show report critique and evidence review." },
  ]
  return (
    <div className="min-w-0 rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Planner summary</div>
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-[hsl(var(--muted-foreground))]">
            <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1">
              Primary goal {(activePrimaryGoal || summary?.primary_goal || plan?.primary_goal || "structural_report").replaceAll("_", " ")}
            </span>
            {planningResult?.goal_confidence != null ? (
              <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1">
                Confidence {Math.round(planningResult.goal_confidence * 100)}%
              </span>
            ) : null}
            {workspaceContract?.runtime_mode ? (
              <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1">
                Mode {workspaceContract.runtime_mode}
              </span>
            ) : null}
          </div>
          <div className="text-[14px] leading-6 text-[hsl(var(--foreground))]">
            {summary?.summary || plan?.handoff_summary || "Select a study or upload files to see how the workspace reasons about available inputs and safe execution."}
          </div>
          {planningResult?.reason_for_track_selection ? (
            <div className="text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">{planningResult.reason_for_track_selection}</div>
          ) : null}
          {planningResult?.blocked_claims?.length ? (
            <div className="text-[12px] leading-6 text-amber-700 dark:text-amber-300">
              Blocked claims: {planningResult.blocked_claims.join(" ")}
            </div>
          ) : null}
        </div>
        <div className="flex flex-col items-start gap-3">
          {planningResult?.user_override_allowed !== false ? (
            <div className="flex flex-wrap gap-2">
              {goals.map((goal) => (
                <button
                  className={cn(
                    "rounded-full px-3 py-1.5 text-[12px] transition-colors",
                    activePrimaryGoal === goal.id
                      ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                      : "border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]",
                  )}
                  key={goal.id}
                  onClick={() => setActivePrimaryGoal(goal.id)}
                  title={goal.title}
                  type="button"
                >
                  {goal.label}
                </button>
              ))}
              {activePrimaryGoal !== plannerPrimaryGoal ? (
                <button
                  className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-1.5 text-[12px] text-[hsl(var(--muted-foreground))] transition-colors hover:text-[hsl(var(--foreground))]"
                  onClick={() => setActivePrimaryGoal(null)}
                  type="button"
                >
                  Follow planner
                </button>
              ) : null}
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2">
          {(summary?.detected_inputs ?? []).slice(0, 4).map((value) => (
            <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] text-[hsl(var(--foreground))]" key={value}>
              {value.replaceAll("_", " ")}
            </span>
          ))}
          {summary?.track ? (
            <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] text-[hsl(var(--foreground))]">
              Track {summary.track.replaceAll("_", " ")}
            </span>
          ) : null}
          {summary?.dashboard_profile ? (
            <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] text-[hsl(var(--foreground))]">
              Dashboard {summary.dashboard_profile.replaceAll("_", " ")}
            </span>
          ) : null}
          {(workspaceContract?.secondary_lanes ?? []).slice(0, 3).map((lane) => (
            <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] text-[hsl(var(--foreground))]" key={lane}>
              Lane {lane.replaceAll("_", " ")}
            </span>
          ))}
          {summary?.chosen_mode ? (
            <span className="rounded-full border border-[hsl(var(--primary)/0.25)] bg-[hsl(var(--primary)/0.08)] px-2.5 py-1 text-[11px] text-[hsl(var(--foreground))]">
              Running {summary.chosen_mode}
            </span>
          ) : null}
          <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] text-[hsl(var(--foreground))]">
            Viewer {summary?.viewer_type ?? "png_fallback"}
          </span>
          {summary?.missing_info?.length ? (
            <span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-700 dark:text-amber-300">
              Missing {summary.missing_info.length}
            </span>
          ) : null}
          </div>
        </div>
      </div>

      <details className="mt-4 min-w-0 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-4 py-3">
        <summary className="cursor-pointer list-none text-[12px] font-medium uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">
          View detailed capability reasoning
        </summary>
        <div className="mt-3 grid gap-4 lg:grid-cols-3">
          <div>
            <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Detected inputs</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {(summary?.detected_inputs ?? []).length ? (
                summary?.detected_inputs.map((value) => (
                  <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] text-[hsl(var(--foreground))]" key={value}>
                    {value.replaceAll("_", " ")}
                  </span>
                ))
              ) : (
                <span className="text-[12px] text-[hsl(var(--muted-foreground))]">Waiting for input discovery.</span>
              )}
            </div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Allowed analyses</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {(plan?.allowed_analyses ?? []).length ? (
                plan?.allowed_analyses.map((value) => (
                  <span className="rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-1 text-[11px] text-emerald-600 dark:text-emerald-400" key={value}>
                    {value.replaceAll("_", " ")}
                  </span>
                ))
              ) : (
                <span className="text-[12px] text-[hsl(var(--muted-foreground))]">No runnable analysis selected yet.</span>
              )}
            </div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Missing inputs</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {(summary?.missing_info ?? []).length ? (
                summary?.missing_info.map((value) => (
                  <span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-700 dark:text-amber-300" key={value}>
                    {value.replaceAll("_", " ")}
                  </span>
                ))
              ) : (
                <span className="text-[12px] text-[hsl(var(--muted-foreground))]">No missing inputs for the current plan.</span>
              )}
            </div>
          </div>
        </div>
        {summary?.safety_fallback || capabilitySummary?.blocked_reasons?.length ? (
          <div className="mt-4 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
            {summary?.safety_fallback || capabilitySummary?.blocked_reasons.join(" ")}
          </div>
        ) : null}
      </details>
    </div>
  )
}

function MetricChip({
  label,
  value,
}: {
  label: string
  value: string
}) {
  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-3">
      <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">{label}</div>
      <div className="mt-1 text-[14px] font-medium text-[hsl(var(--foreground))]">{value}</div>
    </div>
  )
}

function ReviewLane({
  review,
  open,
  onToggle,
}: {
  review: DashboardPayloads["review"] | null
  open: boolean
  onToggle: () => void
}) {
  return (
    <div className="min-w-0 overflow-hidden rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <div className="flex items-center justify-between gap-3 border-b border-[hsl(var(--border)/0.7)] px-5 py-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Review lane</div>
          <div className="mt-1 text-[16px] font-medium text-[hsl(var(--foreground))]">Report critique and revision support</div>
        </div>
        <Button onClick={onToggle} size="sm" type="button" variant="outline">
          {open ? "Hide review" : "Open review"}
        </Button>
      </div>
      {open ? (
        <div className="px-5 py-5">
          <ReviewLaneContent review={review} />
        </div>
      ) : (
        <div className="px-5 py-5 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
          Keep this lane collapsed if you want the workspace to stay focused on the primary imaging analysis.
        </div>
      )}
    </div>
  )
}

function VolumeTrendPanel({
  title,
  subtitle,
  trendSeries,
  trendGroups,
  selectedSeries,
  setSelectedSeries,
  trendData,
}: {
  title: string
  subtitle: string
  trendSeries: TrendSeriesMeta[]
  trendGroups: Array<{ id: string; displayName: string; series: TrendSeriesMeta[] }>
  selectedSeries: string[]
  setSelectedSeries: (value: string[]) => void
  trendData: Array<Record<string, string | number | null>>
}) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerSearch, setPickerSearch] = useState("")
  const closeTimeoutRef = useRef<number | null>(null)
  const pickerRef = useRef<HTMLDivElement | null>(null)
  const effectiveSeries = selectedSeries
    .map((seriesName) => trendSeries.find((series) => series.name === seriesName) ?? null)
    .filter((series): series is TrendSeriesMeta => series != null)
  const pickerSummary = effectiveSeries.length
    ? `${effectiveSeries.slice(0, 2).map((series) => series.display_name).join(", ")}${effectiveSeries.length > 2 ? ` +${effectiveSeries.length - 2}` : ""}`
    : "Choose up to 4 structures"
  const filteredGroups = useMemo(() => {
    const query = pickerSearch.trim().toLowerCase()
    return trendGroups
      .map((group) => ({
        ...group,
        series: group.series.filter((series) => !query || series.display_name.toLowerCase().includes(query)),
      }))
      .filter((group) => group.series.length)
  }, [pickerSearch, trendGroups])
  const hasMissingMeasurements = useMemo(
    () =>
      effectiveSeries.some((series) => {
        const { valueKey } = trendValueKeys(series.name)
        return trendData.some((point) => point[valueKey] == null)
      }),
    [effectiveSeries, trendData],
  )

  useEffect(() => {
    if (!pickerOpen) {
      return
    }
    const onPointerDown = (event: PointerEvent) => {
      if (!pickerRef.current?.contains(event.target as Node)) {
        setPickerOpen(false)
      }
    }
    document.addEventListener("pointerdown", onPointerDown)
    return () => document.removeEventListener("pointerdown", onPointerDown)
  }, [pickerOpen])

  function clearCloseTimeout() {
    if (closeTimeoutRef.current != null) {
      window.clearTimeout(closeTimeoutRef.current)
      closeTimeoutRef.current = null
    }
  }

  function scheduleClose() {
    clearCloseTimeout()
    closeTimeoutRef.current = window.setTimeout(() => {
      setPickerOpen(false)
      closeTimeoutRef.current = null
    }, 140)
  }

  return (
    <div className="min-w-0 overflow-hidden rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]" ref={pickerRef}>
      <div className="border-b border-[hsl(var(--border)/0.7)] px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Volume trend</div>
            <div className="mt-1 text-[16px] font-medium text-[hsl(var(--foreground))]">{title}</div>
            <div className="mt-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">{subtitle}</div>
          </div>
          <div className="w-full max-w-[17rem] shrink-0">
            <button
              className="flex min-h-[4.9rem] w-full items-center justify-between gap-3 rounded-[1rem] border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-3 text-left transition-colors hover:border-[hsl(var(--primary)/0.35)]"
              onMouseEnter={() => {
                clearCloseTimeout()
                setPickerOpen(true)
              }}
              onMouseLeave={scheduleClose}
              onClick={() => setPickerOpen((current) => !current)}
              type="button"
            >
              <div className="min-w-0">
                <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Structure picker</div>
                <div className="mt-1 truncate text-[13px] font-medium text-[hsl(var(--foreground))]">{pickerSummary}</div>
                <div className="mt-1 text-[11px] text-[hsl(var(--muted-foreground))]">{selectedSeries.length} selected · max 4</div>
              </div>
              <ChevronDown className={cn("size-4 shrink-0 text-[hsl(var(--muted-foreground))] transition-transform", pickerOpen ? "rotate-180" : "")} />
            </button>
          </div>
        </div>
      </div>
      {pickerOpen ? (
        <div
          className="border-b border-[hsl(var(--border)/0.7)] bg-[hsl(var(--background)/0.45)] px-5 py-4"
          onMouseEnter={clearCloseTimeout}
          onMouseLeave={scheduleClose}
        >
          <div className="rounded-[1rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
            <div className="border-b border-[hsl(var(--border)/0.7)] px-4 py-3">
              <input
                className="w-full rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-[13px] text-[hsl(var(--foreground))] outline-none placeholder:text-[hsl(var(--muted-foreground))]"
                onChange={(event) => setPickerSearch(event.target.value)}
                placeholder="Search structural trajectories"
                type="text"
                value={pickerSearch}
              />
            </div>
            <div className="max-h-[18rem] space-y-4 overflow-y-auto px-4 py-4">
              {filteredGroups.map((group) => (
                <div key={group.id}>
                  <div className="mb-2 text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">{group.displayName}</div>
                  <div className="space-y-2">
                    {group.series.map((series) => {
                      const active = selectedSeries.includes(series.name)
                      return (
                        <button
                          className={cn(
                            "flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2 text-left text-[12px] transition-colors",
                            active
                              ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.08)] text-[hsl(var(--foreground))]"
                              : "border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]",
                          )}
                          key={series.name}
                          onClick={() => setSelectedSeries(toggleTrendSeriesSelection(selectedSeries, series.name))}
                          type="button"
                        >
                          <span className="truncate">{series.display_name}</span>
                          <span className="shrink-0 text-[11px]">{active ? "Selected" : "Add"}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))}
              {!filteredGroups.length ? (
                <div className="rounded-xl border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4 text-[12px] text-[hsl(var(--muted-foreground))]">
                  No trajectories match this search.
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
      <div className="space-y-4 px-5 py-5">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {effectiveSeries.slice(0, 4).map((series) => {
            const latest = trendData[trendData.length - 1]
            const { valueKey } = trendValueKeys(series.name)
            const value = latest?.[valueKey]
            return (
              <MetricChip
                key={series.name}
                label={series.display_name}
                value={
                  typeof value === "number"
                    ? `${Math.round(value).toLocaleString()} ${formatTrendUnit(series)}`
                    : "—"
                }
              />
            )
          })}
        </div>
        <div className="h-[20rem]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={trendData}>
              <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" />
              <XAxis dataKey="date" stroke="hsl(var(--muted-foreground))" />
              <YAxis stroke="hsl(var(--muted-foreground))" />
              <Tooltip
                contentStyle={{
                  background: "hsl(var(--card))",
                  borderColor: "hsl(var(--border))",
                  borderRadius: "14px",
                }}
              />
              {effectiveSeries.map((series, index) => {
                const { valueKey } = trendValueKeys(series.name)
                return (
                  <Line
                    dataKey={valueKey}
                    dot={false}
                    key={series.name}
                    name={`${series.display_name} (${formatTrendUnit(series)})`}
                    stroke={TREND_COLORS[index % TREND_COLORS.length]}
                    strokeWidth={2.5}
                    type="monotone"
                  />
                )
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>
        {hasMissingMeasurements ? (
          <div className="rounded-xl border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-3 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">
            Gaps in the trend indicate that this structure has no measurement for that specific timepoint, not that its volume is zero.
          </div>
        ) : null}
      </div>
    </div>
  )
}

function BaselineComparePanel({
  activeStudy,
  baselineStudy,
  comparisonMetrics,
  selectedCount,
}: {
  activeStudy: ViewerStudySummary | null
  baselineStudy: ViewerStudySummary | null
  comparisonMetrics: Array<{ id: string; label: string; value: string; delta: string }>
  selectedCount: number
}) {
  const enoughForCompare = selectedCount >= 2 && baselineStudy && activeStudy
  const timeSpanDays =
    enoughForCompare ? Math.max(0, Math.round((studyTime(activeStudy.study_date) - studyTime(baselineStudy.study_date)) / (1000 * 60 * 60 * 24))) : null

  return (
    <div className="min-w-0 rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Baseline compare</div>
        <Badge className="rounded-full px-2.5 py-0.5 text-[10px] font-medium" variant="outline">
          {selectedCount} selected
        </Badge>
      </div>
      {enoughForCompare ? (
        <div className="mt-3 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-3">
              <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Baseline study</div>
              <div className="mt-1 text-[14px] font-medium text-[hsl(var(--foreground))]">{formatShortDate(baselineStudy.study_date)}</div>
            </div>
            <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-3">
              <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Active study</div>
              <div className="mt-1 text-[14px] font-medium text-[hsl(var(--foreground))]">{formatShortDate(activeStudy.study_date)}</div>
            </div>
          </div>
          <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-3">
            <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Time span</div>
            <div className="mt-1 text-[14px] font-medium text-[hsl(var(--foreground))]">
              {timeSpanDays === 0 ? "Same-day comparison" : `${timeSpanDays} days from baseline`}
            </div>
          </div>
          <div className="space-y-2">
            {comparisonMetrics.length ? (
              comparisonMetrics.map((metric) => (
                <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-3" key={metric.id}>
                  <div className="text-[12px] font-medium text-[hsl(var(--foreground))]">{metric.label}</div>
                  <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-[12px] text-[hsl(var(--muted-foreground))]">
                    <span>{metric.value}</span>
                    <span>{metric.delta}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-xl border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-3 text-[12px] text-[hsl(var(--muted-foreground))]">
                Add structures in the trend picker to compute baseline deltas.
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="mt-3 rounded-xl border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-3 text-[12px] leading-6 text-[hsl(var(--muted-foreground))]">
          Select at least two timepoints to compare the current study against the earliest baseline.
        </div>
      )}
    </div>
  )
}

function ResponsePreviewPanel({
  response,
}: {
  response: DashboardPayloads["response"]
}) {
  const imageUrl = response.key_slice_compare?.image_url
  return (
    <div className="min-w-0 overflow-hidden rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <div className="border-b border-[hsl(var(--border)/0.7)] px-5 py-4">
        <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Key slice compare</div>
        <div className="mt-1 text-[16px] font-medium text-[hsl(var(--foreground))]">
          {response.key_slice_compare?.title || "Representative response view"}
        </div>
      </div>
      <div className="space-y-4 px-5 py-5">
        {imageUrl ? (
          <div className="overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-black">
            <img alt={response.key_slice_compare?.title || "Response preview"} className="h-auto w-full object-cover" src={imageUrl} />
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 text-[13px] text-[hsl(var(--muted-foreground))]">
            Slice comparison anchors will appear here when response imaging previews are available.
          </div>
        )}
        <div className="text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
          {response.key_slice_compare?.caption || "Compare representative follow-up anchors alongside lesion burden and response summaries."}
        </div>
      </div>
    </div>
  )
}

function ResponseSummaryPanel({
  response,
}: {
  response: DashboardPayloads["response"]
}) {
  return (
    <div className="min-w-0 overflow-hidden rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <div className="border-b border-[hsl(var(--border)/0.7)] px-5 py-4">
        <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Response report</div>
        <div className="mt-1 text-[16px] font-medium text-[hsl(var(--foreground))]">Treatment-aligned summary</div>
      </div>
      <div className="max-h-[28rem] space-y-4 overflow-y-auto px-5 py-5">
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4 text-[13px] leading-6 text-[hsl(var(--foreground))]">
          {response.report_summary || response.summary}
        </div>
        {(response.report_sections ?? []).map((section, index) => (
          <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4" key={`${section.title}-${index}`}>
            <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">{section.title || "Section"}</div>
            <div className="mt-2 text-[13px] leading-6 text-[hsl(var(--foreground))]">{section.body || "No section text provided."}</div>
          </div>
        ))}
        {(response.next_checks ?? []).length ? (
          <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
            <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Next checks</div>
            <div className="mt-3 space-y-2">
              {response.next_checks?.map((item, index) => (
                <div className="text-[13px] leading-6 text-[hsl(var(--foreground))]" key={`${item}-${index}`}>
                  {item}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}

function ReviewDashboard({
  review,
  report,
  reportSections,
}: {
  review: DashboardPayloads["review"]
  report: string
  reportSections: ReportSections | null
}) {
  return (
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.95fr)]">
      <ReportPanel report={report} reportSections={reportSections ?? review.source_report_sections ?? null} />
      <ReviewLane onToggle={() => {}} open review={review} />
    </div>
  )
}

function StructuralDashboard({
  currentCaseId,
  patientLabel,
  slices,
  overlaySlices,
  sliceManifest,
  sliceRequest,
  viewerAssets,
  showOverlay,
  setShowOverlay,
  overlayModel,
  viewerMode,
  setViewerMode,
  visibleLabelIds,
  activeLabelId,
  activeGroup,
  expandedGroups,
  onToggleGroupExpanded,
  onToggleGroupVisibility,
  onToggleLabelVisibility,
  onSelectAllLabels,
  onDeselectAllLabels,
  onReplaceVisibleLabelIds,
  onSelectGroup,
  onSelectLabel,
  report,
  reportSections,
  volumetrics,
  segmentationLabelSourceLabel,
  segmentationLabelMappingPath,
  review,
  patientStudies,
  selectedStudyId,
  selectedStudySummary,
  trendSeries,
  trendGroups,
  selectedTrendSeries,
  setSelectedTrendSeries,
  trendData,
  hasSessionLongitudinalContext,
  selectedComparisonStudyIds,
  activeComparisonStudyId,
  baselineStudyId,
  latestComparisonStudyId,
  onToggleComparisonStudy,
  onActivateComparisonStudy,
  comparisonMetrics,
  highlights,
  heatmap,
  csvExportUrl,
  onSelectStudy,
  showTrendSection = true,
}: {
  currentCaseId: string | null
  patientLabel: string | null
  slices: SlicePlaneSet | null
  overlaySlices: SlicePlaneSet | null
  sliceManifest: SliceManifest | null
  sliceRequest: StructuralSliceRequestContext | null
  viewerAssets: ViewerAssets | null
  showOverlay: boolean
  setShowOverlay: (value: boolean) => void
  overlayModel: SegmentationOverlayModel | null
  viewerMode: ViewerMode
  setViewerMode: (mode: ViewerMode) => void
  visibleLabelIds: number[]
  activeLabelId: number | null
  activeGroup: string | null
  expandedGroups: string[]
  onToggleGroupExpanded: (groupId: string) => void
  onToggleGroupVisibility: (groupId: string) => void
  onToggleLabelVisibility: (labelId: number) => void
  onSelectAllLabels: () => void
  onDeselectAllLabels: () => void
  onReplaceVisibleLabelIds: (labelIds: number[]) => void
  onSelectGroup: (groupId: string | null) => void
  onSelectLabel: (labelId: number | null) => void
  report: string
  reportSections: ReportSections | null
  volumetrics: VolumetricsResponse | null
  segmentationLabelSourceLabel: string | null
  segmentationLabelMappingPath: string | null
  review: DashboardPayloads["review"] | null
  patientStudies: PatientStudy[]
  selectedStudyId: string | null
  selectedStudySummary: ViewerStudySummary | null
  trendSeries: TrendSeriesMeta[]
  trendGroups: Array<{ id: string; displayName: string; series: TrendSeriesMeta[] }>
  selectedTrendSeries: string[]
  setSelectedTrendSeries: (value: string[]) => void
  trendData: Array<Record<string, string | number | null>>
  hasSessionLongitudinalContext: boolean
  selectedComparisonStudyIds: string[]
  activeComparisonStudyId: string | null
  baselineStudyId: string | null
  latestComparisonStudyId: string | null
  onToggleComparisonStudy: (study: PatientStudy) => void
  onActivateComparisonStudy: (study: PatientStudy) => void
  comparisonMetrics: Array<{ id: string; label: string; value: string; delta: string }>
  highlights: PatientDataResponse["highlights"]
  heatmap: HeatmapResponse | null
  csvExportUrl: string | null
  onSelectStudy: (study: PatientStudy) => void
  showTrendSection?: boolean
}) {
  return (
    <>
      <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.04fr)_minmax(0,0.96fr)]">
        <div className="min-w-0 space-y-3">
          <ViewerStudySelector
            caseId={currentCaseId}
            onSelectStudy={onSelectStudy}
            patientStudies={patientStudies}
            patientLabel={patientLabel}
            selectedStudyId={selectedStudyId}
            selectedStudySummary={selectedStudySummary}
          />
          <HybridImagingViewer
            activeGroup={activeGroup}
            activeLabelId={activeLabelId}
            expandedGroups={expandedGroups}
            onSelectGroup={onSelectGroup}
            onSelectLabel={onSelectLabel}
            onToggleGroupExpanded={onToggleGroupExpanded}
            onToggleGroupVisibility={onToggleGroupVisibility}
            onToggleLabelVisibility={onToggleLabelVisibility}
            onSelectAllLabels={onSelectAllLabels}
            onDeselectAllLabels={onDeselectAllLabels}
            onReplaceVisibleLabelIds={onReplaceVisibleLabelIds}
            overlayModel={overlayModel}
            overlaySlices={overlaySlices}
            sliceManifest={sliceManifest}
            sliceRequest={sliceRequest}
            setShowOverlay={setShowOverlay}
            showOverlay={showOverlay}
            slices={slices}
            preferTriView
            segmentationLabelMappingPath={segmentationLabelMappingPath}
            segmentationLabelSourceLabel={segmentationLabelSourceLabel}
            viewerMode={viewerMode}
            viewerAssets={viewerAssets}
            visibleLabelIds={visibleLabelIds}
            setViewerMode={setViewerMode}
          />
        </div>
        <ClinicalDraftPanel
          report={report}
          reportSections={reportSections}
          review={review}
          volumetrics={volumetrics}
        />
      </section>

      {overlayModel ? (
        <section>
          <StructuralRegionTablePanel
            activeGroup={activeGroup}
            activeLabelId={activeLabelId}
            csvExportUrl={csvExportUrl}
            expandedGroups={expandedGroups}
            onSelectGroup={onSelectGroup}
            onSelectLabel={onSelectLabel}
            onToggleGroupExpanded={onToggleGroupExpanded}
            overlayModel={overlayModel}
            visibleLabelIds={visibleLabelIds}
          />
        </section>
      ) : null}

      {showTrendSection ? (
      <section className="min-w-0 space-y-4 overflow-hidden rounded-[1.5rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-6 py-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Longitudinal context</div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <div className="text-[20px] font-medium text-[hsl(var(--foreground))]">Volume trend</div>
              {patientLabel ? (
                <Badge className="rounded-full px-2.5 py-0.5 text-[10px] font-medium" variant="outline">
                  {patientLabel}
                </Badge>
              ) : null}
              {currentCaseId ? (
                <Badge className="rounded-full px-2.5 py-0.5 text-[10px] font-medium" variant="outline">
                  Case {currentCaseId}
                </Badge>
              ) : null}
            </div>
            {hasSessionLongitudinalContext ? (
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-[hsl(var(--muted-foreground))]">
                <span>{selectedComparisonStudyIds.length} selected</span>
                {baselineStudyId ? <span>Baseline: {formatShortDate(patientStudies.find((study) => study.study_id === baselineStudyId)?.study_date ?? "")}</span> : null}
                {latestComparisonStudyId ? <span>Latest: {formatShortDate(patientStudies.find((study) => study.study_id === latestComparisonStudyId)?.study_date ?? "")}</span> : null}
              </div>
            ) : null}
          </div>
          <div className="text-[12px] text-[hsl(var(--muted-foreground))]">
            {hasSessionLongitudinalContext
              ? "Switch studies without leaving the MRI report workspace."
              : "Longitudinal history appears only when this session is backed by a patient timeline."}
          </div>
        </div>

        {hasSessionLongitudinalContext ? (
          <>
            <div className="flex items-stretch gap-3 overflow-x-auto pb-2">
              {patientStudies.map((study) => (
                <div
                  className={cn(
                    "flex min-h-[11.75rem] min-w-[11rem] flex-col rounded-[1rem] border p-3 text-left transition-all",
                    selectedComparisonStudyIds.includes(study.study_id)
                      ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.08)]"
                      : "border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:border-[hsl(var(--primary)/0.25)]",
                  )}
                  key={study.study_id}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex flex-wrap gap-1">
                      {study.study_id === baselineStudyId ? (
                        <Badge className="rounded-full px-2 py-0.5 text-[10px] font-medium" variant="secondary">
                          Baseline
                        </Badge>
                      ) : null}
                      {study.study_id === activeComparisonStudyId ? (
                        <Badge className="rounded-full px-2 py-0.5 text-[10px] font-medium" variant="outline">
                          Viewing
                        </Badge>
                      ) : null}
                    </div>
                    <Button
                      className="h-7 rounded-full px-2.5 text-[11px]"
                      onClick={() => onToggleComparisonStudy(study)}
                      size="sm"
                      type="button"
                      variant={selectedComparisonStudyIds.includes(study.study_id) ? "default" : "outline"}
                    >
                      {selectedComparisonStudyIds.includes(study.study_id) ? "Selected" : "Add"}
                    </Button>
                  </div>
                  <button className="mt-2 flex flex-1 flex-col text-left" onClick={() => onActivateComparisonStudy(study)} type="button">
                    <div className="relative aspect-[4/3] w-full overflow-hidden rounded-xl bg-black">
                      <img
                        alt={study.study_id}
                        className="absolute inset-0 h-full w-full object-cover object-center"
                        src={`data:image/png;base64,${study.thumbnail_base64}`}
                      />
                    </div>
                    <div className="mt-3 text-[12px] uppercase tracking-[0.12em] text-[hsl(var(--muted-foreground))]">
                      {formatShortDate(study.study_date)}
                    </div>
                  </button>
                </div>
              ))}
            </div>

            <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
              <VolumeTrendPanel
                selectedSeries={selectedTrendSeries}
                setSelectedSeries={setSelectedTrendSeries}
                subtitle="The planner selects the most relevant structural trajectories by default, and you can swap in other regions when needed."
                title="Volume trend"
                trendData={trendData}
                trendGroups={trendGroups}
                trendSeries={trendSeries}
              />

              <div className="min-w-0 space-y-4">
                <BaselineComparePanel
                  activeStudy={patientStudies.find((study) => study.study_id === activeComparisonStudyId) ?? selectedStudySummary}
                  baselineStudy={patientStudies.find((study) => study.study_id === baselineStudyId) ?? null}
                  comparisonMetrics={comparisonMetrics}
                  selectedCount={selectedComparisonStudyIds.length}
                />
                <div className="min-w-0 rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Longitudinal highlights</div>
                  <div className="mt-3 space-y-3">
                    {highlights.slice(0, 4).map((highlight, index) => (
                      <div className="rounded-xl border border-[hsl(var(--border))] px-3 py-3" key={`${highlight.study_id}-${index}`}>
                        <div className="text-[13px] font-medium text-[hsl(var(--foreground))]">{highlight.display_name}</div>
                        <div className="mt-1 text-[12px] text-[hsl(var(--muted-foreground))]">
                          {formatShortDate(highlight.study_date)} · z={highlight.z_score.toFixed(2)} · {highlight.interpretation}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            <HeatmapPanel heatmap={heatmap} />
          </>
        ) : (
          <div className="rounded-[1.25rem] border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--background))] px-5 py-6 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
            No longitudinal comparison available for this session
          </div>
        )}
      </section>
      ) : null}
    </>
  )
}

function ResponseDashboard({
  response,
  volumetrics,
  trendSeries,
  trendGroups,
  selectedTrendSeries,
  setSelectedTrendSeries,
  trendData,
  review,
  reviewLaneOpen,
  setReviewLaneOpen,
}: {
  response: DashboardPayloads["response"]
  volumetrics: VolumetricsResponse | null
  trendSeries: TrendSeriesMeta[]
  trendGroups: Array<{ id: string; displayName: string; series: TrendSeriesMeta[] }>
  selectedTrendSeries: string[]
  setSelectedTrendSeries: (value: string[]) => void
  trendData: Array<Record<string, string | number | null>>
  review: DashboardPayloads["review"] | null
  reviewLaneOpen: boolean
  setReviewLaneOpen: (value: boolean) => void
}) {
  return (
    <>
      <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <VolumeTrendPanel
          selectedSeries={selectedTrendSeries}
          setSelectedSeries={setSelectedTrendSeries}
          subtitle="Lesion burden, interval change, and response anchors share the same trend surface used by structural cases."
          title="Volume trend"
          trendData={trendData}
          trendGroups={trendGroups}
          trendSeries={trendSeries}
        />
        <ResponseSummaryPanel response={response} />
      </section>
      <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <ResponsePreviewPanel response={response} />
        <div className="space-y-4">
          <VolumetricsPanel volumetrics={volumetrics} />
          <ReviewLane onToggle={() => setReviewLaneOpen(!reviewLaneOpen)} open={reviewLaneOpen} review={review} />
        </div>
      </section>
    </>
  )
}

function NeuroWorkspaceTabNav({
  activeTab,
  onSelectTab,
}: {
  activeTab: NeuroWorkspaceTab
  onSelectTab: (tab: NeuroWorkspaceTab) => void
}) {
  const activeTabMeta = NEURO_WORKSPACE_TABS.find((tab) => tab.id === activeTab) ?? NEURO_WORKSPACE_TABS[0]

  const selectAdjacentTab = (event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) => {
    let nextIndex: number | null = null
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % NEURO_WORKSPACE_TABS.length
    if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + NEURO_WORKSPACE_TABS.length) % NEURO_WORKSPACE_TABS.length
    if (event.key === "Home") nextIndex = 0
    if (event.key === "End") nextIndex = NEURO_WORKSPACE_TABS.length - 1
    if (nextIndex === null) return

    event.preventDefault()
    onSelectTab(NEURO_WORKSPACE_TABS[nextIndex].id)
    const tabButtons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
    tabButtons?.[nextIndex]?.focus()
  }

  return (
    <nav
      aria-label="Neuro MRI workspace"
      className="overflow-hidden rounded-[1rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-[0_1px_2px_hsl(var(--foreground)/0.04)]"
    >
      <div
        aria-label="Workspace views"
        className="grid auto-cols-[minmax(9.5rem,1fr)] grid-flow-col gap-1 overflow-x-auto p-1.5"
        role="tablist"
      >
        {NEURO_WORKSPACE_TABS.map((tab, index) => {
          const Icon = tab.icon
          const isActive = activeTab === tab.id
          return (
            <button
              aria-controls={`neuro-workspace-panel-${tab.id}`}
              aria-label={`${tab.label}: ${tab.description}`}
              aria-selected={isActive}
              className={cn(
                "group relative flex min-h-12 cursor-pointer items-center justify-center gap-2 rounded-[0.7rem] border px-3 text-[13px] font-medium transition-[background-color,border-color,color,box-shadow,transform] duration-150 focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-offset-1 active:scale-[0.98]",
                isActive
                  ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] shadow-[0_3px_10px_hsl(var(--primary)/0.18)]"
                  : "border-transparent text-[hsl(var(--muted-foreground))] hover:border-[hsl(var(--border))] hover:bg-[hsl(var(--background))] hover:text-[hsl(var(--foreground))]",
              )}
              id={`neuro-workspace-tab-${tab.id}`}
              key={tab.id}
              onClick={() => onSelectTab(tab.id)}
              onKeyDown={(event) => selectAdjacentTab(event, index)}
              role="tab"
              tabIndex={isActive ? 0 : -1}
              type="button"
            >
              <Icon aria-hidden="true" className="size-4 shrink-0" strokeWidth={isActive ? 2.2 : 1.8} />
              <span className="whitespace-nowrap">{tab.label}</span>
            </button>
          )
        })}
      </div>
      <div className="flex min-h-11 items-center gap-2 border-t border-[hsl(var(--border))] bg-[hsl(var(--muted)/0.26)] px-4 py-2 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">
        <span className="size-1.5 shrink-0 rounded-full bg-[hsl(var(--primary))]" aria-hidden="true" />
        <span className="font-medium text-[hsl(var(--foreground))]">{activeTabMeta.label}</span>
        <span aria-hidden="true" className="text-[hsl(var(--border))]">/</span>
        <span>{activeTabMeta.description}</span>
      </div>
    </nav>
  )
}

function NeuroOverviewTab({
  patientLabel,
  selectedStudySummary,
  patientStudies,
  capabilitySummary,
  analysisPlan,
  planningResult,
  segmentationReady,
  trendReady,
  alignmentReady,
  onSelectTab,
}: {
  patientLabel: string | null
  selectedStudySummary: ViewerStudySummary | PatientStudy | null
  patientStudies: PatientStudy[]
  capabilitySummary: CapabilityProfileSummary | null
  analysisPlan: AnalysisPlan | null
  planningResult: PlanningResult | null
  segmentationReady: boolean
  trendReady: boolean
  alignmentReady: boolean
  onSelectTab: (tab: NeuroWorkspaceTab) => void
}) {
  const recommendedNextAction =
    planningResult?.recommended_next_action ||
    (alignmentReady ? "Review alignment before using follow-up trend outputs." : null) ||
    (trendReady ? "Open the trend lane to inspect interval change." : null) ||
    (segmentationReady ? "Open segmentation to inspect labels and volumetrics." : "Analyze or attach segmentation to prepare the workspace.")
  const timeline = sortStudiesByDate(patientStudies)
  return (
    <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
      <div className="min-w-0 rounded-[1.5rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
        <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Workspace overview</div>
        <div className="mt-2 text-[22px] font-medium text-[hsl(var(--foreground))]">
          {patientLabel || "Neuro MRI workspace"}
        </div>
        <div className="mt-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
          {analysisPlan?.handoff_summary || "Select a study, run the needed lane, and keep imaging, measurements, and report review in one shared workspace."}
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          {[
            { label: "Selected study", value: selectedStudySummary?.study_id || "None" },
            { label: "Studies", value: patientStudies.length ? `${patientStudies.length}` : "No timeline" },
            { label: "Segmentation", value: segmentationReady ? "Available" : "Optional" },
            { label: "Trend", value: trendReady ? "Ready" : "Needs timeline" },
          ].map((item) => (
            <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-3" key={item.label}>
              <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">{item.label}</div>
              <div className="mt-1 text-[15px] font-medium text-[hsl(var(--foreground))]">{item.value}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="min-w-0 space-y-4">
        <div className="rounded-[1.5rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
          <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Recommended next action</div>
          <div className="mt-2 text-[16px] font-medium text-[hsl(var(--foreground))]">{recommendedNextAction}</div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button className="rounded-full" onClick={() => onSelectTab(segmentationReady ? "segmentation" : "alignment")} type="button">
              {segmentationReady ? "Review segmentation" : "Prepare alignment"}
            </Button>
            <Button className="rounded-full" onClick={() => onSelectTab("trend")} type="button" variant="outline">
              Open trend
            </Button>
            <Button className="rounded-full" onClick={() => onSelectTab("report")} type="button" variant="outline">
              Open report
            </Button>
          </div>
        </div>

        <div className="rounded-[1.5rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
          <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Study timeline</div>
          <div className="mt-3 space-y-2">
            {timeline.slice(0, 6).map((study) => (
              <div className="flex items-center justify-between gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-3" key={study.study_id}>
                <div>
                  <div className="text-[13px] font-medium text-[hsl(var(--foreground))]">{formatShortDate(study.study_date)}</div>
                  <div className="mt-1 text-[12px] text-[hsl(var(--muted-foreground))]">{study.study_id}</div>
                </div>
                {study.has_segmentation ? <Badge variant="outline">Segmentation</Badge> : null}
              </div>
            ))}
            {!timeline.length ? (
              <div className="rounded-xl border border-dashed border-[hsl(var(--border))] px-3 py-3 text-[13px] text-[hsl(var(--muted-foreground))]">
                Timeline appears after a patient study is selected.
              </div>
            ) : null}
          </div>
        </div>

        {capabilitySummary?.missing_info?.length ? (
          <div className="rounded-[1.25rem] border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-[12px] leading-6 text-[hsl(var(--foreground))]">
            Missing: {capabilitySummary.missing_info.join(", ")}
          </div>
        ) : null}
      </div>
    </section>
  )
}

function NeuroAlignmentTab({
  patientId,
  patientStudies,
  selectedStudyId,
  baselineStudyId,
  latestStudyId,
}: {
  patientId: string | null
  patientStudies: PatientStudy[]
  selectedStudyId: string | null
  baselineStudyId: string | null
  latestStudyId: string | null
}) {
  const sortedStudies = useMemo(() => sortStudiesByDate(patientStudies), [patientStudies])
  const [workflow, setWorkflow] = useState<AlignmentWorkflow>("longitudinal_coregistration")
  const [fixedStudyId, setFixedStudyId] = useState<string>("")
  const [movingStudyId, setMovingStudyId] = useState<string>("")
  const [mode, setMode] = useState<"demo" | "remote">("demo")
  const [applyToSegmentation, setApplyToSegmentation] = useState(true)
  const [job, setJob] = useState<AlignmentJobResponse | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setFixedStudyId((current) => current || baselineStudyId || selectedStudyId || sortedStudies[0]?.study_id || "")
    setMovingStudyId((current) => current || latestStudyId || sortedStudies[sortedStudies.length - 1]?.study_id || "")
  }, [baselineStudyId, latestStudyId, selectedStudyId, sortedStudies])

  async function runAlignment() {
    setRunning(true)
    setError(null)
    try {
      const payload = await postJson<AlignmentJobResponse>("/api/demo/neuro-report/alignment-jobs", {
        mode,
        workflow,
        patient_id: patientId,
        fixed_study_id: fixedStudyId,
        moving_study_id: movingStudyId,
        apply_to_segmentation: applyToSegmentation,
      })
      setJob(payload)
      if (payload.status === "failed") {
        setError(payload.error || "Alignment was not available for this selection.")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start alignment.")
    } finally {
      setRunning(false)
    }
  }

  const canRun = Boolean(patientId && fixedStudyId && movingStudyId)
  const qc = job?.qc
  return (
    <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <div className="min-w-0 rounded-[1.5rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
        <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Alignment lane</div>
        <div className="mt-1 text-[20px] font-medium text-[hsl(var(--foreground))]">Prepare registered review space</div>
        <div className="mt-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
          Select a reference study and a moving study, then run a clinician-facing alignment check before using masks or longitudinal trend outputs.
        </div>

        <div className="mt-5 space-y-4">
          <label className="block">
            <div className="mb-2 text-[12px] font-medium text-[hsl(var(--foreground))]">Task</div>
            <select
              className="h-11 w-full rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-[13px] outline-none"
              onChange={(event) => setWorkflow(event.target.value as AlignmentWorkflow)}
              value={workflow}
            >
              <option value="longitudinal_coregistration">Align follow-up to baseline</option>
              <option value="sequence_coregistration">Align sequence to reference</option>
            </select>
          </label>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <div className="mb-2 text-[12px] font-medium text-[hsl(var(--foreground))]">Reference</div>
              <select
                className="h-11 w-full rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-[13px] outline-none"
                onChange={(event) => setFixedStudyId(event.target.value)}
                value={fixedStudyId}
              >
                <option value="">Select reference</option>
                {sortedStudies.map((study) => (
                  <option key={study.study_id} value={study.study_id}>
                    {formatShortDate(study.study_date)} · {study.study_id}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <div className="mb-2 text-[12px] font-medium text-[hsl(var(--foreground))]">Moving</div>
              <select
                className="h-11 w-full rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-[13px] outline-none"
                onChange={(event) => setMovingStudyId(event.target.value)}
                value={movingStudyId}
              >
                <option value="">Select moving study</option>
                {sortedStudies.map((study) => (
                  <option key={study.study_id} value={study.study_id}>
                    {formatShortDate(study.study_date)} · {study.study_id}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <div className="mb-2 text-[12px] font-medium text-[hsl(var(--foreground))]">Execution</div>
              <select
                className="h-11 w-full rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-[13px] outline-none"
                onChange={(event) => setMode(event.target.value as "demo" | "remote")}
                value={mode}
              >
                <option value="demo">Demo sample</option>
                <option value="remote">Configured processor</option>
              </select>
            </label>
            <label className="flex h-[4.35rem] items-center gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3">
              <input checked={applyToSegmentation} onChange={(event) => setApplyToSegmentation(event.target.checked)} type="checkbox" />
              <span className="text-[13px] text-[hsl(var(--foreground))]">Transfer segmentation when available</span>
            </label>
          </div>

          <Button className="h-11 rounded-full px-4" disabled={!canRun || running} onClick={() => void runAlignment()} type="button">
            {running ? <Loader2 className="animate-spin" data-icon="inline-start" /> : <Activity data-icon="inline-start" />}
            {running ? "Preparing…" : "Run alignment check"}
          </Button>

          {error ? (
            <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-3 text-[12px] leading-6 text-rose-200">
              {error}
            </div>
          ) : null}
        </div>
      </div>

      <div className="min-w-0 space-y-4">
        <div className="rounded-[1.5rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Quality check</div>
              <div className="mt-1 text-[18px] font-medium text-[hsl(var(--foreground))]">
                {job ? job.clinical_summary || "Alignment result ready" : "No alignment run yet"}
              </div>
            </div>
            {job ? (
              <Badge className="rounded-full px-3 py-1 text-[11px]" variant={job.status === "completed" ? "secondary" : "destructive"}>
                {job.status}
              </Badge>
            ) : null}
          </div>

          {job ? (
            <div className="mt-4 space-y-4">
              <div className="grid gap-3 sm:grid-cols-3">
                <SummaryMetric label="Translation" value={qc?.translation_norm_mm != null ? `${qc.translation_norm_mm.toFixed(1)} mm` : "—"} />
                <SummaryMetric label="Similarity" value={qc?.ncc_delta != null ? `${qc.ncc_delta > 0 ? "+" : ""}${qc.ncc_delta.toFixed(3)}` : "—"} />
                <SummaryMetric label="Resampled" value={qc?.resampled_to_reference_grid ? "Yes" : "—"} />
              </div>
              <div className="space-y-2">
                {(qc?.clinical_warnings?.length ? qc.clinical_warnings : ["Open the viewer overlay to confirm anatomy before relying on transferred masks or trends."]).map((warning) => (
                  <div className="flex gap-2 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-3 text-[12px] leading-5 text-[hsl(var(--foreground))]" key={warning}>
                    <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-500" />
                    <span>{warning}</span>
                  </div>
                ))}
              </div>
              {job.outputs?.viewer_hint ? (
                <div className="rounded-xl border border-[hsl(var(--primary)/0.25)] bg-[hsl(var(--primary)/0.08)] px-3 py-3 text-[12px] leading-5 text-[hsl(var(--foreground))]">
                  {job.outputs.viewer_hint}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--background))] px-4 py-5 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
              Run the demo sample to review the lane behavior. Switch execution to the configured processor when remote processing is ready.
            </div>
          )}
        </div>

        <div className="rounded-[1.5rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
          <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Review handoff</div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {(job?.stages ?? [
              { stage: "resolve_studies", label: "Resolve selected studies", status: "pending" },
              { stage: "align_images", label: "Align selected imaging", status: "pending" },
              { stage: "quality_check", label: "Quality check", status: "pending" },
            ]).map((stage) => (
              <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-3" key={stage.stage}>
                <div className="flex items-center gap-2 text-[13px] font-medium text-[hsl(var(--foreground))]">
                  {stage.status === "done" ? <CheckCircle2 className="size-4 text-emerald-500" /> : <CircleAlert className="size-4 text-[hsl(var(--muted-foreground))]" />}
                  {stage.label}
                </div>
                <div className="mt-1 text-[12px] capitalize text-[hsl(var(--muted-foreground))]">{stage.status}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

function NeuroTrendTab({
  patientLabel,
  patientStudies,
  selectedComparisonStudyIds,
  activeComparisonStudyId,
  baselineStudyId,
  latestComparisonStudyId,
  trendSeries,
  trendGroups,
  selectedTrendSeries,
  setSelectedTrendSeries,
  trendData,
  hasSessionLongitudinalContext,
  comparisonMetrics,
  highlights,
  heatmap,
}: {
  patientLabel: string | null
  patientStudies: PatientStudy[]
  selectedComparisonStudyIds: string[]
  activeComparisonStudyId: string | null
  baselineStudyId: string | null
  latestComparisonStudyId: string | null
  trendSeries: TrendSeriesMeta[]
  trendGroups: Array<{ id: string; displayName: string; series: TrendSeriesMeta[] }>
  selectedTrendSeries: string[]
  setSelectedTrendSeries: (value: string[]) => void
  trendData: Array<Record<string, string | number | null>>
  hasSessionLongitudinalContext: boolean
  comparisonMetrics: Array<{ id: string; label: string; value: string; delta: string }>
  highlights: PatientDataResponse["highlights"]
  heatmap: HeatmapResponse | null
}) {
  return (
    <section className="min-w-0 space-y-4 overflow-hidden rounded-[1.5rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-6 py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Longitudinal context</div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <div className="text-[20px] font-medium text-[hsl(var(--foreground))]">Volume trend</div>
            {patientLabel ? <Badge variant="outline">{patientLabel}</Badge> : null}
          </div>
          {hasSessionLongitudinalContext ? (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-[hsl(var(--muted-foreground))]">
              <span>{selectedComparisonStudyIds.length} selected</span>
              {baselineStudyId ? <span>Baseline: {formatShortDate(patientStudies.find((study) => study.study_id === baselineStudyId)?.study_date ?? "")}</span> : null}
              {latestComparisonStudyId ? <span>Latest: {formatShortDate(patientStudies.find((study) => study.study_id === latestComparisonStudyId)?.study_date ?? "")}</span> : null}
            </div>
          ) : null}
        </div>
      </div>

      {hasSessionLongitudinalContext ? (
        <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
          <VolumeTrendPanel
            selectedSeries={selectedTrendSeries}
            setSelectedSeries={setSelectedTrendSeries}
            subtitle="Registered follow-up studies can be reviewed here once alignment is complete."
            title="Volume trend"
            trendData={trendData}
            trendGroups={trendGroups}
            trendSeries={trendSeries}
          />
          <div className="min-w-0 space-y-4">
            <BaselineComparePanel
              activeStudy={patientStudies.find((study) => study.study_id === activeComparisonStudyId) ?? null}
              baselineStudy={patientStudies.find((study) => study.study_id === baselineStudyId) ?? null}
              comparisonMetrics={comparisonMetrics}
              selectedCount={selectedComparisonStudyIds.length}
            />
            <div className="min-w-0 rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
              <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Longitudinal highlights</div>
              <div className="mt-3 space-y-3">
                {highlights.slice(0, 4).map((highlight, index) => (
                  <div className="rounded-xl border border-[hsl(var(--border))] px-3 py-3" key={`${highlight.study_id}-${index}`}>
                    <div className="text-[13px] font-medium text-[hsl(var(--foreground))]">{highlight.display_name}</div>
                    <div className="mt-1 text-[12px] text-[hsl(var(--muted-foreground))]">
                      {formatShortDate(highlight.study_date)} · z={highlight.z_score.toFixed(2)} · {highlight.interpretation}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="xl:col-span-2">
            <HeatmapPanel heatmap={heatmap} />
          </div>
        </div>
      ) : (
        <div className="rounded-[1.25rem] border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--background))] px-5 py-6 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
          No longitudinal comparison available for this session
        </div>
      )}
    </section>
  )
}

function ReviewTrackDashboard({
  currentCaseId,
  review,
  report,
  reportSections,
  slices,
  overlaySlices,
  viewerAssets,
  showOverlay,
  setShowOverlay,
  overlayModel,
  viewerMode,
  setViewerMode,
  visibleLabelIds,
  activeLabelId,
  activeGroup,
  expandedGroups,
  onToggleGroupExpanded,
  onToggleGroupVisibility,
  onToggleLabelVisibility,
  onSelectAllLabels,
  onDeselectAllLabels,
  onReplaceVisibleLabelIds,
  onSelectGroup,
  onSelectLabel,
  segmentationLabelSourceLabel,
  segmentationLabelMappingPath,
  patientStudies,
  selectedStudyId,
  selectedStudySummary,
  onSelectStudy,
}: {
  currentCaseId: string | null
  review: DashboardPayloads["review"]
  report: string
  reportSections: ReportSections | null
  slices: SlicePlaneSet | null
  overlaySlices: SlicePlaneSet | null
  viewerAssets: ViewerAssets | null
  showOverlay: boolean
  setShowOverlay: (value: boolean) => void
  overlayModel: SegmentationOverlayModel | null
  viewerMode: ViewerMode
  setViewerMode: (mode: ViewerMode) => void
  visibleLabelIds: number[]
  activeLabelId: number | null
  activeGroup: string | null
  expandedGroups: string[]
  onToggleGroupExpanded: (groupId: string) => void
  onToggleGroupVisibility: (groupId: string) => void
  onToggleLabelVisibility: (labelId: number) => void
  onSelectAllLabels: () => void
  onDeselectAllLabels: () => void
  onReplaceVisibleLabelIds: (labelIds: number[]) => void
  onSelectGroup: (groupId: string | null) => void
  onSelectLabel: (labelId: number | null) => void
  segmentationLabelSourceLabel: string | null
  segmentationLabelMappingPath: string | null
  patientStudies: PatientStudy[]
  selectedStudyId: string | null
  selectedStudySummary: PatientStudy | null
  onSelectStudy: (study: PatientStudy) => void
}) {
  return (
    <>
      <ReviewDashboard report={report} reportSections={reportSections} review={review} />
      <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-3">
          <ViewerStudySelector
            caseId={currentCaseId}
            onSelectStudy={onSelectStudy}
            patientStudies={patientStudies}
            patientLabel={null}
            selectedStudyId={selectedStudyId}
            selectedStudySummary={selectedStudySummary}
          />
          <HybridImagingViewer
            activeGroup={activeGroup}
            activeLabelId={activeLabelId}
            expandedGroups={expandedGroups}
            onSelectGroup={onSelectGroup}
            onSelectLabel={onSelectLabel}
            onToggleGroupExpanded={onToggleGroupExpanded}
            onToggleGroupVisibility={onToggleGroupVisibility}
            onToggleLabelVisibility={onToggleLabelVisibility}
            onSelectAllLabels={onSelectAllLabels}
            onDeselectAllLabels={onDeselectAllLabels}
            onReplaceVisibleLabelIds={onReplaceVisibleLabelIds}
            overlayModel={overlayModel}
            overlaySlices={overlaySlices}
            segmentationLabelMappingPath={segmentationLabelMappingPath}
            segmentationLabelSourceLabel={segmentationLabelSourceLabel}
            setShowOverlay={setShowOverlay}
            showOverlay={showOverlay}
            slices={slices}
            viewerMode={viewerMode}
            viewerAssets={viewerAssets}
            visibleLabelIds={visibleLabelIds}
            setViewerMode={setViewerMode}
          />
        </div>
        <div className="min-w-0 overflow-hidden rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
          <div className="border-b border-[hsl(var(--border)/0.7)] px-5 py-4">
            <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Evidence support</div>
            <div className="mt-1 text-[16px] font-medium text-[hsl(var(--foreground))]">Imaging and structured evidence remain visible</div>
          </div>
          <div className="space-y-4 px-5 py-5">
            <div className="text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
              Review mode keeps the case viewer available as supporting evidence while the critique lane becomes the primary workspace.
            </div>
            {(review.source_report_sections
              ? Object.entries(review.source_report_sections)
              : []
            ).slice(0, 4).map(([label, value]) => (
              <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4" key={label}>
                <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">{label.replaceAll("_", " ")}</div>
                <div className="mt-2 text-[13px] leading-6 text-[hsl(var(--foreground))]">{value || "No text provided."}</div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  )
}

function VolumetricsPanel({
  volumetrics,
}: {
  volumetrics: VolumetricsResponse | null
}) {
  const isLesionBurden = volumetrics?.series_type === "lesion_burden" || volumetrics?.kind === "lesion_burden"
  const keyRegions = useMemo(() => {
    const interpreted = volumetrics?.interpreted_regions ?? volumetrics?.regions ?? []
    if (!interpreted.length) {
      return []
    }
    return [...interpreted]
      .filter((region) => region.z_score != null)
      .sort((left, right) => Math.abs((right.z_score ?? 0)) - Math.abs((left.z_score ?? 0)))
      .slice(0, 6)
  }, [volumetrics])
  const retainedRegionCount = volumetrics?.regions?.length ?? 0

  return (
    <div className="min-w-0 overflow-hidden rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <div className="border-b border-[hsl(var(--border)/0.7)] px-5 py-4">
        <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Volumetrics</div>
        <div className="mt-1 text-[16px] font-medium text-[hsl(var(--foreground))]">Quantitative findings</div>
      </div>
      <div className="max-h-[30rem] space-y-4 overflow-y-auto px-5 py-5">
        {volumetrics ? (
          <>
            <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4 text-[13px] leading-6 text-[hsl(var(--foreground))]">
              {volumetrics.summary}
            </div>
            {isLesionBurden ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <MetricChip
                  label="Lesion count"
                  value={volumetrics.lesion_count != null ? `${volumetrics.lesion_count}` : "—"}
                />
                <MetricChip
                  label="Total lesion volume"
                  value={volumetrics.total_lesion_volume_mm3 != null ? `${Math.round(volumetrics.total_lesion_volume_mm3).toLocaleString()} mm³` : "—"}
                />
                <MetricChip
                  label="Delta vs baseline"
                  value={volumetrics.delta_vs_baseline != null ? `${volumetrics.delta_vs_baseline > 0 ? "+" : ""}${volumetrics.delta_vs_baseline.toFixed(1)}%` : "—"}
                />
                <MetricChip
                  label="Delta vs prior"
                  value={volumetrics.delta_vs_prior != null ? `${volumetrics.delta_vs_prior > 0 ? "+" : ""}${volumetrics.delta_vs_prior.toFixed(1)}%` : "—"}
                />
                {volumetrics.enhancing_burden_mm3 != null ? (
                  <MetricChip
                    label="Enhancing burden"
                    value={`${Math.round(volumetrics.enhancing_burden_mm3).toLocaleString()} mm³`}
                  />
                ) : null}
                <MetricChip
                  label="Response category"
                  value={(volumetrics.response_category || "monitoring").replaceAll("_", " ")}
                />
                {volumetrics.confidence_or_coverage_note ? (
                  <div className="sm:col-span-2 rounded-xl border border-[hsl(var(--border)/0.8)] bg-[hsl(var(--background))] px-4 py-3 text-[12px] leading-6 text-[hsl(var(--muted-foreground))]">
                    {volumetrics.confidence_or_coverage_note}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  {volumetrics.csv_export_url ? (
                    <a
                      className="inline-flex items-center gap-2 rounded-full border border-[hsl(var(--border))] px-3 py-1.5 text-[12px] text-[hsl(var(--muted-foreground))] transition-colors hover:text-[hsl(var(--foreground))]"
                      href={volumetrics.csv_export_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Export structural regions CSV
                    </a>
                  ) : null}
                  {retainedRegionCount ? (
                    <span className="inline-flex items-center gap-2 rounded-full border border-[hsl(var(--border))] px-3 py-1.5 text-[12px] text-[hsl(var(--muted-foreground))]">
                      {retainedRegionCount} retained regions
                    </span>
                  ) : null}
                </div>
                {keyRegions.map((region) => (
                  <div className="rounded-xl border border-[hsl(var(--border)/0.8)] bg-[hsl(var(--background))] px-4 py-3" key={region.name}>
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-[13px] font-medium text-[hsl(var(--foreground))]">{region.display_name}</div>
                        <div className="mt-1 text-[12px] text-[hsl(var(--muted-foreground))]">{region.interpretation}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-[14px] font-medium text-[hsl(var(--foreground))]">
                          {(region.z_score ?? 0) >= 0 ? "+" : ""}
                          {(region.z_score ?? 0).toFixed(2)}
                        </div>
                        <div className="text-[11px] text-[hsl(var(--muted-foreground))]">
                          p{(region.percentile ?? 0).toFixed(0)}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : (
          <div className="rounded-xl border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--background))] p-5 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
            Tool-output and full-agent modes will surface quantitative findings here.
          </div>
        )}
      </div>
    </div>
  )
}

function StructuralRegionTablePanel({
  overlayModel,
  visibleLabelIds,
  activeLabelId,
  activeGroup,
  expandedGroups,
  onToggleGroupExpanded,
  onSelectGroup,
  onSelectLabel,
  csvExportUrl,
}: {
  overlayModel: SegmentationOverlayModel
  visibleLabelIds: number[]
  activeLabelId: number | null
  activeGroup: string | null
  expandedGroups: string[]
  onToggleGroupExpanded: (groupId: string) => void
  onSelectGroup: (groupId: string | null) => void
  onSelectLabel: (labelId: number | null) => void
  csvExportUrl: string | null
}) {
  const [search, setSearch] = useState("")
  const [sortBy, setSortBy] = useState<"volume" | "name">("volume")
  const visibleSet = useMemo(() => new Set(visibleLabelIds), [visibleLabelIds])
  const filteredGroups = useMemo(() => {
    const query = search.trim().toLowerCase()
    return overlayModel.groups
      .map((group) => {
        const labels = [...group.labels]
          .filter((label) => {
            if (!query) {
              return true
            }
            return [label.displayName, label.labelName, label.groupDisplayName, label.hemisphere ?? ""]
              .join(" ")
              .toLowerCase()
              .includes(query)
          })
          .sort((left, right) =>
            sortBy === "volume" ? right.volumeMm3 - left.volumeMm3 : left.displayName.localeCompare(right.displayName),
          )
        return { ...group, labels }
      })
      .filter((group) => group.labels.length)
  }, [overlayModel.groups, search, sortBy])

  return (
    <div className="min-w-0 overflow-hidden rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[hsl(var(--border)/0.7)] px-5 py-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Region table</div>
          <div className="mt-1 text-[16px] font-medium text-[hsl(var(--foreground))]">Structural segmentation breakdown</div>
          <div className="mt-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
            Search retained labels, sort by volume, and click rows to focus the imaging overlay.
          </div>
        </div>
        {csvExportUrl ? (
          <a
            className="inline-flex items-center gap-2 rounded-full border border-[hsl(var(--border))] px-3 py-1.5 text-[12px] text-[hsl(var(--muted-foreground))] transition-colors hover:text-[hsl(var(--foreground))]"
            href={csvExportUrl}
            rel="noreferrer"
            target="_blank"
          >
            Export structural regions CSV
          </a>
        ) : null}
      </div>
      <div className="space-y-4 px-5 py-5">
        <div className="flex flex-wrap gap-3">
          <input
            className="min-w-[16rem] flex-1 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-[13px] text-[hsl(var(--foreground))] outline-none ring-0 placeholder:text-[hsl(var(--muted-foreground))]"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search label or group"
            type="text"
            value={search}
          />
          <select
            className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-[13px] text-[hsl(var(--foreground))]"
            onChange={(event) => setSortBy(event.target.value as "volume" | "name")}
            value={sortBy}
          >
            <option value="volume">Sort by volume</option>
            <option value="name">Sort by name</option>
          </select>
        </div>
        <div className="space-y-3">
          {filteredGroups.map((group) => {
            const expanded = expandedGroups.includes(group.id)
            const groupActive = activeGroup === group.id && activeLabelId == null
            return (
              <div className="overflow-hidden rounded-xl border border-[hsl(var(--border)/0.75)]" key={group.id}>
                <div className="flex items-center gap-3 px-4 py-3">
                  <button
                    className="flex min-w-0 flex-1 items-center gap-3 text-left"
                    onClick={() => onSelectGroup(groupActive ? null : group.id)}
                    type="button"
                  >
                    <span className="h-3.5 w-3.5 rounded-full border border-black/15" style={{ backgroundColor: group.color }} />
                    <div>
                      <div className={cn("text-[13px] font-medium", groupActive ? "text-[hsl(var(--foreground))]" : "text-[hsl(var(--muted-foreground))]")}>
                        {group.displayName}
                      </div>
                      <div className="text-[11px] text-[hsl(var(--muted-foreground))]">{group.labels.length} labels</div>
                    </div>
                  </button>
                  <button
                    className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] text-[hsl(var(--muted-foreground))] transition-colors hover:text-[hsl(var(--foreground))]"
                    onClick={() => onToggleGroupExpanded(group.id)}
                    type="button"
                  >
                    {expanded ? "Collapse" : "Expand"}
                  </button>
                </div>
                {expanded ? (
                  <div className="border-t border-[hsl(var(--border)/0.75)]">
                    <table className="w-full border-collapse text-left text-[12px]">
                      <thead className="bg-[hsl(var(--background))] text-[hsl(var(--muted-foreground))]">
                        <tr>
                          <th className="px-4 py-3 font-medium">Region</th>
                          <th className="px-4 py-3 font-medium">Hemisphere</th>
                          <th className="px-4 py-3 font-medium">Visible</th>
                          <th className="px-4 py-3 font-medium">Volume (mm³)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {group.labels.map((label) => {
                          const active = activeLabelId === label.labelId
                          const visible = visibleSet.has(label.labelId)
                          return (
                            <tr
                              className={cn(
                                "border-t border-[hsl(var(--border)/0.55)] transition-colors",
                                active ? "bg-[hsl(var(--primary)/0.08)]" : "hover:bg-[hsl(var(--accent)/0.35)]",
                              )}
                              key={label.labelId}
                            >
                              <td className="px-4 py-3">
                                <button className="flex items-center gap-3 text-left" onClick={() => onSelectLabel(active ? null : label.labelId)} type="button">
                                  <span className="h-3 w-3 rounded-sm border border-black/15" style={{ backgroundColor: label.color }} />
                                  <div>
                                    <div className={cn("font-medium", active ? "text-[hsl(var(--foreground))]" : "text-[hsl(var(--foreground))]")}>
                                      {label.displayName}
                                    </div>
                                    <div className="text-[11px] text-[hsl(var(--muted-foreground))]">{label.labelName}</div>
                                  </div>
                                </button>
                              </td>
                              <td className="px-4 py-3 text-[hsl(var(--muted-foreground))]">{label.hemisphere ?? "—"}</td>
                              <td className="px-4 py-3 text-[hsl(var(--muted-foreground))]">{visible ? "Shown" : "Hidden"}</td>
                              <td className="px-4 py-3 text-[hsl(var(--foreground))]">{Math.round(label.volumeMm3).toLocaleString()}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function HeatmapPanel({
  heatmap,
}: {
  heatmap: HeatmapResponse | null
}) {
  if (!heatmap) {
    return (
      <div className="rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 text-[13px] text-[hsl(var(--muted-foreground))]">
        Longitudinal heatmap will appear after patient data loads.
      </div>
    )
  }

  return (
    <div className="min-w-0 overflow-hidden rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <div className="border-b border-[hsl(var(--border)/0.7)] px-5 py-4">
        <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Heatmap</div>
        <div className="mt-1 text-[16px] font-medium text-[hsl(var(--foreground))]">Volume trend matrix across studies</div>
      </div>
      <div className="overflow-x-auto px-5 py-5">
        <div className="min-w-[42rem]">
          <div
            className="grid gap-2 text-[11px] uppercase tracking-[0.12em] text-[hsl(var(--muted-foreground))]"
            style={{ gridTemplateColumns: `13rem repeat(${heatmap.dates.length}, minmax(3rem, 1fr))` }}
          >
            <div>Region</div>
            {heatmap.dates.map((date) => (
              <div className="text-center" key={date}>
                {new Date(date).toLocaleDateString("en-US", { month: "short", year: "2-digit" })}
              </div>
            ))}
          </div>
          <div className="mt-3 space-y-2">
            {heatmap.region_names.slice(0, 8).map((regionName) => {
              const meta = heatmap.available_series?.find((item) => item.name === regionName)
              return (
              <div
                className="grid gap-2"
                key={regionName}
                style={{ gridTemplateColumns: `13rem repeat(${heatmap.dates.length}, minmax(3rem, 1fr))` }}
              >
                <div className="truncate rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-[12px] text-[hsl(var(--foreground))]">
                  {meta?.display_name ?? regionName.replaceAll("_", " ")}
                </div>
                {heatmap.matrix[regionName]?.map((cell, index) => (
                  <div
                    className={cn("flex h-10 items-center justify-center rounded-lg text-[11px] font-medium text-white", zColor(cell.z_score))}
                    key={`${regionName}-${index}`}
                    title={cell.volume_mm3 == null ? "No value" : `${Math.round(cell.volume_mm3).toLocaleString()} ${meta?.unit?.toLowerCase() === "mm3" ? "mm³" : meta?.unit ?? "mm³"}`}
                  >
                    {cell.volume_mm3 == null ? "—" : meta?.unit === "count" ? Math.round(cell.volume_mm3) : Math.round(cell.volume_mm3)}
                  </div>
                ))}
              </div>
            )})}
          </div>
        </div>
      </div>
    </div>
  )
}

export function NeuroReportPage() {
  const { chat } = useOutletContext<DemoLayoutContext>()
  const [searchParams, setSearchParams] = useSearchParams()
  const fromChat = searchParams.get("from") === "chat"
  const requestedSource = (searchParams.get("source") as AnalysisSource | null) ?? "example"
  const requestedPatientId = searchParams.get("patient_id")
  const requestedStudyId = searchParams.get("study_id")
  const requestedCaseId = searchParams.get("case_id")
  const requestedKnowledgePatientUid = searchParams.get("knowledge_patient_uid")
  const requestedKnowledgeStudyUid = searchParams.get("knowledge_study_uid")
  const requestedSessionId = searchParams.get("session_id")
  const requestedUploadSourcePath = searchParams.get("source_path")
  const requestedMode = searchParams.get("mode") as AnalysisMode | null
  const requestedPrimaryGoal = searchParams.get("goal") as "structural_report" | "response_review" | "report_review" | null
  const requestedWorkspaceTab = normalizeWorkspaceTab(searchParams.get("tab"))

  const examplesQuery = useApi<ExamplesResponse>("/api/demo/neuro-report/examples")
  const patientsQuery = useApi<PatientsResponse>("/api/demo/neuro-report/patients")

  const [selectedPatientId, setSelectedPatientId] = useState<string | null>(requestedPatientId)
  const [selectedStudyId, setSelectedStudyId] = useState<string | null>(requestedStudyId)
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(requestedCaseId)
  const [selectedMode, setSelectedMode] = useState<AnalysisMode>(requestedMode && MODE_META[requestedMode] ? requestedMode : "full_agent")
  const [sourceType, setSourceType] = useState<AnalysisSource>(
    requestedSource === "upload" ? "upload" : requestedSource === "knowledge" ? "knowledge" : "example",
  )
  const [showOverlay, setShowOverlay] = useState(true)
  const [viewerMode, setViewerMode] = useState<ViewerMode>("blend")
  const [reviewLaneOpen, setReviewLaneOpen] = useState(false)
  const [primaryGoalOverride, setPrimaryGoalOverride] = useState<"structural_report" | "response_review" | "report_review" | null>(requestedPrimaryGoal)
  const [activeWorkspaceTab, setActiveWorkspaceTab] = useState<NeuroWorkspaceTab>(requestedWorkspaceTab)
  const [selectedTrendSeries, setSelectedTrendSeries] = useState<string[]>([])
  const [selectedComparisonStudyIds, setSelectedComparisonStudyIds] = useState<string[]>([])
  const [activeComparisonStudyId, setActiveComparisonStudyId] = useState<string | null>(null)
  const [visibleLabelIds, setVisibleLabelIds] = useState<number[]>([])
  const [activeLabelId, setActiveLabelId] = useState<number | null>(null)
  const [activeGroup, setActiveGroup] = useState<string | null>(null)
  const [expandedGroups, setExpandedGroups] = useState<string[]>([])
  const [analysis, setAnalysis] = useState<AnalysisState>({
    running: false,
    error: null,
    progress: [],
    report: "",
    reportSections: null,
    rawSlices: null,
    overlaySlices: null,
    sliceManifest: null,
    sliceSource: null,
    viewerAssets: null,
    volumetrics: null,
    segmentationRegions: null,
    sessionId: null,
    analysisPlan: null,
    analysisPlanSummary: null,
    capabilityProfile: null,
    capabilityProfileSummary: null,
    planningResult: null,
    workspaceContract: null,
    requestedMode: null,
    executedMode: null,
    dashboardPayloads: null,
    segmentationBackend: null,
    preprocessingProfile: null,
    csvExportUrl: null,
    labelSource: null,
    labelMappingPath: null,
    labelMappingLabelCount: null,
    labelSchemaVersion: null,
    source: null,
  })
  const demoProgressRunRef = useRef(0)
  const [uploadNifti, setUploadNifti] = useState<File | null>(null)
  const [uploadSourcePath, setUploadSourcePath] = useState<string>(requestedUploadSourcePath ?? "")
  const [uploadSeg, setUploadSeg] = useState<File | null>(null)
  const [uploadAutoSegment, setUploadAutoSegment] = useState(false)
  const [uploadAge, setUploadAge] = useState("65")
  const [uploadSex, setUploadSex] = useState("M")
  const [uploadIndication, setUploadIndication] = useState("")
  const [analysisDataSource, setAnalysisDataSource] = useState<"curated_examples" | "uploaded_files" | "mr_rate_knowledge">(
    requestedSource === "upload"
      ? "uploaded_files"
      : requestedSource === "knowledge"
        ? "mr_rate_knowledge"
        : "curated_examples",
  )
  const uploadNiftiInputRef = useRef<HTMLInputElement | null>(null)
  const uploadSegInputRef = useRef<HTMLInputElement | null>(null)
  const [selectedKnowledgePatientUid, setSelectedKnowledgePatientUid] = useState(requestedKnowledgePatientUid ?? "")
  const [requestedKnowledgeStudyUidState, setRequestedKnowledgeStudyUidState] = useState<string | null>(requestedKnowledgeStudyUid)
  const [selectedKnowledgeStudyUid, setSelectedKnowledgeStudyUid] = useState(requestedKnowledgeStudyUid ?? "")
  const [knowledgeCasePayload, setKnowledgeCasePayload] = useState<NeuroKnowledgeCase | null>(null)
  const [knowledgeAssetsPayload, setKnowledgeAssetsPayload] = useState<NeuroKnowledgeAssetsResponse | null>(null)
  const [knowledgeStudyPayload, setKnowledgeStudyPayload] = useState<NeuroKnowledgeStudy | null>(null)
  const [knowledgeCasePickerQuery, setKnowledgeCasePickerQuery] = useState("")
  const [knowledgeCaseFilter, setKnowledgeCaseFilter] = useState<KnowledgeCaseFilter>("all")
  const [knowledgeSearchQuery, setKnowledgeSearchQuery] = useState("")
  const [knowledgeSearchResults, setKnowledgeSearchResults] = useState<NeuroKnowledgeSearchResponse | null>(null)
  const [knowledgeLocalStatus, setKnowledgeLocalStatus] = useState<KnowledgeLocalStatus | null>(null)
  const [knowledgeLocalStatusError, setKnowledgeLocalStatusError] = useState<string | null>(null)
  const [knowledgePreviewSessionId, setKnowledgePreviewSessionId] = useState<string | null>(
    requestedSource === "knowledge" ? requestedSessionId : null,
  )
  const [caseSegmentationState, setCaseSegmentationState] = useState<"idle" | "checking" | "ready" | "unavailable">("idle")

  useEffect(() => {
    setActiveWorkspaceTab(requestedWorkspaceTab)
  }, [requestedWorkspaceTab])

  function selectWorkspaceTab(tab: NeuroWorkspaceTab) {
    setActiveWorkspaceTab(tab)
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.set("tab", tab)
      return next
    })
  }

  useEffect(() => {
    let cancelled = false
    if (!requestedSessionId) {
      return () => {
        cancelled = true
      }
    }
    const knowledgeSelectionConflictsWithUrl =
      requestedSource === "knowledge" &&
      sourceType === "knowledge" &&
      Boolean(selectedKnowledgePatientUid) &&
      ((requestedKnowledgePatientUid && selectedKnowledgePatientUid !== requestedKnowledgePatientUid) ||
        (requestedKnowledgeStudyUid && selectedKnowledgeStudyUid !== requestedKnowledgeStudyUid))
    if (knowledgeSelectionConflictsWithUrl) {
      return () => {
        cancelled = true
      }
    }
    if (analysis.sessionId === requestedSessionId && analysis.report) {
      return () => {
        cancelled = true
      }
    }

    fetchJson<AnalysisSessionResponse>(`/api/demo/neuro-report/sessions/${requestedSessionId}`)
      .then((payload) => {
        if (cancelled) {
          return
        }
        const sessionConflictsWithKnowledgeUrl =
          requestedSource === "knowledge" &&
          ((requestedKnowledgePatientUid && payload.patient_id !== requestedKnowledgePatientUid) ||
            (requestedKnowledgeStudyUid && payload.study_id !== requestedKnowledgeStudyUid))
        if (sessionConflictsWithKnowledgeUrl) {
          return
        }
        const restoredSource =
          payload.source === "knowledge" || payload.source === "upload" ? payload.source : "example"
        setSourceType(restoredSource)
        setAnalysisDataSource(
          restoredSource === "knowledge"
            ? "mr_rate_knowledge"
            : restoredSource === "upload"
              ? "uploaded_files"
              : "curated_examples",
        )
        if (payload.requested_mode && MODE_META[payload.requested_mode]) {
          setSelectedMode(payload.requested_mode)
        } else if (payload.mode && MODE_META[payload.mode]) {
          setSelectedMode(payload.mode)
        }
        if (payload.indication) {
          setUploadIndication(payload.indication)
        }
        if (payload.age != null) {
          setUploadAge(String(payload.age))
        }
        if (payload.sex) {
          setUploadSex(payload.sex)
        }
        if (restoredSource === "knowledge") {
          setSelectedKnowledgePatientUid(payload.patient_id ?? "")
          setRequestedKnowledgeStudyUidState(payload.study_id ?? null)
          setSelectedKnowledgeStudyUid(payload.study_id ?? "")
          setKnowledgePreviewSessionId(payload.session_id)
        } else {
          setSelectedPatientId(payload.patient_id)
          setSelectedStudyId(payload.study_id)
          setSelectedCaseId(payload.case_id)
        }
        if (restoredSource === "upload") {
          setUploadSourcePath("")
        }
        setAnalysis({
          running: false,
          error: null,
          progress: [],
          report: payload.report ?? "",
          reportSections: payload.report_sections ?? null,
          rawSlices: null,
          overlaySlices: null,
          sliceManifest: payload.slice_manifest ?? null,
          sliceSource: payload.slice_source ?? null,
          viewerAssets: payload.viewer_assets ?? null,
          volumetrics: payload.volumetrics ?? null,
          segmentationRegions: payload.segmentation_regions ?? null,
          sessionId: payload.session_id,
          analysisPlan: payload.analysis_plan ?? null,
          analysisPlanSummary: payload.analysis_plan_summary ?? null,
          capabilityProfile: payload.capability_profile ?? null,
          capabilityProfileSummary: payload.capability_profile_summary ?? null,
          planningResult: payload.planning_result ?? null,
          workspaceContract: payload.workspace_contract ?? null,
          requestedMode: payload.requested_mode ?? null,
          executedMode: payload.mode ?? null,
          dashboardPayloads: payload.dashboard_payloads ?? null,
          segmentationBackend: payload.segmentation_backend ?? null,
          preprocessingProfile: payload.preprocessing_profile ?? null,
          csvExportUrl: payload.csv_export_url ?? null,
          labelSource: payload.label_source ?? null,
          labelMappingPath: payload.label_mapping_path ?? null,
          labelMappingLabelCount: payload.label_mapping_label_count ?? null,
          labelSchemaVersion: payload.label_schema_version ?? null,
          source: restoredSource,
        })
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setAnalysis((current) => ({
            ...current,
            error: error instanceof Error ? error.message : "Failed to restore analysis session.",
          }))
        }
      })

    return () => {
      cancelled = true
    }
  }, [
    analysis.report,
    analysis.sessionId,
    requestedKnowledgePatientUid,
    requestedKnowledgeStudyUid,
    requestedSessionId,
    requestedSource,
    selectedKnowledgePatientUid,
    selectedKnowledgeStudyUid,
    sourceType,
  ])

  useEffect(() => {
    if (requestedUploadSourcePath && sourceType === "upload" && !analysis.sessionId && !uploadNifti) {
      setUploadSourcePath(requestedUploadSourcePath)
    }
  }, [analysis.sessionId, requestedUploadSourcePath, sourceType, uploadNifti])
  const [knowledgeCaseLoading, setKnowledgeCaseLoading] = useState(false)
  const [knowledgeStudyLoading, setKnowledgeStudyLoading] = useState(false)
  const [knowledgeSearchLoading, setKnowledgeSearchLoading] = useState(false)
  const [knowledgeCaseError, setKnowledgeCaseError] = useState<string | null>(null)
  const [knowledgeStudyError, setKnowledgeStudyError] = useState<string | null>(null)
  const trendRegionsParam = selectedTrendSeries.length ? `?regions=${selectedTrendSeries.join(",")}` : ""
  const knowledgeCohortQuery = useApi<NeuroKnowledgeCohortResponse>("/api/neuro-knowledge/cohorts/v1")

  const patientQuery = useApi<PatientDataResponse>(
    selectedPatientId ? `/api/demo/neuro-report/patients/${selectedPatientId}` : null,
  )
  const studyDetailQuery = useApi<StudyDetailResponse>(
    selectedPatientId && selectedStudyId
      ? `/api/demo/neuro-report/patients/${selectedPatientId}/studies/${selectedStudyId}`
      : null,
  )
  const longitudinalQuery = useApi<LongitudinalResponse>(
    sourceType === "example" && selectedPatientId
      ? `/api/demo/neuro-report/patients/${selectedPatientId}/volumetrics${trendRegionsParam}`
      : sourceType === "knowledge" && selectedKnowledgePatientUid
        ? `/api/demo/neuro-report/knowledge/patients/${selectedKnowledgePatientUid}/volumetrics${trendRegionsParam}`
      : null,
  )
  const heatmapQuery = useApi<HeatmapResponse>(
    sourceType === "example" && selectedPatientId
      ? `/api/demo/neuro-report/patients/${selectedPatientId}/heatmap${trendRegionsParam}`
      : sourceType === "knowledge" && selectedKnowledgePatientUid
        ? `/api/demo/neuro-report/knowledge/patients/${selectedKnowledgePatientUid}/heatmap${trendRegionsParam}`
      : null,
  )
  const segmentationServiceQuery = useApi<SegmentationServiceStatus>("/api/demo/neuro-report/segmentation/service")
  const exampleLibraryAvailable = Boolean(examplesQuery.data?.examples?.length)

  useEffect(() => {
    if (sourceType !== "example" || examplesQuery.loading || !examplesQuery.data || exampleLibraryAvailable) {
      return
    }
    setSourceType("knowledge")
    setAnalysisDataSource("mr_rate_knowledge")
    setSelectedPatientId(null)
    setSelectedStudyId(null)
    setSelectedCaseId(null)
  }, [exampleLibraryAvailable, examplesQuery.data, examplesQuery.loading, sourceType])

  useEffect(() => {
    if (sourceType === "knowledge" && requestedKnowledgePatientUid && !selectedKnowledgePatientUid) {
      setSelectedKnowledgePatientUid(requestedKnowledgePatientUid)
    }
  }, [requestedKnowledgePatientUid, selectedKnowledgePatientUid, sourceType])

  useEffect(() => {
    if (!selectedKnowledgePatientUid) {
      setKnowledgeCasePayload(null)
      setKnowledgeAssetsPayload(null)
      setSelectedKnowledgeStudyUid("")
      return
    }

    let cancelled = false
    setKnowledgeCaseLoading(true)
    setKnowledgeCaseError(null)

    Promise.all([
      fetchJson<NeuroKnowledgeCase>(`/api/neuro-knowledge/cases/${selectedKnowledgePatientUid}`),
      fetchJson<NeuroKnowledgeAssetsResponse>(`/api/neuro-knowledge/cases/${selectedKnowledgePatientUid}/assets`),
    ])
      .then(([caseData, assetsData]) => {
        if (cancelled) {
          return
        }
        setKnowledgeCasePayload(caseData)
        setKnowledgeAssetsPayload(assetsData)
        const availableStudies = caseData.studies ?? []
        const requestedStudy = requestedKnowledgeStudyUidState
          ? availableStudies.find((study) => study.study_uid === requestedKnowledgeStudyUidState)
          : null
        setSelectedKnowledgeStudyUid((current) => {
          if (requestedStudy) {
            return requestedStudy.study_uid
          }
          return current && availableStudies.some((study) => study.study_uid === current) ? current : ""
        })
        setRequestedKnowledgeStudyUidState(null)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setKnowledgeCaseError(error instanceof Error ? error.message : "Failed to load MR-RATE case")
          setKnowledgeCasePayload(null)
          setKnowledgeAssetsPayload(null)
          setSelectedKnowledgeStudyUid("")
        }
      })
      .finally(() => {
        if (!cancelled) {
          setKnowledgeCaseLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [requestedKnowledgeStudyUidState, selectedKnowledgePatientUid])

  useEffect(() => {
    if (!selectedKnowledgeStudyUid) {
      setKnowledgeStudyPayload(null)
      setKnowledgeLocalStatus(null)
      setKnowledgeLocalStatusError(null)
      setKnowledgePreviewSessionId(null)
      setAnalysis((current) => ({
        ...current,
        report: "",
        reportSections: null,
        rawSlices: null,
        overlaySlices: null,
        sliceManifest: null,
        sliceSource: null,
        viewerAssets: null,
        volumetrics: null,
        segmentationRegions: null,
        sessionId: null,
        analysisPlan: null,
        analysisPlanSummary: null,
        capabilityProfile: null,
        capabilityProfileSummary: null,
        planningResult: null,
        workspaceContract: null,
        dashboardPayloads: null,
        segmentationBackend: null,
        preprocessingProfile: null,
        csvExportUrl: null,
        labelSource: null,
        labelMappingPath: null,
        labelMappingLabelCount: null,
        labelSchemaVersion: null,
        source: current.source === "knowledge" ? "knowledge" : current.source,
      }))
      return
    }

    let cancelled = false
    setKnowledgeStudyLoading(true)
    setKnowledgeStudyError(null)
    setKnowledgeLocalStatus("checking")
    setKnowledgeLocalStatusError(null)
    setAnalysis((current) => ({
      ...current,
      running: false,
      error: null,
      progress: [],
      report: "",
      reportSections: null,
      rawSlices: null,
      overlaySlices: null,
      sliceManifest: null,
      sliceSource: null,
      viewerAssets: null,
      volumetrics: null,
      segmentationRegions: null,
      sessionId: null,
      analysisPlan: null,
      analysisPlanSummary: null,
      capabilityProfile: null,
      capabilityProfileSummary: null,
      planningResult: null,
      workspaceContract: null,
      dashboardPayloads: null,
      segmentationBackend: null,
      preprocessingProfile: null,
      csvExportUrl: null,
      labelSource: null,
      labelMappingPath: null,
      labelMappingLabelCount: null,
      labelSchemaVersion: null,
      source: "knowledge",
    }))

    fetchJson<NeuroKnowledgeStudy>(`/api/neuro-knowledge/studies/${selectedKnowledgeStudyUid}`)
      .then((payload) => {
        if (!cancelled) {
          setKnowledgeStudyPayload(payload)
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setKnowledgeStudyError(error instanceof Error ? error.message : "Failed to load MR-RATE study")
          setKnowledgeStudyPayload(null)
        }
      })
      .finally(() => {
        if (!cancelled) {
          setKnowledgeStudyLoading(false)
        }
      })

    postJson<KnowledgeWorkspaceHydrationResponse>("/api/demo/neuro-report/knowledge-preview", {
      patient_uid: selectedKnowledgePatientUid,
      study_uid: selectedKnowledgeStudyUid,
    })
      .then((payload) => {
        if (!cancelled) {
          setKnowledgeLocalStatus(payload.local_status)
          setKnowledgePreviewSessionId(payload.session_id)
          setAnalysis((current) => ({
            ...current,
            running: false,
            error: null,
            progress: [],
            report: payload.report ?? "",
            reportSections: payload.report_sections ?? null,
            rawSlices: null,
            overlaySlices: null,
            sliceManifest: payload.slice_manifest ?? null,
            sliceSource: payload.slice_source ?? null,
            viewerAssets: payload.viewer_assets ?? null,
            volumetrics: payload.volumetrics ?? null,
            segmentationRegions: payload.segmentation_regions ?? null,
            sessionId: payload.session_id,
            analysisPlan: payload.analysis_plan ?? null,
            analysisPlanSummary: payload.analysis_plan_summary ?? null,
            capabilityProfile: payload.capability_profile ?? null,
            capabilityProfileSummary: payload.capability_profile_summary ?? null,
            planningResult: payload.planning_result ?? null,
            workspaceContract: payload.workspace_contract ?? null,
            requestedMode: payload.requested_mode ?? current.requestedMode,
            executedMode: payload.mode ?? current.executedMode,
            dashboardPayloads: payload.dashboard_payloads ?? null,
            segmentationBackend: payload.segmentation_backend ?? null,
            preprocessingProfile: payload.preprocessing_profile ?? null,
            csvExportUrl: payload.csv_export_url ?? null,
            labelSource: payload.label_source ?? null,
            labelMappingPath: payload.label_mapping_path ?? null,
            labelMappingLabelCount: payload.label_mapping_label_count ?? null,
            labelSchemaVersion: payload.label_schema_version ?? null,
            source: "knowledge",
          }))
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setKnowledgeLocalStatus(null)
          setKnowledgeLocalStatusError(error instanceof Error ? error.message : "Failed to prepare MR-RATE preview workspace")
          setKnowledgePreviewSessionId(null)
        }
      })

    return () => {
      cancelled = true
    }
  }, [selectedKnowledgePatientUid, selectedKnowledgeStudyUid])

  const selectedExample = useMemo(
    () =>
      examplesQuery.data?.examples.find((example) =>
        selectedCaseId ? example.case_id === selectedCaseId : example.patient_id === selectedPatientId && example.study_id === selectedStudyId,
      ) ?? null,
    [examplesQuery.data?.examples, selectedCaseId, selectedPatientId, selectedStudyId],
  )
  const curatedPatientGroups = useMemo(() => {
    const grouped = new Map<string, ExampleCase[]>()
    for (const example of examplesQuery.data?.examples ?? []) {
      const current = grouped.get(example.patient_id) ?? []
      current.push(example)
      grouped.set(example.patient_id, current)
    }
    return [...grouped.entries()]
      .map(([patientId, studies]) => ({
        patientId,
        studies: [...studies].sort(
          (left, right) => studyTime(extractExampleStudyDate(right)) - studyTime(extractExampleStudyDate(left)),
        ),
      }))
      .map((group) => ({
        ...group,
        representative: group.studies[0],
      }))
      .sort((left, right) => left.patientId.localeCompare(right.patientId, undefined, { numeric: true }))
  }, [examplesQuery.data?.examples])
  const knowledgeStudyRows = knowledgeCasePayload?.studies ?? []
  const selectedKnowledgeSummary = knowledgeCasePayload?.summary ?? null
  const selectedKnowledgeAssets = knowledgeAssetsPayload?.assets ?? []
  const selectedKnowledgeStudyAssets = useMemo(
    () => selectedKnowledgeAssets.filter((asset) => asset.study_uid === selectedKnowledgeStudyUid),
    [selectedKnowledgeAssets, selectedKnowledgeStudyUid],
  )
  const currentKnowledgeCohortEntry = useMemo(
    () => knowledgeCohortQuery.data?.cohort?.find((entry) => entry.patient_uid === selectedKnowledgePatientUid) ?? null,
    [knowledgeCohortQuery.data, selectedKnowledgePatientUid],
  )
  const rankedKnowledgeCohort = useMemo(
    () =>
      [...(knowledgeCohortQuery.data?.cohort ?? [])].sort((left, right) => {
        const scoreDelta = knowledgeCohortRankScore(right) - knowledgeCohortRankScore(left)
        if (scoreDelta !== 0) {
          return scoreDelta
        }
        return left.patient_uid.localeCompare(right.patient_uid, undefined, { numeric: true })
      }),
    [knowledgeCohortQuery.data?.cohort],
  )
  const filteredKnowledgeCohort = useMemo(
    () =>
      rankedKnowledgeCohort.filter(
        (entry) =>
          knowledgeCohortFilterMatches(entry, knowledgeCaseFilter) &&
          knowledgeCohortMatches(entry, knowledgeCasePickerQuery),
      ),
    [knowledgeCaseFilter, knowledgeCasePickerQuery, rankedKnowledgeCohort],
  )
  const sharedChatPreview = useMemo(
    () =>
      chat.messages
        .filter((message): message is Extract<ChatMessage, { type: "text" }> => message.type === "text" && message.role !== "system")
        .slice(-4),
    [chat.messages],
  )

  const patientStudies = patientQuery.data?.studies ?? []
  const selectedStudySummary = patientStudies.find((study) => study.study_id === selectedStudyId) ?? null
  const displaySlices = analysis.rawSlices ?? studyDetailQuery.data?.raw_slices ?? studyDetailQuery.data?.slices ?? null
  const displayOverlaySlices = analysis.overlaySlices ?? studyDetailQuery.data?.overlay_slices ?? null
  const displaySliceManifest = analysis.sliceManifest ?? studyDetailQuery.data?.slice_manifest ?? null
  const displaySliceSource = analysis.sliceSource ?? studyDetailQuery.data?.slice_source ?? null
  const displayViewerAssets = analysis.viewerAssets ?? studyDetailQuery.data?.viewer_assets ?? selectedExample?.viewer_assets ?? null
  const displayReport =
    analysis.report ||
    studyDetailQuery.data?.report.full_text ||
    selectedExample?.report?.full_text ||
    knowledgeStudyPayload?.report?.report_text ||
    ""
  const displaySections =
    analysis.reportSections ??
    studyDetailQuery.data?.report.sections ??
    selectedExample?.report?.sections ??
    (knowledgeStudyPayload?.report
      ? {
          clinical_information: knowledgeStudyPayload.report.clinical_information ?? "",
          technique: knowledgeStudyPayload.report.technique ?? "",
          findings: knowledgeStudyPayload.report.findings ?? "",
          impression: knowledgeStudyPayload.report.impression ?? "",
        }
      : null)
  const displayVolumetrics = analysis.volumetrics ?? studyDetailQuery.data?.volumetrics ?? null
  const displaySegmentationRegions =
    analysis.segmentationRegions ??
    studyDetailQuery.data?.segmentation_regions ??
    displayVolumetrics?.regions ??
    null
  const displayLabelSource =
    analysis.labelSource ??
    studyDetailQuery.data?.label_source ??
    displayVolumetrics?.label_source ??
    null
  const displayLabelMappingPath =
    analysis.labelMappingPath ??
    studyDetailQuery.data?.label_mapping_path ??
    displayVolumetrics?.label_mapping_path ??
    studyDetailQuery.data?.label_schema_path ??
    displayVolumetrics?.label_schema_path ??
    null
  const displayLabelMappingLabelCount =
    analysis.labelMappingLabelCount ??
    studyDetailQuery.data?.label_mapping_label_count ??
    displayVolumetrics?.label_mapping_label_count ??
    null
  const exampleHasNativeSegmentation = Boolean(
    selectedStudySummary?.has_segmentation ||
      studyDetailQuery.data?.capability_profile?.has_segmentation ||
      selectedExample?.capability_profile?.has_segmentation,
  )
  const knowledgeHasNativeSegmentation = Boolean(
    selectedKnowledgeStudyAssets.some(isKnowledgeSegmentationAsset),
  )
  const selectedKnowledgeStudyRow = useMemo(
    () => knowledgeStudyRows.find((study) => study.study_uid === selectedKnowledgeStudyUid) ?? null,
    [knowledgeStudyRows, selectedKnowledgeStudyUid],
  )
  const knowledgeViewerStudySummary = useMemo<ViewerStudySummary | null>(
    () =>
      selectedKnowledgeStudyUid
        ? {
            study_id: selectedKnowledgeStudyUid,
            study_date: knowledgeStudyPayload?.study?.anon_study_date ?? selectedKnowledgeStudyRow?.anon_study_date ?? "",
            has_segmentation: knowledgeHasNativeSegmentation,
          }
        : null,
    [knowledgeHasNativeSegmentation, knowledgeStudyPayload?.study?.anon_study_date, selectedKnowledgeStudyRow?.anon_study_date, selectedKnowledgeStudyUid],
  )
  const knowledgePatientStudies = useMemo<PatientStudy[]>(
    () =>
      sortStudiesByDate(
        knowledgeStudyRows.map((study) => ({
          study_id: study.study_uid,
          study_date: study.anon_study_date ?? "",
          age_at_study: Number(study.patient_age ?? 0),
          thumbnail_base64: KNOWLEDGE_STUDY_THUMBNAIL_BASE64,
          indication: selectedKnowledgeSummary?.summary_text ?? "MR-RATE knowledge study",
          has_segmentation: selectedKnowledgeAssets.some(
            (asset) => asset.study_uid === study.study_uid && isKnowledgeSegmentationAsset(asset),
          ),
          supported_modes: ["vanilla", "seg_overlay", "tool_output", "full_agent"] as AnalysisMode[],
        })),
      ),
    [knowledgeStudyRows, selectedKnowledgeAssets, selectedKnowledgeSummary?.summary_text],
  )
  const displayAnalysisPlan = analysis.analysisPlan ?? studyDetailQuery.data?.analysis_plan ?? selectedExample?.analysis_plan ?? null
  const displayAnalysisPlanSummary =
    analysis.analysisPlanSummary ?? studyDetailQuery.data?.analysis_plan_summary ?? selectedExample?.analysis_plan_summary ?? null
  const displayCapabilitySummary =
    analysis.capabilityProfileSummary ?? studyDetailQuery.data?.capability_profile_summary ?? selectedExample?.capability_profile_summary ?? null
  const displayDashboardPayloads =
    analysis.dashboardPayloads ?? studyDetailQuery.data?.dashboard_payloads ?? selectedExample?.dashboard_payloads ?? null
  const displayPlanningResult =
    analysis.planningResult ?? studyDetailQuery.data?.planning_result ?? selectedExample?.planning_result ?? null
  const displayWorkspaceContract =
    analysis.workspaceContract ?? studyDetailQuery.data?.workspace_contract ?? selectedExample?.workspace_contract ?? null
  const plannerPrimaryGoal =
    displayPlanningResult?.primary_goal ??
    displayAnalysisPlanSummary?.primary_goal ??
    displayAnalysisPlan?.primary_goal ??
    "structural_report"
  const activePrimaryGoal = primaryGoalOverride ?? plannerPrimaryGoal
  const activeReviewPayload = displayDashboardPayloads?.review ?? null
  const activeResponsePayload = displayDashboardPayloads?.response ?? null
  const structuralPatientStudies =
    sourceType === "example" ? patientStudies : sourceType === "knowledge" ? knowledgePatientStudies : []
  const sortedStructuralPatientStudies = useMemo(() => sortStudiesByDate(structuralPatientStudies), [structuralPatientStudies])
  const selectedComparisonStudies = useMemo(
    () => sortedStructuralPatientStudies.filter((study) => selectedComparisonStudyIds.includes(study.study_id)),
    [selectedComparisonStudyIds, sortedStructuralPatientStudies],
  )
  const baselineComparisonStudy = selectedComparisonStudies[0] ?? null
  const latestComparisonStudy = selectedComparisonStudies[selectedComparisonStudies.length - 1] ?? null
  const sessionPatientLabel = useMemo(() => {
    if (sourceType === "example") {
      return selectedPatientId ? `Patient ${selectedPatientId}` : null
    }
    if (sourceType === "knowledge") {
      return selectedKnowledgePatientUid ? `Patient ${selectedKnowledgePatientUid}` : null
    }
    return analysis.sessionId ? `Upload session ${analysis.sessionId}` : "Upload session"
  }, [analysis.sessionId, selectedKnowledgePatientUid, selectedPatientId, sourceType])
  const hasSessionLongitudinalContext = useMemo(
    () =>
      (sourceType === "example" && Boolean(selectedPatientId && patientStudies.length && longitudinalQuery.data?.series?.length)) ||
      (sourceType === "knowledge" && Boolean(selectedKnowledgePatientUid && knowledgePatientStudies.length > 1 && longitudinalQuery.data?.series?.length)),
    [knowledgePatientStudies.length, longitudinalQuery.data?.series?.length, patientStudies.length, selectedKnowledgePatientUid, selectedPatientId, sourceType],
  )
  const structuralHighlights =
    hasSessionLongitudinalContext
      ? sourceType === "knowledge"
        ? longitudinalQuery.data?.highlights ?? []
        : patientQuery.data?.highlights ?? []
      : []
  const structuralSelectedStudyId =
    sourceType === "example" ? selectedStudyId : sourceType === "knowledge" ? selectedKnowledgeStudyUid : null
  const structuralSelectedStudySummary =
    sourceType === "example" ? selectedStudySummary : sourceType === "knowledge" ? knowledgeViewerStudySummary : null
  const structuralCsvExportUrl =
    analysis.csvExportUrl ??
    displayVolumetrics?.csv_export_url ??
    studyDetailQuery.data?.volumetrics?.csv_export_url ??
    null
  const overlayModel = useMemo(
    () => buildSegmentationOverlayModel(displaySegmentationRegions ?? []),
    [displaySegmentationRegions],
  )
  const segmentationLabelSourceLabel = useMemo(() => {
    if (!displayLabelSource) {
      return null
    }
    const countSuffix = displayLabelMappingLabelCount ? ` · ${displayLabelMappingLabelCount} mapped` : ""
    if (displayLabelSource === "vista_tsv") {
      return `Vista labels${countSuffix}`
    }
    if (displayLabelSource === "remote_schema") {
      return `Remote 111-label schema${countSuffix}`
    }
    return `${displayLabelSource}${countSuffix}`
  }, [displayLabelMappingLabelCount, displayLabelSource])
  const segmentationServiceReady = Boolean(segmentationServiceQuery.data?.service_ready)
  const uploadCanAutoSegment = !uploadSeg && segmentationServiceReady
  const sourceSelectionReady =
    sourceType === "upload"
      ? Boolean(uploadNifti || uploadSourcePath)
      : sourceType === "knowledge"
        ? Boolean(selectedKnowledgePatientUid && selectedKnowledgeStudyUid)
        : Boolean(selectedPatientId && selectedStudyId)
  const sourceCanAutoSegment =
    sourceType === "upload"
      ? uploadCanAutoSegment
      : Boolean(sourceSelectionReady && segmentationServiceReady)
  const segmentationServiceCopy = useMemo(() => {
    if (segmentationServiceQuery.loading) {
      return "Checking optional segmentation service…"
    }
    if (segmentationServiceReady) {
      const labelCount = segmentationServiceQuery.data?.model?.label_count
      return `Optional segmentation ready${labelCount ? ` · ${labelCount} labels` : ""}`
    }
    const status = segmentationServiceQuery.data?.status
    if (status === "tunnel_down") {
      return "Optional segmentation tunnel is down. Analysis can still continue without it."
    }
    if (status === "remote_unhealthy") {
      return "Optional segmentation service is waking up. Analysis can still continue without it."
    }
    if (status === "not_configured") {
      return "Optional segmentation is not configured. The main chat and MRI report pipeline are still connected."
    }
    return segmentationServiceQuery.error || segmentationServiceQuery.data?.error || "Optional segmentation is unavailable right now."
  }, [
    segmentationServiceQuery.data?.error,
    segmentationServiceQuery.data?.model?.label_count,
    segmentationServiceQuery.data?.status,
    segmentationServiceQuery.error,
    segmentationServiceQuery.loading,
    segmentationServiceReady,
  ])
  const sourceSegmentationState = useMemo(() => {
    if (sourceType === "example") {
      if (caseSegmentationState === "idle") {
        return {
          label: "Auto segmentation",
          tone: "neutral" as const,
          loading: false,
          copy: "",
        }
      }
      if (caseSegmentationState === "checking") {
        return {
          label: "Checking auto segmentation",
          tone: "neutral" as const,
          loading: true,
          copy: "",
        }
      }
      if (caseSegmentationState === "ready") {
        return {
          label: "Auto segmentation ready",
          tone: "ready" as const,
          loading: false,
          copy: "",
        }
      }
      return {
        label: "Auto segmentation unavailable",
        tone: "unavailable" as const,
        loading: false,
        copy: "",
      }
    }
    if (!sourceSelectionReady) {
      return {
        label: "Auto segmentation",
        tone: "neutral" as const,
        loading: false,
        copy: "",
      }
    }
    if (segmentationServiceQuery.loading) {
      return {
        label: "Checking auto segmentation",
        tone: "neutral" as const,
        loading: true,
        copy: "",
      }
    }
    if (sourceCanAutoSegment) {
      return {
        label: "Auto segmentation ready",
        tone: "ready" as const,
        loading: false,
        copy: "",
      }
    }
    if (segmentationServiceQuery.data?.status === "remote_unhealthy") {
      return {
        label: "Auto segmentation waking up",
        tone: "warming" as const,
        loading: false,
        copy: "",
      }
    }
    return {
      label: "Auto segmentation unavailable",
      tone: "unavailable" as const,
      loading: false,
      copy: "",
    }
  }, [
    caseSegmentationState,
    segmentationServiceQuery.data?.status,
    segmentationServiceQuery.loading,
    sourceCanAutoSegment,
    sourceSelectionReady,
    sourceType,
  ])
  const composerHasText = uploadIndication.trim().length > 0
  const canAnalyzeCurrent =
    sourceType === "upload"
      ? Boolean(uploadNifti || uploadSourcePath)
      : sourceType === "knowledge"
        ? Boolean(selectedKnowledgePatientUid && selectedKnowledgeStudyUid)
        : Boolean(selectedPatientId && selectedStudyId)
  const uploadDisplayName = useMemo(() => {
    if (uploadNifti?.name) {
      return uploadNifti.name
    }
    if (!uploadSourcePath) {
      return "MRI files"
    }
    const normalized = uploadSourcePath.split(/[\\/]/).filter(Boolean)
    return normalized[normalized.length - 1] || "MRI files"
  }, [uploadNifti?.name, uploadSourcePath])
  const suggestedPrompts = [
    "Summarize the MRI findings and draft a concise impression.",
    "Prioritize the key abnormalities and tell me what to inspect first.",
    "Review this study for volumetrics, lesions, and follow-up questions.",
  ]
  const neuroReportLogoMarkSrc = `${import.meta.env.BASE_URL}clinagent-logo-mark.svg`
  const structuralSliceRequest = useMemo<StructuralSliceRequestContext | null>(() => {
    if (displaySliceSource !== "on_demand") {
      return null
    }
    if ((analysis.source === "upload" || analysis.source === "knowledge") && analysis.sessionId) {
      return {
        kind: "session",
        sessionId: analysis.sessionId,
      }
    }
    if (selectedPatientId && selectedStudyId) {
      return {
        kind: "study",
        patientId: selectedPatientId,
        studyId: selectedStudyId,
      }
    }
    return null
  }, [analysis.sessionId, analysis.source, displaySliceSource, selectedPatientId, selectedStudyId])
  const preloadStatus = examplesQuery.data?.preload_status ?? null
  const segmentedStudyCount = patientStudies.filter((study) => study.has_segmentation).length
  const priorStudyCount = Math.max(0, patientStudies.length - 1)
  const exampleHydrationMetrics = useMemo<HydrationMetric[]>(() => {
    const preloadLabel = preloadStatus?.structural_ready
      ? `Ready · ${preloadStatus.structural_patient_count} patients`
      : preloadStatus
        ? "Partial"
        : "Checking"
    const segmentationLabel = selectedStudyId
      ? exampleHasNativeSegmentation
        ? "Study ready"
        : segmentationServiceReady
          ? "Auto ready"
          : "Pending"
      : segmentedStudyCount
        ? `${segmentedStudyCount} studies ready`
        : "Pending"
    return [
      {
        label: "Studies linked",
        value: patientStudies.length ? `${patientStudies.length} studies` : "Pending",
      },
      {
        label: "Prior exams",
        value: priorStudyCount ? `${priorStudyCount} prior exams` : "Single timepoint",
      },
      {
        label: "Segmentation",
        value: segmentationLabel,
      },
      {
        label: "Preload",
        value: preloadLabel,
      },
    ]
  }, [exampleHasNativeSegmentation, patientStudies.length, preloadStatus, priorStudyCount, segmentedStudyCount, segmentationServiceReady, selectedStudyId])
  const exampleHydrationSteps = useMemo<HydrationStage[]>(() => {
    const patientResolved = Boolean(selectedPatientId && patientQuery.data?.patient)
    const timelineReady = Boolean(patientQuery.data?.studies?.length && longitudinalQuery.data?.series?.length)
    const viewerReady = Boolean(selectedStudyId && displayViewerAssets)
    const quantReady = Boolean(displayVolumetrics || displaySegmentationRegions?.length)
    const reportReady = Boolean(displaySections || displayReport)
    return [
      {
        stage: "patient_context",
        label: "Resolve patient",
        hint: patientResolved
          ? `${patientQuery.data?.patient.name || `Patient ${selectedPatientId}`}`
          : "Select a patient to load the case shell.",
        status: selectedPatientId ? (patientQuery.loading ? "running" : patientResolved ? "done" : "pending") : "pending",
      },
      {
        stage: "timeline",
        label: "Load timeline",
        hint: timelineReady
          ? `${patientStudies.length} studies with longitudinal context`
          : "Attach priors, study dates, and record continuity.",
        status:
          selectedPatientId && (patientQuery.loading || longitudinalQuery.loading)
            ? "running"
            : timelineReady
              ? "done"
              : "pending",
      },
      {
        stage: "viewer",
        label: "Attach viewer",
        hint: viewerReady
          ? `${displayViewerAssets?.viewer_type === "dicomweb" ? "DICOMweb" : "MRI"} viewer ready`
          : "Prepare slices and navigation assets.",
        status: selectedStudyId ? (studyDetailQuery.loading ? "running" : viewerReady ? "done" : "pending") : "pending",
      },
      {
        stage: "quantification",
        label: "Load quantification",
        hint: quantReady
          ? `${displaySegmentationRegions?.length || displayVolumetrics?.regions?.length || 0} labeled regions available`
          : "Attach segmentation, volumetrics, and comparison signals.",
        status:
          selectedStudyId && (studyDetailQuery.loading || longitudinalQuery.loading || heatmapQuery.loading)
            ? "running"
            : quantReady
              ? "done"
              : "pending",
      },
      {
        stage: "workspace",
        label: "Hydrate workspace",
        hint: reportReady
          ? "Report, measurements, and review state are attached."
          : "Compose the MRI review workspace shell.",
        status: selectedStudyId ? (studyDetailQuery.loading ? "running" : reportReady ? "done" : "pending") : "pending",
      },
    ]
  }, [
    selectedPatientId,
    patientQuery.data,
    patientQuery.loading,
    longitudinalQuery.data?.series?.length,
    longitudinalQuery.loading,
    patientStudies.length,
    selectedStudyId,
    displayViewerAssets,
    displayVolumetrics,
    displaySegmentationRegions,
    displaySections,
    displayReport,
    studyDetailQuery.loading,
    heatmapQuery.loading,
  ])
  const knowledgeHydrationMetrics = useMemo<HydrationMetric[]>(() => {
    return [
      {
        label: "Cohort access",
        value: knowledgeCohortQuery.data?.cohort?.length ? `${knowledgeCohortQuery.data.cohort.length} patients` : "Checking",
      },
      {
        label: "Studies linked",
        value: knowledgeStudyRows.length ? `${knowledgeStudyRows.length} studies` : "Pending",
      },
      {
        label: "Local mirror",
        value: knowledgeLocalStatusLabel(knowledgeLocalStatus),
      },
      {
        label: "Segmentation",
        value: knowledgeHasNativeSegmentation
          ? "Study ready"
          : selectedKnowledgeStudyUid && segmentationServiceReady
            ? "Auto ready"
            : "Pending",
      },
    ]
  }, [knowledgeCohortQuery.data?.cohort, knowledgeHasNativeSegmentation, knowledgeLocalStatus, knowledgeStudyRows.length, segmentationServiceReady, selectedKnowledgeStudyUid])
  const knowledgeHydrationSteps = useMemo<HydrationStage[]>(() => {
    const cohortReady = Boolean(knowledgeCohortQuery.data?.cohort?.length)
    const caseReady = Boolean(knowledgeCasePayload)
    const studyReady = Boolean(knowledgeStudyPayload)
    const mirrorReady = knowledgeLocalStatus === "ready_local" || knowledgeLocalStatus === "downloaded"
    const launchReady = Boolean(selectedKnowledgePatientUid && selectedKnowledgeStudyUid && (studyReady || mirrorReady))
    return [
      {
        stage: "cohort",
        label: "Read cohort",
        hint: cohortReady ? "Knowledge registry is available." : "Check MR-RATE cohort availability.",
        status: knowledgeCohortQuery.loading ? "running" : cohortReady ? "done" : "pending",
      },
      {
        stage: "case",
        label: "Load case metadata",
        hint: caseReady ? `${knowledgeCasePayload?.summary?.patient_uid || knowledgeCasePayload?.case.patient_uid || selectedKnowledgePatientUid}` : "Attach patient-level report and study metadata.",
        status: selectedKnowledgePatientUid ? (knowledgeCaseLoading ? "running" : caseReady ? "done" : "pending") : "pending",
      },
      {
        stage: "study",
        label: "Load study detail",
        hint: studyReady ? `${selectedKnowledgeStudyUid || "Study selected"}` : "Inspect report detail and indexed assets.",
        status: selectedKnowledgeStudyUid ? (knowledgeStudyLoading ? "running" : studyReady ? "done" : "pending") : "pending",
      },
      {
        stage: "mirror",
        label: "Check local mirror",
        hint: mirrorReady ? "Local files are already available." : "Check whether the study is mirrored locally.",
        status: knowledgeLocalStatus === "checking" ? "running" : mirrorReady ? "done" : "pending",
      },
      {
        stage: "launch",
        label: "Prepare launch bundle",
        hint: launchReady ? "Ready to hydrate the MRI workspace." : "Resolve local bundle and segmentation preference.",
        status: launchReady ? "done" : selectedKnowledgeStudyUid ? "running" : "pending",
      },
    ]
  }, [
    knowledgeCohortQuery.data?.cohort,
    knowledgeCohortQuery.loading,
    knowledgeCaseLoading,
    knowledgeCasePayload,
    selectedKnowledgePatientUid,
    selectedKnowledgeStudyUid,
    knowledgeStudyLoading,
    knowledgeStudyPayload,
    knowledgeLocalStatus,
  ])
  const uploadHydrationMetrics = useMemo<HydrationMetric[]>(() => {
    return [
      {
        label: "Source",
        value: uploadNifti || uploadSourcePath ? uploadDisplayName : "Attach MRI source",
      },
      {
        label: "Demographics",
        value: uploadAge && uploadSex ? `${uploadAge}y · ${uploadSex}` : "Pending",
      },
      {
        label: "Segmentation",
        value: uploadSeg ? "Uploaded" : segmentationServiceReady ? "Auto segmentation ready" : "Optional",
      },
      {
        label: "Workspace",
        value: analysis.sessionId ? "Hydrated" : analysis.running ? "Preparing" : "Ready to launch",
      },
    ]
  }, [analysis.running, analysis.sessionId, segmentationServiceReady, uploadAge, uploadDisplayName, uploadNifti, uploadSeg, uploadSex, uploadSourcePath])
  const uploadHydrationSteps = useMemo<HydrationStage[]>(() => {
    const sourceReady = Boolean(uploadNifti || uploadSourcePath)
    const demographicsReady = Boolean(uploadAge && uploadSex)
    const segmentationReady = Boolean(uploadSeg || segmentationServiceReady)
    const workspaceReady = Boolean(analysis.sessionId || analysis.report || analysis.viewerAssets)
    const reportReady = Boolean(analysis.sessionId || analysis.progress.some((step) => step.stage === "report" && step.status === "done"))
    return [
      {
        stage: "source",
        label: "Attach source",
        hint: sourceReady ? uploadDisplayName : "Upload a NIfTI file or provide a case path.",
        status: sourceReady ? "done" : "pending",
      },
      {
        stage: "intake",
        label: "Capture intake",
        hint: demographicsReady ? "Age, sex, and case prompt are ready." : "Capture demographics and analysis intent.",
        status: sourceReady && !workspaceReady ? "running" : demographicsReady ? "done" : "pending",
      },
      {
        stage: "segmentation",
        label: "Check segmentation",
        hint: uploadSeg ? "Segmentation file attached." : segmentationServiceCopy,
        status: segmentationServiceQuery.loading ? "running" : segmentationReady ? "done" : "pending",
      },
      {
        stage: "workspace",
        label: "Prepare workspace",
        hint: workspaceReady ? "Viewer assets and report shell are ready." : "Prepare slices, labels, and report context.",
        status: analysis.running ? "running" : workspaceReady ? "done" : sourceReady ? "running" : "pending",
      },
      {
        stage: "report",
        label: "Attach report",
        hint: reportReady ? "Structured output is attached to the session." : "Generate the initial MRI report context.",
        status: analysis.running ? "running" : reportReady ? "done" : "pending",
      },
    ]
  }, [
    uploadNifti,
    uploadSourcePath,
    uploadDisplayName,
    uploadAge,
    uploadSex,
    analysis.sessionId,
    analysis.report,
    analysis.viewerAssets,
    analysis.running,
    analysis.progress,
    uploadSeg,
    segmentationServiceReady,
    segmentationServiceCopy,
    segmentationServiceQuery.loading,
  ])
  const hydrationPanel = useMemo(() => {
    if (sourceType === "knowledge") {
      return (
        <WorkspaceHydrationPanel
          eyebrow="Case Aggregation"
          metrics={knowledgeHydrationMetrics}
          steps={knowledgeHydrationSteps}
          summary="Select a patient and study to load the MR-RATE context and local mirror status. Analysis starts only after you click Analyze Selected MR-RATE Study."
          title={selectedKnowledgePatientUid ? `Knowledge intake for ${selectedKnowledgePatientUid}` : "Knowledge intake"}
        />
      )
    }
    if (sourceType === "upload") {
      return (
        <WorkspaceHydrationPanel
          eyebrow="Case Aggregation"
          metrics={uploadHydrationMetrics}
          steps={uploadHydrationSteps}
          summary="Upload a case, attach segmentation or enable auto-segmentation, then hydrate the viewer, report shell, and follow-up workspace in sequence."
          title={uploadHydrationTitle(uploadDisplayName, Boolean(uploadNifti), uploadSourcePath)}
        />
      )
    }
    return (
      <WorkspaceHydrationPanel
        eyebrow="Case Aggregation"
        metrics={exampleHydrationMetrics}
        steps={exampleHydrationSteps}
        summary="Select a patient to load the full MRI context: study timeline, prior records, viewer assets, segmentation, volumetrics, and the report workspace."
        title={selectedPatientId ? `${patientQuery.data?.patient.name || `Patient ${selectedPatientId}`}` : "Patient library intake"}
      />
    )
  }, [
    sourceType,
    knowledgeHydrationMetrics,
    knowledgeHydrationSteps,
    selectedKnowledgePatientUid,
    uploadHydrationMetrics,
    uploadHydrationSteps,
    uploadDisplayName,
    uploadNifti,
    uploadSourcePath,
    exampleHydrationMetrics,
    exampleHydrationSteps,
    selectedPatientId,
    patientQuery.data?.patient.name,
  ])
  const shouldShowHydrationPanel = Boolean(
    sourceType === "knowledge"
      ? selectedKnowledgePatientUid && selectedKnowledgeStudyUid
      : analysis.running || analysis.sessionId || analysis.report || analysis.viewerAssets,
  )

  useEffect(() => {
    if (!requestedPatientId || selectedPatientId) {
      return
    }
    if (patientsQuery.data?.patients.some((patient) => patient.id === requestedPatientId)) {
      setSelectedPatientId(requestedPatientId)
    }
  }, [patientsQuery.data?.patients, requestedPatientId, selectedPatientId])

  useEffect(() => {
    if (!patientQuery.data) {
      return
    }
    const requestedInPatient = patientQuery.data.studies.find((study) => study.study_id === requestedStudyId)
    if (!selectedStudyId || !patientQuery.data.studies.some((study) => study.study_id === selectedStudyId)) {
      setSelectedStudyId(requestedInPatient?.study_id ?? patientQuery.data.default_study_id)
    }
  }, [patientQuery.data, requestedStudyId, selectedStudyId])

  useEffect(() => {
    if (!["example", "knowledge"].includes(sourceType) || !sortedStructuralPatientStudies.length) {
      setSelectedComparisonStudyIds((current) => (current.length ? [] : current))
      setActiveComparisonStudyId((current) => (current != null ? null : current))
      return
    }
    const nextIds = sortedStructuralPatientStudies.map((study) => study.study_id)
    setSelectedComparisonStudyIds((current) => {
      if (current.length === nextIds.length && current.every((id, index) => id === nextIds[index])) {
        return current
      }
      return nextIds
    })
    const nextActive =
      (sourceType === "example" && selectedStudyId && nextIds.includes(selectedStudyId) ? selectedStudyId : null) ??
      (sourceType === "knowledge" && selectedKnowledgeStudyUid && nextIds.includes(selectedKnowledgeStudyUid) ? selectedKnowledgeStudyUid : null) ??
      nextIds[nextIds.length - 1] ??
      null
    setActiveComparisonStudyId((current) => (current === nextActive ? current : nextActive))
  }, [selectedKnowledgeStudyUid, selectedStudyId, sortedStructuralPatientStudies, sourceType])

  useEffect(() => {
    if (!["example", "knowledge"].includes(sourceType)) {
      return
    }
    const activeStudyId = sourceType === "knowledge" ? selectedKnowledgeStudyUid : selectedStudyId
    if (!activeStudyId || !sortedStructuralPatientStudies.some((study) => study.study_id === activeStudyId)) {
      return
    }
    setActiveComparisonStudyId((current) => (current === activeStudyId ? current : activeStudyId))
    setSelectedComparisonStudyIds((current) =>
      current.includes(activeStudyId) ? current : [...current, activeStudyId],
    )
  }, [selectedKnowledgeStudyUid, selectedStudyId, sortedStructuralPatientStudies, sourceType])

  useEffect(() => {
    if (sourceType !== "example" || !selectedPatientId || !selectedStudyId) {
      setCaseSegmentationState("idle")
      return
    }
    setCaseSegmentationState("checking")
    const timeoutId = window.setTimeout(() => {
      if (segmentationServiceQuery.loading) {
        return
      }
      setCaseSegmentationState(segmentationServiceReady ? "ready" : "unavailable")
    }, 1000)
    return () => window.clearTimeout(timeoutId)
  }, [segmentationServiceQuery.loading, segmentationServiceReady, selectedPatientId, selectedStudyId, sourceType])

  useEffect(() => {
    if (!patientQuery.data?.studies?.length) {
      return
    }
    setSelectedCaseId((current) => {
      if (!current) {
        return current
      }
      const selectedExampleForCase = examplesQuery.data?.examples.find((example) => example.case_id === current) ?? null
      if (!selectedExampleForCase || selectedExampleForCase.patient_id !== selectedPatientId) {
        return null
      }
      return current
    })
  }, [examplesQuery.data?.examples, patientQuery.data?.studies, selectedPatientId])

  useEffect(() => {
    const next = new URLSearchParams(searchParams)
    next.set("source", sourceType)
    next.set("mode", selectedMode)
    const effectiveSessionId =
      sourceType === "knowledge"
        ? selectedKnowledgeStudyUid
          ? analysis.sessionId || knowledgePreviewSessionId
          : null
        : analysis.sessionId && analysis.source === sourceType
          ? analysis.sessionId
          : null
    if (effectiveSessionId) {
      next.set("session_id", effectiveSessionId)
    } else if (sourceType !== "knowledge" && analysis.sessionId && analysis.source === sourceType) {
      next.set("session_id", analysis.sessionId)
    } else if (sourceType !== "knowledge" && requestedSessionId && !analysis.sessionId) {
      next.set("session_id", requestedSessionId)
    } else {
      next.delete("session_id")
    }
    if (sourceType === "example" && selectedPatientId && selectedStudyId) {
      next.set("patient_id", selectedPatientId)
      next.set("study_id", selectedStudyId)
      if (selectedCaseId) {
        next.set("case_id", selectedCaseId)
      } else {
        next.delete("case_id")
      }
      next.delete("knowledge_patient_uid")
      next.delete("knowledge_study_uid")
    } else if (sourceType === "knowledge" && selectedKnowledgePatientUid && selectedKnowledgeStudyUid) {
      next.set("knowledge_patient_uid", selectedKnowledgePatientUid)
      next.set("knowledge_study_uid", selectedKnowledgeStudyUid)
      next.delete("patient_id")
      next.delete("study_id")
      next.delete("case_id")
    } else {
      next.delete("patient_id")
      next.delete("study_id")
      next.delete("case_id")
      next.delete("knowledge_patient_uid")
      next.delete("knowledge_study_uid")
    }
    if (sourceType === "upload" && uploadSourcePath && !analysis.sessionId) {
      next.set("source_path", uploadSourcePath)
    } else {
      next.delete("source_path")
    }
    if (primaryGoalOverride) {
      next.set("goal", primaryGoalOverride)
    } else {
      next.delete("goal")
    }
    if (fromChat) {
      next.set("from", "chat")
    }
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true })
    }
  }, [
    fromChat,
    primaryGoalOverride,
    searchParams,
    selectedCaseId,
    selectedKnowledgePatientUid,
    selectedKnowledgeStudyUid,
    selectedMode,
    selectedPatientId,
    selectedStudyId,
    setSearchParams,
    sourceType,
    uploadSourcePath,
    analysis.sessionId,
    analysis.source,
    knowledgePreviewSessionId,
    requestedSessionId,
  ])

  useEffect(() => {
    setReviewLaneOpen(activePrimaryGoal === "report_review")
  }, [activePrimaryGoal])

  async function handleKnowledgeSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const query = knowledgeSearchQuery.trim()
    if (!query) {
      setKnowledgeSearchResults(null)
      return
    }
    setKnowledgeSearchLoading(true)
    try {
      const payload = await fetchJson<NeuroKnowledgeSearchResponse>(`/api/neuro-knowledge/search?q=${encodeURIComponent(query)}`)
      setKnowledgeSearchResults(payload)
    } catch (error) {
      setKnowledgeSearchResults({
        ok: false,
        query,
        results: [],
      })
      setKnowledgeCaseError(error instanceof Error ? error.message : "MR-RATE search failed")
    } finally {
      setKnowledgeSearchLoading(false)
    }
  }

  function clearKnowledgePreviewState() {
    setKnowledgeStudyPayload(null)
    setKnowledgeLocalStatus(null)
    setKnowledgeLocalStatusError(null)
    setKnowledgePreviewSessionId(null)
    setAnalysis((current) => ({
      ...current,
      running: false,
      error: null,
      progress: [],
      report: "",
      reportSections: null,
      rawSlices: null,
      overlaySlices: null,
      sliceManifest: null,
      sliceSource: null,
      viewerAssets: null,
      volumetrics: null,
      segmentationRegions: null,
      sessionId: null,
      analysisPlan: null,
      analysisPlanSummary: null,
      capabilityProfile: null,
      capabilityProfileSummary: null,
      planningResult: null,
      workspaceContract: null,
      dashboardPayloads: null,
      segmentationBackend: null,
      preprocessingProfile: null,
      csvExportUrl: null,
      labelSource: null,
      labelMappingPath: null,
      labelMappingLabelCount: null,
      labelSchemaVersion: null,
      source: "knowledge",
    }))
  }

  function selectKnowledgeStudy(studyUid: string) {
    setSourceType("knowledge")
    setAnalysisDataSource("mr_rate_knowledge")
    setRequestedKnowledgeStudyUidState(null)
    clearKnowledgePreviewState()
    setSelectedKnowledgeStudyUid(studyUid)
  }

  function selectKnowledgeCase(patientUid: string, studyUid?: string) {
    setSourceType("knowledge")
    setAnalysisDataSource("mr_rate_knowledge")
    setSelectedCaseId(null)
    setSelectedKnowledgePatientUid(patientUid)
    setRequestedKnowledgeStudyUidState(studyUid ?? null)
    setSelectedKnowledgeStudyUid(studyUid ?? "")
    clearKnowledgePreviewState()
  }

  useEffect(() => {
    const nextVisible = overlayModel ? Object.keys(overlayModel.labelById).map((value) => Number(value)) : []
    setVisibleLabelIds(nextVisible)
    setActiveLabelId(null)
    setActiveGroup(null)
    setExpandedGroups(defaultExpandedGroups(overlayModel))
  }, [overlayModel])

  function toggleLabelVisibility(labelId: number) {
    setVisibleLabelIds((current) =>
      current.includes(labelId) ? current.filter((value) => value !== labelId) : [...current, labelId].sort((left, right) => left - right),
    )
  }

  function toggleGroupVisibility(groupId: string) {
    if (!overlayModel) {
      return
    }
    const group = overlayModel.groups.find((item) => item.id === groupId)
    if (!group) {
      return
    }
    const groupIds = group.labels.map((label) => label.labelId)
    setVisibleLabelIds((current) => {
      const visible = new Set(current)
      const allVisible = groupIds.every((labelId) => visible.has(labelId))
      if (allVisible) {
        return current.filter((value) => !groupIds.includes(value))
      }
      return [...new Set([...current, ...groupIds])].sort((left, right) => left - right)
    })
  }

  function toggleGroupExpanded(groupId: string) {
    setExpandedGroups((current) => (current.includes(groupId) ? current.filter((value) => value !== groupId) : [...current, groupId]))
  }

  function selectAllLabels() {
    const nextVisible = overlayModel ? Object.keys(overlayModel.labelById).map((value) => Number(value)) : []
    setVisibleLabelIds(nextVisible)
  }

  function deselectAllLabels() {
    setVisibleLabelIds([])
  }

  function replaceVisibleLabelIds(labelIds: number[]) {
    setVisibleLabelIds([...new Set(labelIds)].sort((left, right) => left - right))
  }

  const trendSeries = useMemo(() => {
    return (
      longitudinalQuery.data?.available_series ??
      displayVolumetrics?.available_series ??
      []
    )
  }, [displayVolumetrics?.available_series, longitudinalQuery.data?.available_series])
  const trendGroups = useMemo(
    () => buildTrendSeriesGroups(trendSeries, displaySegmentationRegions),
    [displaySegmentationRegions, trendSeries],
  )

  const defaultTrendSeries = useMemo(() => {
    return (
      longitudinalQuery.data?.default_series ??
      displayVolumetrics?.default_series ??
      []
    )
  }, [displayVolumetrics?.default_series, longitudinalQuery.data?.default_series])

  useEffect(() => {
    if (!defaultTrendSeries.length) {
      return
    }
    setSelectedTrendSeries((current) => {
      const availableNames = new Set(trendSeries.map((item) => item.name))
      const validCurrent = current.filter((item) => availableNames.has(item))
      return validCurrent.length ? validCurrent : defaultTrendSeries
    })
  }, [defaultTrendSeries, trendSeries])

  useEffect(() => {
    if (uploadSeg) {
      setUploadAutoSegment(false)
      return
    }
    if (!segmentationServiceReady && uploadAutoSegment) {
      setUploadAutoSegment(false)
    }
  }, [segmentationServiceReady, uploadAutoSegment, uploadSeg])

  async function runAnalysis(source: AnalysisSource) {
    let latestVolumetrics: VolumetricsResponse | null = null
    let pendingCompletePayload: Record<string, unknown> | null = null
    let didStreamFail = false
    const startedAt = performance.now()
    const demoProgressPlan = buildDemoProgressPlan(source)
    const minimumDemoDurationMs = demoProgressPlan.reduce((total, step) => total + step.durationMs, 0)
    const demoRunId = demoProgressRunRef.current + 1
    demoProgressRunRef.current = demoRunId
    setAnalysis({
      running: true,
      error: null,
      progress: demoProgressPlan.map(({ durationMs, ...step }) => step),
      report: "",
      reportSections: null,
      rawSlices: null,
      overlaySlices: null,
      sliceManifest: null,
      sliceSource: null,
      viewerAssets: null,
      volumetrics: null,
      segmentationRegions: null,
      sessionId: null,
      analysisPlan: null,
      analysisPlanSummary: null,
      capabilityProfile: null,
      capabilityProfileSummary: null,
      planningResult: null,
      workspaceContract: null,
      requestedMode: selectedMode,
      executedMode: null,
      dashboardPayloads: null,
      segmentationBackend: null,
      preprocessingProfile: null,
      csvExportUrl: null,
      labelSource: null,
      labelMappingPath: null,
      labelMappingLabelCount: null,
      labelSchemaVersion: null,
      source,
    })

    void (async () => {
      for (let index = 0; index < demoProgressPlan.length; index += 1) {
        if (demoProgressRunRef.current !== demoRunId) {
          return
        }
        setAnalysis((current) => ({
          ...current,
          progress: current.progress.map((step, stepIndex) => {
            if (stepIndex < index) {
              return { ...step, status: "done" }
            }
            if (stepIndex === index) {
              return { ...step, status: "running" }
            }
            return step
          }),
        }))
        const isLastStep = index === demoProgressPlan.length - 1
        if (isLastStep) {
          return
        }
        await wait(demoProgressPlan[index].durationMs)
      }
    })()

    const stopDemoProgress = () => {
      if (demoProgressRunRef.current === demoRunId) {
        demoProgressRunRef.current = demoRunId + 1
      }
    }

    const formData = new FormData()
    formData.append("mode", selectedMode)

    if (source === "example") {
      if (!selectedPatientId || !selectedStudyId) {
        stopDemoProgress()
        setAnalysis((current) => ({ ...current, running: false, error: "Pick a study before analyzing." }))
        return
      }
      formData.append("patient_id", selectedPatientId)
      formData.append("study_id", selectedStudyId)
      formData.append("request_text", selectedExample?.analysis_plan?.requested_goal || selectedExample?.description || "Analyze this MRI study.")
      if (selectedCaseId || selectedExample?.case_id) {
        formData.append("case_id", selectedCaseId ?? selectedExample!.case_id)
      }
      if (!exampleHasNativeSegmentation && segmentationServiceReady) {
        formData.append("auto_segment", "true")
        formData.append("segmentation_backend", "structural_segmenter")
      }
    } else if (source === "knowledge") {
      if (!selectedKnowledgePatientUid || !selectedKnowledgeStudyUid) {
        stopDemoProgress()
        setAnalysis((current) => ({ ...current, running: false, error: "Pick an MR-RATE study before analyzing." }))
        return
      }
      const effectiveKnowledgeSessionId = analysis.sessionId || knowledgePreviewSessionId || requestedSessionId
      if (effectiveKnowledgeSessionId) {
        formData.append("session_id", effectiveKnowledgeSessionId)
      }
      formData.append("knowledge_launch_patient_uid", selectedKnowledgePatientUid)
      formData.append("knowledge_launch_study_uid", selectedKnowledgeStudyUid)
      formData.append(
        "request_text",
        knowledgeStudyPayload?.summary?.summary_text ||
          knowledgeStudyPayload?.report?.impression ||
          "Analyze this MR-RATE MRI study.",
      )
      if (!knowledgeHasNativeSegmentation && segmentationServiceReady) {
        formData.append("auto_segment", "true")
        formData.append("segmentation_backend", "structural_segmenter")
      }
    } else {
      if (!uploadNifti && !uploadSourcePath) {
        stopDemoProgress()
        setAnalysis((current) => ({ ...current, running: false, error: "Upload a NIfTI file to continue." }))
        return
      }
      if (uploadAge.trim()) {
        formData.append("age", uploadAge)
      }
      if (uploadSex.trim()) {
        formData.append("sex", uploadSex)
      }
      formData.append("indication", uploadIndication)
      formData.append("request_text", uploadIndication || "Analyze this uploaded brain MRI.")
      if (uploadSourcePath) {
        formData.append("source_path", uploadSourcePath)
      }
      if (uploadNifti) {
        formData.append("nifti_file", uploadNifti)
      }
      if (uploadSeg) {
        formData.append("seg_file", uploadSeg)
      } else if (uploadAutoSegment && segmentationServiceReady) {
        formData.append("auto_segment", "true")
        formData.append("segmentation_backend", "structural_segmenter")
      }
    }

    try {
      const response = await fetch("/api/demo/neuro-report/analyze", {
        method: "POST",
        body: formData,
      })

      const applyCompletion = async (payload: Record<string, unknown>) => {
        const elapsed = performance.now() - startedAt
        if (elapsed < minimumDemoDurationMs) {
          await wait(minimumDemoDurationMs - elapsed)
        }

        demoProgressRunRef.current = demoRunId
        setAnalysis((current) => {
          return {
            ...current,
            progress: current.progress.map((step) => ({ ...step, status: "done" })),
          }
        })

        const report = String(payload.report ?? "")
        const reportSections = (payload.report_sections as ReportSections | null) ?? null
        const sessionId = String(payload.session_id ?? "")
        const patientId =
          (payload.patient_id as string | null) ??
          (source === "knowledge" ? selectedKnowledgePatientUid : selectedPatientId)
        const studyId =
          (payload.study_id as string | null) ??
          (source === "knowledge" ? selectedKnowledgeStudyUid : selectedStudyId)
        const viewerAssets = (payload.viewer_assets as ViewerAssets | null) ?? null
        const segmentationRegions = (payload.segmentation_regions as Region[] | null) ?? (latestVolumetrics?.regions ?? null)
        const analysisPlan = (payload.analysis_plan as AnalysisPlan | null) ?? null
        const analysisPlanSummary = (payload.analysis_plan_summary as AnalysisPlanSummary | null) ?? null
        const capabilityProfile = (payload.capability_profile as CapabilityProfile | null) ?? null
        const capabilityProfileSummary = (payload.capability_profile_summary as CapabilityProfileSummary | null) ?? null
        const dashboardPayloads = (payload.dashboard_payloads as DashboardPayloads | null) ?? null
        const planningResult = (payload.planning_result as PlanningResult | null) ?? null
        const workspaceContract = (payload.workspace_contract as WorkspaceContract | null) ?? null
        const executedMode = (payload.mode as AnalysisMode | null) ?? selectedMode
        const requestedMode = (payload.requested_mode as AnalysisMode | null) ?? selectedMode
        const csvExportUrl = (payload.csv_export_url as string | null) ?? (latestVolumetrics?.csv_export_url ?? null)
        const segmentationBackend = (payload.segmentation_backend as string | null) ?? (latestVolumetrics?.segmentation_backend ?? null)
        const preprocessingProfile = (payload.preprocessing_profile as string | null) ?? (latestVolumetrics?.preprocessing_profile ?? null)
        const labelSource = (payload.label_source as AnalysisState["labelSource"]) ?? (latestVolumetrics?.label_source ?? null)
        const labelMappingPath =
          (payload.label_mapping_path as string | null) ??
          ((payload.label_schema_path as string | null) ?? latestVolumetrics?.label_mapping_path ?? latestVolumetrics?.label_schema_path ?? null)
        const labelMappingLabelCount =
          (payload.label_mapping_label_count as number | null) ?? (latestVolumetrics?.label_mapping_label_count ?? null)
        const labelSchemaVersion =
          (payload.label_schema_version as string | null) ?? (latestVolumetrics?.label_schema_version ?? null)
        const sliceManifest = (payload.slice_manifest as SliceManifest | null) ?? null
        const sliceSource = (payload.slice_source as "on_demand" | "sampled" | null) ?? null
        setAnalysis((current) => ({
          ...current,
          running: false,
          report,
          reportSections,
          sessionId,
          viewerAssets,
          segmentationRegions,
          analysisPlan,
          analysisPlanSummary,
          capabilityProfile,
          capabilityProfileSummary,
          planningResult,
          workspaceContract,
          dashboardPayloads,
          requestedMode,
          executedMode,
          segmentationBackend,
          preprocessingProfile,
          csvExportUrl,
          labelSource,
          labelMappingPath,
          labelMappingLabelCount,
          labelSchemaVersion,
          sliceManifest,
          sliceSource,
        }))

        const artifact = {
          title: "Neuro MRI Report",
          subtitle: patientId && studyId ? `${patientId} · ${studyId}` : "Uploaded MRI study",
          riskLevel: summarizeRisk(latestVolumetrics) as "low" | "moderate" | "high" | "critical",
          metrics: [
            { label: "Goal", value: planningResult?.primary_goal ?? analysisPlan?.primary_goal ?? "structural_report" },
            { label: "Track", value: analysisPlanSummary?.track ?? analysisPlan?.analysis_track ?? "structural" },
            { label: "Dashboard", value: analysisPlanSummary?.dashboard_profile ?? analysisPlan?.dashboard_profile ?? "volumetry" },
            { label: "Patient", value: patientId || "Upload" },
            { label: "Study", value: studyId || "Uploaded" },
            { label: "Mode", value: MODE_META[selectedMode].label },
          ],
          reportPreview: reportPreviewText(reportSections, report),
          qaStatus: { privacy: true, terminology: true, completeness: true },
          claimsSummary: latestVolumetrics?.summary || analysisPlan?.handoff_summary || "Structured MRI report generated with the specialized neuro workspace.",
          planSummary: analysisPlanSummary?.summary || analysisPlan?.handoff_summary,
          missingInputs: analysisPlanSummary?.missing_info ?? analysisPlan?.missing_inputs ?? [],
          allowedAnalyses: analysisPlan?.allowed_analyses ?? [],
          capabilityStatus: analysisPlanSummary?.detected_inputs ?? capabilityProfile?.available_inputs ?? [],
          availableData: (planningResult?.available_data as string[] | undefined) ?? capabilityProfile?.available_inputs ?? [],
          intent: typeof planningResult?.intent === "string" ? planningResult.intent : undefined,
          recommendedNextAction:
            typeof planningResult?.recommended_next_action === "string" ? planningResult.recommended_next_action : undefined,
          executionReadiness:
            typeof planningResult?.can_execute === "boolean" ? (planningResult.can_execute ? "ready" : "intake_only") : undefined,
          viewerType:
            (analysisPlanSummary?.viewer_type as "dicomweb" | "nifti" | "png_fallback" | undefined) ??
            (viewerAssets?.viewer_type as "dicomweb" | "nifti" | "png_fallback" | undefined),
          workspaceUrl:
            source === "upload" || source === "knowledge"
              ? `/demo/analysis/neuro-report?source=${source}&session_id=${sessionId}&mode=${executedMode || selectedMode}&goal=${planningResult?.primary_goal || analysisPlan?.primary_goal || "structural_report"}&from=chat`
              : `/demo/analysis/neuro-report?patient_id=${patientId || ""}&study_id=${studyId || ""}&mode=${executedMode || selectedMode}&goal=${planningResult?.primary_goal || analysisPlan?.primary_goal || "structural_report"}&from=chat`,
        }
        if (source === "knowledge") {
          setKnowledgePreviewSessionId(sessionId)
        }
        const summaryMessage: ChatMessage = {
          type: "text",
          role: "assistant",
          content: `MRI report completed for ${artifact.subtitle}. ${analysisPlan?.handoff_summary || "Open the workspace to inspect slices, volumetrics, and the structured report."}`,
        }
        chat.appendMessages([{ type: "run_result", artifact }, summaryMessage])
      }

      await consumeSse(response, (eventName, payload) => {
        if (eventName === "progress") {
          return
        }
        if (eventName === "slices") {
          setAnalysis((current) => ({
            ...current,
            rawSlices: (payload.raw as SlicePlaneSet | null) ?? null,
            overlaySlices: (payload.overlay as SlicePlaneSet | null) ?? null,
            sliceManifest: (payload.manifest as SliceManifest | null) ?? null,
            sliceSource: (payload.source as "on_demand" | "sampled" | null) ?? null,
          }))
          return
        }
        if (eventName === "volumetrics") {
          latestVolumetrics = payload as unknown as VolumetricsResponse
          setAnalysis((current) => ({ ...current, volumetrics: latestVolumetrics }))
          return
        }
        if (eventName === "report_chunk") {
          setAnalysis((current) => ({
            ...current,
            report: String(payload.content ?? current.report),
          }))
          return
        }
        if (eventName === "complete") {
          pendingCompletePayload = payload
          return
        }
        if (eventName === "error") {
          didStreamFail = true
          stopDemoProgress()
          setAnalysis((current) => ({
            ...current,
            running: false,
            error: String(payload.error ?? "Analysis failed."),
          }))
        }
      })
      if (pendingCompletePayload && !didStreamFail) {
        await applyCompletion(pendingCompletePayload)
      }
    } catch (error) {
      stopDemoProgress()
      setAnalysis((current) => ({
        ...current,
        running: false,
        error: error instanceof Error ? error.message : "Analysis failed.",
      }))
    }
  }

  function handleChatSubmit() {
    if (!composerHasText || chat.streaming) {
      return
    }
    const nextMessage = uploadIndication.trim()
    setUploadIndication("")
    void chat.sendMessage(nextMessage)
  }

  const trendData = useMemo(() => {
    return (longitudinalQuery.data?.series ?? []).map((point) => {
      const row: Record<string, string | number | null> = {
        date: formatShortDate(String(point.study_date)),
        studyId: String(point.study_id),
      }
      for (const regionName of longitudinalQuery.data?.region_names ?? []) {
        const { valueKey, deltaKey } = trendValueKeys(regionName)
        row[valueKey] = (point as Record<string, string | number | null>)[valueKey] ?? null
        row[deltaKey] = (point as Record<string, string | number | null>)[deltaKey] ?? null
      }
      return row
    })
  }, [longitudinalQuery.data?.region_names, longitudinalQuery.data?.series])

  const filteredTrendData = useMemo(() => {
    if (!selectedComparisonStudyIds.length) {
      return trendData
    }
    return trendData.filter((point) => selectedComparisonStudyIds.includes(String(point.studyId ?? "")))
  }, [selectedComparisonStudyIds, trendData])

  const filteredHeatmap = useMemo(() => {
    if (!heatmapQuery.data || !selectedComparisonStudyIds.length) {
      return heatmapQuery.data
    }
    const selectedDateSet = new Set(
      (longitudinalQuery.data?.series ?? [])
        .filter((point) => selectedComparisonStudyIds.includes(String(point.study_id ?? "")))
        .map((point) => String(point.study_date ?? "")),
    )
    const selectedIndices = heatmapQuery.data.dates
      .map((date, index) => (selectedDateSet.has(date) ? index : -1))
      .filter((index) => index >= 0)
    if (!selectedIndices.length || selectedIndices.length === heatmapQuery.data.dates.length) {
      return heatmapQuery.data
    }
    return {
      ...heatmapQuery.data,
      dates: selectedIndices.map((index) => heatmapQuery.data!.dates[index]),
      matrix: Object.fromEntries(
        Object.entries(heatmapQuery.data.matrix).map(([regionName, cells]) => [
          regionName,
          selectedIndices.map((index) => cells[index] ?? { z_score: null, volume_mm3: null }),
        ]),
      ),
    }
  }, [heatmapQuery.data, longitudinalQuery.data?.series, selectedComparisonStudyIds])

  const comparisonMetrics = useMemo(() => {
    if (!baselineComparisonStudy || !activeComparisonStudyId) {
      return []
    }
    const baselineRow = filteredTrendData.find((point) => String(point.studyId ?? "") === baselineComparisonStudy.study_id)
    const activeRow = filteredTrendData.find((point) => String(point.studyId ?? "") === activeComparisonStudyId)
    if (!baselineRow || !activeRow) {
      return []
    }
    return selectedTrendSeries
      .map((seriesName) => trendSeries.find((series) => series.name === seriesName) ?? null)
      .filter((series): series is TrendSeriesMeta => series != null)
      .slice(0, 3)
      .flatMap((series) => {
        const { valueKey } = trendValueKeys(series.name)
        const baselineValue = baselineRow[valueKey]
        const activeValue = activeRow[valueKey]
        if (typeof baselineValue !== "number" || typeof activeValue !== "number") {
          return []
        }
        const delta = activeValue - baselineValue
        const percentDelta = baselineValue !== 0 ? (delta / baselineValue) * 100 : null
        const unit = formatTrendUnit(series)
        return [
          {
            id: series.name,
            label: series.display_name,
            value: `${formatCompareValue(baselineValue, unit)} → ${formatCompareValue(activeValue, unit)}`,
            delta: `${delta > 0 ? "+" : ""}${formatCompareValue(delta, unit)} · ${formatPercentDelta(percentDelta)}`,
          },
        ]
      })
  }, [activeComparisonStudyId, baselineComparisonStudy, filteredTrendData, selectedTrendSeries, trendSeries])

  function activateComparisonStudy(study: PatientStudy) {
    setActiveComparisonStudyId(study.study_id)
    if (sourceType === "knowledge") {
      selectKnowledgeStudy(study.study_id)
    } else {
      setSourceType("example")
      setSelectedStudyId(study.study_id)
      setSelectedCaseId(null)
    }
    setPrimaryGoalOverride(null)
    if (study.supported_modes.length && !study.supported_modes.includes(selectedMode)) {
      setSelectedMode(study.supported_modes[0])
    }
  }

  function toggleComparisonStudy(study: PatientStudy) {
    setSelectedComparisonStudyIds((current) => {
      const sortedIds = sortStudiesByDate(structuralPatientStudies).map((item) => item.study_id)
      const isSelected = current.includes(study.study_id)
      if (isSelected) {
        if (current.length <= 1) {
          return current
        }
        const next = current.filter((id) => id !== study.study_id)
        if (activeComparisonStudyId === study.study_id) {
          const nextActive = [...sortedIds].reverse().find((id) => next.includes(id)) ?? next[0] ?? null
          setActiveComparisonStudyId(nextActive)
          if (nextActive) {
            const nextStudy = structuralPatientStudies.find((item) => item.study_id === nextActive)
            if (nextStudy) {
              activateComparisonStudy(nextStudy)
            }
          }
        }
        return next
      }
      const next = [...current, study.study_id]
      const nextSorted = sortedIds.filter((id) => next.includes(id))
      setActiveComparisonStudyId(study.study_id)
      return nextSorted
    })
  }

  const segmentationWorkspace = (
    <StructuralDashboard
      activeGroup={activeGroup}
      activeLabelId={activeLabelId}
      csvExportUrl={structuralCsvExportUrl}
      currentCaseId={sourceType === "example" ? selectedExample?.case_id ?? selectedCaseId : null}
      expandedGroups={expandedGroups}
      hasSessionLongitudinalContext={hasSessionLongitudinalContext}
      heatmap={null}
      highlights={structuralHighlights}
      onSelectStudy={activateComparisonStudy}
      onSelectGroup={(groupId) => {
        setActiveGroup(groupId)
        setActiveLabelId(null)
      }}
      onSelectLabel={(labelId) => {
        setActiveLabelId(labelId)
        setActiveGroup(null)
      }}
      overlaySlices={displayOverlaySlices}
      sliceManifest={displaySliceManifest}
      sliceRequest={structuralSliceRequest}
      overlayModel={overlayModel}
      onToggleGroupExpanded={toggleGroupExpanded}
      onToggleGroupVisibility={toggleGroupVisibility}
      onToggleLabelVisibility={toggleLabelVisibility}
      onSelectAllLabels={selectAllLabels}
      onDeselectAllLabels={deselectAllLabels}
      onReplaceVisibleLabelIds={replaceVisibleLabelIds}
      patientLabel={sessionPatientLabel}
      patientStudies={structuralPatientStudies}
      report={displayReport}
      reportSections={displaySections}
      review={activeReviewPayload}
      selectedTrendSeries={selectedTrendSeries}
      selectedComparisonStudyIds={selectedComparisonStudyIds}
      selectedStudyId={structuralSelectedStudyId}
      selectedStudySummary={structuralSelectedStudySummary}
      activeComparisonStudyId={activeComparisonStudyId}
      baselineStudyId={baselineComparisonStudy?.study_id ?? null}
      latestComparisonStudyId={latestComparisonStudy?.study_id ?? null}
      onToggleComparisonStudy={toggleComparisonStudy}
      onActivateComparisonStudy={activateComparisonStudy}
      comparisonMetrics={comparisonMetrics}
      setSelectedTrendSeries={setSelectedTrendSeries}
      setShowOverlay={setShowOverlay}
      setViewerMode={setViewerMode}
      showOverlay={showOverlay}
      slices={displaySlices}
      trendData={[]}
      trendGroups={trendGroups}
      trendSeries={trendSeries}
      viewerAssets={displayViewerAssets}
      viewerMode={viewerMode}
      visibleLabelIds={visibleLabelIds}
      volumetrics={displayVolumetrics}
      segmentationLabelMappingPath={displayLabelMappingPath}
      segmentationLabelSourceLabel={segmentationLabelSourceLabel}
      showTrendSection={false}
    />
  )

  const reportWorkspace = activePrimaryGoal === "report_review" && activeReviewPayload ? (
    <ReviewTrackDashboard
        activeGroup={activeGroup}
        activeLabelId={activeLabelId}
        currentCaseId={sourceType === "example" ? selectedExample?.case_id ?? selectedCaseId : null}
        expandedGroups={expandedGroups}
        onSelectGroup={(groupId) => {
          setActiveGroup(groupId)
          setActiveLabelId(null)
        }}
        onSelectLabel={(labelId) => {
          setActiveLabelId(labelId)
          setActiveGroup(null)
        }}
        onToggleGroupExpanded={toggleGroupExpanded}
        onToggleGroupVisibility={toggleGroupVisibility}
        onToggleLabelVisibility={toggleLabelVisibility}
        onSelectAllLabels={selectAllLabels}
        onDeselectAllLabels={deselectAllLabels}
        onReplaceVisibleLabelIds={replaceVisibleLabelIds}
        overlayModel={overlayModel}
        overlaySlices={displayOverlaySlices}
        onSelectStudy={(study) => {
          setSourceType("example")
          setSelectedStudyId(study.study_id)
          setSelectedCaseId(null)
          setPrimaryGoalOverride(null)
          if (study.supported_modes.length && !study.supported_modes.includes(selectedMode)) {
            setSelectedMode(study.supported_modes[0])
          }
        }}
        patientStudies={patientStudies}
        report={displayReport}
        reportSections={displaySections}
        review={activeReviewPayload}
        selectedStudyId={selectedStudyId}
        selectedStudySummary={selectedStudySummary}
        segmentationLabelMappingPath={displayLabelMappingPath}
        segmentationLabelSourceLabel={segmentationLabelSourceLabel}
        setShowOverlay={setShowOverlay}
        setViewerMode={setViewerMode}
        showOverlay={showOverlay}
        slices={displaySlices}
        viewerMode={viewerMode}
        viewerAssets={displayViewerAssets}
        visibleLabelIds={visibleLabelIds}
      />
    ) : (
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
      <ClinicalDraftPanel
        report={displayReport}
        reportSections={displaySections}
        review={activeReviewPayload}
        volumetrics={displayVolumetrics}
      />
      <div className="space-y-4">
        <ReviewLane onToggle={() => setReviewLaneOpen(!reviewLaneOpen)} open={reviewLaneOpen} review={activeReviewPayload} />
        <VolumetricsPanel volumetrics={displayVolumetrics} />
      </div>
    </div>
  )

  const adaptiveWorkspace =
    activeWorkspaceTab === "overview" ? (
      <NeuroOverviewTab
        patientLabel={sessionPatientLabel}
        selectedStudySummary={structuralSelectedStudySummary}
        patientStudies={structuralPatientStudies}
        capabilitySummary={displayCapabilitySummary}
        analysisPlan={displayAnalysisPlan}
        planningResult={displayPlanningResult}
        segmentationReady={Boolean(displayVolumetrics || displaySegmentationRegions?.length)}
        trendReady={hasSessionLongitudinalContext}
        alignmentReady={Boolean(hasSessionLongitudinalContext && structuralPatientStudies.length > 1)}
        onSelectTab={selectWorkspaceTab}
      />
    ) : activeWorkspaceTab === "segmentation" ? (
      segmentationWorkspace
    ) : activeWorkspaceTab === "alignment" ? (
      <NeuroAlignmentTab
        patientId={sourceType === "example" ? selectedPatientId : sourceType === "knowledge" ? selectedKnowledgePatientUid : null}
        patientStudies={structuralPatientStudies}
        selectedStudyId={structuralSelectedStudyId}
        baselineStudyId={baselineComparisonStudy?.study_id ?? sortedStructuralPatientStudies[0]?.study_id ?? null}
        latestStudyId={latestComparisonStudy?.study_id ?? sortedStructuralPatientStudies[sortedStructuralPatientStudies.length - 1]?.study_id ?? null}
      />
    ) : activeWorkspaceTab === "trend" ? (
      activePrimaryGoal === "response_review" && activeResponsePayload ? (
        <ResponseDashboard
          response={activeResponsePayload}
          trendData={filteredTrendData}
          trendGroups={trendGroups}
          trendSeries={trendSeries}
          selectedTrendSeries={selectedTrendSeries}
          setSelectedTrendSeries={setSelectedTrendSeries}
          volumetrics={displayVolumetrics}
          review={activeReviewPayload}
          reviewLaneOpen={reviewLaneOpen}
          setReviewLaneOpen={setReviewLaneOpen}
        />
      ) : (
        <NeuroTrendTab
          patientLabel={sessionPatientLabel}
          patientStudies={structuralPatientStudies}
          selectedComparisonStudyIds={selectedComparisonStudyIds}
          activeComparisonStudyId={activeComparisonStudyId}
          baselineStudyId={baselineComparisonStudy?.study_id ?? null}
          latestComparisonStudyId={latestComparisonStudy?.study_id ?? null}
          trendSeries={trendSeries}
          trendGroups={trendGroups}
          selectedTrendSeries={selectedTrendSeries}
          setSelectedTrendSeries={setSelectedTrendSeries}
          trendData={hasSessionLongitudinalContext ? filteredTrendData : []}
          hasSessionLongitudinalContext={hasSessionLongitudinalContext}
          comparisonMetrics={comparisonMetrics}
          highlights={structuralHighlights}
          heatmap={hasSessionLongitudinalContext ? filteredHeatmap : null}
        />
      )
    ) : (
      reportWorkspace
    )
  const shouldShowAnalysisWorkspace =
    sourceType !== "knowledge" ||
    Boolean(selectedKnowledgeStudyUid)
  const knowledgeCasePickerPanel = sourceType === "knowledge" ? (
    <KnowledgeDemoCasePicker
      assets={selectedKnowledgeAssets}
      caseError={knowledgeCaseError}
      caseLoading={knowledgeCaseLoading}
      cohort={rankedKnowledgeCohort}
      cohortError={knowledgeCohortQuery.error}
      cohortLoading={knowledgeCohortQuery.loading}
      filter={knowledgeCaseFilter}
      filteredCohort={filteredKnowledgeCohort}
      localStatus={knowledgeLocalStatus}
      localStatusError={knowledgeLocalStatusError}
      onFilterChange={setKnowledgeCaseFilter}
      onQueryChange={setKnowledgeCasePickerQuery}
      onSelectCase={selectKnowledgeCase}
      onUseStudy={selectKnowledgeStudy}
      query={knowledgeCasePickerQuery}
      segmentationStatus={sourceSegmentationState}
      selectedEntry={currentKnowledgeCohortEntry}
      selectedPatientUid={selectedKnowledgePatientUid}
      selectedStudyUid={selectedKnowledgeStudyUid}
      selectedSummary={selectedKnowledgeSummary}
      studies={knowledgeStudyRows}
      studyError={knowledgeStudyError}
      studyLoading={knowledgeStudyLoading}
    />
  ) : null

  return (
    <div className="min-w-0 space-y-6">
      <section className="overflow-hidden rounded-[1.5rem] border border-[hsl(var(--border))] bg-[linear-gradient(135deg,hsl(var(--card)),hsl(var(--background)))]">
        <div className="px-6 py-6">
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-3">
              <div className="inline-flex items-center gap-2 rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--background)/0.7)] px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">
                <Brain className="size-3.5" />
                Neuro MRI
              </div>
            </div>
            <div className="max-w-3xl space-y-3">
              <h1 className="text-[30px] font-medium tracking-[-0.05em] text-[hsl(var(--foreground))]">
                Neuro MRI Report Generator
              </h1>
              <p className="max-w-2xl text-[15px] leading-7 text-[hsl(var(--muted-foreground))]">
                Analyze a single MRI study, inspect slices and measurements, and review longitudinal context in one workspace.
              </p>
            </div>

            {shouldShowHydrationPanel ? hydrationPanel : null}

            {sourceType === "knowledge" && selectedKnowledgePatientUid && selectedKnowledgeStudyUid ? (
              <div className="rounded-[1.15rem] border border-[hsl(var(--primary)/0.18)] bg-[hsl(var(--primary)/0.07)] px-4 py-3 text-[13px] leading-6 text-[hsl(var(--foreground))]">
                {`Loaded Case ${selectedKnowledgePatientUid} · Study ${selectedKnowledgeStudyUid}. Review the context, then click Analyze when you want to start the MR-RATE analysis.`}
              </div>
            ) : null}

            <div className="min-w-0">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start">
                <div className="max-w-2xl space-y-1">
                  <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">
                    <MessageSquare className="size-3.5" />
                    Shared Home chat
                  </div>
                  <p className="text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
                    {sourceType === "knowledge"
                      ? selectedKnowledgePatientUid && selectedKnowledgeStudyUid
                        ? "MR-RATE knowledge context is loaded. You can ask questions first, then click Analyze when you want to run the MRI workflow."
                        : "Choose an MR-RATE case below, then select a study before running the MRI workflow."
                      : "Start from a case in the patient library below or upload MRI files here. Analysis summaries and follow-up answers will keep appending to the shared Home chat history."}
                  </p>
                </div>

                <div className="grid w-full gap-2 sm:grid-cols-[5.25rem_5.25rem_minmax(12rem,14rem)] lg:ml-auto lg:w-auto">
                  <label className="flex h-14 flex-col justify-center rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-[12px]">
                    <div className="mb-1 text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Age</div>
                    <input
                      autoComplete="off"
                      className="w-full bg-transparent outline-none"
                      name="age"
                      onChange={(event) => setUploadAge(event.target.value)}
                      value={uploadAge}
                    />
                  </label>

                  <label className="flex h-14 flex-col justify-center rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-[12px]">
                    <div className="mb-1 text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Sex</div>
                    <select
                      autoComplete="off"
                      className="w-full bg-transparent outline-none"
                      name="sex"
                      onChange={(event) => setUploadSex(event.target.value)}
                      value={uploadSex}
                    >
                      <option value="M">M</option>
                      <option value="F">F</option>
                    </select>
                  </label>

                  <div className="min-w-0">
                    <Select
                      onValueChange={(value) => {
                        const next = value as "curated_examples" | "uploaded_files" | "mr_rate_knowledge"
                        setAnalysisDataSource(next)
                        if (next === "uploaded_files") {
                          setSourceType("upload")
                        }
                        if (next === "curated_examples") {
                          setSourceType("example")
                        }
                        if (next === "mr_rate_knowledge") {
                          setSourceType("knowledge")
                        }
                      }}
                      value={analysisDataSource}
                    >
                      <SelectTrigger className="h-14 rounded-xl bg-[hsl(var(--background))] text-[13px] shadow-none">
                        <SelectValue placeholder="Analysis data" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          <SelectLabel>Analysis data</SelectLabel>
                          <SelectItem value="curated_examples">Patient library</SelectItem>
                          <SelectItem value="uploaded_files">Upload files</SelectItem>
                          <SelectItem value="mr_rate_knowledge">MR-RATE knowledge</SelectItem>
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>

              <input
                className="hidden"
                onChange={(event) => {
                  setSourceType("upload")
                  setAnalysisDataSource("uploaded_files")
                  setUploadNifti(event.target.files?.[0] ?? null)
                  setUploadSourcePath("")
                }}
                ref={uploadNiftiInputRef}
                type="file"
              />
              <input
                className="hidden"
                onChange={(event) => {
                  setSourceType("upload")
                  setAnalysisDataSource("uploaded_files")
                  setUploadSeg(event.target.files?.[0] ?? null)
                }}
                ref={uploadSegInputRef}
                type="file"
              />

              <div className="mt-4 min-w-0 rounded-[1.9rem] border border-[hsl(var(--border)/0.78)] bg-[hsl(var(--background)/0.97)] p-4 shadow-[0_16px_42px_-28px_rgba(15,23,42,0.22)] ring-1 ring-[hsl(var(--background))]">
                <div className="flex min-h-[31rem] min-w-0 flex-col gap-4">
                  {!sharedChatPreview.length ? (
                    <div className="flex min-h-[21rem] flex-1 items-center justify-center bg-[radial-gradient(circle_at_top,hsl(var(--primary)/0.08),transparent_52%),transparent] px-6 py-8">
                      <div className="flex w-full max-w-[40rem] flex-col items-center gap-3 text-center">
                        <div className="-my-[20px] flex justify-center sm:-my-[24px]">
                          <img
                            alt="ClinAgent logo mark"
                            className="h-[160px] w-auto scale-[1.06] object-contain opacity-95"
                            src={neuroReportLogoMarkSrc}
                          />
                        </div>
                        <div className="grid w-full gap-2.5 md:grid-cols-2">
                          {suggestedPrompts.map((prompt, index) => (
                            <Button
                              className={cn(
                                "h-auto min-h-[66px] w-full justify-start rounded-[1.6rem] border-[hsl(var(--border)/0.58)] bg-[hsl(var(--background)/0.78)] px-4 py-3 text-left text-[13px] leading-6 whitespace-normal text-[hsl(var(--muted-foreground))] shadow-none transition-[transform,border-color,background-color,box-shadow,color] duration-200 ease-out hover:-translate-y-0.5 hover:border-[hsl(var(--primary)/0.42)] hover:bg-[hsl(var(--background)/0.96)] hover:text-[hsl(var(--foreground))] hover:shadow-[0_18px_40px_-30px_hsl(var(--primary)/0.3)]",
                                index === 0 ? "md:col-span-2" : "",
                              )}
                              key={prompt}
                              onClick={() => setUploadIndication(prompt)}
                              type="button"
                              variant="outline"
                            >
                              {prompt}
                            </Button>
                          ))}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="flex min-h-[22rem] flex-1 min-w-0 flex-col gap-3 overflow-y-auto pr-1">
                      {sharedChatPreview.map((message, index) => (
                        <div className={cn("flex min-w-0", message.role === "user" ? "justify-end" : "justify-start")} key={`${message.role}-${index}`}>
                          <div
                            className={cn(
                              "max-w-[92%] rounded-[1.15rem] px-3.5 py-2.5 text-[13px] leading-6 [overflow-wrap:anywhere]",
                              message.role === "user"
                                ? "bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--foreground))]"
                                : "border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[hsl(var(--foreground))]",
                            )}
                          >
                            {message.role === "user" ? (
                              message.content
                            ) : (
                              <MarkdownContent className="text-[13px] leading-6" content={message.content} />
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="mt-auto rounded-[1.65rem] border border-[hsl(var(--border)/0.9)] bg-[hsl(var(--background))] px-4 py-3 shadow-[0_12px_28px_-20px_rgba(15,23,42,0.2)]">
                    <textarea
                      className="min-h-[46px] w-full resize-none bg-transparent text-[14px] leading-6 text-[hsl(var(--foreground))] outline-none placeholder:text-[hsl(var(--muted-foreground))]"
                      onChange={(event) => setUploadIndication(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && !event.shiftKey) {
                          event.preventDefault()
                          handleChatSubmit()
                        }
                      }}
                      placeholder="Ask anything about the case, request an analysis, or describe what to prioritize…"
                      value={uploadIndication}
                    />

                    <div className="mt-4 flex flex-wrap items-end gap-2">
                      <Button
                        className="h-9 max-w-full rounded-full px-2.5 text-[12px] text-[hsl(var(--muted-foreground))] shadow-none"
                        onClick={() => uploadNiftiInputRef.current?.click()}
                        type="button"
                        variant="ghost"
                      >
                        <Upload data-icon="inline-start" />
                        <span className="truncate">{uploadDisplayName}</span>
                      </Button>

                      <Button
                        className="h-9 max-w-full rounded-full px-2.5 text-[12px] text-[hsl(var(--muted-foreground))] shadow-none"
                        onClick={() => uploadSegInputRef.current?.click()}
                        type="button"
                        variant="ghost"
                      >
                        <Upload data-icon="inline-start" />
                        <span className="truncate">{uploadSeg ? uploadSeg.name : "Segmentation files"}</span>
                      </Button>

                      <div className="ml-auto flex items-center gap-2">
                        {sourceType === "example" && caseSegmentationState !== "idle" ? (
                          <SegmentationReadyPill
                            label={sourceSegmentationState.label}
                            loading={sourceSegmentationState.loading}
                            tone={sourceSegmentationState.tone}
                          />
                        ) : null}
                        <Button
                          className="h-10 rounded-full px-4 text-[13px]"
                          disabled={!composerHasText || chat.streaming}
                          onClick={handleChatSubmit}
                          type="button"
                          variant="outline"
                        >
                          {chat.streaming ? <Loader2 className="animate-spin" data-icon="inline-start" /> : <Send data-icon="inline-start" />}
                          {chat.streaming ? "Chatting…" : "Chat"}
                        </Button>
                        <Button
                          className="h-10 rounded-full px-4 text-[13px]"
                          disabled={!canAnalyzeCurrent || analysis.running}
                          onClick={() => void runAnalysis(sourceType)}
                          type="button"
                        >
                          {analysis.running ? <Loader2 className="animate-spin" data-icon="inline-start" /> : <Activity data-icon="inline-start" />}
                          {analysis.running ? "Analyzing…" : "Analyze"}
                        </Button>
                      </div>
                    </div>
                    {chat.latestError ? (
                      <div aria-live="polite" className="mt-2 text-[12px] leading-6 text-destructive [overflow-wrap:anywhere]">
                        {chat.latestError}
                      </div>
                    ) : chat.streaming ? (
                      <div aria-live="polite" className="mt-2 text-[12px] leading-6 text-[hsl(var(--muted-foreground))]">
                        ClinAgent is thinking…
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            </div>

            {knowledgeCasePickerPanel}
          </div>
        </div>
      </section>

      {sourceType === "upload" ? (
        <div className="px-1 text-[12px] leading-6 text-[hsl(var(--muted-foreground))] [overflow-wrap:anywhere]">
          {!uploadSeg
            ? `Use deployed structure segmenter to do own segmentation. ${segmentationServiceCopy}`
            : "Uploaded segmentation file attached."}
        </div>
      ) : null}

      {sourceType === "example" ? (
        <section className="min-w-0 space-y-4">
          <div className="grid min-w-0 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
            {curatedPatientGroups.map((group) => (
              <CaseCard
                group={group}
                key={group.patientId}
                onSelect={() => {
                  const example = group.representative
                  setSourceType("example")
                  setAnalysisDataSource("curated_examples")
                  setSelectedPatientId(example.patient_id)
                  setSelectedStudyId(example.study_id)
                  setSelectedCaseId(example.case_id)
                  if (!MODE_META[selectedMode] || !example.supported_modes.includes(selectedMode)) {
                    setSelectedMode(example.default_mode)
                  }
                }}
                selected={selectedPatientId === group.patientId && sourceType === "example"}
              />
            ))}
          </div>
          {selectedExample ? <SelectedCaseDetailStrip example={selectedExample} /> : null}
        </section>
      ) : null}

      {false ? (
        <section className="grid min-w-0 gap-4 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <div className="min-w-0 rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">
            <Database className="size-3.5" />
            MR-RATE Knowledge
          </div>
          <div className="mt-2 text-[15px] font-medium text-[hsl(var(--foreground))]">Select a mirrored MR-RATE study</div>
          <p className="mt-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
            This lane reads knowledge metadata first, then checks your local MR-RATE mirror before analysis.
          </p>

          <form className="mt-4 flex gap-2" onSubmit={(event) => void handleKnowledgeSearchSubmit(event)}>
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
              <input
                className="w-full rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] py-2 pl-9 pr-3 text-[13px] outline-none"
                onChange={(event) => setKnowledgeSearchQuery(event.target.value)}
                placeholder="Search MR-RATE reports"
                value={knowledgeSearchQuery}
              />
            </div>
            <Button disabled={knowledgeSearchLoading} type="submit" variant="outline">
              {knowledgeSearchLoading ? "Searching…" : "Search"}
            </Button>
          </form>

          {knowledgeSearchResults?.results?.length ? (
            <div className="mt-3 max-h-44 space-y-2 overflow-y-auto">
              {(knowledgeSearchResults?.results ?? []).slice(0, 6).map((result, index) => (
                <button
                  className="w-full rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-left text-[12px] transition-colors hover:border-[hsl(var(--primary)/0.35)]"
                  key={`${result.patient_uid}-${result.study_uid ?? index}`}
                  onClick={() => selectKnowledgeCase(result.patient_uid, result.study_uid)}
                  type="button"
                >
                  <div className="font-medium text-[hsl(var(--foreground))]">
                    Case {result.patient_uid}{result.study_uid ? ` · ${result.study_uid}` : ""}
                  </div>
                  <div className="mt-1 text-[hsl(var(--muted-foreground))]">{result.snippet || result.summary_text || "Open this study in the MR-RATE lane."}</div>
                </button>
              ))}
            </div>
          ) : null}

          <div className="mt-4 max-h-[28rem] space-y-2 overflow-y-auto">
            {(knowledgeCohortQuery.data?.cohort ?? []).map((entry) => (
              <button
                className={cn(
                  "w-full rounded-xl border px-3 py-3 text-left transition-colors",
                  entry.patient_uid === selectedKnowledgePatientUid
                    ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.08)]"
                    : "border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:border-[hsl(var(--primary)/0.25)]",
                )}
                key={entry.patient_uid}
                onClick={() => selectKnowledgeCase(entry.patient_uid)}
                type="button"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium text-[hsl(var(--foreground))]">Case {entry.patient_uid}</span>
                  <span className="text-[11px] text-[hsl(var(--muted-foreground))]">#{entry.cohort_rank ?? "—"}</span>
                </div>
                <div className="mt-2 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">
                  {entry.summary_text || entry.selection_reason || "No summary available."}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="min-w-0 rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Selected MR-RATE case</div>
              <div className="mt-1 text-[18px] font-medium text-[hsl(var(--foreground))]">
                {selectedKnowledgePatientUid ? `Case ${selectedKnowledgePatientUid}` : "Choose a case"}
              </div>
              <div className="mt-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
                {selectedKnowledgeSummary?.summary_text || currentKnowledgeCohortEntry?.summary_text || "Select a cohort case or a search hit to inspect MR-RATE study metadata."}
              </div>
            </div>
            <div className="space-y-2 text-right">
              <Badge className="rounded-full px-4 py-1.5 text-[12px] font-medium" variant="outline">
                {knowledgeLocalStatusLabel(knowledgeLocalStatus)}
              </Badge>
              {knowledgeLocalStatusError ? (
                <div className="text-[12px] text-destructive">{knowledgeLocalStatusError}</div>
              ) : null}
              {selectedKnowledgePatientUid && selectedKnowledgeStudyUid ? (
                <div className="max-w-[24rem] rounded-2xl border border-[hsl(var(--primary)/0.18)] bg-[hsl(var(--primary)/0.07)] px-3 py-2 text-left text-[12px] leading-5 text-[hsl(var(--foreground))]">
                  {`Loaded Case ${selectedKnowledgePatientUid} · Study ${selectedKnowledgeStudyUid}. Review the metadata, then click Analyze Selected MR-RATE Study to start analysis.`}
                </div>
              ) : null}
              <div className="flex flex-wrap items-center justify-end gap-2">
                <SegmentationReadyPill
                  className="shrink-0"
                  label={
                    selectedKnowledgePatientUid && selectedKnowledgeStudyUid
                      ? sourceSegmentationState.label
                      : "Auto segmentation"
                  }
                  loading={Boolean(selectedKnowledgePatientUid && selectedKnowledgeStudyUid && sourceSegmentationState.loading)}
                  tone={selectedKnowledgePatientUid && selectedKnowledgeStudyUid ? sourceSegmentationState.tone : "neutral"}
                />
                <Button
                  className="rounded-full px-4"
                  disabled={!selectedKnowledgePatientUid || !selectedKnowledgeStudyUid || analysis.running}
                  onClick={() => {
                    setSourceType("knowledge")
                    setAnalysisDataSource("mr_rate_knowledge")
                    void runAnalysis("knowledge")
                  }}
                  size="lg"
                  type="button"
                >
                  {analysis.running && sourceType === "knowledge" ? "Analyzing…" : "Analyze Selected MR-RATE Study"}
                </Button>
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <div className="space-y-3">
              <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Studies</div>
              <div className="max-h-72 space-y-2 overflow-y-auto">
                {knowledgeCaseLoading ? (
                  <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-3 text-[12px] text-[hsl(var(--muted-foreground))]">
                    Loading MR-RATE case…
                  </div>
                ) : null}
                {knowledgeCaseError ? (
                  <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-3 text-[12px] text-rose-200">
                    {knowledgeCaseError}
                  </div>
                ) : null}
                {knowledgeStudyRows.map((study) => (
                  <button
                    className={cn(
                      "w-full rounded-xl border px-3 py-3 text-left transition-colors",
                      study.study_uid === selectedKnowledgeStudyUid
                        ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.08)]"
                        : "border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:border-[hsl(var(--primary)/0.25)]",
                    )}
                    key={study.study_uid}
                    onClick={() => selectKnowledgeStudy(study.study_uid)}
                    type="button"
                  >
                    <div className="font-medium text-[hsl(var(--foreground))]">{study.study_uid}</div>
                    <div className="mt-1 text-[12px] text-[hsl(var(--muted-foreground))]">
                      {study.anon_study_date || "Unknown date"} · report {study.report_available ? "available" : "missing"}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-3">
              <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Study detail</div>
              <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
                <div className="text-[15px] font-medium text-[hsl(var(--foreground))]">
                  {selectedKnowledgeStudyUid || "No study selected"}
                </div>
                <div className="mt-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
                  {knowledgeStudyPayload?.summary?.summary_text || "Choose a study to inspect its report and mirror status."}
                </div>
                {knowledgeStudyError ? (
                  <div className="mt-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-3 text-[12px] text-rose-200">
                    {knowledgeStudyError}
                  </div>
                ) : null}
                {knowledgeStudyLoading ? (
                  <div className="mt-3 text-[12px] text-[hsl(var(--muted-foreground))]">Loading study detail…</div>
                ) : null}
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-[hsl(var(--border))] px-3 py-3 text-[12px] text-[hsl(var(--muted-foreground))]">
                    <div className="text-[11px] uppercase tracking-[0.14em]">Report impression</div>
                    <div className="mt-2 text-[hsl(var(--foreground))]">
                      {knowledgeStudyPayload?.report?.impression || "No impression indexed."}
                    </div>
                  </div>
                  <div className="rounded-xl border border-[hsl(var(--border))] px-3 py-3 text-[12px] text-[hsl(var(--muted-foreground))]">
                    <div className="text-[11px] uppercase tracking-[0.14em]">Assets</div>
                    <div className="mt-2 text-[hsl(var(--foreground))]">
                      {selectedKnowledgeAssets.filter((asset) => asset.study_uid === selectedKnowledgeStudyUid).map((asset) => asset.asset_kind).join(", ") || "No assets indexed."}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        </section>
      ) : null}

      {shouldShowAnalysisWorkspace ? (
        <>
          <ProgressRail steps={analysis.progress} />

          <AnalysisSummaryBar
            capabilitySummary={displayCapabilitySummary}
            plan={displayAnalysisPlan}
            planningResult={displayPlanningResult}
            workspaceContract={displayWorkspaceContract}
            activePrimaryGoal={activePrimaryGoal}
            plannerPrimaryGoal={plannerPrimaryGoal}
            setActivePrimaryGoal={setPrimaryGoalOverride}
            summary={displayAnalysisPlanSummary}
          />

          <NeuroWorkspaceTabNav activeTab={activeWorkspaceTab} onSelectTab={selectWorkspaceTab} />

          {analysis.error ? (
            <div className="rounded-[1.25rem] border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-[13px] text-rose-200">
              {analysis.error}
            </div>
          ) : null}

          <div
            aria-labelledby={`neuro-workspace-tab-${activeWorkspaceTab}`}
            id={`neuro-workspace-panel-${activeWorkspaceTab}`}
            role="tabpanel"
          >
            {adaptiveWorkspace}
          </div>
        </>
      ) : null}
    </div>
  )
}
