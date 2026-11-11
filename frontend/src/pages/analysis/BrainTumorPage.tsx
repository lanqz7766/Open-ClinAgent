import type { ComponentType, DragEvent as ReactDragEvent, KeyboardEvent, ReactNode } from "react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  ArrowUp,
  ArrowDown,
  Brain,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clipboard,
  Database,
  Download,
  Eye,
  FileText,
  FileUp,
  FolderOpen,
  HardDrive,
  Layers,
  Loader2,
  Minus,
  Pin,
  Play,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Trash2,
  Wand2,
  X,
  XCircle,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { CornerstoneStructuralViewer } from "@/components/CornerstoneStructuralViewer"
import type { ViewerPanelConfig } from "@/components/CornerstoneStructuralViewer"
import { HoldToViewMriButton } from "@/components/HoldToViewMriButton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useApi } from "@/hooks/useApi"
import { useAuth } from "@/lib/auth"
import type { ViewerMode } from "@/lib/segmentationOverlay"
import { cn } from "@/lib/utils"
import { beginCaseReview, isRegistered, registrationLabel } from "./brainTumor.provenance"
import { readUploadJob, sendUpload } from "./brainTumor.upload"
import type { ArchiveProgress } from "./brainTumor.archive"
import { emptyVisitDraft, groupVisitFiles, uploadCasePoints, validateVisitDrafts } from "./brainTumor.visitUpload"
import type { UploadVisitDraft } from "./brainTumor.visitUpload"
import { PreviewFeedback, UploadExamples } from "./PreviewSupport"
import { BrainTumorAlignment } from "./BrainTumorAlignment"
import { VisitTimingSummary } from "./VisitTimingSummary"
import { TumorTrendChart } from "./TumorTrendChart"
import "./brainTumor.workspace.css"
import {
  defaultTumorLabelIds, modalityMeta, modalityOrder, qcReasonOptions,
  regionLabels, requiredModalities, tumorPalette,
} from "./brainTumor.constants"
import type {
  BrainTumorReportDraftResponse, DicomSeries, DicomStudy, InputMode,
  LongitudinalAlignJob, LongitudinalPoint, LongitudinalRow, ModalityKey,
  MountedDicomStatus, PreloadExample, PreloadExampleMeta, QcReasonKey,
  RegistryCase, RegistrySegmentJob, ReviewState, ServiceStatus, TimepointRole,
  TumorSession, UploadedCase, UploadInferenceRow, UploadSegmentJob, WorkflowStatus,
} from "./brainTumor.types"
import { formatDay, timelineScale, visitDisplayLabel, visitTimeLabel, visitTimeDetail, visitTimingLabel, visitIntervalValues } from "./brainTumor.timing.ts"
import {
  buildVisitTimingText, activePointImpression, activePointReport, buildActiveArtifactUrls,
  buildGbmTumorOverlayModel, buildLongitudinalRows, buildMeasurementsCsv,
  buildReportExportText, buildReportFigureSvg, buildReportHtml, buildReportPayload,
  buildRunSegmentationHint, buildWorkflowSteps, changeTone, downloadTextFile,
  formatCompactMm3, formatMm3, formatMm3Number, formatPct,
  inferModalityFromFileName, isNiftiFileName, qcReasonLabel, reviewStateLabel,
  safeFilePart, toAbsoluteAssetUrl,
} from "./brainTumor.logic"

const delay = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

type BrainTumorWorkspaceTab = "review" | "longitudinal" | "report"

const brainTumorWorkspaceTabs: Array<{
  id: BrainTumorWorkspaceTab
  label: string
  description: string
  icon: ComponentType<{ className?: string; strokeWidth?: number }>
}> = [
  { id: "review", label: "Review", description: "MRI viewer, model mask, and QC decision", icon: Eye },
  { id: "longitudinal", label: "Longitudinal", description: "Visit selection, alignment, and volume change", icon: Layers },
  { id: "report", label: "Report", description: "Findings, impression, provenance, and export", icon: FileText },
]

const workflowStageIcons: Record<string, ComponentType<{ className?: string; strokeWidth?: number }>> = {
  Intake: FolderOpen,
  Map: Layers,
  "QC gate": CheckCircle2,
  Segment: Brain,
  Review: Eye,
  Handoff: FileUp,
}

function segmentStageLabel(stage?: RegistrySegmentJob["stage"] | UploadSegmentJob["stage"]): string {
  if (stage === "starting" || stage === "preparing") return "Preparing model inputs"
  if (stage === "segmenting") return "Running model segmentation"
  if (stage === "materializing") return "Saving the new result"
  if (stage === "finalizing") return "Finalizing measurements"
  return "Segmentation queued"
}

async function fetchSvgAssetDataUrl(url: string, viewBox?: string): Promise<string> {
  const response = await fetch(url, { cache: "force-cache" })
  if (!response.ok) throw new Error(`Failed to load ${url}`)
  let svg = await response.text()
  if (viewBox) {
    svg = svg.replace(/viewBox="[^"]+"/, `viewBox="${viewBox}"`)
  }
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

type PanelOverlay = "off" | "fill" | "outline"
type ReviewPanel = { id: string; modality: ModalityKey; overlay: PanelOverlay; overlayBeforeOff?: PanelOverlay }
type PanelPresetKey = "pair" | "five"
type ComparisonPlane = "axial" | "coronal" | "sagittal"

// Layout presets are named by what the physician sees, not by panel count.
const PANEL_PRESETS: Record<PanelPresetKey, { label: string; description: string; panels: Array<Pick<ReviewPanel, "modality" | "overlay">> }> = {
  pair: {
    label: "T1c + FLAIR",
    description: "Contrast T1 and FLAIR side by side, both with the tumor mask",
    panels: [{ modality: "t1c", overlay: "fill" }, { modality: "t2f", overlay: "fill" }],
  },
  five: {
    label: "T1 · T1c · FLAIR + outlines",
    description: "T1, T1c, T1c with the tumor outlined, FLAIR, FLAIR with the tumor outlined",
    panels: [
      { modality: "t1n", overlay: "off" },
      { modality: "t1c", overlay: "off" },
      { modality: "t1c", overlay: "outline" },
      { modality: "t2f", overlay: "off" },
      { modality: "t2f", overlay: "outline" },
    ],
  },
}
const MAX_REVIEW_PANELS = 6

function presetPanels(key: PanelPresetKey): ReviewPanel[] {
  return PANEL_PRESETS[key].panels.map((panel, index) => ({ id: `p${index + 1}`, ...panel }))
}

function matchesPreset(panels: ReviewPanel[], key: PanelPresetKey) {
  const preset = PANEL_PRESETS[key].panels
  return panels.length === preset.length && panels.every((panel, index) => panel.modality === preset[index].modality && panel.overlay === preset[index].overlay)
}

export function BrainTumorPage() {
  const auth = useAuth()
  const service = useApi<ServiceStatus>("/api/demo/brain-tumor/service")
  const mountStatus = useApi<MountedDicomStatus>("/api/demo/brain-tumor/dicom-mount/status")
  const [inputMode, setInputMode] = useState<InputMode>("mount")
  const [patientQuery, setPatientQuery] = useState("")
  const [accessionQuery, setAccessionQuery] = useState("")
  const [patientLabel, setPatientLabel] = useState("")
  const [studies, setStudies] = useState<DicomStudy[]>([])
  const [series, setSeries] = useState<DicomSeries[]>([])
  const [selectedStudyUid, setSelectedStudyUid] = useState("")
  const [mapping, setMapping] = useState<Partial<Record<ModalityKey, string>>>({})
  const [files, setFiles] = useState<Partial<Record<ModalityKey, File>>>({})
  const [uploadInferenceRows, setUploadInferenceRows] = useState<UploadInferenceRow[]>([])
  const [archiveProgress, setArchiveProgress] = useState<ArchiveProgress | null>(null)
  const archiveRequestRef = useRef<AbortController | null>(null)
  const preparingArchive = archiveProgress !== null && archiveProgress.phase !== "ready"
  const [loadingStudies, setLoadingStudies] = useState(false)
  const [loadingSeries, setLoadingSeries] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [session, setSession] = useState<TumorSession | null>(null)
  const [activeModality, setActiveModality] = useState<ModalityKey>("t2f")
  const [reviewPanels, setReviewPanels] = useState<ReviewPanel[]>(() => presetPanels("pair"))
  const nextPanelIdRef = useRef(100)
  const reviewPanelKey = reviewPanels.map((panel) => `${panel.id}:${panel.modality}:${panel.overlay}`).join("|")
  const [overlayOpacity, setOverlayOpacity] = useState(82)
  const [reviewState, setReviewState] = useState<ReviewState>("pending")
  const [qcReasonsByPoint, setQcReasonsByPoint] = useState<Record<string, QcReasonKey[]>>({})
  const [generatedReportText, setGeneratedReportText] = useState("")
  const [reportDraftSource, setReportDraftSource] = useState<"none" | "local" | "ai">("none")
  const [draftingReport, setDraftingReport] = useState(false)
  const [reportError, setReportError] = useState<string | null>(null)
  const reportRequestRef = useRef<AbortController | null>(null)
  const [timepointRole, setTimepointRole] = useState<TimepointRole>("pre_treatment_baseline")
  const [timepointDate, setTimepointDate] = useState("")
  const [longitudinalPoints, setLongitudinalPoints] = useState<LongitudinalPoint[]>([])
  const [baselinePointId, setBaselinePointId] = useState("")
  const [activePointId, setActivePointId] = useState("")
  const [registeringPointId, setRegisteringPointId] = useState("")
  const [registrationError, setRegistrationError] = useState<string | null>(null)
  const [demoTimelineLoaded, setDemoTimelineLoaded] = useState(false)
  const [preloadSourceNote, setPreloadSourceNote] = useState("")
  const [preloadExampleMeta, setPreloadExampleMeta] = useState<PreloadExampleMeta | null>(null)
  const [preloadExamples, setPreloadExamples] = useState<PreloadExample[]>([])
  const [activePreloadExampleId, setActivePreloadExampleId] = useState("")
  const [segmentationReadyByPoint, setSegmentationReadyByPoint] = useState<Record<string, boolean>>({})
  const [loadingPreload, setLoadingPreload] = useState(false)
  const [registryCases, setRegistryCases] = useState<RegistryCase[]>([])
  const [registryNote, setRegistryNote] = useState("")
  const [loadingRegistry, setLoadingRegistry] = useState(false)
  const [runningRegistryCaseId, setRunningRegistryCaseId] = useState("")
  const [activeRegistryCaseId, setActiveRegistryCaseId] = useState("")
  const registrySelectionRef = useRef("")
  const [segmentJob, setSegmentJob] = useState<RegistrySegmentJob | null>(null)
  const [segmentResumeChecked, setSegmentResumeChecked] = useState(false)
  const [uploadedCases, setUploadedCases] = useState<UploadedCase[]>([])
  const uploadCaseRef = useRef<UploadedCase | null>(null)
  const [uploadsLoaded, setUploadsLoaded] = useState(false)
  const [selectedUploadCaseId, setSelectedUploadCaseId] = useState("")
  const uploadSelectionRef = useRef(new URLSearchParams(window.location.search).get("upload") ?? "")
  const [uploadPanelOpen, setUploadPanelOpen] = useState(false)
  const [uploadingCase, setUploadingCase] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadReconnecting, setUploadReconnecting] = useState(false)
  const uploadPolls = useRef(new Map<string, AbortController>())
  const [uploadJob, setUploadJob] = useState<UploadSegmentJob | null>(null)
  const [uploadResumeChecked, setUploadResumeChecked] = useState(false)
  const [uploadResumeComplete, setUploadResumeComplete] = useState(false)
  const [, setDeidentifiedConfirmed] = useState(false)
  const [alignJob, setAlignJob] = useState<LongitudinalAlignJob | null>(null)
  const [aligningAll, setAligningAll] = useState(false)
  const [biasCorrection, setBiasCorrection] = useState(false)
  const [alignmentDisplay, setAlignmentDisplay] = useState<"original" | "aligned">("original")
  const alignmentRequestRef = useRef<AbortController | null>(null)
  const alignmentPanelRef = useRef<HTMLDivElement | null>(null)
  const [showVolumeOverlay, setShowVolumeOverlay] = useState(true)
  const [showViewerOptions, setShowViewerOptions] = useState(false)
  const [maskSource, setMaskSource] = useState<"model" | "gt">("model")
  const [activeWorkspaceTab, setActiveWorkspaceTab] = useState<BrainTumorWorkspaceTab>("review")
  const [volumeViewerMode, setVolumeViewerMode] = useState<ViewerMode>("blend")
  const [reviewPlane, setReviewPlane] = useState<ComparisonPlane | "mpr">("mpr")
  const [comparisonPlane, setComparisonPlane] = useState<ComparisonPlane>("axial")
  const [previewOriginal, setPreviewOriginal] = useState(false)
  const [visibleTumorLabelIds, setVisibleTumorLabelIds] = useState(defaultTumorLabelIds)
  const [activeTumorLabelId, setActiveTumorLabelId] = useState<number | null>(null)
  const [activeTumorGroup, setActiveTumorGroup] = useState<string | null>(null)
  const [expandedTumorGroups, setExpandedTumorGroups] = useState<string[]>(["rano_target", "flair_context", "treatment_anatomy", "research_labels"])
  const [volumeViewerError, setVolumeViewerError] = useState<string | null>(null)
  const physicianCuratedOnly = auth.physician_curated_only || Boolean(service.data?.physician_curated_only)

  const hasRequired = useMemo(() => {
    if (inputMode === "dicomweb" || inputMode === "mount") {
      return Boolean(mapping.t1c && mapping.t2f && mapping.t2w && mapping.t1n)
    }
    return Boolean(files.t1c && files.t2f && files.t2w && files.t1n)
  }, [files.t1c, files.t1n, files.t2f, files.t2w, inputMode, mapping.t1c, mapping.t1n, mapping.t2f, mapping.t2w])

  const intakeReady = inputMode === "upload" ? Boolean(files.t1c || files.t2f) : Boolean(selectedStudyUid)
  const selectedStudy = studies.find((study) => study.study_instance_uid === selectedStudyUid)
  const displayModel = session?.service.model_id || service.data?.model_info?.model_id || service.data?.model_id || "GlioMODA"
  const requiredReadyCount = requiredModalities.filter((key) =>
    inputMode === "upload" ? Boolean(files[key]) : Boolean(mapping[key]),
  ).length
  const samePatientLongitudinal = preloadExampleMeta?.samePatientLongitudinal ?? true
  const baselinePoint = longitudinalPoints.find((point) => point.id === baselinePointId) ?? longitudinalPoints[0]
  const longitudinalRows = useMemo(
    () => buildLongitudinalRows(longitudinalPoints, baselinePoint?.id ?? "", samePatientLongitudinal),
    [baselinePoint?.id, longitudinalPoints, samePatientLongitudinal],
  )
  const activePoint = longitudinalRows.find((point) => point.id === activePointId) ?? longitudinalRows[0]
  const activeIsPreloadPoint = Boolean(activePreloadExampleId && activePoint)
  const activeHasSegmentationArtifact = Boolean(activePoint ? activePoint.segmentationUrl : session?.viewer_assets?.segmentation_url)
  const activeSegmentationReady = Boolean(activePoint || session) && (
    Boolean(session && !activePoint) ||
    Boolean(activePoint?.id && segmentationReadyByPoint[activePoint.id]) ||
    activeHasSegmentationArtifact
  )
  const hasGroundTruthMask = Boolean(activePoint?.groundTruthSegmentationUrl)
  const rawActiveOverlayUrl =
    maskSource === "gt" && activePoint?.groundTruthOverlayUrl
      ? activePoint.groundTruthOverlayUrl
      : activePoint ? activePoint.modalityPreviewUrls?.[activeModality] ?? activePoint.overlayUrl : session?.viewer_assets?.overlay_preview_url
  const activeOverlayUrl = activeSegmentationReady ? rawActiveOverlayUrl : undefined
  const activeRegistration = activePoint?.registration?.baseline_session_id === baselinePoint?.sessionId
    ? activePoint?.registration : undefined
  const showingAligned = alignmentDisplay === "aligned" && Boolean(activeRegistration?.modality_volume_urls?.[activeModality])
  const activeVolumeUrl = showingAligned
    ? activeRegistration?.modality_volume_urls?.[activeModality]
    : activePoint?.modalityVolumeUrls?.[activeModality]
  // Every comparison panel must share one space, so a sequence missing from the
  // aligned set falls back to the active volume instead of mixing spaces.
  const resolveModalityVolumeUrl = (modality: ModalityKey) => (showingAligned
    ? activeRegistration?.modality_volume_urls?.[modality]
    : activePoint?.modalityVolumeUrls?.[modality]) ?? activeVolumeUrl
  const availableModalities = useMemo(
    () => modalityOrder.filter((key) => Boolean(activePoint?.modalityVolumeUrls?.[key])),
    [activePoint?.modalityVolumeUrls],
  )
  const rawActiveSegmentationUrl =
    maskSource === "gt" && activePoint?.groundTruthSegmentationUrl
      ? activePoint.groundTruthSegmentationUrl
      : activePoint ? activePoint.segmentationUrl : session?.viewer_assets?.segmentation_url
  const activeSegmentationUrl = activeSegmentationReady
    ? showingAligned
      ? maskSource === "gt" ? activeRegistration?.ground_truth_segmentation_url : activeRegistration?.segmentation_url
      : rawActiveSegmentationUrl
    : undefined
  const activeVolumeAssetUrl = useMemo(() => toAbsoluteAssetUrl(activeVolumeUrl), [activeVolumeUrl])
  const activeSegmentationAssetUrl = useMemo(() => toAbsoluteAssetUrl(activeSegmentationUrl), [activeSegmentationUrl])
  const activeVolumes = activePoint?.volumes ?? session?.volumes ?? []
  const tumorOverlayModel = useMemo(() => activeSegmentationReady ? buildGbmTumorOverlayModel(activeVolumes) : null, [activeSegmentationReady, activeVolumes])
  const activeLabel = activePoint?.label || session?.patient_label || selectedStudy?.description || patientLabel || "No case loaded"
  const activeDate = activePoint ? visitTimeLabel(activePoint) : selectedStudy?.study_date || "No date"
  const activeSessionId = activePoint ? activePoint.sessionId : session?.session_id || ""
  useEffect(() => {
    setAlignmentDisplay("original")
  }, [activeSessionId, baselinePoint?.sessionId])
  const alignmentCaseKey = longitudinalPoints.map((point) => point.sessionId).join("|")
  useEffect(() => () => {
    alignmentRequestRef.current?.abort()
    alignmentRequestRef.current = null
  }, [alignmentCaseKey, baselinePoint?.sessionId])
  const activeReviewState = activePoint?.reviewState ?? reviewState
  const activeQcReasons = qcReasonsByPoint[activePoint?.id || activeSessionId || "current"] ?? []
  const reportContextKey = JSON.stringify([activeSessionId, activePoint, longitudinalRows, session?.volumes, baselinePointId, activeReviewState, activeQcReasons])

  useEffect(() => {
    setGeneratedReportText("")
    setReportDraftSource("none")
    setReportError(null)
    setDraftingReport(false)
    return () => {
      reportRequestRef.current?.abort()
      reportRequestRef.current = null
    }
  }, [reportContextKey])
  const activeWarnings = activePoint?.registration?.warnings ?? session?.qc?.warnings ?? []
  const activeArtifactUrls = buildActiveArtifactUrls(activePoint, session)
  const hasLoadedCase = Boolean(activePoint || session)
  const latestPoint = longitudinalRows[longitudinalRows.length - 1]
  const baselineReady = Boolean(baselinePoint)
  const registrationRequired = samePatientLongitudinal && longitudinalRows.length > 1
  const registrationComplete = registrationRequired
    ? Boolean(longitudinalRows.length && longitudinalRows.every((point) => point.id === baselinePoint?.id || isRegistered(point.registration)))
    : false
  const reportEligible = hasLoadedCase && activeSegmentationReady && activeReviewState === "accepted"
  const activeMaskSourceLabel = maskSource === "gt" ? "Reference label" : "Model prediction"
  const activeMaskSourceDetail = maskSource === "gt"
    ? "Reference overlay. Measurements and reports remain model-derived."
    : "Model overlay. Measurements and reports are model-derived."
  const canLoadPrecomputedSegmentation = Boolean(activeIsPreloadPoint && activePoint?.segmentationUrl && activePoint?.modalityVolumeUrls)
  const segmentJobRunning = segmentJob?.status === "queued" || segmentJob?.status === "running"
  const displayedUploadedCases = useMemo(
    () => uploadedCases.map((item) => uploadJob?.case_id === item.id ? { ...item, job: uploadJob } : item),
    [uploadJob, uploadedCases],
  )
  const activeUploadCase = displayedUploadedCases.find((item) => item.id === selectedUploadCaseId)
  const activeUploadJob = activeUploadCase?.job ?? null
  const uploadJobRunning = activeUploadJob?.status === "queued" || activeUploadJob?.status === "running"
  const segmentationJobRunning = segmentJobRunning || uploadJobRunning
  const segmentProgressTotal = uploadJobRunning ? (activeUploadJob?.total_count ?? 1) : (segmentJob?.total_count ?? longitudinalRows.length)
  const segmentProgressCompleted = uploadJobRunning
    ? (activeUploadJob?.completed_count ?? 0)
    : (segmentJob?.completed_count ?? longitudinalRows.filter((point) => segmentationReadyByPoint[point.id]).length)
  const segmentProgressPct = segmentProgressTotal ? Math.min(100, Math.round((segmentProgressCompleted / segmentProgressTotal) * 100)) : 0
  const alignmentProgressTotal = longitudinalRows.length
  const alignmentProgressCompleted = samePatientLongitudinal
    ? longitudinalRows.filter((point) => point.id === baselinePoint?.id || isRegistered(point.registration)).length
    : longitudinalRows.length
  const canRunRegistrySegmentation = Boolean(activeRegistryCaseId && longitudinalPoints.length && !segmentJobRunning)
  const canRunSegmentation = !selectedUploadCaseId && !running && (canRunRegistrySegmentation || canLoadPrecomputedSegmentation || hasRequired)
  const runSegmentationHint = canLoadPrecomputedSegmentation
    ? "Open the segmentation mask and label controls for this visit."
    : activeRegistryCaseId
      ? "Run model segmentation for the loaded registry visits."
    : buildRunSegmentationHint(inputMode, hasRequired, hasLoadedCase)
  const canUseVolumeViewer = Boolean(activeVolumeAssetUrl && !volumeViewerError)
  const canReview = activeSegmentationReady && Boolean(activeVolumeUrl || activeOverlayUrl)
  const workflowIntakeReady = intakeReady || Boolean(activePoint)
  const workflowInputsReady = hasRequired || Boolean(activePoint)
  const workflowSteps = buildWorkflowSteps({
    canReview,
    hasRequired: workflowInputsReady,
    intakeReady: workflowIntakeReady,
    reviewState: activeReviewState,
    running: running || segmentationJobRunning,
    serviceReady: Boolean(service.data?.ready),
    sessionComplete: activeSegmentationReady,
  })

  useEffect(() => {
    if (physicianCuratedOnly) {
      setDemoTimelineLoaded(true)
      return
    }
    if (demoTimelineLoaded) return
    void loadPreloadTimeline()
  }, [demoTimelineLoaded, physicianCuratedOnly])

  useEffect(() => {
    void loadRegistryCases()
    void loadUploadedCases()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => () => {
    archiveRequestRef.current?.abort()
    uploadPolls.current.forEach((controller) => controller.abort())
    uploadPolls.current.clear()
  }, [])

  useEffect(() => {
    if (uploadResumeChecked || !uploadsLoaded) return
    setUploadResumeChecked(true)
    if (uploadSelectionRef.current) {
      const saved = uploadedCases.find((item) => item.id === uploadSelectionRef.current)
      if (saved) {
        openUploadedCase(saved)
        if (saved.job?.status === "queued" || saved.job?.status === "running") {
          void pollUploadJob(saved.job.job_id).catch((err) => setRegistrationError(String(err)))
        }
      } else {
        setRegistrationError("The selected upload is no longer available. Choose another case.")
      }
      setUploadResumeComplete(true)
      return
    }
    void resumeUploadJob().finally(() => setUploadResumeComplete(true))
  }, [uploadResumeChecked, uploadsLoaded, uploadedCases])

  useEffect(() => {
    if (uploadSelectionRef.current || registrySelectionRef.current || !physicianCuratedOnly || !uploadResumeComplete || segmentResumeChecked || loadingRegistry || !registryCases.length) return
    setSegmentResumeChecked(true)
    void openInitialRegistryCase()
  }, [loadingRegistry, physicianCuratedOnly, registryCases.length, segmentResumeChecked, uploadResumeComplete])

  useEffect(() => {
    setVolumeViewerError(null)
  }, [activeModality, reviewPanelKey, activePoint?.id, showingAligned])

  const handleVolumeViewerError = useCallback((message: string) => {
    if (showingAligned) {
      setAlignmentDisplay("original")
      setRegistrationError("The aligned image could not be displayed. Restored the original image.")
      return
    }
    setVolumeViewerError(message)
  }, [showingAligned])

  function toggleTumorGroupExpanded(groupId: string) {
    setExpandedTumorGroups((current) =>
      current.includes(groupId) ? current.filter((item) => item !== groupId) : current.concat(groupId),
    )
  }

  function toggleTumorGroupVisibility(groupId: string) {
    const labels = tumorOverlayModel?.groups.find((group) => group.id === groupId)?.labels.map((label) => label.labelId) ?? []
    if (!labels.length) {
      return
    }
    setVisibleTumorLabelIds((current) => {
      const currentSet = new Set(current)
      const allVisible = labels.every((labelId) => currentSet.has(labelId))
      if (allVisible) {
        return current.filter((labelId) => !labels.includes(labelId))
      }
      return Array.from(new Set(current.concat(labels))).sort((left, right) => left - right)
    })
  }

  function toggleTumorLabelVisibility(labelId: number) {
    setVisibleTumorLabelIds((current) =>
      current.includes(labelId) ? current.filter((item) => item !== labelId) : current.concat(labelId).sort((left, right) => left - right),
    )
  }

  // A newly opened case shows FLAIR in the three planes and the T1c + FLAIR pair in comparison mode.
  function resetViewerModalities() {
    setActiveModality("t2f")
    setReviewPanels(presetPanels("pair"))
  }

  function setAllVolumeOverlays(value: boolean) {
    setShowVolumeOverlay(value)
    setReviewPanels((panels) => {
      if (!value) {
        return panels.map((panel) => ({ ...panel, overlay: "off", overlayBeforeOff: panel.overlay !== "off" ? panel.overlay : panel.overlayBeforeOff }))
      }
      // Restore what was switched off; with nothing remembered, fill every panel.
      const remembered = panels.some((panel) => panel.overlayBeforeOff)
      return panels.map((panel) => remembered
        ? panel.overlayBeforeOff ? { ...panel, overlay: panel.overlayBeforeOff, overlayBeforeOff: undefined } : panel
        : { ...panel, overlay: panel.overlay === "off" ? "fill" : panel.overlay })
    })
  }

  function updateReviewPanel(id: string, patch: Partial<Pick<ReviewPanel, "modality" | "overlay">>) {
    setReviewPanels((panels) => panels.map((panel) => (panel.id === id ? { ...panel, ...patch, overlayBeforeOff: undefined } : panel)))
  }

  function removeReviewPanel(id: string) {
    setReviewPanels((panels) => (panels.length > 1 ? panels.filter((panel) => panel.id !== id) : panels))
  }

  function addReviewPanel() {
    setReviewPanels((panels) => {
      if (panels.length >= MAX_REVIEW_PANELS) return panels
      const last = panels[panels.length - 1]
      nextPanelIdRef.current += 1
      return [...panels, { id: `p${nextPanelIdRef.current}`, modality: last?.modality ?? "t1c", overlay: "fill" }]
    })
  }

  function changeMaskSource(source: "model" | "gt") {
    setMaskSource(source)
    setAllVolumeOverlays(true)
    setVolumeViewerMode("blend")
    setActiveTumorLabelId(null)
    setActiveTumorGroup(null)
    setVisibleTumorLabelIds(defaultTumorLabelIds)
  }

  function changeViewerMode(mode: ViewerMode) {
    setVolumeViewerMode(mode)
    setAllVolumeOverlays(true)
  }

  const anyVolumeOverlay = reviewPlane === "mpr" ? showVolumeOverlay : reviewPanels.some((panel) => panel.overlay !== "off")
  const activePanelPreset = (Object.keys(PANEL_PRESETS) as PanelPresetKey[]).find((key) => matchesPreset(reviewPanels, key))
  const reviewPanelStatus = (panel: ReviewPanel) => {
    const parts: string[] = []
    if (panel.overlay !== "off") {
      const source = maskSource === "gt" ? "reference" : "model"
      if (!activeSegmentationReady) parts.push("mask pending")
      else if (previewOriginal) parts.push("mask hidden")
      else parts.push(panel.overlay === "outline" ? `${source} outline` : `${source} mask`)
    }
    if (showingAligned) parts.push("aligned")
    return parts.length ? parts.join(" · ") : "MRI only"
  }
  const chooseLayout = (key: PanelPresetKey) => {
    setReviewPanels(presetPanels(key))
    if (reviewPlane === "mpr") setReviewPlane(comparisonPlane)
  }
  const choosePlane = (plane: ComparisonPlane) => {
    setComparisonPlane(plane)
    setReviewPlane(plane)
  }
  const viewerPanels: ViewerPanelConfig[] | undefined = reviewPlane === "mpr" || !activeVolumeAssetUrl
    ? undefined
    : reviewPanels.map((panel) => ({
        id: panel.id,
        plane: reviewPlane,
        imageAssetUrl: toAbsoluteAssetUrl(resolveModalityVolumeUrl(panel.modality)) ?? activeVolumeAssetUrl,
        label: reviewPanelStatus(panel),
        badge: modalityMeta[panel.modality].label,
        showOverlay: panel.overlay !== "off",
        overlayMode: panel.overlay === "outline" ? "contour" : undefined,
      }))

  useEffect(() => {
    if (maskSource === "gt" && !hasGroundTruthMask) {
      changeMaskSource("model")
    }
  }, [hasGroundTruthMask, maskSource])

  function updateReviewState(nextReviewState: ReviewState) {
    setReviewState(nextReviewState)
    setReportError(null)
    setGeneratedReportText("")
    setReportDraftSource("none")
    const targetPointId = activePoint?.id
    if (!targetPointId) return
    setLongitudinalPoints((current) =>
      current.map((point) => (point.id === targetPointId ? { ...point, reviewState: nextReviewState } : point)),
    )
  }

  function toggleQcReason(reason: QcReasonKey) {
    const targetPointId = activePoint?.id || activeSessionId || "current"
    setGeneratedReportText("")
    setReportDraftSource("none")
    setQcReasonsByPoint((current) => {
      const reasons = current[targetPointId] ?? []
      const nextReasons = reasons.includes(reason) ? reasons.filter((item) => item !== reason) : reasons.concat(reason)
      return { ...current, [targetPointId]: nextReasons }
    })
  }

  async function prepareBulkNiftiUpload(fileList: FileList | File[] | null) {
    const selected = Array.from(fileList ?? [])
    if (!selected.length) return
    archiveRequestRef.current?.abort()
    const controller = new AbortController()
    archiveRequestRef.current = controller
    setFiles({})
    setDeidentifiedConfirmed(false)
    setUploadInferenceRows([])
    setError(null)
    setArchiveProgress(null)
    try {
      if (selected.some((file) => /\.zip$/i.test(file.name))) {
        setArchiveProgress({ phase: "reading", completed: 0, total: 0, percent: 0 })
        const { prepareNiftiSelection } = await import("./brainTumor.archive")
        const extracted = await prepareNiftiSelection(selected, (progress) => {
          if (!controller.signal.aborted) setArchiveProgress(progress)
        }, controller.signal)
        controller.signal.throwIfAborted()
        handleBulkNiftiUpload(extracted)
      } else {
        handleBulkNiftiUpload(selected)
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        setArchiveProgress(null)
        setError(err instanceof Error ? err.message : "The files could not be prepared.")
      }
    } finally {
      if (archiveRequestRef.current === controller) archiveRequestRef.current = null
    }
  }

  function handleBulkNiftiUpload(fileList: FileList | File[] | null) {
    const selectedFiles = Array.from(fileList ?? [])
    const niftiFiles = selectedFiles.filter((file) => isNiftiFileName(file.name))
    const inferred = niftiFiles.map((file) => inferModalityFromFileName(file.name)?.modality).filter(Boolean)
    if (niftiFiles.length > 4 || new Set(inferred).size !== inferred.length) {
      setFiles({})
      setDeidentifiedConfirmed(false)
      setUploadInferenceRows([])
      setError("Multiple visits or duplicate modalities were selected. Choose the four files from one examination; no files have been mapped.")
      return
    }
    if (!niftiFiles.length && selectedFiles.length) {
      setFiles({})
      setDeidentifiedConfirmed(false)
      setUploadInferenceRows([])
      setError("No NIfTI files found. Choose a NIfTI ZIP, folder or four files. DICOM upload is not available in this preview.")
      return
    }
    setDeidentifiedConfirmed(false)
    const nextFiles: Partial<Record<ModalityKey, File>> = {}
    const assigned = new Set<ModalityKey>()
    const rows: UploadInferenceRow[] = []
    selectedFiles.forEach((file) => {
      if (!isNiftiFileName(file.name)) {
        rows.push({ fileName: file.name, modality: null, reason: "Skipped: not a .nii or .nii.gz file" })
        return
      }
      const inference = inferModalityFromFileName(file.name)
      if (!inference) {
        rows.push({ fileName: file.name, modality: null, reason: "Could not infer modality from filename" })
        return
      }
      if (assigned.has(inference.modality)) {
        rows.push({ fileName: file.name, modality: inference.modality, reason: `Duplicate ${modalityMeta[inference.modality].label}; kept first match` })
        return
      }
      nextFiles[inference.modality] = file
      assigned.add(inference.modality)
      rows.push({ fileName: file.name, modality: inference.modality, reason: inference.reason })
    })
    setFiles(nextFiles)
    setUploadInferenceRows(rows)
    setError(null)
  }

  async function loadUploadedCases() {
    try {
      const response = await fetch("/api/demo/brain-tumor/uploads", { credentials: "include" })
      const payload = await response.json() as { ok: boolean; cases?: UploadedCase[]; error?: string }
      if (!response.ok || payload.ok === false) throw new Error(payload.error || "Could not load uploaded cases.")
      setUploadedCases(payload.cases ?? [])
      setUploadsLoaded(true)
    } catch (err) {
      setRegistrationError(err instanceof Error ? err.message : "Could not load uploaded cases.")
    }
  }

  function rememberUploadSelection(caseId: string) {
    uploadSelectionRef.current = caseId
    const url = new URL(window.location.href)
    if (caseId) url.searchParams.set("upload", caseId)
    else url.searchParams.delete("upload")
    window.history.replaceState(window.history.state, "", url)
  }

  function applyUploadedTimeline(uploadedCase: UploadedCase, job: UploadSegmentJob | null | undefined, reset = false) {
    const points = uploadCasePoints(uploadedCase, job)
    uploadCaseRef.current = uploadedCase
    setPreloadExampleMeta({
      title: uploadedCase.label, description: "De-identified MRI visits.", sourceNote: "My uploads",
      samePatientLongitudinal: points.length > 1, displayMode: "response_trend",
    })
    setLongitudinalPoints((current) => points.map((point) => {
      const prior = !reset && current.find((item) => item.id === point.id)
      return prior ? { ...point, reviewState: prior.reviewState, registration: prior.registration } : point
    }))
    setBaselinePointId((current) => !reset && points.some((point) => point.id === current) ? current : points[0]?.id || "")
    setActivePointId((current) => !reset && points.some((point) => point.id === current) ? current : points[0]?.id || "")
    setSegmentationReadyByPoint(Object.fromEntries(points.map((point) => [point.id, Boolean(point.segmentationUrl)])))
    if (reset) {
      setSession(job?.visits?.[0]?.session || uploadedCase.visits?.[0]?.session || job?.session || null)
      resetViewerModalities()
      setShowVolumeOverlay(true)
    }
  }

  function openUploadedCase(uploadedCase: UploadedCase) {
    registrySelectionRef.current = ""
    setSegmentResumeChecked(true)
    rememberUploadSelection(uploadedCase.id)
    setSelectedUploadCaseId(uploadedCase.id)
    setActiveRegistryCaseId("")
    setActivePreloadExampleId("")
    setSegmentJob(null)
    setAlignJob(null)
    setReviewState("pending")
    setMaskSource("model")
    setRegistrationError(null)
    setUploadJob(uploadedCase.job || null)
    applyUploadedTimeline(uploadedCase, uploadedCase.job, true)
    if (uploadedCase.job?.status === "queued" || uploadedCase.job?.status === "running") {
      void pollUploadJob(uploadedCase.job.job_id).catch((err) => setRegistrationError(String(err)))
    }
  }

  function applyUploadJobUpdate(job: UploadSegmentJob) {
    setUploadJob(job)
    if (uploadSelectionRef.current !== job.case_id || uploadCaseRef.current?.id !== job.case_id) return
    applyUploadedTimeline(uploadCaseRef.current, job)
    if (job.status === "failed") {
      setRegistrationError(job.error || "Some visits could not be segmented. Completed visits remain available.")
    }
  }

  async function pollUploadJob(jobId: string) {
    if (uploadPolls.current.has(jobId)) return
    const controller = new AbortController()
    uploadPolls.current.set(jobId, controller)
    try {
      for (let attempt = 0; attempt < 600; attempt += 1) {
        await delay(1600)
        const payload = await readUploadJob<UploadSegmentJob>(
          `/api/demo/brain-tumor/uploads/jobs/${encodeURIComponent(jobId)}`, setUploadReconnecting, controller.signal,
        )
        if (payload.ok === false && payload.status !== "failed") throw new Error(payload.error || "Could not refresh upload segmentation status.")
        applyUploadJobUpdate(payload)
        if (payload.status !== "queued" && payload.status !== "running") {
          await loadUploadedCases()
          return payload
        }
      }
      throw new Error("Segmentation is still running. Reopen the case in My uploads to reconnect.")
    } catch (err) {
      if (!controller.signal.aborted) throw err
    } finally {
      if (uploadPolls.current.get(jobId) === controller) uploadPolls.current.delete(jobId)
    }
  }

  async function resumeUploadJob() {
    try {
      const response = await fetch("/api/demo/brain-tumor/uploads/jobs/current", { credentials: "include" })
      const payload = await response.json() as { ok: boolean; job?: UploadSegmentJob | null; error?: string }
      if (!response.ok || payload.ok === false || !payload.job) return
      if (payload.job.status !== "queued" && payload.job.status !== "running") return
      if (uploadSelectionRef.current || registrySelectionRef.current) return
      const uploadedCase = uploadedCases.find((item) => item.id === payload.job?.case_id)
      if (uploadedCase) openUploadedCase(uploadedCase)
      applyUploadJobUpdate(payload.job)
      if (payload.job.status === "queued" || payload.job.status === "running") await pollUploadJob(payload.job.job_id)
    } catch (err) {
      setRegistrationError(err instanceof Error ? err.message : "Could not resume upload segmentation.")
    }
  }

  async function submitUploadedCase(visits: UploadVisitDraft[], targetCaseId: string) {
    const existingDates = uploadedCases.find((item) => item.id === targetCaseId)?.visits?.map((visit) => visit.date) || []
    const validationError = validateVisitDrafts(visits, existingDates)
    if (validationError) { setError(validationError); return }
    setUploadingCase(true)
    setUploadProgress(0)
    setError(null)
    setRegistrationError(null)
    try {
      const body = new FormData()
      body.set("deidentified_confirmed", "true")
      body.set("same_patient_confirmed", "true")
      if (targetCaseId) body.set("target_case_id", targetCaseId)
      let fileIndex = 0
      body.set("visits_json", JSON.stringify(visits.map((visit) => ({
        date: visit.date || null,
        files: Object.fromEntries(requiredModalities.map((key) => {
          body.append("files", visit.files[key] as File)
          return [key, fileIndex++]
        })),
      }))))
      const payload = await sendUpload(body, setUploadProgress) as { ok: boolean; case?: UploadedCase; job?: UploadSegmentJob; error?: string }
      if (payload.ok === false || !payload.case || !payload.job) {
        throw new Error(payload.error || "The upload could not be prepared.")
      }
      setUploadedCases((current) => [payload.case as UploadedCase, ...current.filter((item) => item.id !== payload.case?.id)])
      openUploadedCase(payload.case)
      applyUploadJobUpdate(payload.job)
      setUploadPanelOpen(false)
      setFiles({})
      setUploadInferenceRows([])
      setArchiveProgress(null)
      setDeidentifiedConfirmed(false)
      void pollUploadJob(payload.job.job_id).catch((err) => setRegistrationError(String(err)))
    } catch (err) {
      setError(err instanceof Error ? err.message : "The upload could not be prepared.")
      void loadUploadedCases()
    } finally {
      setUploadingCase(false)
    }
  }

  async function retryUploadedCase(uploadedCase: UploadedCase) {
    setRegistrationError(null)
    const response = await fetch(`/api/demo/brain-tumor/uploads/${encodeURIComponent(uploadedCase.id)}/retry`, {
      method: "POST",
      credentials: "include",
    })
    const payload = await response.json() as UploadSegmentJob
    if (!response.ok || payload.ok === false) {
      setRegistrationError(payload.error || "The segmentation retry could not be queued.")
      return
    }
    openUploadedCase(uploadedCase)
    applyUploadJobUpdate(payload)
    void pollUploadJob(payload.job_id).catch((err) => setRegistrationError(err instanceof Error ? err.message : "Could not refresh segmentation status."))
  }

  async function deleteUploadedCase(uploadedCase: UploadedCase) {
    if (!window.confirm(`Delete ${uploadedCase.label} and its derived results?`)) return
    const response = await fetch(`/api/demo/brain-tumor/uploads/${encodeURIComponent(uploadedCase.id)}`, {
      method: "DELETE",
      credentials: "include",
    })
    const payload = await response.json() as { ok: boolean; error?: string }
    if (!response.ok || payload.ok === false) {
      setRegistrationError(payload.error || "The uploaded case could not be deleted.")
      return
    }
    setUploadedCases((current) => current.filter((item) => item.id !== uploadedCase.id))
    if (selectedUploadCaseId === uploadedCase.id) clearTimeline()
  }

  function applyPreloadExample(example: PreloadExample) {
    registrySelectionRef.current = ""
    if (!example.points.length) return
    setLongitudinalPoints(beginCaseReview(example.points))
    setBaselinePointId(example.points[0]?.id ?? "")
    setActivePointId(example.points[0]?.id ?? "")
    resetViewerModalities()
    setTimepointRole("follow_up")
    setTimepointDate("")
    setReviewState("pending")
    setQcReasonsByPoint({})
    setGeneratedReportText("")
    setReportDraftSource("none")
    setPreloadSourceNote("")
    setPreloadExampleMeta({
      title: example.title || "Case",
      description: example.description || "",
      displayMode: example.display_mode,
      sourceNote: "",
      samePatientLongitudinal: Boolean(example.same_patient_longitudinal),
    })
    setShowVolumeOverlay(true)
    setMaskSource("model")
    setActivePreloadExampleId(example.id)
    setActiveRegistryCaseId("")
    setSelectedUploadCaseId("")
    setSegmentJob(null)
    setAlignJob(null)
    setDemoTimelineLoaded(true)
  }

  async function loadPreloadTimeline() {
    setLoadingPreload(true)
    setRegistrationError(null)
    try {
      const response = await fetch("/api/demo/brain-tumor/preload/examples", { credentials: "include" })
      const payload = await response.json()
      if (!response.ok || payload.ok === false || !payload.configured) {
        throw new Error(payload.error || "No case worklist is available in this workspace.")
      }
      const examples = ((payload.examples ?? []) as PreloadExample[]).filter((example) => example.points?.length)
      const example = examples.find((item) => item.id === payload.default_example_id) ?? examples[0]
      if (!example) {
        throw new Error("Case worklist did not include any timeline rows.")
      }
      setPreloadExamples(examples)
      applyPreloadExample(example)
    } catch (err) {
      setRegistrationError(err instanceof Error ? err.message : "Failed to open case worklist.")
    } finally {
      setLoadingPreload(false)
    }
  }

  function clearTimeline() {
    registrySelectionRef.current = ""
    setSegmentResumeChecked(true)
    rememberUploadSelection("")
    setLongitudinalPoints([])
    setBaselinePointId("")
    setActivePointId("")
    setRegistrationError(null)
    setPreloadSourceNote("")
    setPreloadExampleMeta(null)
    setPreloadExamples([])
    setActivePreloadExampleId("")
    setActiveRegistryCaseId("")
    setSelectedUploadCaseId("")
    setSegmentJob(null)
    setAlignJob(null)
    setSegmentationReadyByPoint({})
    setMaskSource("model")
    setDemoTimelineLoaded(false)
  }

  function selectReference(pointId: string) {
    if (pointId === baselinePointId || aligningAll || registeringPointId) return
    setBaselinePointId(pointId)
    setLongitudinalPoints((points) => points.map((point) => ({ ...point, registration: undefined })))
    setAlignJob(null)
    setGeneratedReportText("")
    setReportDraftSource("none")
  }

  function addSessionToTimeline(payload: TumorSession, options: { dateLabel?: string; replaceTimeline?: boolean } = {}) {
    const defaultRole: TimepointRole = longitudinalPoints.length ? "follow_up" : "pre_treatment_baseline"
    const role = timepointRole || defaultRole
    const dateLabel = options.dateLabel || timepointDate || selectedStudy?.study_date || "Unscheduled"
    const label =
      payload.patient_label ||
      selectedStudy?.description ||
      patientLabel ||
      (role === "pre_treatment_baseline" || role === "post_rt_baseline" ? "Reference scan" : `Follow-up ${longitudinalPoints.length}`)
    const point: LongitudinalPoint = {
      id: payload.session_id,
      sessionId: payload.session_id,
      label,
      role: role || defaultRole,
      dateLabel,
      // Mounted-study dates may be derived from directory names. Only explicit input is trusted here.
      scanDate: options.dateLabel || timepointDate || (inputMode === "dicomweb" ? selectedStudy?.study_date : null) || null,
      reviewState,
      volumes: payload.volumes ?? [],
      overlayUrl: payload.viewer_assets?.overlay_preview_url,
      modalityVolumeUrls: payload.viewer_assets?.modality_volume_urls,
      segmentationUrl: payload.viewer_assets?.segmentation_url,
      reportSlices: payload.viewer_assets?.report_slices,
    }
    registrySelectionRef.current = ""
    setActiveRegistryCaseId("")
    setSegmentJob(null)
    setAlignJob(null)
    setLongitudinalPoints((current) => {
      const seed = options.replaceTimeline ? [] : current
      const next = seed.filter((item) => item.id !== point.id).concat(point)
      if (!baselinePointId && next.length) {
        setBaselinePointId(next[0].id)
      }
      return next
    })
    setActivePointId(point.id)
    if (longitudinalPoints.length === 0) {
      setTimepointRole("follow_up")
    }
  }

  async function loadRegistryCases() {
    setLoadingRegistry(true)
    setRegistrationError(null)
    try {
      const response = await fetch("/api/demo/brain-tumor/registry/cases", { credentials: "include" })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || "Failed to load case registry.")
      }
      setRegistryCases(payload.cases ?? [])
      setRegistryNote(payload.source_note || `${payload.case_count ?? 0} registry cases available.`)
    } catch (err) {
      setRegistryNote(err instanceof Error ? err.message : "Failed to load case registry.")
    } finally {
      setLoadingRegistry(false)
    }
  }

  async function openInitialRegistryCase() {
    try {
      const response = await fetch("/api/demo/brain-tumor/registry/segment-jobs/current", { credentials: "include" })
      const payload = (await response.json()) as { ok: boolean; job?: RegistrySegmentJob | null }
      if (uploadSelectionRef.current || registrySelectionRef.current) return
      if (!response.ok || payload.ok === false) return
      const job = payload.job
      if (job && (job.status === "queued" || job.status === "running")) {
        setRunning(true)
        await runRegistryCase(job.case_id)
        if (uploadSelectionRef.current || registrySelectionRef.current !== job.case_id) return
        applySegmentJobUpdate(job)
        await pollSegmentJob(job.job_id)
      } else {
        const defaultCase = selectDefaultRegistryCase(registryCases)
        if (defaultCase) await runRegistryCase(defaultCase.id)
      }
    } catch (err) {
      setRegistrationError(err instanceof Error ? err.message : "Could not open the initial case.")
    } finally {
      setRunning(false)
    }
  }

  async function runRegistryCase(caseId: string) {
    registrySelectionRef.current = caseId
    setSegmentResumeChecked(true)
    rememberUploadSelection("")
    setRunningRegistryCaseId(caseId)
    setError(null)
    setRegistrationError(null)
    setGeneratedReportText("")
    setReportDraftSource("none")
    setSegmentJob(null)
    setAlignJob(null)
    try {
      const response = await fetch("/api/demo/brain-tumor/registry/load", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_id: caseId }),
      })
      const payload = await response.json()
      if (uploadSelectionRef.current || registrySelectionRef.current !== caseId) return
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || `Registry load failed with status ${response.status}`)
      }
      const points = (payload.points ?? []) as LongitudinalPoint[]
      if (!points.length) {
        throw new Error("Registry load did not return any timepoints.")
      }
      const cachedResultLoaded = points.some((point) => Boolean(point.segmentationUrl))
      setLongitudinalPoints(points)
      setBaselinePointId(points[0]?.id ?? "")
      setActivePointId(points[0]?.id ?? "")
      resetViewerModalities()
      setReviewState("pending")
      setPreloadExampleMeta({
        title: registryCases.find((item) => item.id === caseId)?.title || "Registry case",
        description: cachedResultLoaded
          ? "Verified model outputs loaded for review. Re-run the model to create a new result without replacing this baseline."
          : "Raw MRI visits loaded from the case registry. Run segmentation to generate masks, measurements, QC, and report context.",
        displayMode: points.length > 2 ? "response_trend" : "stage_comparison",
        sourceNote: "case registry",
        samePatientLongitudinal: Boolean(payload.same_patient_longitudinal),
      })
      setActivePreloadExampleId("")
      setActiveRegistryCaseId(caseId)
      setSelectedUploadCaseId("")
      setSegmentationReadyByPoint(Object.fromEntries(points.map((point) => [point.id, Boolean(point.segmentationUrl)])))
      setShowVolumeOverlay(cachedResultLoaded)
      setMaskSource("model")
      setPreloadSourceNote(
        cachedResultLoaded
          ? "Verified result loaded. You can review it now or re-run the model."
          : "Raw MRI loaded. Click Run segmentation to generate masks, volumes, QC, and report context.",
      )
    } catch (err) {
      if (registrySelectionRef.current === caseId && !uploadSelectionRef.current) setRegistrationError(err instanceof Error ? err.message : "Registry load failed.")
    } finally {
      setRunningRegistryCaseId((current) => current === caseId ? "" : current)
    }
  }

  function applySegmentJobUpdate(job: RegistrySegmentJob) {
    if (registrySelectionRef.current !== job.case_id || uploadSelectionRef.current) return
    setSegmentJob(job)
    const completeVisits = job.visits.filter((visit) => visit.status === "complete" && visit.point)
    if (completeVisits.length) {
      const activeReplacement = completeVisits.find((visit) => visit.point?.timepointId === activePoint?.timepointId)?.point
      const baselineReplacement = completeVisits.find((visit) => visit.point?.timepointId === baselinePoint?.timepointId)?.point
      setLongitudinalPoints((current) =>
        current.map((point) => {
          const visit = completeVisits.find((item) => item.point?.id === point.id || item.point?.timepointId === point.timepointId)
          return visit?.point ? { ...point, ...visit.point } : point
        }),
      )
      if (activeReplacement?.id) setActivePointId(activeReplacement.id)
      if (baselineReplacement?.id) setBaselinePointId(baselineReplacement.id)
      setSegmentationReadyByPoint((current) => ({
        ...current,
        ...Object.fromEntries(completeVisits.map((visit) => [visit.point?.id ?? "", true]).filter(([id]) => Boolean(id))),
      }))
    }
    if (job.status === "completed") {
      setPreloadSourceNote(`${job.force_rerun ? "New model result" : "Segmentation"} complete: ${job.completed_count}/${job.total_count} visit${job.total_count === 1 ? "" : "s"} ready.`)
      setShowVolumeOverlay(true)
      setVisibleTumorLabelIds(defaultTumorLabelIds)
      setReviewState("pending")
      return
    }
    if (job.status === "completed_with_errors" || job.status === "failed") {
      setPreloadSourceNote(job.error || `Segmentation finished with ${job.failed_count ?? 1} failed visit${job.failed_count === 1 ? "" : "s"}.`)
      return
    }
    const runningVisit = job.visits.find((visit) => visit.status === "running")
    setPreloadSourceNote(
      runningVisit
        ? `${segmentStageLabel(job.stage)}: ${runningVisit.dateLabel || runningVisit.label}.`
        : `${segmentStageLabel(job.stage)}. The current images remain available for review.`,
    )
  }

  async function pollSegmentJob(jobId: string) {
    for (let attempt = 0; attempt < 240; attempt += 1) {
      await delay(1600)
      const response = await fetch(`/api/demo/brain-tumor/registry/segment-jobs/${encodeURIComponent(jobId)}`, { credentials: "include" })
      const payload = (await response.json()) as RegistrySegmentJob
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || `Segmentation job polling failed with status ${response.status}`)
      }
      applySegmentJobUpdate(payload)
      if (payload.status !== "queued" && payload.status !== "running") return payload
    }
    throw new Error("Segmentation job timed out while polling.")
  }

  async function runRegistrationQc(followupId: string) {
    const followupPoint = longitudinalPoints.find((point) => point.id === followupId)
    if (!baselinePoint || baselinePoint.id === followupId || !followupPoint) return
    setActivePointId(followupId)
    await startAlignment([followupPoint.sessionId], followupId)
  }

  function applyAlignJobUpdate(job: LongitudinalAlignJob) {
    setAlignJob(job)
    setLongitudinalPoints((current) =>
      current.map((point) => {
        const visit = job.visits.find((item) => item.session_id === point.sessionId || item.followup_session_id === point.sessionId)
        if (!visit?.registration) return point
        return { ...point, registration: visit.registration }
      }),
    )
    if (job.status === "completed") {
      setPreloadSourceNote(`Alignment complete: ${job.completed_count}/${job.total_count} visit${job.total_count === 1 ? "" : "s"} aligned.`)
      setAlignmentDisplay("aligned")
    } else if (job.status === "completed_with_errors" || job.status === "failed") {
      setRegistrationError("Some visits could not be aligned. Original images remain available; review the failed step before retrying.")
    } else {
      const runningVisit = job.visits.find((visit) => visit.status === "running")
      setPreloadSourceNote(
        runningVisit
          ? `Aligning visits ${job.completed_count}/${job.total_count}: ${runningVisit.dateLabel || runningVisit.label || runningVisit.session_id}.`
          : `Alignment queued: ${job.completed_count}/${job.total_count} visits ready.`,
      )
    }
  }

  async function pollAlignJob(jobId: string, signal: AbortSignal) {
    for (let attempt = 0; attempt < 1200; attempt += 1) {
      await delay(1600)
      signal.throwIfAborted()
      const response = await fetch(`/api/demo/brain-tumor/longitudinal/align-jobs/${encodeURIComponent(jobId)}`, { credentials: "include", signal })
      const payload = (await response.json()) as LongitudinalAlignJob
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || `Alignment job polling failed with status ${response.status}`)
      }
      signal.throwIfAborted()
      applyAlignJobUpdate(payload)
      if (payload.status !== "running") return payload
    }
    throw new Error("Alignment job timed out while polling.")
  }

  async function runAlignAll() {
    if (!baselinePoint) return
    const followupSessionIds = longitudinalPoints
      .filter((point) => point.sessionId && point.id !== baselinePoint.id)
      .map((point) => point.sessionId)
    await startAlignment(followupSessionIds, "__all__")
  }

  async function startAlignment(followupSessionIds: string[], pointId: string) {
    if (!baselinePoint || !followupSessionIds.length || alignmentRequestRef.current) return
    const controller = new AbortController()
    alignmentRequestRef.current = controller
    setRegistrationError(null)
    setAligningAll(true)
    setRegisteringPointId(pointId)
    setAlignmentDisplay("original")
    setAlignJob(null)
    try {
      const response = await fetch("/api/demo/brain-tumor/longitudinal/align-jobs", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          baseline_session_id: baselinePoint.sessionId,
          followup_session_ids: followupSessionIds,
          bias_correction: biasCorrection,
        }),
      })
      const payload = (await response.json()) as LongitudinalAlignJob
      controller.signal.throwIfAborted()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || `Alignment job failed with status ${response.status}`)
      }
      applyAlignJobUpdate(payload)
      requestAnimationFrame(() => alignmentPanelRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }))
      if (payload.status === "running") {
        await pollAlignJob(payload.job_id, controller.signal)
      }
    } catch (err) {
      if (!controller.signal.aborted) setRegistrationError(err instanceof Error ? err.message : "Alignment job failed.")
    } finally {
      if (alignmentRequestRef.current === controller) alignmentRequestRef.current = null
      if (!alignmentRequestRef.current) {
        setRegisteringPointId("")
        setAligningAll(false)
      }
    }
  }

  async function searchStudies() {
    setError(null)
    setLoadingStudies(true)
    try {
      const params = new URLSearchParams()
      if (patientQuery.trim()) params.set("patient_id", patientQuery.trim())
      if (accessionQuery.trim()) params.set("accession_number", accessionQuery.trim())
      const basePath =
        inputMode === "mount"
          ? "/api/demo/brain-tumor/dicom-mount/studies"
          : "/api/demo/brain-tumor/dicom/studies"
      const response = await fetch(`${basePath}?${params.toString()}`, {
        credentials: "include",
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || `Study search failed with status ${response.status}`)
      }
      if (payload.message) setError(payload.message)
      setStudies(payload.studies ?? [])
      setSeries([])
      setSelectedStudyUid("")
      setMapping({})
      setSession(null)
      setReviewState("pending")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Study search failed.")
    } finally {
      setLoadingStudies(false)
    }
  }

  async function loadSeries(studyUid: string) {
    setSelectedStudyUid(studyUid)
    setError(null)
    setLoadingSeries(true)
    setSession(null)
    setReviewState("pending")
    try {
      const basePath =
        inputMode === "mount"
          ? "/api/demo/brain-tumor/dicom-mount/studies"
          : "/api/demo/brain-tumor/dicom/studies"
      const response = await fetch(
        `${basePath}/${encodeURIComponent(studyUid)}/series`,
        {
          credentials: "include",
        },
      )
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || `Series load failed with status ${response.status}`)
      }
      setSeries(payload.series ?? [])
      setMapping(payload.suggested_mapping ?? {})
    } catch (err) {
      setError(err instanceof Error ? err.message : "Series load failed.")
    } finally {
      setLoadingSeries(false)
    }
  }

  async function runSegmentation() {
    setError(null)
    if (activeRegistryCaseId) {
      setRunning(true)
      setRegistrationError(null)
      setGeneratedReportText("")
      setReportDraftSource("none")
      try {
        const response = await fetch("/api/demo/brain-tumor/registry/segment-jobs", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            case_id: activeRegistryCaseId,
            timepoint_ids: physicianCuratedOnly && activePoint?.timepointId ? [activePoint.timepointId] : undefined,
            force_rerun: Boolean(activeSegmentationReady),
          }),
        })
        const payload = (await response.json()) as RegistrySegmentJob
        if (!response.ok || payload.ok === false) {
          throw new Error(payload.error || `Segmentation job failed with status ${response.status}`)
        }
        applySegmentJobUpdate(payload)
        if (payload.status === "queued" || payload.status === "running") {
          await pollSegmentJob(payload.job_id)
        }
      } catch (err) {
        setRegistrationError(err instanceof Error ? err.message : "Segmentation job failed.")
      } finally {
        setRunning(false)
      }
      return
    }
    if (canLoadPrecomputedSegmentation && activePoint) {
      setShowVolumeOverlay(true)
      setVisibleTumorLabelIds(defaultTumorLabelIds)
      return
    }
    setRunning(true)
    setSession(null)
    setReviewState("pending")
    try {
      const body = new FormData()
      body.set("input_mode", inputMode === "dicomweb" ? "dicomweb" : inputMode === "mount" ? "dicom_mount" : "nifti_upload")
      body.set("patient_label", patientLabel || selectedStudy?.patient_id || patientQuery)
      body.set("study_instance_uid", selectedStudyUid)
      body.set("modality_mapping_json", JSON.stringify(mapping))
      modalityOrder.forEach((key) => {
        const file = files[key]
        if (file) body.set(`${key}_file`, file)
      })
      const response = await fetch("/api/demo/brain-tumor/analyze", {
        method: "POST",
        credentials: "include",
        body,
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || `Segmentation failed with status ${response.status}`)
      }
      setSession(payload)
      addSessionToTimeline(payload, { replaceTimeline: Boolean(preloadExampleMeta && !preloadExampleMeta.samePatientLongitudinal) })
      setSegmentationReadyByPoint((current) => ({ ...current, [payload.session_id]: true }))
      setPreloadExampleMeta(null)
      setPreloadSourceNote("")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Segmentation failed.")
    } finally {
      setRunning(false)
    }
  }

  function copyReport() {
    const text = generatedReportText ? reportDraftSource === "ai" ? `${buildVisitTimingText(longitudinalRows, samePatientLongitudinal)}\n\n${generatedReportText}` : generatedReportText : buildReportExportText(activeLabel, activeDate, activeReviewState, activeQcReasons, activePoint, session, longitudinalRows, samePatientLongitudinal)
    void navigator.clipboard?.writeText(text)
  }

  function downloadReport() {
    downloadTextFile(
      `${safeFilePart(activeLabel)}_gbm_report.txt`,
      generatedReportText ? reportDraftSource === "ai" ? `${buildVisitTimingText(longitudinalRows, samePatientLongitudinal)}\n\n${generatedReportText}` : generatedReportText : buildReportExportText(activeLabel, activeDate, activeReviewState, activeQcReasons, activePoint, session, longitudinalRows, samePatientLongitudinal),
      "text/plain;charset=utf-8",
    )
  }

  async function generateReportDraft() {
    if (!hasLoadedCase || !activeSegmentationReady) return
    reportRequestRef.current?.abort()
    const controller = new AbortController()
    reportRequestRef.current = controller
    setDraftingReport(true)
    setReportError(null)
    const timeout = window.setTimeout(() => controller.abort(), 45000)
    try {
      const response = await fetch("/api/demo/brain-tumor/report/draft", {
        method: "POST",
        signal: controller.signal,
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildReportPayload(
          activeLabel,
          activeDate,
          activeReviewState,
          activeQcReasons,
          activePoint,
          longitudinalRows,
          session,
          undefined,
          samePatientLongitudinal,
        )),
      })
      const payload = (await response.json()) as BrainTumorReportDraftResponse
      if (reportRequestRef.current !== controller) return
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || `Report draft failed with status ${response.status}`)
      }
      if (!payload.report_text?.trim()) throw new Error("The report service returned an empty draft.")
      setGeneratedReportText(payload.generated ? payload.report_text : buildReportExportText(activeLabel, activeDate, activeReviewState, activeQcReasons, activePoint, session, longitudinalRows, samePatientLongitudinal))
      setReportDraftSource(payload.generated ? "ai" : "local")
      setReportError(payload.generated ? null : "AI drafting is unavailable. A structured draft from the measured volumes is shown instead.")
    } catch {
      if (reportRequestRef.current !== controller) return
      setGeneratedReportText(buildReportExportText(activeLabel, activeDate, activeReviewState, activeQcReasons, activePoint, session, longitudinalRows, samePatientLongitudinal))
      setReportDraftSource("local")
      setReportError("AI drafting is unavailable. A structured draft from the measured volumes is shown instead.")
    } finally {
      window.clearTimeout(timeout)
      if (reportRequestRef.current === controller) {
        reportRequestRef.current = null
        setDraftingReport(false)
      }
    }
  }

  async function downloadHtmlReport() {
    const findingsText = activePoint ? activePointReport(activePoint) : session?.report_snippet.findings ?? activePointReport(activePoint)
    const summaryText = activePoint ? activePointImpression(activePoint, samePatientLongitudinal) : session?.report_snippet.impression ?? activePointImpression(activePoint, samePatientLongitudinal)
    const logoDataUrl = await fetchSvgAssetDataUrl(`${import.meta.env.BASE_URL}clinagent-logo-stacked-clean.svg`, "135 145 900 610").catch(() => "")
    downloadTextFile(
      `${safeFilePart(activeLabel)}_gbm_report.html`,
      buildReportHtml({
        activePoint,
        caseLabel: activeLabel,
        dateLabel: activeDate,
        draftSource: reportDraftSource,
        draftText: generatedReportText,
        exportedAtLabel: new Date().toLocaleString(),
        figureSvg: buildReportFigureSvg(longitudinalRows, activePoint?.id),
        findingsText,
        logoDataUrl,
        measurementsCsv: buildMeasurementsCsv(longitudinalRows),
        points: longitudinalRows,
        reviewState: activeReviewState,
        qcReasons: activeQcReasons,
        summaryText,
      }),
      "text/html;charset=utf-8",
    )
  }

  function downloadMeasurementsCsv() {
    downloadTextFile(
      `${safeFilePart(activeLabel)}_gbm_measurements.csv`,
      buildMeasurementsCsv(longitudinalRows),
      "text/csv;charset=utf-8",
    )
  }

  return (
    <div className="min-h-[calc(100vh-7rem)] space-y-3">
      <header className="space-y-3 pb-1">
        <div className="flex min-w-0 flex-wrap items-end justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-[hsl(var(--muted-foreground))]">
            <span>Workspaces</span>
            <span>/</span>
            <span>GBM Care</span>
            <span>/</span>
            <span className="font-medium text-[hsl(var(--foreground))]">{activeLabel}</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button className="min-h-[44px] text-[13px]" onClick={() => setUploadPanelOpen(true)} variant="ghost"><Download />Example MRI</Button>
            <PreviewFeedback caseId={selectedUploadCaseId || activeSessionId || undefined} step={activeWorkspaceTab} />
          </div>
        </div>
        <CompactWorkflowStrip steps={workflowSteps} />
      </header>

      <ClinicalContextRail
        activeDate={activeDate}
        activeLabel={activeLabel}
        activeReviewState={activeReviewState}
        activeSegmentationReady={activeSegmentationReady}
        baselineReady={baselineReady}
        hasGroundTruthMask={hasGroundTruthMask}
        hasLoadedCase={hasLoadedCase}
        registrationComplete={registrationComplete}
        registrationRequired={registrationRequired}
        reportEligible={reportEligible}
        latestPoint={latestPoint}
        points={longitudinalRows}
        samePatientLongitudinal={samePatientLongitudinal}
        segmentJobRunning={segmentationJobRunning}
        segmentProgressCompleted={segmentProgressCompleted}
        segmentProgressPct={segmentProgressPct}
        segmentProgressTotal={segmentProgressTotal}
        aligningAll={aligningAll}
      />

      <main className="brain-tumor-workspace-grid">
        <aside aria-label="Case library" className="brain-tumor-case-library">
          <div className="brain-tumor-case-library-body">
          <SoftPanel className="brain-tumor-case-library-panel p-3">
            <CaseLibrary
              activeExampleId={activePreloadExampleId}
              activeRegistryCaseId={activeRegistryCaseId}
              activeUploadCaseId={selectedUploadCaseId}
              curatedOnly={physicianCuratedOnly}
              examples={preloadExamples}
              loadingPreload={loadingPreload}
              meta={preloadExampleMeta}
              note={preloadSourceNote}
              onClear={clearTimeline}
              onLoadDemo={() => void loadPreloadTimeline()}
              onLoadRegistry={() => void loadRegistryCases()}
              onLoadUploads={() => void loadUploadedCases()}
              onRunRegistryCase={(caseId) => void runRegistryCase(caseId)}
              onSelectExample={applyPreloadExample}
              onDeleteUpload={(uploadedCase) => void deleteUploadedCase(uploadedCase)}
              onOpenUpload={openUploadedCase}
              onRetryUpload={(uploadedCase) => void retryUploadedCase(uploadedCase)}
              onUpload={() => {
                setInputMode("upload")
                setError(null)
                setUploadPanelOpen(true)
              }}
              points={longitudinalRows}
              registryCases={registryCases}
              registryNote={registryNote}
              loadingRegistry={loadingRegistry}
              runningRegistryCaseId={runningRegistryCaseId}
              uploadedCases={displayedUploadedCases}
            />
          </SoftPanel>

          {!physicianCuratedOnly ? <SoftPanel className="p-3">
            <div className="mb-3 flex items-center justify-between gap-2">
              <SectionTitle compact icon={HardDrive} label="Input source" />
              <StatusDot ok={hasRequired || Boolean(activePoint)} label={hasRequired || activePoint ? "ready" : "setup"} />
            </div>
            <div className="mb-3 grid gap-1 rounded-2xl border border-[hsl(var(--border)/0.58)] bg-[hsl(var(--background)/0.62)] p-1 shadow-[inset_0_1px_0_hsl(var(--card)/0.92)]">
            {[
              { key: "mount" as const, label: "Mounted DICOM", detail: "Server-side source", icon: HardDrive },
              { key: "dicomweb" as const, label: "PACS", detail: "DICOMweb lookup", icon: Database },
              { key: "upload" as const, label: "Upload", detail: "NIfTI modalities", icon: FileUp },
            ].map((item) => {
              const Icon = item.icon
              return (
                <button
                  className={cn(
                    "flex min-h-10 w-full items-center gap-2 rounded-xl px-2 text-left text-[12px] transition duration-200",
                    inputMode === item.key
                      ? "bg-[hsl(var(--foreground))] text-[hsl(var(--background))] shadow-[0_8px_20px_hsl(var(--foreground)/0.12)]"
                      : "text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted)/0.72)] hover:text-[hsl(var(--foreground))]",
                  )}
                  key={item.key}
                  onClick={() => {
                    setInputMode(item.key)
                    setError(null)
                    setSession(null)
                    setReviewState("pending")
                  }}
                  type="button"
                >
                  <Icon className="h-3.5 w-3.5 shrink-0" />
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{item.label}</span>
                    <span
                      className={cn(
                        "block truncate text-[10px] font-normal",
                        inputMode === item.key ? "text-[hsl(var(--background)/0.72)]" : "text-[hsl(var(--muted-foreground))]",
                      )}
                    >
                      {item.detail}
                    </span>
                  </span>
                </button>
              )
            })}
            </div>

          {inputMode === "mount" ? (
            <InlineNotice
              icon={HardDrive}
              text={
                mountStatus.data?.configured
                  ? `Mounted source connected: ${mountStatus.data.root_count} root${mountStatus.data.root_count === 1 ? "" : "s"}, ${mountStatus.data.remote ? "remote" : "local"} scan.`
                  : "Mounted DICOM source is not configured for this gateway session."
              }
            />
          ) : null}

          {inputMode === "dicomweb" || inputMode === "mount" ? (
            <div className="space-y-3">
              <LabeledInput
                label={inputMode === "mount" ? "Patient / case" : "Patient ID"}
                onChange={setPatientQuery}
                placeholder={inputMode === "mount" ? "Case or study name" : "Search patient"}
                value={patientQuery}
              />
              <LabeledInput label="Accession" onChange={setAccessionQuery} placeholder="Optional accession" value={accessionQuery} />
              <Button className="w-full" disabled={loadingStudies} onClick={searchStudies} type="button">
                {loadingStudies ? <Loader2 className="animate-spin" /> : <Search />}
                {inputMode === "mount" ? "Search mounted studies" : "Search studies"}
              </Button>
              <div className="max-h-56 space-y-2 overflow-auto pr-1">
                {studies.map((study) => (
                  <button
                    className={cn(
                      "w-full rounded-xl border p-2 text-left text-[12px] transition duration-200",
                      selectedStudyUid === study.study_instance_uid
                        ? "border-[hsl(var(--primary)/0.58)] bg-[hsl(var(--primary)/0.08)] shadow-[0_10px_26px_hsl(var(--primary)/0.08)]"
                        : "border-[hsl(var(--border)/0.62)] bg-[hsl(var(--background)/0.58)] hover:border-[hsl(var(--primary)/0.22)] hover:bg-[hsl(var(--card)/0.86)] hover:shadow-[0_10px_24px_hsl(var(--foreground)/0.045)]",
                    )}
                    key={study.study_instance_uid}
                    onClick={() => void loadSeries(study.study_instance_uid)}
                    type="button"
                  >
                    <div className="font-medium text-[hsl(var(--foreground))]">{study.description || "MR study"}</div>
                    <div className="mt-1 text-[hsl(var(--muted-foreground))]">
                      {study.patient_id || "Unknown patient"} · {study.study_date || "No date"} · {study.series_count} series
                    </div>
                  </button>
                ))}
              </div>
              {loadingSeries ? <InlineNotice icon={Loader2} text="Loading series and modality suggestions..." spin /> : null}
              {series.length ? (
                <div className="space-y-2">
                  <SectionTitle icon={SlidersHorizontal} label="Modality mapping" compact />
                  {modalityOrder.map((key) => (
                    <label className="block space-y-1" key={key}>
                      <span className="flex items-center justify-between gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
                        <span>
                          {modalityMeta[key].label} {modalityMeta[key].required ? "(required)" : "(optional)"}
                        </span>
                        <span className="truncate">{modalityMeta[key].hint}</span>
                      </span>
                      <select
                        className="h-9 w-full rounded-xl border border-[hsl(var(--input)/0.72)] bg-[hsl(var(--background)/0.72)] px-2 text-[12px] outline-none transition focus:border-[hsl(var(--primary)/0.52)] focus:shadow-[0_0_0_3px_hsl(var(--primary)/0.08)]"
                        onChange={(event) => setMapping((current) => ({ ...current, [key]: event.target.value }))}
                        value={mapping[key] ?? ""}
                      >
                        <option value="">Not selected</option>
                        {series.map((item) => (
                          <option key={item.series_instance_uid} value={item.series_instance_uid}>
                            {item.description || item.series_instance_uid} ({item.instance_count})
                          </option>
                        ))}
                      </select>
                    </label>
                  ))}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="space-y-3">
              <LabeledInput label="Case label" onChange={setPatientLabel} placeholder="Optional display label" value={patientLabel} />
              <TimepointInput dateValue={timepointDate} onDateChange={setTimepointDate} onRoleChange={setTimepointRole} roleValue={timepointRole} />
              <BulkNiftiInput disabled={preparingArchive} inferenceRows={uploadInferenceRows} onChange={prepareBulkNiftiUpload} archiveProgress={archiveProgress} />
              {modalityOrder.map((key) => (
                <FileInput
                  disabled={preparingArchive}
                  key={key}
                  label={`${modalityMeta[key].label} ${modalityMeta[key].required ? "(required)" : "(optional)"}`}
                  onChange={(file) => {
                    setFiles((current) => ({ ...current, [key]: file ?? undefined }))
                    setUploadInferenceRows([])
                    setArchiveProgress(null)
                    setSession(null)
                    setReviewState("pending")
                  }}
                  selectedFile={files[key]}
                />
              ))}
            </div>
          )}
          </SoftPanel> : null}

          </div>
        </aside>

        <section aria-label="Imaging workstation" className="brain-tumor-imaging">
          <SoftPanel className="overflow-hidden rounded-2xl border-[hsl(var(--border)/0.62)] bg-[hsl(var(--background)/0.9)]">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[hsl(var(--border)/0.55)] bg-[hsl(var(--card)/0.66)] px-4 py-3">
              <div className="min-w-0">
                <div className="text-[14px] font-medium text-[hsl(var(--foreground))]">Imaging workstation</div>
                <div className="truncate text-[12px] text-[hsl(var(--muted-foreground))]">
                  {hasLoadedCase ? `${activeLabel} · ${activeDate}` : selectedStudy ? selectedStudy.description || selectedStudy.study_instance_uid : "No study selected"}
                </div>
                {hasLoadedCase ? (
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-[hsl(var(--muted-foreground))]">
                    <span className={cn(
                      "rounded-full border px-2 py-0.5",
                      activeSegmentationReady
                        ? "border-[hsl(var(--status-ok)/0.32)] bg-[hsl(var(--status-ok)/0.08)] text-[hsl(var(--status-ok))]"
                        : "border-[hsl(var(--border))] bg-[hsl(var(--muted)/0.55)]",
                    )}>
                      Mask: {activeSegmentationReady ? activeMaskSourceLabel : segmentationJobRunning ? `running ${segmentProgressCompleted}/${segmentProgressTotal}` : "not loaded"}
                    </span>
                    {hasGroundTruthMask ? <span className="rounded-full bg-[hsl(var(--muted))] px-2 py-0.5">Reference available</span> : null}
                  </div>
                ) : null}
              </div>
              <div className="flex items-center gap-2 rounded-2xl border border-[hsl(var(--border)/0.58)] bg-[hsl(var(--background)/0.62)] p-1.5 shadow-[0_12px_30px_hsl(var(--foreground)/0.05),inset_0_1px_0_hsl(var(--card)/0.9)]">
                {activeUploadCase ? (
                  <div className="flex h-10 items-center gap-2 rounded-xl bg-[hsl(var(--muted)/0.7)] px-3 text-[12px] font-semibold text-[hsl(var(--foreground))]">
                    {uploadJobRunning ? <Loader2 className="h-4 w-4 animate-spin text-[hsl(var(--primary))]" /> : activeSegmentationReady ? <CheckCircle2 className="h-4 w-4 text-[hsl(var(--status-ok))]" /> : <AlertTriangle className="h-4 w-4 text-[hsl(var(--destructive))]" />}
                    {uploadJobRunning ? uploadReconnecting ? "Reconnecting to job" : segmentStageLabel(activeUploadJob?.stage) : activeSegmentationReady ? "Segmentation ready" : "Segmentation needs attention"}
                  </div>
                ) : <Button
                  className="h-10 rounded-xl px-4 text-[13px] font-semibold shadow-[0_12px_28px_hsl(var(--primary)/0.18)] hover:shadow-[0_16px_34px_hsl(var(--primary)/0.22)] disabled:shadow-none"
                  disabled={!canRunSegmentation}
                  onClick={runSegmentation}
                  size="lg"
                  title={runSegmentationHint}
                  type="button"
                  variant="default"
                >
                  {running ? <Loader2 className="animate-spin" /> : <Play />}
                  {canLoadPrecomputedSegmentation ? "Show model mask" : running ? (activeRegistryCaseId ? `Running ${segmentJob?.completed_count ?? 0}/${segmentJob?.total_count ?? Math.max(1, longitudinalRows.length)}` : "Running...") : activeSegmentationReady && hasLoadedCase ? "Rerun segmentation" : "Run segmentation"}
                </Button>}
                <Button
                  aria-label="Viewer options"
                  className="h-10 rounded-xl px-3 text-[12px] font-semibold"
                  onClick={() => setShowViewerOptions((current) => !current)}
                  size="lg"
                  title="Show viewer options"
                  type="button"
                  variant={showViewerOptions ? "default" : "outline"}
                >
                  <SlidersHorizontal />
                  <span className="hidden sm:inline">Controls</span>
                </Button>
              </div>
            </div>
            <BrainTumorVisitNavigator
              activePointId={activePoint?.id ?? ""}
              baselinePointId={baselinePoint?.id ?? ""}
              onSelectActive={setActivePointId}
              points={longitudinalRows}
              samePatientLongitudinal={samePatientLongitudinal}
            />
            {alignJob || aligningAll || activeRegistration ? <div ref={alignmentPanelRef}>
              <BrainTumorAlignment
                key={alignJob?.job_id || activePoint?.sessionId}
                job={alignJob} registration={activeRegistration} points={longitudinalPoints}
                activeSessionId={activeSessionId}
                referenceLabel={baselinePoint ? visitTimeLabel(baselinePoint) : "Reference visit"}
                busy={aligningAll} error={registrationError}
              />
            </div> : null}
            {activeRegistration?.modality_volume_urls ? <div className="gbm-alignment-view">
              <div className="gbm-alignment-view-modes" role="group" aria-label="Image alignment space">
                {(["original", "aligned"] as const).map((mode) => <button
                  key={mode} type="button" aria-pressed={mode === "aligned" ? showingAligned : !showingAligned}
                  onClick={() => setAlignmentDisplay(mode)}
                  disabled={mode === "aligned" && !activeRegistration.modality_volume_urls?.[activeModality]}
                >{mode === "original" ? "Original" : "Aligned"}</button>)}
              </div>
              <span>{showingAligned ? `Reference space: ${baselinePoint ? visitTimeLabel(baselinePoint) : "Reference"} / T1c${activeRegistration.bias_correction ? " · N4 corrected" : ""}` : "Original acquisition space"}</span>
            </div> : null}
            {!activeUploadCase && !hasRequired && !canLoadPrecomputedSegmentation ? (
              <div className="border-b border-[hsl(var(--border)/0.55)] bg-[hsl(var(--background)/0.55)] px-4 py-2 text-[12px] text-[hsl(var(--muted-foreground))]">
                {runSegmentationHint}
              </div>
            ) : null}
            {segmentationJobRunning ? (
              <div className="border-b border-[hsl(var(--border)/0.55)] bg-[hsl(var(--primary)/0.055)] px-4 py-2.5">
                <div className="flex items-center justify-between gap-3 text-[11px] text-[hsl(var(--muted-foreground))]">
                  <span className="inline-flex items-center gap-1.5 font-medium text-[hsl(var(--foreground))]">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-[hsl(var(--primary))]" />
                    {segmentStageLabel(segmentJob?.stage ?? activeUploadJob?.stage)}
                  </span>
                  <span className="tabular-nums">{segmentProgressCompleted}/{segmentProgressTotal}</span>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[hsl(var(--border)/0.52)]">
                  <div className="h-full rounded-full bg-[hsl(var(--primary))] transition-all duration-500" style={{ width: `${segmentProgressPct}%` }} />
                </div>
              </div>
            ) : null}

            {showViewerOptions ? (
              <div className="flex flex-wrap items-center gap-3 border-b border-[hsl(var(--border)/0.55)] bg-[hsl(var(--background)/0.55)] px-4 py-2.5 text-[12px] text-[hsl(var(--muted-foreground))]">
                <div className="inline-flex items-center gap-1.5">
                  <span className="text-[10px] uppercase tracking-[0.12em]">Overlay</span>
                  <button
                    className={cn(
                      "rounded-xl border px-2.5 py-1 transition duration-200",
                      anyVolumeOverlay
                        ? "border-[hsl(var(--primary)/0.42)] bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--foreground))] shadow-[0_6px_18px_hsl(var(--primary)/0.08)]"
                        : "border-[hsl(var(--border)/0.66)] hover:bg-[hsl(var(--muted)/0.72)]",
                    )}
                    disabled={!activeSegmentationReady}
                    onClick={() => setAllVolumeOverlays(!anyVolumeOverlay)}
                    type="button"
                  >
                    {anyVolumeOverlay ? "On" : "Off"}
                  </button>
                </div>
                <div className="inline-flex items-center gap-1.5">
                  <span className="text-[10px] uppercase tracking-[0.12em]">Source</span>
                  {(["model", "gt"] as const).map((source) => (
                    <button
                      className={cn(
                        "rounded-xl border px-2.5 py-1 transition duration-200",
                        maskSource === source
                          ? "border-[hsl(var(--primary)/0.42)] bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--foreground))] shadow-[0_6px_18px_hsl(var(--primary)/0.08)]"
                          : "border-[hsl(var(--border)/0.66)] hover:bg-[hsl(var(--muted)/0.72)]",
                      )}
                      disabled={!activeSegmentationReady || (source === "gt" && !hasGroundTruthMask)}
                      key={source}
                      onClick={() => changeMaskSource(source)}
                      title={source === "gt" && !hasGroundTruthMask ? "No reference mask is available for this visit." : undefined}
                      type="button"
                    >
                      {source === "model" ? "Model prediction" : "Reference label"}
                    </button>
                  ))}
                </div>
                <div className="inline-flex items-center gap-1.5">
                  <span className="text-[10px] uppercase tracking-[0.12em]">Display</span>
                  {(["blend", "mask", "contour"] as ViewerMode[]).map((mode) => (
                    <button
                      className={cn(
                        "rounded-xl border px-2.5 py-1 transition duration-200",
                        volumeViewerMode === mode
                          ? "border-[hsl(var(--primary)/0.42)] bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--foreground))] shadow-[0_6px_18px_hsl(var(--primary)/0.08)]"
                          : "border-[hsl(var(--border)/0.66)] hover:bg-[hsl(var(--muted)/0.72)]",
                      )}
                      disabled={!activeSegmentationReady}
                      key={mode}
                      onClick={() => changeViewerMode(mode)}
                      type="button"
                    >
                      {mode === "mask" ? "Mask only" : mode === "contour" ? "Contour" : "Blend"}
                    </button>
                  ))}
                </div>
                <span className="max-w-xl text-[11px] leading-4">{activeSegmentationReady ? `${activeMaskSourceLabel} · ${volumeViewerMode === "mask" ? "mask only" : volumeViewerMode}. ${activeMaskSourceDetail}` : "Run segmentation to enable mask controls."}</span>
              </div>
            ) : null}

          {error ? (
            <div className="border-b border-[hsl(var(--border))] bg-[hsl(var(--destructive)/0.08)] px-3 py-2 text-[12px] text-[hsl(var(--destructive))]">
              {error}
            </div>
          ) : null}

            <div className="flex flex-wrap items-center justify-between gap-2 bg-[hsl(var(--card)/0.34)] px-4 py-3">
            {canUseVolumeViewer && reviewPlane !== "mpr" ? (
              <span className="text-[11px] text-[hsl(var(--muted-foreground))]">Scroll in any panel to move all of them together; click to place the crosshair. Change a panel's sequence or overlay with the menus above it. Window/level is per panel.</span>
            ) : (
              <ModalityChipRow
                ariaLabel="MRI sequence"
                available={activePoint ? availableModalities : modalityOrder}
                onChange={(key) => setActiveModality(key)}
                value={activeModality}
              />
            )}
            {canUseVolumeViewer ? (
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-[hsl(var(--muted-foreground))] max-lg:hidden">
                <span className="inline-flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] px-2 py-1">
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                  Drag window/level
                </span>
                <span className="rounded-lg border border-[hsl(var(--border))] px-2 py-1">Wheel scroll</span>
              </div>
            ) : (
              <label className="flex min-w-48 items-center gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
                <Layers className="h-3.5 w-3.5" />
                Overlay
                <input
                  className="w-28 accent-[hsl(var(--primary))]"
                  max={100}
                  min={0}
                  onChange={(event) => setOverlayOpacity(Number(event.target.value))}
                  type="range"
                  value={overlayOpacity}
                />
                <span className="w-8 text-right">{overlayOpacity}%</span>
              </label>
            )}
            </div>

            {canUseVolumeViewer ? <div className="flex flex-wrap items-center justify-between gap-2 bg-black px-4 py-3 text-sm text-zinc-300">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Layout">
                  <span className="pr-1 text-[11px] uppercase tracking-[0.12em] text-zinc-500">Layout</span>
                  <button
                    type="button" aria-pressed={reviewPlane === "mpr"}
                    className={cn("min-h-9 rounded-md px-3 font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white", reviewPlane === "mpr" ? "bg-zinc-200 text-zinc-950" : "text-zinc-300 hover:bg-zinc-800")}
                    onClick={() => setReviewPlane("mpr")}
                    title="Axial, coronal and sagittal views of one sequence"
                  >3 planes</button>
                  {(Object.keys(PANEL_PRESETS) as PanelPresetKey[]).map((key) => {
                    const active = reviewPlane !== "mpr" && activePanelPreset === key
                    return <button
                      key={key} type="button" aria-pressed={active}
                      className={cn("min-h-9 rounded-md px-3 font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white", active ? "bg-zinc-200 text-zinc-950" : "text-zinc-300 hover:bg-zinc-800")}
                      onClick={() => chooseLayout(key)}
                      title={PANEL_PRESETS[key].description}
                    >{PANEL_PRESETS[key].label}</button>
                  })}
                  {reviewPlane !== "mpr" ? <>
                    {activePanelPreset ? null : <span className="min-h-9 rounded-md bg-zinc-200 px-3 font-medium leading-9 text-zinc-950">Custom</span>}
                    <button
                      type="button"
                      className="min-h-9 rounded-md px-3 text-xs font-medium text-zinc-300 transition-colors hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                      disabled={reviewPanels.length >= MAX_REVIEW_PANELS}
                      onClick={addReviewPanel}
                      title="Add another panel with its own sequence and overlay"
                    >+ Panel</button>
                  </> : null}
                </div>
                {reviewPlane !== "mpr" ? <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Plane">
                  <span className="pr-1 text-[11px] uppercase tracking-[0.12em] text-zinc-500">Plane</span>
                  {(["axial", "coronal", "sagittal"] as const).map((plane) => <button
                    key={plane} type="button" aria-pressed={reviewPlane === plane}
                    className={cn("min-h-9 rounded-md px-3 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white", reviewPlane === plane ? "bg-zinc-200 text-zinc-950" : "text-zinc-300 hover:bg-zinc-800")}
                    onClick={() => choosePlane(plane)}
                  >{plane[0].toUpperCase() + plane.slice(1)}</button>)}
                </div> : null}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-xs text-zinc-400">{showingAligned ? "Aligned space" : "Original space"}</span>
                <HoldToViewMriButton
                  key={`${activeVolumeAssetUrl}-${activeSegmentationAssetUrl}-${reviewPlane}`}
                  pressed={previewOriginal}
                  disabled={!activeSegmentationReady || !activeSegmentationAssetUrl || !anyVolumeOverlay}
                  onPressedChange={setPreviewOriginal}
                />
              </div>
            </div> : null}
            <div className="bg-black px-4 pb-4">
            {canUseVolumeViewer && activeVolumeAssetUrl ? (
              <div className="w-full space-y-3">
                <CornerstoneStructuralViewer
                  activeGroup={activeTumorGroup}
                  activeLabelId={activeTumorLabelId}
                  compact
                  expandedGroups={expandedTumorGroups}
                  imageAssetUrl={activeVolumeAssetUrl}
                  key={`${activePoint?.id ?? "session"}-${maskSource}-${activeSegmentationReady ? "seg" : "image"}`}
                  onInitializationError={handleVolumeViewerError}
                  onSelectGroup={setActiveTumorGroup}
                  onSelectLabel={setActiveTumorLabelId}
                  onToggleGroupExpanded={toggleTumorGroupExpanded}
                  onToggleGroupVisibility={toggleTumorGroupVisibility}
                  onToggleLabelVisibility={toggleTumorLabelVisibility}
                  overlayModel={tumorOverlayModel}
                  panels={viewerPanels}
                  renderPanelControls={(panelId) => {
                    const panel = reviewPanels.find((item) => item.id === panelId)
                    const index = reviewPanels.findIndex((item) => item.id === panelId)
                    if (!panel) return null
                    return (
                      <ReviewPanelControls
                        available={availableModalities}
                        canRemove={reviewPanels.length > 1}
                        index={index}
                        onChange={(patch) => updateReviewPanel(panel.id, patch)}
                        onRemove={() => removeReviewPanel(panel.id)}
                        overlayEnabled={activeSegmentationReady}
                        panel={panel}
                      />
                    )
                  }}
                  segmentationAssetUrl={activeSegmentationAssetUrl ?? null}
                  setShowOverlay={(value) => (reviewPlane === "mpr" ? setShowVolumeOverlay(value) : setAllVolumeOverlays(value))}
                  setViewerMode={changeViewerMode}
                  showOverlay={showVolumeOverlay}
                  hideOverlayTemporarily={previewOriginal}
                  viewerMode={volumeViewerMode}
                  visibleLabelIds={visibleTumorLabelIds}
                />
              </div>
            ) : activeOverlayUrl ? (
              <div className="w-full max-w-4xl space-y-3">
                {volumeViewerError ? (
                  <div className="rounded-xl border border-[hsl(var(--destructive)/0.35)] bg-[hsl(var(--destructive)/0.08)] px-3 py-2 text-[12px] text-[hsl(var(--destructive))]">
                    Volume viewer fallback: {volumeViewerError}
                  </div>
                ) : null}
                <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-black shadow-[0_18px_48px_rgba(0,0,0,0.28)]">
                  <img
                    alt="Tumor segmentation overlay preview"
                    className="max-h-[32rem] w-full object-contain"
                    src={activeOverlayUrl}
                    style={{ opacity: overlayOpacity / 100 }}
                  />
                  <div className="absolute left-2 top-2 rounded bg-black/70 px-2 py-1 text-[11px] font-medium text-white">
                    {activeLabel} · {modalityMeta[activeModality].label} + {maskSource === "gt" ? "reference" : "model"} overlay
                  </div>
                  <div className="absolute bottom-2 right-2 rounded bg-black/70 px-2 py-1 text-[11px] font-medium text-white">
                    Overlay opacity {overlayOpacity}%
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 text-[12px] text-[hsl(var(--muted-foreground))]">
                  <LegendChip color={tumorPalette.et} label="Contrast-enhancing tumor" />
                  <LegendChip color={tumorPalette.wt} label="T2/FLAIR abnormality" />
                  <LegendChip color={tumorPalette.rc} label="Cavity / exclusion candidate" />
                  <LegendChip color={tumorPalette.net} label="Advanced: non-enhancing core candidate" />
                </div>
                {activePoint?.previewProvenance ? (
                  <div className="rounded-xl border border-[hsl(var(--border)/0.62)] bg-[hsl(var(--background)/0.74)] px-2 py-1 text-[11px] text-[hsl(var(--muted-foreground))]">
                    Active MRI volume with model mask overlay.
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="grid min-h-[32rem] place-items-center rounded-b-2xl bg-[radial-gradient(circle_at_50%_0%,rgba(255,255,255,0.08),transparent_34%),linear-gradient(180deg,rgba(255,255,255,0.04),transparent)] px-4 py-8">
                <div className="w-full max-w-xl space-y-4 text-center">
                  <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl border border-white/10 bg-white/8 shadow-[0_20px_44px_rgba(0,0,0,0.28)]">
                    <Brain className="h-7 w-7 text-white/70" />
                  </div>
                  <div>
                    <div className="text-[15px] font-semibold text-white">
                      {demoTimelineLoaded ? "Waiting for active case" : inputMode === "upload" ? "Modalities pending" : "Study context pending"}
                    </div>
                    <p className="mx-auto mt-1 max-w-sm text-[12px] leading-5 text-white/55">
                      The workstation will show raw MRI first, then model mask, alignment state, and report handoff as each stage becomes available.
                    </p>
                  </div>
                  <div className="grid gap-2 text-left sm:grid-cols-4">
                    <WorkflowEmptyStep label="Case" state={hasLoadedCase ? "ready" : "pending"} />
                    <WorkflowEmptyStep label="Mask" state={activeSegmentationReady ? "ready" : segmentationJobRunning ? "running" : "pending"} />
                    <WorkflowEmptyStep label="Align" state={registrationComplete ? "ready" : aligningAll ? "running" : "pending"} />
                    <WorkflowEmptyStep label="Report" state={reportEligible ? "ready" : "gated"} />
                  </div>
                </div>
              </div>
            )}
            </div>
          </SoftPanel>
        </section>

        <section aria-label="Case results" className="brain-tumor-results space-y-3">
          <BrainTumorWorkspaceNav activeTab={activeWorkspaceTab} onSelectTab={setActiveWorkspaceTab} />
          <div
            aria-labelledby={`brain-tumor-workspace-tab-${activeWorkspaceTab}`}
            className="min-w-0 space-y-4"
            id={`brain-tumor-workspace-panel-${activeWorkspaceTab}`}
            key={activeWorkspaceTab}
            role="tabpanel"
          >

          {activeWorkspaceTab === "longitudinal" ? <TrendReviewPanel
            activePointId={activePoint?.id ?? ""}
            baselinePointId={baselinePoint?.id ?? ""}
            onRegister={runRegistrationQc}
            onAlignAll={() => void runAlignAll()}
            onSelectActive={setActivePointId}
            onSelectBaseline={selectReference}
            points={longitudinalRows}
            alignJob={alignJob}
            aligningAll={aligningAll}
            biasCorrection={biasCorrection}
            onBiasCorrectionChange={setBiasCorrection}
            registrationError={registrationError}
            registeringPointId={registeringPointId}
            displayMode={preloadExampleMeta?.displayMode}
            samePatientLongitudinal={samePatientLongitudinal}
            comparisonCases={registryCases.filter((item) => item.timepoint_count > 1 && isRunnableRegistryCase(item))}
            onOpenComparisonCase={(caseId) => void runRegistryCase(caseId)}
            loadingCase={Boolean(runningRegistryCaseId)}
          /> : null}

          {activeWorkspaceTab === "report" ? (
            <SoftPanel className="brain-tumor-report overflow-hidden p-0">
              <header className="report-toolbar">
                <div className="flex min-w-0 flex-wrap items-center gap-3">
                  <h2 className="flex items-center gap-2 text-[18px] font-semibold"><FileText className="h-[18px] w-[18px]" aria-hidden="true" />Report</h2>
                  <span className="report-draft-status" role="status">
                    {draftingReport ? "Preparing draft" : reportDraftSource === "none" ? "Measurement preview" : reportDraftSource === "ai" ? "AI-assisted draft" : "Structured draft"}
                  </span>
                </div>
                <Button className="min-h-10" disabled={!activeSegmentationReady || draftingReport} onClick={() => void generateReportDraft()} type="button">
                  {draftingReport ? <Loader2 className="animate-spin" /> : <Wand2 />}
                  {draftingReport ? "Drafting..." : generatedReportText ? "Regenerate draft" : "Create draft"}
                </Button>
              </header>
              <div className="report-layout">
                <article className="report-document" aria-label="Report content" aria-busy={draftingReport}>
                  {longitudinalRows.length ? <section aria-label="Visit timing" className="report-visit-timing">
                    <h3>Visit timing</h3>
                    <dl>{longitudinalRows.map((point, index) => <div key={point.id}>
                      <dt>{samePatientLongitudinal ? "Visit" : "Scan"} {index + 1}</dt>
                      <dd><strong>{visitTimeDetail(point)}</strong><span>{visitTimingLabel(point, samePatientLongitudinal)}</span>{samePatientLongitudinal ? <span>From reference: {visitIntervalValues(point).reference}</span> : null}</dd>
                    </div>)}</dl>
                  </section> : null}
                  {!activeSegmentationReady ? (
                    <p className="report-empty">{hasLoadedCase ? "Measurements will be available after segmentation completes." : "No case selected."}</p>
                  ) : generatedReportText && reportDraftSource === "ai" ? <ReportText text={generatedReportText} /> : (
                    <>
                      <section>
                        <h3>Basic information</h3>
                        <p>{activeLabel}</p>
                      </section>
                      <section>
                        <div className="flex items-baseline justify-between gap-3">
                          <h3>Findings</h3>
                          <span className="report-unit">Volume · mm³</span>
                        </div>
                        <dl className="report-measurements">
                          {[
                            ["enhancing_tumor", "CE tumor"],
                            ["flair_abnormality", "T2/FLAIR abnormality"],
                            ["whole_tumor", "Whole abnormality"],
                            ["cavity_or_post_surgical_change", "Cavity / exclusion candidate"],
                          ].map(([region, label], index) => {
                            const value = activeVolumes.find((row) => row.region === region)?.volume_ml
                            return <div className={index < 2 ? "report-primary-measurement" : ""} key={region}>
                              <dt>{label}</dt>
                              <dd>{typeof value === "number" && Number.isFinite(value) ? formatMm3Number(value) : "Unavailable"}</dd>
                            </div>
                          })}
                        </dl>
                      </section>
                      <section>
                        <h3>Impression</h3>
                        <p>{activePointImpression(activePoint, samePatientLongitudinal || longitudinalRows.length <= 1)}</p>
                      </section>
                    </>
                  )}
                </article>
                <aside className="report-review" aria-label="Report review status">
                  <h3>QC & provenance</h3>
                  <dl>
                    <div><dt>Measurement source</dt><dd>{activeSegmentationReady ? "Model segmentation" : "Not available"}</dd></div>
                    <div><dt>Selected scan</dt><dd>{hasLoadedCase ? activeDate : "None"}</dd></div>
                    <div><dt>Mask review</dt><dd>{hasLoadedCase ? reviewStateLabel(activeReviewState) : "Not started"}</dd></div>
                    {activeQcReasons.length ? <div><dt>Review flags</dt><dd>{activeQcReasons.map(qcReasonLabel).join("; ")}</dd></div> : null}
                    {registrationRequired ? <div><dt>Longitudinal alignment</dt><dd>{alignmentProgressCompleted}/{alignmentProgressTotal} visits, including reference</dd></div> : null}
                  </dl>
                  <div className={cn("report-review-note", reportEligible && "report-review-passed")}>
                    {reportEligible ? <CheckCircle2 aria-hidden="true" /> : <Eye aria-hidden="true" />}
                    <p>{reportEligible ? "QC passed for this scan." : activeReviewState === "needs_revision" || activeReviewState === "excluded" ? "Review flags must be resolved before handoff." : "Human review is required before handoff."}</p>
                  </div>
                  <Button className="min-h-10 w-full" disabled={!activeSegmentationReady} onClick={() => setActiveWorkspaceTab("review")} variant="outline" type="button"><Eye />Review mask</Button>
                  <p className="report-research-note">Research preview. Not a diagnostic report.</p>
                </aside>
              </div>
              {reportError ? <p className="report-notice" role="status">{reportError}</p> : null}
              <footer className="report-export">
                <span>{generatedReportText ? "Export draft" : "Export measurements"}</span>
                <div className="flex flex-wrap gap-2">
                  <Button disabled={!activeSegmentationReady || draftingReport} onClick={() => void downloadHtmlReport()} size="sm" type="button" variant="outline"><Download />HTML</Button>
                  <Button disabled={!activeSegmentationReady || draftingReport} onClick={copyReport} size="sm" type="button" variant="outline"><Clipboard />Copy</Button>
                  <Button disabled={!activeSegmentationReady || draftingReport} onClick={downloadReport} size="sm" type="button" variant="outline"><Download />TXT</Button>
                  <Button disabled={!activeSegmentationReady} onClick={downloadMeasurementsCsv} size="sm" type="button" variant="outline"><Download />CSV</Button>
                </div>
              </footer>
            </SoftPanel>
          ) : null}
          {activeWorkspaceTab === "review" && activeSegmentationReady ? <SoftPanel className="p-3">
            <RanoMetricsBoard activePoint={activePoint} referencePointId={baselinePoint?.id} points={longitudinalRows.every((point) => point.volumes.length > 0) ? longitudinalRows : activePoint ? [activePoint] : []} volumes={activeVolumes} />
            {longitudinalRows.some((point) => !point.volumes.length) ? <p className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">Longitudinal comparisons pending remaining measurements.</p> : null}
          </SoftPanel> : null}

          {activeWorkspaceTab === "review" ? <SoftPanel className="overflow-hidden p-0">
            <div className="border-b border-[hsl(var(--border)/0.52)] bg-[hsl(var(--card)/0.68)] px-3 py-3">
              <SectionTitle icon={Eye} label="Mask QC" compact />
            </div>
            <div className="space-y-3 px-3 py-3">
              <div className="rounded-3xl border border-[hsl(var(--border)/0.5)] bg-[hsl(var(--background)/0.56)] p-2.5 shadow-[inset_0_1px_0_hsl(var(--card)/0.86)]">
                <div className="mb-2 text-[12px] text-[hsl(var(--muted-foreground))]">{reviewStateLabel(activeReviewState)}</div>
                <div className="grid grid-cols-3 gap-1.5">
                  <ReviewButton active={activeReviewState === "accepted"} disabled={!activeSegmentationReady} icon={CheckCircle2} label="Pass" onClick={() => updateReviewState("accepted")} />
                  <ReviewButton active={activeReviewState === "needs_revision"} disabled={!activeSegmentationReady} icon={RefreshCw} label="Flag" onClick={() => updateReviewState("needs_revision")} />
                  <ReviewButton active={activeReviewState === "excluded"} disabled={!activeSegmentationReady} icon={XCircle} label="Exclude" onClick={() => updateReviewState("excluded")} />
                </div>
                <div className="mt-2 text-[11px] leading-4 text-[hsl(var(--muted-foreground))]">
                  Review the displayed mask before drafting or exporting the handoff.
                </div>
                {activeReviewState === "needs_revision" || activeReviewState === "excluded" ? (
                  <div className="mt-3 space-y-2">
                    <div className="text-[10px] font-medium uppercase tracking-[0.12em] text-[hsl(var(--muted-foreground))]">Reason</div>
                    <div className="flex flex-wrap gap-1.5">
                      {qcReasonOptions.map((reason) => (
                        <button
                          className={cn(
                            "rounded-xl border px-2.5 py-1 text-[11px] transition duration-200",
                            activeQcReasons.includes(reason.key)
                              ? "border-[hsl(var(--primary)/0.58)] bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--primary))] shadow-[0_8px_20px_hsl(var(--primary)/0.07)]"
                              : "border-[hsl(var(--border)/0.66)] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted)/0.72)] hover:text-[hsl(var(--foreground))]",
                          )}
                          disabled={!hasLoadedCase}
                          key={reason.key}
                          onClick={() => toggleQcReason(reason.key)}
                          type="button"
                        >
                          {reason.label}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </SoftPanel> : null}

          {activeWorkspaceTab === "report" ? <SoftPanel className="p-3">
            <details>
              <summary className="cursor-pointer text-[13px] font-medium text-[hsl(var(--foreground))]">Technical details</summary>
              <div className="mt-3 space-y-3">
                <div className="space-y-2 text-[12px] text-[hsl(var(--muted-foreground))]">
                  <MetricLine label="Model" value={displayModel} />
                  <MetricLine label="Service" value={service.data?.ready ? "Ready" : service.data?.error ? "Unavailable" : "Checking"} />
                  <MetricLine label="Inputs" value={`${requiredReadyCount}/4`} />
                  <MetricLine label="Mode" value={activePoint ? "case-ready" : session?.service.mode ?? "Pending"} />
                </div>
                <ModalityReadiness activeLoaded={Boolean(activePoint)} files={files} inputMode={inputMode} mapping={mapping} session={session} />
                <div className="grid gap-2">
                  <ExportLink href={activeArtifactUrls.volumes_csv} label="Volumes CSV" />
                  <ExportLink href={activeArtifactUrls.tumor_regions} label="Region JSON" />
                  <ExportLink href={activeArtifactUrls.seg} label="Segmentation NIfTI" />
                  <ExportLink href={activeArtifactUrls.overlay_preview} label="Overlay PNG" />
                  <ExportLink href={activeArtifactUrls.gt_seg} label="Reference NIfTI" />
                  <ExportLink href={activeArtifactUrls.overlay_gt} label="Reference overlay" />
                  <ExportLink href={activeArtifactUrls.volumes_gt_csv} label="Reference volumes" />
                </div>
                {activeWarnings.length ? (
                  <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-2 text-[12px] text-[hsl(var(--muted-foreground))]">
                    {activeWarnings.map((warning) => <div key={warning}>{warning}</div>)}
                  </div>
                ) : null}
              </div>
            </details>
          </SoftPanel> : null}
          </div>
        </section>
      </main>

      {uploadPanelOpen ? (
        <UploadCaseDialog
          error={error}
          onClearError={() => setError(null)}
          uploadedCases={displayedUploadedCases}
          selectedCaseId={selectedUploadCaseId}
          onClose={() => { if (!uploadingCase) setUploadPanelOpen(false) }}
          onSubmit={(visits, targetCaseId) => void submitUploadedCase(visits, targetCaseId)}
          submitting={uploadingCase}
          progress={uploadProgress}
        />
      ) : null}
    </div>
  )
}


function BrainTumorVisitNavigator({
  activePointId,
  baselinePointId,
  onSelectActive,
  points,
  samePatientLongitudinal,
}: {
  activePointId: string
  baselinePointId: string
  onSelectActive: (pointId: string) => void
  points: LongitudinalRow[]
  samePatientLongitudinal: boolean
}) {
  if (!points.length) return null
  const activeIndex = points.findIndex((point) => point.id === activePointId)
  const noun = samePatientLongitudinal ? "Visit" : "Scan"
  const isReference = (id: string) => samePatientLongitudinal && id === baselinePointId
  // Supplied labels show as text; only dates or numeric days ever become intervals.
  const dateLabel = (point: LongitudinalRow) => visitDisplayLabel(point) ?? point.stageLabel ?? ""
  const move = (offset: number) => {
    const point = activeIndex >= 0 ? points[activeIndex + offset] : undefined
    if (point) onSelectActive(point.id)
  }

  return (
    <nav aria-label="Scan visits" className="brain-tumor-visit-nav">
      <VisitTimingSummary points={points} activePointId={activePointId} baselinePointId={baselinePointId} samePatient={samePatientLongitudinal} />
      {points.length > 1 ? (
        <div className={cn("visit-controls", points.length > 8 && "visit-controls-many")}>
          <button aria-label={`Previous ${noun.toLowerCase()}`} className="visit-arrow" disabled={activeIndex <= 0} onClick={() => move(-1)} title={`Previous ${noun.toLowerCase()}`} type="button"><ChevronLeft aria-hidden="true" /></button>
          <div aria-label="Choose a scan" className="visit-options" role="group">
            {points.map((point, index) => (
              <button
                aria-label={`View ${noun.toLowerCase()} ${index + 1}${dateLabel(point) ? `, ${dateLabel(point)}` : ""}${isReference(point.id) ? ", reference" : ""}`}
                aria-pressed={point.id === activePointId}
                className="visit-option"
                key={point.id}
                onClick={() => onSelectActive(point.id)}
                title={`${point.label}${point.dateLabel ? ` · ${point.dateLabel}` : ""}${isReference(point.id) ? " · Alignment reference" : ""}`}
                type="button"
              >
                <span>{noun} {index + 1}{isReference(point.id) ? <Pin aria-hidden="true" /> : null}</span>
                {dateLabel(point) ? <small>{dateLabel(point)}</small> : null}
                {samePatientLongitudinal && !point.firstVisit && point.intervalDays != null ? <small>{`${formatDay(point.intervalDays)}d since prior`}</small> : null}
              </button>
            ))}
          </div>
          <select aria-label="Viewing scan" className="visit-select" onChange={(event) => onSelectActive(event.currentTarget.value)} value={activePointId}>
            {activeIndex < 0 ? <option disabled value="">Select a scan</option> : null}
            {points.map((point, index) => <option key={point.id} value={point.id}>{noun} {index + 1}{dateLabel(point) ? ` · ${dateLabel(point)}` : ""}{isReference(point.id) ? " · Reference" : ""}</option>)}
          </select>
          <button aria-label={`Next ${noun.toLowerCase()}`} className="visit-arrow" disabled={activeIndex < 0 || activeIndex >= points.length - 1} onClick={() => move(1)} title={`Next ${noun.toLowerCase()}`} type="button"><ChevronRight aria-hidden="true" /></button>
        </div>
      ) : null}
    </nav>
  )
}

function SoftPanel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section
      className={cn(
        "rounded-2xl border border-[hsl(var(--border)/0.58)] bg-[hsl(var(--card)/0.88)] shadow-[0_1px_0_hsl(var(--background)/0.9),0_18px_48px_hsl(var(--foreground)/0.045)] backdrop-blur-sm",
        className,
      )}
    >
      {children}
    </section>
  )
}

function BrainTumorWorkspaceNav({
  activeTab,
  onSelectTab,
}: {
  activeTab: BrainTumorWorkspaceTab
  onSelectTab: (tab: BrainTumorWorkspaceTab) => void
}) {
  function selectAdjacentTab(event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) {
    let nextIndex: number | null = null
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % brainTumorWorkspaceTabs.length
    if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + brainTumorWorkspaceTabs.length) % brainTumorWorkspaceTabs.length
    if (event.key === "Home") nextIndex = 0
    if (event.key === "End") nextIndex = brainTumorWorkspaceTabs.length - 1
    if (nextIndex === null) return

    event.preventDefault()
    onSelectTab(brainTumorWorkspaceTabs[nextIndex].id)
    const tabButtons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
    tabButtons?.[nextIndex]?.focus()
  }

  return (
    <nav
      aria-label="Brain tumor workspace"
      className="shrink-0 rounded-lg border border-[hsl(var(--border)/0.68)] bg-[hsl(var(--card)/0.92)]"
    >
      <div aria-label="Workspace views" className="grid grid-cols-[1fr_1.4fr_1fr] gap-1 p-1" role="tablist">
        {brainTumorWorkspaceTabs.map((tab, index) => {
          const Icon = tab.icon
          const isActive = activeTab === tab.id
          return (
            <button
              aria-controls={`brain-tumor-workspace-panel-${tab.id}`}
              aria-label={`${tab.label}: ${tab.description}`}
              aria-selected={isActive}
              className={cn(
                "group flex min-h-11 min-w-0 cursor-pointer items-center justify-center gap-1.5 rounded-md border px-2 text-[13px] font-semibold transition-colors duration-150 focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-offset-1",
                isActive
                  ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] shadow-[0_3px_10px_hsl(var(--primary)/0.18)]"
                  : "border-transparent text-[hsl(var(--muted-foreground))] hover:border-[hsl(var(--border))] hover:bg-[hsl(var(--background))] hover:text-[hsl(var(--foreground))]",
              )}
              id={`brain-tumor-workspace-tab-${tab.id}`}
              key={tab.id}
              onClick={() => onSelectTab(tab.id)}
              onKeyDown={(event) => selectAdjacentTab(event, index)}
              role="tab"
              tabIndex={isActive ? 0 : -1}
              type="button"
            >
              <Icon aria-hidden="true" className="h-4 w-4 shrink-0" strokeWidth={isActive ? 2.2 : 1.8} />
              <span className="whitespace-nowrap">{tab.label}</span>
            </button>
          )
        })}
      </div>
    </nav>
  )
}

function ClinicalContextRail({
  activeDate,
  activeLabel,
  activeReviewState,
  activeSegmentationReady,
  aligningAll,
  baselineReady,
  hasGroundTruthMask,
  hasLoadedCase,
  registrationComplete,
  registrationRequired,
  reportEligible,
  latestPoint,
  points,
  samePatientLongitudinal,
  segmentJobRunning,
  segmentProgressCompleted,
  segmentProgressPct,
  segmentProgressTotal,
}: {
  activeDate: string
  activeLabel: string
  activeReviewState: ReviewState
  activeSegmentationReady: boolean
  aligningAll: boolean
  baselineReady: boolean
  hasGroundTruthMask: boolean
  hasLoadedCase: boolean
  registrationComplete: boolean
  registrationRequired: boolean
  reportEligible: boolean
  latestPoint?: LongitudinalRow
  points: LongitudinalRow[]
  samePatientLongitudinal: boolean
  segmentJobRunning: boolean
  segmentProgressCompleted: number
  segmentProgressPct: number
  segmentProgressTotal: number
}) {
  const singleScan = points.length <= 1
  const trendLabel = latestPoint && !latestPoint.volumes.length
    ? "Measurements pending"
    : latestPoint
    ? singleScan
      ? "Baseline"
      : samePatientLongitudinal
      ? `${formatPct(latestPoint.etChangePct)} CE`
      : "Cohort view"
    : "No trend"
  const trendDetail = latestPoint
    ? singleScan
      ? "No prior comparison"
      : samePatientLongitudinal
      ? `${latestPoint.dateLabel || "Latest scan"} vs reference`
      : `${points.length} case${points.length === 1 ? "" : "s"}`
    : "Open a case"
  const states = [
    { detail: hasLoadedCase ? `${points.length || 1} scan${(points.length || 1) === 1 ? "" : "s"}` : "awaiting source", label: "Raw input", state: hasLoadedCase ? "complete" : "pending" },
    { detail: activeSegmentationReady ? "available" : "run required", label: "Model mask", state: activeSegmentationReady ? "complete" : "blocked" },
    { detail: hasGroundTruthMask ? "available" : "not provided", label: "Reference label", state: hasGroundTruthMask ? "complete" : "pending" },
    { detail: !registrationRequired && baselineReady ? "not required" : registrationComplete ? "complete" : baselineReady ? "pending" : "not set", label: "Registration", state: registrationComplete ? "complete" : "pending" },
    { detail: reviewStateLabel(activeReviewState), label: "Your review", state: activeReviewState === "accepted" ? "complete" : activeReviewState === "pending" ? "pending" : "blocked" },
    { detail: reportEligible ? "ready" : "gated", label: "Report eligible", state: reportEligible ? "complete" : "blocked" },
  ] satisfies Array<{ detail: string; label: string; state: "blocked" | "complete" | "pending" }>
  const nextAction = !hasLoadedCase
    ? { detail: "Select from worklist", label: "Open case" }
    : segmentJobRunning
      ? { detail: `${segmentProgressCompleted}/${segmentProgressTotal} visits`, label: "Segmenting" }
      : !activeSegmentationReady
        ? { detail: `${points.length || 1} image${(points.length || 1) === 1 ? "" : "s"} loaded`, label: "Run segmentation" }
        : aligningAll
          ? { detail: "Registration queue active", label: "Aligning visits" }
          : registrationRequired && !registrationComplete
            ? { detail: "Use shared reference", label: "Align visits" }
            : activeReviewState !== "accepted"
              ? { detail: reviewStateLabel(activeReviewState), label: "Review mask" }
              : reportEligible
                ? { detail: "Draft/export enabled", label: "Report handoff" }
                : { detail: "QC gate pending", label: "Report gated" }

  return (
    <section className="overflow-hidden rounded-3xl border border-[hsl(var(--border)/0.58)] bg-[hsl(var(--card)/0.74)] shadow-[0_16px_44px_hsl(var(--foreground)/0.045),inset_0_1px_0_hsl(var(--background)/0.76)]">
      <div className="grid gap-0 lg:grid-cols-[minmax(14rem,0.92fr)_minmax(0,2.15fr)] lg:items-stretch">
        <div className="min-w-0 border-b border-[hsl(var(--border)/0.52)] bg-[hsl(var(--background)/0.36)] px-4 py-3 lg:border-b-0 lg:border-r">
          <div className="truncate text-[13px] font-semibold text-[hsl(var(--foreground))]">{activeLabel}</div>
          <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-[hsl(var(--muted-foreground))]">
            <span>{activeDate}</span>
            <span>{trendLabel}</span>
            <span>{trendDetail}</span>
          </div>
          <div className="mt-3 rounded-2xl border border-[hsl(var(--border)/0.58)] bg-[hsl(var(--card)/0.78)] p-2.5 shadow-[inset_0_1px_0_hsl(var(--background)/0.72)]">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-[10px] font-medium uppercase tracking-[0.12em] text-[hsl(var(--muted-foreground))]">Next action</div>
                <div className="mt-0.5 truncate text-[13px] font-semibold text-[hsl(var(--foreground))]">{nextAction.label}</div>
              </div>
              <StepDot compact index={1} status={reportEligible ? "complete" : hasLoadedCase ? "active" : "pending"} />
            </div>
            <div className="mt-1 truncate text-[11px] text-[hsl(var(--muted-foreground))]">{nextAction.detail}</div>
            {segmentJobRunning ? (
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[hsl(var(--border)/0.52)]">
                <div className="h-full rounded-full bg-[hsl(var(--primary))] transition-all duration-500" style={{ width: `${segmentProgressPct}%` }} />
              </div>
            ) : null}
          </div>
        </div>
        <div className="grid gap-1.5 p-3 sm:grid-cols-3 2xl:grid-cols-6">
          {states.map((item) => (
            <CaseStateItem key={item.label} {...item} />
          ))}
        </div>
      </div>
    </section>
  )
}

function CaseStateItem({ detail, label, state }: { detail: string; label: string; state: "blocked" | "complete" | "pending" }) {
  const stateClass = {
    blocked: "border-[hsl(var(--destructive)/0.34)] text-[hsl(var(--destructive))]",
    complete: "border-[hsl(var(--status-ok)/0.36)] text-[hsl(var(--status-ok))]",
    pending: "border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))]",
  }[state]
  return (
    <div className={cn("min-w-0 rounded-xl border bg-[hsl(var(--background)/0.5)] px-3 py-2.5 shadow-[inset_0_1px_0_hsl(var(--background)/0.7)]", stateClass)}>
      <div className="truncate text-[12px] font-semibold leading-4 text-[hsl(var(--foreground))]">{label}</div>
      <div className="mt-1 truncate text-[12px] leading-4 tabular-nums">{detail}</div>
    </div>
  )
}

type RanoMetricRegion = "enhancing_tumor" | "flair_abnormality" | "whole_tumor" | "cavity_or_post_surgical_change"
type RanoCompareMode = "reference" | "previous" | "peak"

type RanoMeasurementRow = {
  color: string
  compactLabel: string
  currentValue: number
  label: string
  latestValue: number
  peakPoint?: LongitudinalRow
  peakValue: number
  referenceValue: number
  region: RanoMetricRegion
  values: number[]
}

function RanoMetricsBoard({
  activePoint,
  referencePointId,
  points,
  volumes,
}: {
  activePoint?: LongitudinalRow
  referencePointId?: string
  points: LongitudinalRow[]
  volumes: Array<{ region: string; volume_ml: number; voxel_count?: number }>
}) {
  const [selectedRegion, setSelectedRegion] = useState<RanoMetricRegion>("enhancing_tumor")
  const [compareMode, setCompareMode] = useState<RanoCompareMode>("reference")
  const referencePoint = points.find((point) => point.id === referencePointId) ?? points[0]
  const latestPoint = points[points.length - 1]
  const matchedActiveIndex = activePoint
    ? points.findIndex((point) => point.id === activePoint.id || (point.sessionId && point.sessionId === activePoint.sessionId))
    : -1
  const activePointIndex = matchedActiveIndex >= 0 ? matchedActiveIndex : Math.max(0, points.length - 1)
  const previousPoint = activePointIndex > 0 ? points[activePointIndex - 1] : undefined
  const hasComparison = points.length > 1
  const effectiveCompareMode: RanoCompareMode = compareMode === "previous" && !previousPoint ? "reference" : compareMode

  const measurementRows: RanoMeasurementRow[] = ([
    { color: "#c65166", compactLabel: "CE", region: "enhancing_tumor" },
    { color: "#2f7fa7", compactLabel: "FLAIR", region: "flair_abnormality" },
    { color: "#665d83", compactLabel: "Whole", region: "whole_tumor" },
    { color: "#9a7138", compactLabel: "Cavity", region: "cavity_or_post_surgical_change" },
  ] satisfies Array<{ color: string; compactLabel: string; region: RanoMetricRegion }>).map((item) => {
    const fallbackValue = Number(volumes.find((volume) => volume.region === item.region)?.volume_ml ?? 0)
    const valuesWithPoints = points.map((point) => ({ point, value: getRegionMl(point, item.region) }))
    const peak = valuesWithPoints.reduce(
      (best, candidate) => candidate.value > best.value ? candidate : best,
      valuesWithPoints[0] ?? { point: activePoint, value: fallbackValue },
    )
    return {
      ...item,
      currentValue: activePoint ? getRegionMl(activePoint, item.region) : fallbackValue,
      label: regionLabels[item.region],
      latestValue: latestPoint ? getRegionMl(latestPoint, item.region) : fallbackValue,
      peakPoint: peak.point,
      peakValue: peak.value,
      referenceValue: referencePoint ? getRegionMl(referencePoint, item.region) : fallbackValue,
      values: valuesWithPoints.map((entry) => entry.value),
    }
  })

  const selectedRow = measurementRows.find((row) => row.region === selectedRegion) ?? measurementRows[0]
  const comparisonPoint = effectiveCompareMode === "reference"
    ? referencePoint
    : effectiveCompareMode === "previous"
      ? previousPoint
      : selectedRow.peakPoint
  const comparisonValue = effectiveCompareMode === "reference"
    ? selectedRow.referenceValue
    : effectiveCompareMode === "previous"
      ? getRegionMl(previousPoint, selectedRow.region)
      : selectedRow.peakValue
  const comparisonIsSelected = Boolean(
    activePoint
    && comparisonPoint
    && (activePoint.id === comparisonPoint.id || (activePoint.sessionId && activePoint.sessionId === comparisonPoint.sessionId)),
  )
  const absoluteDelta = selectedRow.currentValue - comparisonValue
  const relativeDelta = comparisonIsSelected ? null : percentChange(selectedRow.currentValue, comparisonValue)
  const selectedScanLabel = activePoint ? visitTimeLabel(activePoint) : "Selected scan"
  const selectedScanRole = activePoint?.id === referencePoint?.id ? "Reference" : activePoint ? roleLabelCompact(activePoint.role) : "current"
  const comparisonLabel = effectiveCompareMode === "reference" ? "Reference" : effectiveCompareMode === "previous" ? "Previous" : "Peak"
  const hasMeasuredVolume = Math.max(selectedRow.currentValue, selectedRow.referenceValue, selectedRow.peakValue, selectedRow.latestValue) > 0

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[hsl(var(--border)/0.62)] pb-3">
        <div>
          <SectionTitle icon={Brain} label="Quantitative tumor burden" compact />
          <div className="mt-1 text-[11px] text-[hsl(var(--muted-foreground))]">Model-derived measurements · mm³</div>
        </div>
        <div className="text-right">
          <div className="text-[11px] font-semibold text-[hsl(var(--foreground))]">{selectedScanLabel}</div>
          <div className="mt-0.5 text-[9px] font-medium uppercase tracking-[0.1em] text-[hsl(var(--muted-foreground))]">{selectedScanRole}</div>
        </div>
      </div>

      <div className="space-y-3 py-3">
        <div aria-label="Tumor burden metric" className="rano-metric-selector grid grid-cols-[repeat(auto-fit,minmax(7.5rem,1fr))] gap-2" role="tablist">
          {measurementRows.map((row) => {
            const selected = row.region === selectedRow.region
            return (
              <button
                aria-controls="rano-selected-metric"
                aria-selected={selected}
                className={cn(
                  "rano-metric-tab min-h-11 min-w-0 rounded-lg border px-3 py-2.5 text-left transition-[background-color,border-color,box-shadow] duration-150 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
                  selected
                    ? "font-semibold"
                    : "font-medium",
                )}
                id={`rano-metric-${row.region}`}
                key={row.region}
                onClick={() => setSelectedRegion(row.region)}
                role="tab"
                type="button"
              >
                <div className="flex items-center gap-1.5">
                  <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full" style={{ backgroundColor: row.color }} />
                  <span className="truncate text-xs font-semibold">{row.compactLabel}</span>
                </div>
                <div className="mt-1 truncate text-[13px] font-semibold tabular-nums">
                  {row.currentValue > 0 ? <>{formatCompactMm3(row.currentValue)} <span className="text-[11px] font-normal">mm³</span></> : "Not detected"}
                </div>
              </button>
            )
          })}
        </div>

        <section
          aria-labelledby={`rano-metric-${selectedRow.region}`}
          className="px-1 py-3"
          id="rano-selected-metric"
          role="tabpanel"
        >
          <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,15rem),1fr))] gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="h-5 w-1 rounded-full" style={{ backgroundColor: selectedRow.color }} />
                <div>
                  <div className="text-[13px] font-semibold text-[hsl(var(--foreground))]">{selectedRow.label}</div>
                  <div className="text-[9px] font-medium uppercase tracking-[0.1em] text-[hsl(var(--muted-foreground))]">Selected measurement</div>
                </div>
              </div>

              {hasMeasuredVolume ? <>
                <div className="mt-3 text-[30px] font-semibold leading-none tabular-nums text-[hsl(var(--foreground))]">
                  {formatMm3Number(selectedRow.currentValue)}
                  <span className="ml-1 text-[11px] font-normal text-[hsl(var(--muted-foreground))]">mm³</span>
                </div>
                <RanoChangeSummary
                  absoluteDelta={absoluteDelta}
                  color={selectedRow.color}
                  comparisonIsSelected={comparisonIsSelected}
                  comparisonLabel={comparisonLabel}
                  comparisonPoint={comparisonPoint}
                  relativeDelta={relativeDelta}
                />
              </> : (
                <div className="mt-3 text-[13px] font-medium text-[hsl(var(--muted-foreground))]">Not detected in the selected mask</div>
              )}

              {hasComparison ? (
                <Tabs className="mt-3" onValueChange={(value) => setCompareMode(value as RanoCompareMode)} value={effectiveCompareMode}>
                  <div className="mb-1.5 text-[9px] font-medium uppercase tracking-[0.1em] text-[hsl(var(--muted-foreground))]">Compare against</div>
                  <TabsList className="grid h-8 w-full grid-cols-3 rounded-lg bg-[hsl(var(--muted)/0.42)] p-0.5">
                    <TabsTrigger className="h-7 rounded-md px-1.5 text-[10px] data-[state=active]:shadow-sm" value="reference">Reference</TabsTrigger>
                    <TabsTrigger className="h-7 rounded-md px-1.5 text-[10px] data-[state=active]:shadow-sm" disabled={!previousPoint} value="previous">Previous</TabsTrigger>
                    <TabsTrigger className="h-7 rounded-md px-1.5 text-[10px] data-[state=active]:shadow-sm" value="peak">Peak</TabsTrigger>
                  </TabsList>
                </Tabs>
              ) : null}
            </div>

            <div className="min-w-0 pt-1">
              <div className="flex items-center justify-between gap-3">
                <span className="text-[10px] font-medium uppercase tracking-[0.1em] text-[hsl(var(--muted-foreground))]">Volume over time</span>
                <span className="text-[10px] tabular-nums text-[hsl(var(--muted-foreground))]">
                  {points.length === 0 ? "No scans" : `${points.length} scan${points.length === 1 ? "" : "s"}`}
                </span>
              </div>
              {points.length > 0 ? (
                <>
                  <RanoTrendPreview activeIndex={activePointIndex} color={selectedRow.color} label={selectedRow.label} points={points} values={selectedRow.values} />
                  <div className="mt-1 flex items-center justify-between gap-3 text-[9px] text-[hsl(var(--muted-foreground))]">
                    <span className="truncate">{referencePoint?.dateLabel || "Reference"}</span>
                    <span className="truncate text-right">Selected · {selectedScanLabel}</span>
                  </div>
                </>
              ) : (
                <div className="mt-3 grid min-h-24 place-items-center rounded-md border border-dashed border-[hsl(var(--border))] px-4 text-center text-xs text-[hsl(var(--muted-foreground))]">
                  Open a case to view the longitudinal trend.
                </div>
              )}
            </div>
          </div>
        </section>

        <details open className="group border-t border-[hsl(var(--border)/0.52)] pt-2">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-lg px-1 py-1.5 text-[11px] font-semibold text-[hsl(var(--foreground))] outline-none transition hover:text-[hsl(var(--primary))] focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] [&::-webkit-details-marker]:hidden">
            <span>Measurement details <span className="ml-1 font-normal text-[hsl(var(--muted-foreground))]">mm³</span></span>
            <ChevronDown aria-hidden="true" className="size-3.5 text-[hsl(var(--muted-foreground))] transition-transform group-open:rotate-180" strokeWidth={1.8} />
          </summary>
          <Table className="mt-1 min-w-[360px] text-[11px]">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="h-8 pl-1">Metric</TableHead>
                <TableHead className="h-8 text-right">Selected</TableHead>
                <TableHead className="h-8 text-right">Reference</TableHead>
                <TableHead className="h-8 text-right">Peak</TableHead>
                <TableHead className="h-8 pr-1 text-right">Latest</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {measurementRows.map((row) => (
                <TableRow key={row.region}>
                  <TableCell className="py-2 pl-1 font-medium">
                    <span className="mr-1.5 inline-block size-1.5 rounded-full align-middle" style={{ backgroundColor: row.color }} />
                    {row.compactLabel}
                  </TableCell>
                  <TableCell className="py-2 text-right tabular-nums">{formatMm3Number(row.currentValue)}</TableCell>
                  <TableCell className="py-2 text-right tabular-nums">{formatMm3Number(row.referenceValue)}</TableCell>
                  <TableCell className="py-2 text-right tabular-nums">{formatMm3Number(row.peakValue)}</TableCell>
                  <TableCell className="py-2 pr-1 text-right tabular-nums">{formatMm3Number(row.latestValue)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </details>

        <div className="px-1 text-[10px] leading-4 text-[hsl(var(--muted-foreground))]">
          Volumes use model masks and voxel spacing, including when viewing reference labels. Directional change alone does not establish treatment response.
        </div>
      </div>
    </div>
  )
}

function RanoChangeSummary({
  absoluteDelta,
  color,
  comparisonIsSelected,
  comparisonLabel,
  comparisonPoint,
  relativeDelta,
}: {
  absoluteDelta: number
  color: string
  comparisonIsSelected: boolean
  comparisonLabel: string
  comparisonPoint?: LongitudinalRow
  relativeDelta: number | null
}) {
  if (comparisonIsSelected) {
    return (
      <div className="mt-3 inline-flex items-center rounded-full border border-[hsl(var(--border)/0.56)] bg-[hsl(var(--card)/0.72)] px-2.5 py-1 text-[10px] font-medium text-[hsl(var(--muted-foreground))]">
        {comparisonLabel} scan · no interval comparison
      </div>
    )
  }

  const direction = Math.abs(absoluteDelta) < 0.0005 ? "flat" : absoluteDelta > 0 ? "up" : "down"
  const DirectionIcon = direction === "up" ? ArrowUpRight : direction === "down" ? ArrowDownRight : Minus
  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="inline-flex items-center gap-1 text-[13px] font-semibold tabular-nums text-[hsl(var(--foreground))]">
          <DirectionIcon aria-hidden="true" className="size-3.5" style={{ color }} strokeWidth={2} />
          {formatSignedMm3(absoluteDelta)}
        </span>
        <span className="text-[11px] font-medium tabular-nums text-[hsl(var(--muted-foreground))]">{formatPct(relativeDelta)}</span>
      </div>
      <div className="mt-1 text-[10px] text-[hsl(var(--muted-foreground))]">
        vs {comparisonLabel.toLowerCase()}{comparisonPoint?.dateLabel ? ` · ${comparisonPoint.dateLabel}` : ""}
      </div>
    </div>
  )
}

function RanoTrendPreview({
  activeIndex,
  color,
  label,
  points,
  values,
}: {
  activeIndex: number
  color: string
  label: string
  points: LongitudinalRow[]
  values: number[]
}) {
  const chartWidth = 320
  const chartHeight = 82
  const maxValue = Math.max(1, ...values)
  const time = timelineScale(points)
  const xFor = (index: number) => 10 + time.positions[index] * (chartWidth - 20)
  const yFor = (value: number) => chartHeight - 10 - (Math.max(0, value) / maxValue) * (chartHeight - 24)
  const chartPoints = values.map((value, index) => ({ x: xFor(index), y: yFor(value) }))
  const path = chartPoints.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ")
  const areaPath = chartPoints.length
    ? `${path} L ${chartPoints[chartPoints.length - 1].x} ${chartHeight - 8} L ${chartPoints[0].x} ${chartHeight - 8} Z`
    : ""

  return (
    <div>
    <svg aria-label={`${label} volume trend across ${values.length} scan${values.length === 1 ? "" : "s"}`} data-time-axis={time.mode} className="mt-2 h-[5.25rem] w-full overflow-visible" role="img" viewBox={`0 0 ${chartWidth} ${chartHeight}`}>
      <path d={areaPath} fill={color} opacity="0.08" />
      <path d={path} fill="none" opacity="0.14" stroke={color} strokeLinecap="round" strokeLinejoin="round" strokeWidth="7" />
      <path d={path} fill="none" opacity="0.9" stroke={color} strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.4" />
      {chartPoints.map((point, index) => {
        const selected = index === activeIndex
        return (
          <g key={`${points[index]?.id || index}-${values[index]}`}>
            <title>{`${visitTimeLabel(points[index], index)}: ${formatMm3(values[index])}`}</title>
            {selected ? <circle cx={point.x} cy={point.y} fill="hsl(var(--card))" r="6" stroke="hsl(var(--primary))" strokeWidth="2" /> : null}
            <circle cx={point.x} cy={point.y} fill="hsl(var(--card))" r={selected ? 3.5 : 3} stroke={color} strokeWidth="2" />
          </g>
        )
      })}
    </svg>
    <div className="mt-1 text-[10px] text-[hsl(var(--muted-foreground))]">{time.label}</div>
    </div>
  )
}

function getRegionMl(point: LongitudinalRow | undefined, region: string): number {
  if (!point) return 0
  if (region === "enhancing_tumor") return point.etMl
  if (region === "flair_abnormality") return point.flairMl
  if (region === "whole_tumor") return point.wtMl
  if (region === "cavity_or_post_surgical_change") return point.rcMl
  if (region === "non_enhancing_core_candidate") return point.netMl
  if (region === "tumor_core") return point.tcMl
  return 0
}

function StatusDot({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[11px]", ok ? "text-[hsl(var(--status-ok))]" : "text-[hsl(var(--muted-foreground))]")}>
      <span className={cn("h-1.5 w-1.5 rounded-full", ok ? "bg-[hsl(var(--status-ok))]" : "bg-[hsl(var(--muted-foreground))]")} />
      {label}
    </span>
  )
}

function WorkflowEmptyStep({ label, state }: { label: string; state: "gated" | "pending" | "ready" | "running" }) {
  const ready = state === "ready"
  const running = state === "running"
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.055] px-3 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium text-white/82">{label}</span>
        <span
          className={cn(
            "h-2 w-2 rounded-full",
            ready ? "bg-[hsl(var(--status-ok))]" : running ? "bg-[hsl(var(--primary))]" : "bg-white/24",
          )}
        />
      </div>
      <div className="mt-1 text-[10px] text-white/45">{running ? "running" : ready ? "ready" : state}</div>
    </div>
  )
}

function CompactWorkflowStrip({ steps }: { steps: Array<{ label: string; detail: string; status: WorkflowStatus }> }) {
  const activeIndex = steps.findIndex((step) => step.status === "active" || step.status === "blocked")
  const currentIndex = activeIndex >= 0 ? activeIndex : steps.length - 1
  return (
    <nav aria-label="Case workflow" className="max-w-full overflow-x-auto py-0.5">
      <ol className="relative grid min-w-[48rem] grid-cols-6 gap-2">
        {steps.map((step, index) => {
          const isCurrent = index === currentIndex
          const StageIcon = workflowStageIcons[step.label] ?? CheckCircle2
          return (
            <li
              aria-current={isCurrent ? "step" : undefined}
              className={cn(
                "relative min-w-0 rounded-xl px-2.5 py-2 text-center transition-[background-color,color,box-shadow] duration-150",
                step.status === "complete" && "bg-[hsl(var(--status-ok)/0.035)]",
                isCurrent && step.status === "active" && "bg-[hsl(var(--primary))] shadow-[0_4px_14px_hsl(var(--primary)/0.18)]",
                isCurrent && step.status === "blocked" && "bg-[hsl(var(--destructive))] shadow-[0_4px_14px_hsl(var(--destructive)/0.14)]",
              )}
              key={step.label}
            >
              {index < steps.length - 1 ? (
                <span
                  aria-hidden="true"
                  className={cn(
                    "pointer-events-none absolute -right-2 top-[calc(1.25rem-1px)] h-0.5 w-2 rounded-full",
                    step.status === "complete"
                      ? "bg-[hsl(var(--status-ok)/0.46)]"
                      : step.status === "active"
                        ? "bg-[hsl(var(--primary)/0.34)]"
                        : "bg-[hsl(var(--border)/0.78)]",
                  )}
                />
              ) : null}
              <div className="flex items-center justify-center gap-2">
                <WorkflowStepMarker icon={StageIcon} status={step.status} />
                <div className={cn(
                  "truncate text-[12px] leading-[1.35]",
                  isCurrent && step.status === "active" ? "font-semibold text-[hsl(var(--primary-foreground))]" : isCurrent && step.status === "blocked" ? "font-semibold text-[hsl(var(--destructive-foreground))]" : step.status === "complete" ? "font-semibold text-[hsl(var(--foreground)/0.88)]" : "font-medium text-[hsl(var(--muted-foreground))]",
                )}>
                  {step.label}
                </div>
              </div>
              <div className={cn(
                "mx-auto mt-1 max-w-[9.5rem] truncate px-1 text-[10px] leading-[1.4]",
                isCurrent && step.status === "active" ? "text-[hsl(var(--primary-foreground)/0.78)]" : isCurrent && step.status === "blocked" ? "text-[hsl(var(--destructive-foreground)/0.8)]" : step.status === "blocked" ? "text-[hsl(var(--destructive))]" : step.status === "complete" ? "text-[hsl(var(--status-ok))]" : "text-[hsl(var(--muted-foreground)/0.82)]",
              )} title={step.detail}>
                {step.detail}
              </div>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

function WorkflowStepMarker({
  icon: Icon,
  status,
}: {
  icon: ComponentType<{ className?: string; strokeWidth?: number }>
  status: WorkflowStatus
}) {
  return (
    <span
      className={cn(
        "relative z-10 grid size-6 shrink-0 place-items-center rounded-full border text-[11px] font-semibold",
        status === "complete" && "border-[hsl(var(--status-ok)/0.42)] bg-[hsl(var(--status-ok)/0.11)] text-[hsl(var(--status-ok))]",
        status === "active" && "border-[hsl(var(--primary-foreground)/0.48)] bg-[hsl(var(--primary-foreground)/0.14)] text-[hsl(var(--primary-foreground))]",
        status === "blocked" && "border-[hsl(var(--destructive-foreground)/0.48)] bg-[hsl(var(--destructive-foreground)/0.14)] text-[hsl(var(--destructive-foreground))]",
        status === "pending" && "border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--muted-foreground))]",
      )}
    >
      {status === "blocked"
        ? <AlertTriangle aria-hidden="true" className="size-3.5" strokeWidth={2} />
        : <Icon aria-hidden="true" className="size-3.5" strokeWidth={2.1} />}
    </span>
  )
}

function CaseLibrary({
  activeExampleId,
  activeRegistryCaseId,
  activeUploadCaseId,
  curatedOnly,
  examples,
  loadingPreload,
  loadingRegistry,
  onClear,
  onDeleteUpload,
  onLoadDemo,
  onLoadRegistry,
  onLoadUploads,
  onOpenUpload,
  onRetryUpload,
  onRunRegistryCase,
  onSelectExample,
  onUpload,
  points,
  registryCases,
  registryNote,
  runningRegistryCaseId,
  uploadedCases,
}: {
  activeExampleId: string
  activeRegistryCaseId: string
  activeUploadCaseId: string
  curatedOnly: boolean
  examples: PreloadExample[]
  loadingPreload: boolean
  loadingRegistry: boolean
  meta: PreloadExampleMeta | null
  note: string
  onClear: () => void
  onDeleteUpload: (uploadedCase: UploadedCase) => void
  onLoadDemo: () => void
  onLoadRegistry: () => void
  onLoadUploads: () => void
  onOpenUpload: (uploadedCase: UploadedCase) => void
  onRetryUpload: (uploadedCase: UploadedCase) => void
  onRunRegistryCase: (caseId: string) => void
  onSelectExample: (example: PreloadExample) => void
  onUpload: () => void
  points: LongitudinalRow[]
  registryCases: RegistryCase[]
  registryNote: string
  runningRegistryCaseId: string
  uploadedCases: UploadedCase[]
}) {
  const [lane, setLane] = useState<"curated" | "uploads">("curated")
  const primaryExamples = curatedOnly ? [] : examples.slice(0, 2)
  const runnableRegistryCases = useMemo(() => registryCases.filter(isRunnableRegistryCase), [registryCases])
  const featuredRegistryCases = useMemo(
    () => {
      const available = [...(curatedOnly ? runnableRegistryCases : runnableRegistryCases.filter(isModuleReadyRegistryCase))].sort(compareRegistryCasesForPicker)
      return curatedOnly ? available : available.slice(0, 8)
    },
    [curatedOnly, runnableRegistryCases],
  )
  useEffect(() => {
    if (activeUploadCaseId) setLane("uploads")
    else if (activeExampleId || activeRegistryCaseId) setLane("curated")
  }, [activeExampleId, activeRegistryCaseId, activeUploadCaseId])
  return (
    <section className="brain-tumor-case-picker">
      <div className="mb-2 flex shrink-0 items-start justify-between gap-2">
        <div className="flex min-h-[24px] items-center gap-2 text-[14px] font-medium"><Database aria-hidden="true" className="size-4" />Cases</div>
        <div className="flex items-center gap-1">
          <Button className="size-[44px]" aria-label="Refresh cases" onClick={lane === "curated" ? onLoadRegistry : onLoadUploads} size="icon-sm" title="Refresh cases" type="button" variant="ghost">
            {loadingRegistry ? <Loader2 className="animate-spin" /> : <RefreshCw />}
          </Button>
          <Button className="size-[44px]" disabled={!points.length} onClick={onClear} size="icon-sm" type="button" variant="ghost" aria-label="Clear active case" title="Clear active case"><X className="size-4" /></Button>
        </div>
      </div>
      <Tabs className="brain-tumor-case-source" value={lane} onValueChange={(value) => setLane(value as "curated" | "uploads")}>
        <TabsList aria-label="Case source" className="grid h-auto w-full shrink-0 grid-cols-2 gap-1 rounded-lg border border-[hsl(var(--border)/0.64)] bg-[hsl(var(--background)/0.58)] p-1">
          <TabsTrigger aria-label="Curated cases" className="min-h-[44px] min-w-0 px-1 text-[13px] leading-4 data-[state=active]:bg-[hsl(var(--foreground))] data-[state=active]:text-[hsl(var(--background))]" value="curated">Curated</TabsTrigger>
          <TabsTrigger aria-label="My uploads" className="min-h-[44px] min-w-0 px-1 text-[13px] leading-4 data-[state=active]:bg-[hsl(var(--foreground))] data-[state=active]:text-[hsl(var(--background))]" value="uploads">My uploads</TabsTrigger>
        </TabsList>
      <Button className="mb-3 mt-2 min-h-[44px] w-full shrink-0 justify-center gap-2 text-[13px]" onClick={onUpload} type="button"><FileUp />Upload MRI</Button>

        <TabsContent className="brain-tumor-case-list mt-0 space-y-2" value="curated">
          {primaryExamples.map((example, index) => {
            const summary = summarizePreloadExample(example)
            const active = activeExampleId === example.id
            return (
              <button className={cn("w-full rounded-xl border px-2.5 py-2.5 text-left transition", active ? "border-[hsl(var(--primary)/0.58)] bg-[hsl(var(--primary)/0.09)]" : "border-[hsl(var(--border)/0.62)] bg-[hsl(var(--background)/0.56)] hover:border-[hsl(var(--primary)/0.24)]")} key={example.id} onClick={() => onSelectExample(example)} type="button">
                <div className="flex items-center justify-between gap-2"><span className="truncate text-[12px] font-semibold">{example.title || `Case ${index + 1}`}</span><span className="text-[10px] text-[hsl(var(--muted-foreground))]">{summary.timepoints} visits</span></div>
                <div className="mt-1 text-[11px] text-[hsl(var(--muted-foreground))]">CE max {formatMm3(summary.maxEtMl)}</div>
              </button>
            )
          })}
          {featuredRegistryCases.map((item) => (
            <RegistryCaseRow caseItem={item} disabled={Boolean(runningRegistryCaseId)} key={item.id} loading={runningRegistryCaseId === item.id} onOpen={() => onRunRegistryCase(item.id)} selected={activeRegistryCaseId === item.id} />
          ))}
          {!primaryExamples.length && !featuredRegistryCases.length ? (
            <div className="rounded-xl border border-dashed border-[hsl(var(--border))] p-3 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">{curatedOnly ? "No curated cases are available for this preview." : registryNote || "No curated cases are available."}</div>
          ) : null}
          {!curatedOnly ? <Button className="w-full" onClick={onLoadDemo} size="sm" type="button" variant="ghost">{loadingPreload ? <Loader2 className="animate-spin" /> : <Database />}Refresh full worklist</Button> : null}
        </TabsContent>
        <TabsContent className="brain-tumor-case-list mt-0 space-y-2" value="uploads">
          {uploadedCases.map((uploadedCase) => (
            <UploadedCaseRow
              key={uploadedCase.id}
              onDelete={() => onDeleteUpload(uploadedCase)}
              onOpen={() => onOpenUpload(uploadedCase)}
              onRetry={() => onRetryUpload(uploadedCase)}
              selected={activeUploadCaseId === uploadedCase.id}
              uploadedCase={uploadedCase}
            />
          ))}
          {!uploadedCases.length ? (
            <div className="rounded-xl border border-dashed border-[hsl(var(--border))] p-3 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">No uploaded cases yet. Four de-identified NIfTI modalities are required.</div>
          ) : null}
          <div className="px-1 pt-1 text-[10px] leading-4 text-[hsl(var(--muted-foreground))]">Uploads and derived results are retained for 30 days.</div>
        </TabsContent>
      </Tabs>
    </section>
  )
}

function UploadedCaseRow({ uploadedCase, selected, onDelete, onOpen, onRetry }: { uploadedCase: UploadedCase; selected: boolean; onDelete: () => void; onOpen: () => void; onRetry: () => void }) {
  const status = uploadedCase.job?.status ?? "queued"
  const running = status === "queued" || status === "running"
  const statusLabel = status === "completed" ? "Masks ready" : status === "failed" ? `${uploadedCase.job?.completed_count || 0}/${uploadedCase.visit_count || 1} complete · Retry unfinished` : `${segmentStageLabel(uploadedCase.job?.stage)} · ${uploadedCase.job?.completed_count || 0}/${uploadedCase.visit_count || 1}`
  return (
    <div className={cn("relative overflow-hidden rounded-lg border p-3 transition-colors", selected ? "border-[hsl(var(--primary)/0.62)] bg-[hsl(var(--primary)/0.09)]" : "border-[hsl(var(--border)/0.62)] bg-[hsl(var(--background)/0.56)]")}>
      {selected ? <span className="absolute inset-y-3 left-0 w-1 rounded-r-full bg-[hsl(var(--primary))]" /> : null}
      <button aria-current={selected ? "true" : undefined} className="w-full rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]" onClick={onOpen} type="button">
        <span className="block min-w-0 text-[14px] font-semibold leading-5 text-[hsl(var(--foreground))] [overflow-wrap:anywhere]">{uploadedCase.label}</span>
        <div className="mt-1 text-[12px] text-[hsl(var(--muted-foreground))]">{uploadedCase.visit_count || 1} {(uploadedCase.visit_count || 1) === 1 ? "visit" : "visits"} · T1 / T1c / T2 / FLAIR</div>
      </button>
      <div className="mt-2 flex items-center justify-between gap-2 border-t border-[hsl(var(--border)/0.52)] pt-1">
        <span className={cn("inline-flex min-w-0 items-center gap-1.5 text-[11px] font-medium leading-4", status === "failed" ? "text-[hsl(var(--destructive))]" : status === "completed" ? "text-[hsl(var(--status-ok))]" : "text-[hsl(var(--primary))]")}>{running ? <Loader2 aria-hidden="true" className="size-3 shrink-0 animate-spin" /> : status === "completed" ? <CheckCircle2 aria-hidden="true" className="size-3 shrink-0" /> : <AlertTriangle aria-hidden="true" className="size-3 shrink-0" />}<span className="min-w-0 break-words">{statusLabel}</span></span>
        <div className="flex shrink-0 gap-1">
          {status === "failed" ? <Button aria-label="Retry segmentation" className="size-[32px]" onClick={onRetry} size="icon" title="Retry segmentation" type="button" variant="ghost"><RefreshCw /></Button> : null}
          <Button aria-label="Delete uploaded case" className="size-[32px]" onClick={onDelete} size="icon" title="Delete uploaded case" type="button" variant="ghost"><Trash2 /></Button>
        </div>
      </div>
    </div>
  )
}

function RegistryCaseRow({
  caseItem,
  disabled,
  loading,
  onOpen,
  selected,
}: {
  caseItem: RegistryCase
  disabled: boolean
  loading: boolean
  onOpen: () => void
  selected: boolean
}) {
  const maxEnhancing = caseItem.demo_quality?.max_enhancing_ml
  const displayName = formatRegistryCaseDisplayName(caseItem)
  const datasetLabel = formatRegistryDatasetLabel(caseItem.dataset)
  const visitLabel = `${caseItem.timepoint_count} visit${caseItem.timepoint_count === 1 ? "" : "s"}`
  const actionLabel = loading ? "Loading" : selected ? "Selected" : "Open case"
  return (
    <button
      aria-current={selected ? "true" : undefined}
      aria-label={`${actionLabel}: ${displayName}`}
      className={cn(
        "group relative w-full overflow-hidden rounded-lg border p-3 text-left transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-inset",
        selected
          ? "border-[hsl(var(--primary)/0.62)] bg-[hsl(var(--primary)/0.09)]"
          : "border-[hsl(var(--border)/0.62)] bg-[hsl(var(--background)/0.56)] hover:border-[hsl(var(--primary)/0.38)] hover:bg-[hsl(var(--card))]",
        disabled && !selected && "cursor-not-allowed opacity-70 hover:translate-y-0 hover:shadow-none",
        disabled && selected && "cursor-not-allowed",
      )}
      disabled={disabled}
      onClick={onOpen}
      type="button"
    >
      {selected ? <span className="absolute inset-y-3 left-0 w-1 rounded-r-full bg-[hsl(var(--primary))]" /> : null}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="break-words text-[14px] font-semibold leading-5 text-[hsl(var(--foreground))]">{displayName}</div>
          <div className="mt-1 truncate text-[12px] leading-4 text-[hsl(var(--muted-foreground))]" title={datasetLabel}>
            {datasetLabel}
          </div>
        </div>
        <span
          className={cn(
            "inline-flex size-5 shrink-0 items-center justify-center",
            selected
              ? "text-[hsl(var(--primary))]"
              : "text-[hsl(var(--muted-foreground))] group-hover:text-[hsl(var(--primary))]",
          )}
        >
          {loading ? <Loader2 className="size-4 animate-spin" /> : selected ? <CheckCircle2 className="size-4" /> : <ChevronRight className="size-4" />}
          <span className="sr-only">{loading ? "Loading" : selected ? "Selected" : "Open"}</span>
        </span>
      </div>
      <div className="mt-2 flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1 text-[12px] leading-4 text-[hsl(var(--muted-foreground))]">
        <div>{visitLabel}</div>
        <div>CE max <span className="font-medium tabular-nums text-[hsl(var(--foreground))]">{typeof maxEnhancing === "number" ? formatMm3(maxEnhancing) : "Not measured"}</span></div>
      </div>
    </button>
  )
}

function formatRegistryCaseDisplayName(item: RegistryCase) {
  const patientId = formatRegistryPatientId(item.patient_id)
  if (patientId) return patientId

  const title = item.title || item.id || "Registry case"
  const datasetLabel = formatRegistryDatasetLabel(item.dataset)
  const cleaned = title
    .replace(new RegExp(`^${escapeRegExp(datasetLabel)}\\s*`, "i"), "")
    .replace(/^patientid[\s_-]*/i, "Patient ")
    .replace(/[_-]+/g, " ")
    .trim()
  return cleaned || title
}

function formatRegistryPatientId(patientId?: string) {
  if (!patientId) return ""
  const normalized = patientId.replace(/[_-]+/g, " ").trim()
  const patientIdMatch = normalized.match(/^patientid\s*(.+)$/i)
  if (patientIdMatch?.[1]) return `Patient ${patientIdMatch[1].trim()}`
  return /^\d+$/.test(normalized) ? `Case ${normalized}` : normalized
}

function formatRegistryDatasetLabel(dataset?: string) {
  return (dataset || "Registry").replace(/[_-]+/g, " ").trim()
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

function isModuleReadyRegistryCase(item: RegistryCase) {
  if (item.timepoint_count < 2) return false
  const cacheCount = item.demo_quality?.cache_count ?? 0
  if (cacheCount < item.timepoint_count) return false
  return item.timepoints.every((point) => (
    point.gt_available &&
    requiredModalities.every((modality) => point.modalities.includes(modality))
  ))
}

function isRunnableRegistryCase(item: RegistryCase) {
  if (item.timepoint_count < 1) return false
  return item.timepoints.every((point) => (
    requiredModalities.every((modality) => point.modalities.includes(modality))
  ))
}

function compareRegistryCasesForPicker(left: RegistryCase, right: RegistryCase) {
  return registryCasePickerScore(right) - registryCasePickerScore(left) || (left.title || left.id).localeCompare(right.title || right.id)
}

function selectDefaultRegistryCase(cases: RegistryCase[]) {
  return cases.filter((item) => (
    item.timepoint_count === 6 && item.timepoints.length === 6 &&
    (item.demo_quality?.cache_count ?? 0) >= 6 && isRunnableRegistryCase(item)
  )).sort(compareRegistryCasesForPicker)[0]
}

function registryCasePickerScore(item: RegistryCase) {
  const cacheCount = item.demo_quality?.cache_count ?? 0
  const fullyCached = cacheCount >= item.timepoint_count && item.timepoint_count > 0
  return (
    (item.demo_quality?.recommended ? 1_000_000 : 0) +
    (fullyCached ? 100_000 : 0) +
    (item.timepoint_count > 1 ? 10_000 : 0) +
    cacheCount * 100 +
    item.timepoint_count
  )
}

function summarizePreloadExample(example: PreloadExample) {
  const maxEtMl = Math.max(0, ...example.points.map((point) => {
    const row = point.volumes.find((item) => item.region === "enhancing_tumor")
    return Number(row?.volume_ml ?? 0)
  }))
  return {
    kind: example.points.length > 1 ? "Follow-up" : "Single scan",
    maxEtMl,
    timepoints: example.points.length,
  }
}

function TrendReviewPanel({
  alignJob,
  aligningAll,
  biasCorrection,
  onBiasCorrectionChange,
  activePointId,
  baselinePointId,
  displayMode,
  onAlignAll,
  onRegister,
  onSelectActive,
  onSelectBaseline,
  points,
  registrationError,
  registeringPointId,
  samePatientLongitudinal,
  comparisonCases,
  onOpenComparisonCase,
  loadingCase,
}: {
  alignJob: LongitudinalAlignJob | null
  aligningAll: boolean
  biasCorrection: boolean
  onBiasCorrectionChange: (value: boolean) => void
  activePointId: string
  baselinePointId: string
  displayMode?: PreloadExampleMeta["displayMode"]
  onAlignAll: () => void
  onRegister: (pointId: string) => void
  onSelectActive: (pointId: string) => void
  onSelectBaseline: (pointId: string) => void
  points: LongitudinalRow[]
  registrationError: string | null
  registeringPointId: string
  samePatientLongitudinal: boolean
  comparisonCases: RegistryCase[]
  onOpenComparisonCase: (caseId: string) => void
  loadingCase: boolean
}) {
  const [comparisonCaseId, setComparisonCaseId] = useState("")
  const [inspectedPointId, setInspectedPointId] = useState<string | null>(null)
  if (points.length < 2) {
    const point = points[0]
    return (
      <SoftPanel className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <SectionTitle icon={Layers} label="Longitudinal comparison" />
          <span className="text-[12px] text-[hsl(var(--muted-foreground))]">{point ? "1 scan" : "No case selected"}</span>
        </div>
        {point ? (
          <div className="mt-4 border-y border-[hsl(var(--border))] py-4">
            <div className="text-[13px] font-semibold">{point.label}</div>
            <div className="mt-1 text-[12px] text-[hsl(var(--muted-foreground))]">{point.dateLabel}</div>
            <dl className="mt-4 grid grid-cols-2 gap-4">
              {[
                { region: "enhancing_tumor", label: "CE tumor", value: point.etMl },
                { region: "flair_abnormality", label: "T2/FLAIR", value: point.flairMl },
              ].map((metric) => (
                <div key={metric.region}>
                  <dt className="text-[12px] text-[hsl(var(--muted-foreground))]">{metric.label}</dt>
                  <dd className="mt-1 text-[16px] font-semibold tabular-nums">
                    {point.volumes.some((volume) => volume.region === metric.region) ? formatMm3(metric.value) : "Not measured"}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        ) : null}
        <div className="py-4">
          <div className="text-[14px] font-semibold">{point ? "No follow-up scan linked" : "Select a case for comparison"}</div>
          <p className="mt-1 text-[13px] leading-5 text-[hsl(var(--muted-foreground))]">
            {point ? "Interval change and alignment are unavailable for a single scan. A second examination from the same patient is required." : "No visits or measurements are loaded."}
          </p>
        </div>
        {comparisonCases.length ? (
          <div className="border-t border-[hsl(var(--border))] pt-4">
            <label className="text-[12px] font-medium" htmlFor="longitudinal-case-picker">Multi-visit cases</label>
            <div className="mt-2 flex flex-wrap gap-2">
              <select
                className="h-9 min-w-0 flex-1 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2 text-[12px]"
                id="longitudinal-case-picker"
                onChange={(event) => setComparisonCaseId(event.target.value)}
                value={comparisonCaseId}
              >
                <option value="">Select a case</option>
                {comparisonCases.map((item) => <option key={item.id} value={item.id}>{formatRegistryCaseDisplayName(item)} · {item.timepoint_count} visits</option>)}
              </select>
              <Button disabled={!comparisonCaseId || loadingCase} onClick={() => onOpenComparisonCase(comparisonCaseId)} size="sm" type="button" variant="outline">
                {loadingCase ? <Loader2 className="animate-spin" /> : <FolderOpen />}Open case
              </Button>
            </div>
          </div>
        ) : null}
      </SoftPanel>
    )
  }
  const isStageComparison = samePatientLongitudinal && (displayMode === "stage_comparison" || points.length <= 3)
  const isTrajectory = samePatientLongitudinal && !isStageComparison && points.length > 2
  const alignedCount = samePatientLongitudinal
    ? points.filter((point) => point.id === baselinePointId || isRegistered(point.registration)).length
    : 0
  const measuredCount = points.filter((point) => point.volumes.length > 0).length
  const canAlignAll = samePatientLongitudinal && points.length > 1 && points.every((point) => Boolean(point.sessionId)) && !aligningAll && !registeringPointId
  const alignTotal = Math.max(points.length, alignJob?.total_count ?? 0)
  const alignCompleted = Math.min(alignTotal || alignedCount, Math.max(alignedCount, alignJob?.completed_count ?? 0))
  const alignPct = alignTotal ? Math.min(100, Math.round((alignCompleted / alignTotal) * 100)) : 0

  return (
    <SoftPanel className="p-4">
      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SectionTitle icon={Layers} label={isStageComparison ? "Stage comparison" : isTrajectory ? "Longitudinal trajectory" : "Cohort measurements"} />
          <div className="flex flex-wrap items-center gap-2">
            {samePatientLongitudinal ? <label className="gbm-alignment-option">
              <input type="checkbox" checked={biasCorrection} disabled={aligningAll || Boolean(registeringPointId)} onChange={(event) => onBiasCorrectionChange(event.target.checked)} />
              N4 bias-field correction
            </label> : null}
            {samePatientLongitudinal ? (
              <div className="flex items-center gap-1.5 rounded-2xl border border-[hsl(var(--border)/0.58)] bg-[hsl(var(--background)/0.62)] p-1 shadow-[0_10px_24px_hsl(var(--foreground)/0.045),inset_0_1px_0_hsl(var(--card)/0.9)]">
                <div className="flex min-w-24 items-center gap-2 px-2">
                  <Layers className="h-3.5 w-3.5 text-[hsl(var(--muted-foreground))]" />
                  <div className="min-w-0">
                    <div className="text-[11px] font-semibold tabular-nums text-[hsl(var(--foreground))]">Alignment {alignCompleted}/{alignTotal}</div>
                    <div className="mt-1 h-1 overflow-hidden rounded-full bg-[hsl(var(--border)/0.56)]">
                      <div className="h-full rounded-full bg-[hsl(var(--primary))] transition-all duration-500" style={{ width: `${alignPct}%` }} />
                    </div>
                  </div>
                </div>
                <Button className="h-7 rounded-xl px-2.5 text-[11px] font-semibold" disabled={!canAlignAll} onClick={onAlignAll} size="sm" type="button" variant="outline">
                {aligningAll ? <Loader2 className="animate-spin" /> : <Layers />}
                  {aligningAll ? `Aligning ${alignCompleted}/${alignTotal}` : "Align all"}
                </Button>
              </div>
            ) : null}
            <span className="border-l border-[hsl(var(--border))] pl-2 text-[11px] text-[hsl(var(--foreground))]">
              {isStageComparison ? "Stage summary" : "Volume trend"}
            </span>
          </div>
        </div>
        {!samePatientLongitudinal ? (
          <div className="rounded-2xl border border-[hsl(var(--border)/0.58)] bg-[hsl(var(--background)/0.62)] p-2.5 text-[12px] leading-5 text-[hsl(var(--muted-foreground))] shadow-[inset_0_1px_0_hsl(var(--card)/0.9)]">
            These scans belong to separate cases, not one patient's treatment timeline. Alignment is only shown for same-patient follow-up.
          </div>
        ) : null}
        {aligningAll ? (
          <div className="rounded-2xl border border-[hsl(var(--primary)/0.24)] bg-[hsl(var(--primary)/0.055)] p-3 shadow-[inset_0_1px_0_hsl(var(--card)/0.8)]">
            <div className="flex items-center justify-between gap-3 text-[11px]">
              <span className="inline-flex items-center gap-1.5 font-medium text-[hsl(var(--foreground))]">
                <Loader2 className="h-3.5 w-3.5 animate-spin text-[hsl(var(--primary))]" />
                Aligning longitudinal visits
              </span>
              <span className="tabular-nums text-[hsl(var(--muted-foreground))]">{alignCompleted}/{alignTotal}</span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[hsl(var(--border)/0.52)]">
              <div className="h-full rounded-full bg-[hsl(var(--primary))] transition-all duration-500" style={{ width: `${alignPct}%` }} />
            </div>
          </div>
        ) : null}
        <VisitTimingSummary points={points} activePointId={activePointId} baselinePointId={baselinePointId} samePatient={samePatientLongitudinal} />
        <div className="relative rounded-lg border border-[hsl(var(--border)/0.58)] bg-[hsl(var(--background)/0.64)] p-4">
          {!points.length ? (
            <div className="grid h-64 place-items-center">
              <div className="max-w-xs text-center">
                <Layers className="mx-auto h-7 w-7 text-[hsl(var(--muted-foreground))]" />
                <div className="mt-2 text-[13px] font-medium text-[hsl(var(--foreground))]">No longitudinal data loaded</div>
                <div className="mt-1 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">Open a worklist case to populate visit cards, trend measurements, and alignment status.</div>
              </div>
            </div>
          ) : measuredCount < points.length ? (
            <div className="grid min-h-40 content-center gap-2 text-center">
              <div className="text-sm font-semibold">{measuredCount}/{points.length} visits measured</div>
              <div className="text-sm text-[hsl(var(--muted-foreground))]">Trend pending remaining measurements</div>
            </div>
          ) : isStageComparison ? (
            <StageComparisonChart activePointId={activePointId} baselinePointId={baselinePointId} points={points} />
          ) : (
            <TumorTrendChart points={points} activePointId={activePointId} baselinePointId={baselinePointId} onSelectActive={onSelectActive} onInspect={setInspectedPointId} />
          )}
          {isStageComparison ? <div className="mt-1 flex flex-wrap gap-3 text-[12px] text-[hsl(var(--muted-foreground))]">
            <LegendChip color={tumorPalette.et} label="CE tumor" />
            <LegendChip color={tumorPalette.wt} label="T2/FLAIR abnormality" />
          </div> : null}
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          {points.map((point) => {
            const alignVisit = alignJob?.visits.find((visit) => visit.session_id === point.sessionId || visit.followup_session_id === point.sessionId)
            const alignState = alignVisit?.status
            return (
              <div
                className={cn(
                  "tumor-trend-visit-card rounded-lg border p-3 text-left transition-colors",
                  activePointId === point.id
                    ? "border-[hsl(var(--primary)/0.62)] bg-[hsl(var(--primary)/0.09)] shadow-[0_8px_24px_hsl(var(--primary)/0.08)]"
                    : "border-[hsl(var(--border)/0.72)] bg-[hsl(var(--background)/0.72)] hover:border-[hsl(var(--primary)/0.22)] hover:bg-[hsl(var(--card)/0.82)]",
                )}
                data-trend-visit={point.id}
                data-inspected={inspectedPointId === point.id}
                key={point.id}
              >
              <div className="flex items-start justify-between gap-2">
                <button aria-label={`View ${point.label}`} aria-pressed={activePointId === point.id} className="min-w-0 flex-1 rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]" onClick={() => onSelectActive(point.id)} type="button">
                  <span className="block text-[13px] font-semibold text-[hsl(var(--foreground))]">{trendTimeLabel(point)}</span>
                  <span className="mt-1 block text-[11px] text-[hsl(var(--muted-foreground))]">{activePointId === point.id ? "Viewing" : "View scan"}</span>
                </button>
                {samePatientLongitudinal ? (
                  <input
                    aria-label={`Use ${point.label} as reference`}
                    checked={baselinePointId === point.id}
                    className="mt-1 accent-[hsl(var(--primary))]"
                    onChange={() => onSelectBaseline(point.id)}
                    title="Use as reference"
                    type="radio"
                  />
                ) : null}
              </div>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px]">
                <span className={changeTone(point.etChangePct)}>{!point.volumes.length ? "Not measured" : baselinePointId === point.id ? "baseline" : point.etChangePct === null ? "Comparison pending" : `${formatPct(point.etChangePct)} ET`}</span>
                {!samePatientLongitudinal ? (
                  <span className="text-[hsl(var(--muted-foreground))]">cohort case</span>
                ) : baselinePointId === point.id ? (
                  <span className="text-[hsl(var(--status-ok))]">reference</span>
                ) : alignState === "queued" || alignState === "running" ? (
                  <span className="inline-flex items-center gap-1 text-[hsl(var(--primary))]">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    {alignState === "running" ? "aligning" : "queued"}
                  </span>
                ) : (
                  <span className="flex flex-wrap items-center gap-2">
                  {point.registration ? <span>{registrationLabel(point.registration)}</span> : null}
                  <button
                    className="rounded-xl border border-[hsl(var(--border)/0.66)] px-2 py-1 text-[hsl(var(--muted-foreground))] transition hover:bg-[hsl(var(--muted)/0.72)] hover:text-[hsl(var(--foreground))]"
                    onClick={(event) => {
                      event.stopPropagation()
                      onRegister(point.id)
                    }}
                    disabled={aligningAll || Boolean(registeringPointId) || !point.sessionId || !points.find((candidate) => candidate.id === baselinePointId)?.sessionId}
                    type="button"
                  >
                    {registeringPointId === point.id ? "Aligning" : alignState === "failed" ? "Retry alignment" : "Align"}
                  </button>
                  </span>
                )}
              </div>
              </div>
            )
          })}
        </div>
        {registrationError ? (
          <div className="rounded-xl border border-[hsl(var(--destructive)/0.35)] bg-[hsl(var(--destructive)/0.08)] p-2 text-[12px] text-[hsl(var(--destructive))]">
            {registrationError}
          </div>
        ) : null}
      </div>

    </SoftPanel>
  )
}

function StageComparisonChart({ activePointId, baselinePointId, points }: { activePointId: string; baselinePointId: string; points: LongitudinalRow[] }) {
  return (
    <Table aria-label="Tumor burden stage comparison" className="text-[12px]">
      <TableHeader>
        <TableRow>
          <TableHead>Visit</TableHead>
          <TableHead className="text-right">CE · mm³</TableHead>
          <TableHead className="text-right">FLAIR · mm³</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {points.map((point) => (
          <TableRow className={cn(point.id === activePointId && "bg-[hsl(var(--primary)/0.07)]")} key={point.id}>
            <TableCell>
              <div className="font-semibold">{trendTimeLabel(point)}</div>
              <div className="mt-0.5 text-[11px] text-[hsl(var(--muted-foreground))]">
                {point.id === baselinePointId ? "Reference" : ""}{point.id === activePointId ? (point.id === baselinePointId ? " · Viewing" : "Viewing") : ""}
              </div>
            </TableCell>
            <TableCell className="text-right font-medium tabular-nums">{formatMm3Number(point.etMl)}</TableCell>
            <TableCell className="text-right font-medium tabular-nums">{formatMm3Number(point.flairMl)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function formatSignedMm3(value: number) {
  if (Math.abs(value) < 0.5) return "0 mm³"
  const prefix = value > 0 ? "+" : "-"
  return `${prefix}${formatMm3(Math.abs(value))}`
}

function percentChange(current: number, reference: number) {
  if (!Number.isFinite(current) || !Number.isFinite(reference) || reference <= 0) return null
  return ((current - reference) / reference) * 100
}


function trendTimeLabel(point: LongitudinalRow, index?: number) {
  return visitTimeLabel(point, index)
}

function roleLabelCompact(role: TimepointRole) {
  return role === "pre_treatment_baseline" || role === "post_rt_baseline" || role === "screening_baseline"
    ? "reference"
    : role === "nadir"
      ? "nadir"
      : "follow-up"
}

function StepDot({ compact, index, status }: { compact?: boolean; index: number; status: WorkflowStatus }) {
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-full border text-[10px] font-medium",
        compact ? "h-5 w-5" : "h-6 w-6",
        status === "complete" && "border-[hsl(var(--status-ok)/0.45)] bg-[hsl(var(--status-ok)/0.12)] text-[hsl(var(--status-ok))]",
        status === "active" && "border-[hsl(var(--primary)/0.55)] bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))]",
        status === "blocked" && "border-[hsl(var(--destructive)/0.4)] bg-[hsl(var(--destructive)/0.1)] text-[hsl(var(--destructive))]",
        status === "pending" && "border-[hsl(var(--border))] bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]",
      )}
    >
      {status === "complete" ? <Check className="h-3 w-3" /> : index}
    </span>
  )
}

function ModalityReadiness({
  activeLoaded,
  files,
  inputMode,
  mapping,
  session,
}: {
  activeLoaded?: boolean
  files: Partial<Record<ModalityKey, File>>
  inputMode: InputMode
  mapping: Partial<Record<ModalityKey, string>>
  session: TumorSession | null
}) {
  return (
    <div className="mt-3 grid grid-cols-2 gap-2">
      {modalityOrder.map((key) => {
        const present = activeLoaded || session?.modality_status?.[key]?.present || (inputMode === "upload" ? Boolean(files[key]) : Boolean(mapping[key]))
        return (
          <div
            className={cn(
              "rounded-md border p-2 text-[11px]",
              present
                ? "border-[hsl(var(--status-ok)/0.4)] bg-[hsl(var(--status-ok)/0.08)]"
                : "border-[hsl(var(--border))] bg-[hsl(var(--background))]",
            )}
            key={key}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-[hsl(var(--foreground))]">{modalityMeta[key].label}</span>
              {present ? <CheckCircle2 className="h-3.5 w-3.5 text-[hsl(var(--status-ok))]" /> : <AlertTriangle className="h-3.5 w-3.5 text-[hsl(var(--muted-foreground))]" />}
            </div>
            <div className="mt-1 truncate text-[hsl(var(--muted-foreground))]">
              {present ? session?.modality_status?.[key]?.path_name || (activeLoaded ? "Available" : "Selected") : modalityMeta[key].required ? "Required" : "Optional"}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function SectionTitle({
  compact,
  icon: Icon,
  label,
}: {
  compact?: boolean
  icon: ComponentType<{ className?: string }>
  label: string
}) {
  return (
    <div className={cn("flex items-center gap-2 font-medium text-[hsl(var(--foreground))]", compact ? "text-[13px]" : "text-[14px]")}>
      <Icon className="h-3.5 w-3.5" />
      {label}
    </div>
  )
}

function LabeledInput({
  label,
  onChange,
  placeholder,
  value,
}: {
  label: string
  onChange: (value: string) => void
  placeholder: string
  value: string
}) {
  return (
    <label className="block space-y-1">
      <span className="text-[11px] text-[hsl(var(--muted-foreground))]">{label}</span>
      <input
        className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-[12px] outline-none"
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        value={value}
      />
    </label>
  )
}

function readDroppedFile(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject))
}

function readDroppedEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  return new Promise((resolve, reject) => reader.readEntries(resolve, reject))
}

async function readDroppedEntry(entry: FileSystemEntry): Promise<File[]> {
  if (entry.isFile) {
    const file = await readDroppedFile(entry as FileSystemFileEntry)
    Object.defineProperty(file, "webkitRelativePath", { value: entry.fullPath.replace(/^\//, "") })
    return [file]
  }
  if (!entry.isDirectory) return []

  const reader = (entry as FileSystemDirectoryEntry).createReader()
  const files: File[] = []
  while (true) {
    const entries = await readDroppedEntries(reader)
    if (!entries.length) break
    const nested = await Promise.all(entries.map(readDroppedEntry))
    files.push(...nested.flat())
  }
  return files
}

async function filesFromDrop(dataTransfer: DataTransfer): Promise<File[]> {
  const entries = Array.from(dataTransfer.items)
    .filter((item) => item.kind === "file")
    .map((item) => item.webkitGetAsEntry())
    .filter((entry): entry is FileSystemEntry => Boolean(entry))

  if (!entries.length) return Array.from(dataTransfer.files)
  const nested = await Promise.all(entries.map(readDroppedEntry))
  return nested.flat()
}

function BulkNiftiInput({
  disabled = false,
  inferenceRows,
  onChange,
  archiveProgress,
}: {
  disabled?: boolean
  inferenceRows: UploadInferenceRow[]
  onChange: (files: FileList | File[] | null) => void
  archiveProgress?: ArchiveProgress | null
}) {
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (folderInputRef.current) folderInputRef.current.webkitdirectory = true
  }, [])

  async function handleDrop(event: ReactDragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragActive(false)
    if (disabled) return
    const fallbackFiles = Array.from(event.dataTransfer.files)
    try {
      onChange(await filesFromDrop(event.dataTransfer))
    } catch {
      onChange(fallbackFiles)
    }
  }

  function handleInputChange(event: React.ChangeEvent<HTMLInputElement>) {
    onChange(Array.from(event.currentTarget.files ?? []))
    event.currentTarget.value = ""
  }

  return (
    <div className="min-w-0">
      <div
        className={cn(
          "grid min-h-[152px] place-items-center rounded-lg border border-dashed px-4 py-5 text-center transition-colors",
          dragActive
            ? "border-[hsl(var(--primary)/0.72)] bg-[hsl(var(--primary)/0.08)]"
            : "border-[hsl(var(--border))] bg-[hsl(var(--card)/0.62)]",
        )}
        onDragEnter={(event) => {
          event.preventDefault()
          if (!disabled) setDragActive(true)
        }}
        onDragLeave={(event) => {
          event.preventDefault()
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragActive(false)
        }}
        onDragOver={(event) => {
          event.preventDefault()
          event.dataTransfer.dropEffect = disabled ? "none" : "copy"
          if (!disabled) setDragActive(true)
        }}
        onDrop={(event) => void handleDrop(event)}
      >
        <div className="min-w-0">
          <FileUp aria-hidden="true" className="mx-auto size-6 text-[hsl(var(--primary))]" />
          <div className="mt-2 text-[14px] font-medium leading-5 text-[hsl(var(--foreground))]">Drop a NIfTI ZIP, files or a folder</div>
          <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
            <Button className="min-h-[40px] gap-2 px-3 text-[13px]" disabled={disabled} onClick={() => fileInputRef.current?.click()} type="button" variant="outline">
              <FileUp />Choose ZIP or files
            </Button>
            <Button className="min-h-[40px] gap-2 px-3 text-[13px]" disabled={disabled} onClick={() => folderInputRef.current?.click()} type="button" variant="outline">
              <FolderOpen />Choose folder
            </Button>
          </div>
        </div>
        <input aria-label="Choose NIfTI ZIP or files" accept=".zip,.nii,.nii.gz" className="hidden" disabled={disabled} multiple onChange={handleInputChange} ref={fileInputRef} type="file" />
        <input aria-label="Choose NIfTI folder" className="hidden" disabled={disabled} multiple onChange={handleInputChange} ref={folderInputRef} type="file" />
      </div>
      {archiveProgress ? <div className="mt-3 space-y-2 text-[13px] text-[hsl(var(--foreground))]">
        <div role="status" aria-live="polite" className="flex min-h-6 flex-wrap items-center justify-between gap-2">
          <span className="flex items-center gap-2">{archiveProgress.phase === "ready" ? <CheckCircle2 aria-hidden="true" className="size-4 text-[hsl(var(--status-ok))]" /> : <Loader2 aria-hidden="true" className="size-4 motion-safe:animate-spin text-[hsl(var(--primary))]" />}{archiveProgress.phase === "reading" ? "Reading ZIP" : archiveProgress.phase === "ready" ? "ZIP extracted" : "Extracting NIfTI files"}</span>
          {archiveProgress.total > 0 ? <span className="tabular-nums text-[hsl(var(--muted-foreground))]">{archiveProgress.completed}/{archiveProgress.total} files</span> : null}
        </div>
        {archiveProgress.phase === "extracting" ? <progress aria-label="ZIP extraction" className="block h-2 w-full accent-[hsl(var(--primary))]" max={100} value={archiveProgress.percent} /> : null}
      </div> : null}
      {inferenceRows.some((row) => !row.modality || row.reason.startsWith("Duplicate")) ? (
        <div aria-live="polite" className="mt-3 space-y-2 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">
          {inferenceRows.filter((row) => !row.modality || row.reason.startsWith("Duplicate")).map((row) => (
            <div className="flex items-start gap-2" key={`${row.fileName}-${row.modality ?? "unmapped"}`}>
              <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              <span className="min-w-0 [overflow-wrap:anywhere]"><span className="font-medium text-[hsl(var(--foreground))]">{row.fileName}</span> · {row.reason}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function UploadCaseDialog({
  error, onClose, onSubmit, submitting, progress, uploadedCases, selectedCaseId, onClearError,
}: {
  error: string | null
  onClose: () => void
  onSubmit: (visits: UploadVisitDraft[], targetCaseId: string) => void
  submitting: boolean
  progress: number
  uploadedCases: UploadedCase[]
  selectedCaseId: string
  onClearError: () => void
}) {
  const [visits, setVisits] = useState<UploadVisitDraft[]>(() => [emptyVisitDraft()])
  const [activeIndex, setActiveIndex] = useState(0)
  const [targetCaseId, setTargetCaseId] = useState("")
  const [confirmed, setConfirmed] = useState(false)
  const [samePatient, setSamePatient] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const [archiveProgress, setArchiveProgress] = useState<ArchiveProgress | null>(null)
  const [preparing, setPreparing] = useState(false)
  const requestRef = useRef<AbortController | null>(null)
  const returnFocusRef = useRef(document.activeElement)
  useEffect(() => () => requestRef.current?.abort(), [])
  const targetCase = uploadedCases.find((item) => item.id === targetCaseId)
  const existingDates = targetCase?.visits?.map((visit) => visit.date) || []
  const existingCount = targetCase?.visit_count || (targetCase ? 1 : 0)
  const active = visits[activeIndex]
  const needsSamePatient = Boolean(targetCaseId) || visits.length > 1
  const validation = validateVisitDrafts(visits, existingDates)
  const readyCount = visits.filter((visit) => requiredModalities.every((key) => visit.files[key]) && !visit.unassigned.length).length
  const errorText = localError || error
  function changed() { setConfirmed(false); setSamePatient(false); setLocalError(null); onClearError() }
  function updateVisit(index: number, update: Partial<UploadVisitDraft>) {
    changed()
    setVisits((current) => current.map((visit, i) => i === index ? { ...visit, ...update } : visit))
  }
  function reorder(index: number, delta: number) {
    changed()
    const next = [...visits]
    ;[next[index], next[index + delta]] = [next[index + delta], next[index]]
    setVisits(next)
    setActiveIndex(index + delta)
  }
  async function prepare(fileList: FileList | File[] | null) {
    const selected = Array.from(fileList || [])
    if (!selected.length) return
    requestRef.current?.abort()
    const controller = new AbortController()
    requestRef.current = controller
    changed()
    setPreparing(true)
    setArchiveProgress(null)
    try {
      const { prepareNiftiSelection } = await import("./brainTumor.archive")
      const extracted = await prepareNiftiSelection(selected, (value) => {
        if (!controller.signal.aborted) setArchiveProgress(value)
      }, controller.signal)
      controller.signal.throwIfAborted()
      const groups = groupVisitFiles(extracted, inferModalityFromFileName)
      if (groups.length + existingCount > 6) throw new Error("A case can contain up to six visits.")
      if (groups.length === 1) {
        setVisits((current) => current.map((visit, index) => index === activeIndex ? { ...groups[0], id: visit.id, date: visit.date } : visit))
      } else {
        setVisits(groups)
        setActiveIndex(0)
      }
    } catch (err) {
      if (!controller.signal.aborted) { setLocalError(err instanceof Error ? err.message : "Files could not be prepared."); setArchiveProgress(null) }
    } finally {
      if (requestRef.current === controller) { requestRef.current = null; setPreparing(false) }
    }
  }
  return (
    <DialogPrimitive.Root open onOpenChange={(open) => { if (!open && !submitting) onClose() }}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/48 backdrop-blur-sm" />
        <DialogPrimitive.Content aria-busy={submitting || preparing}
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[calc(100dvh-32px)] w-[calc(100%-32px)] max-w-[820px] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-[0_28px_90px_rgba(0,0,0,0.34)] outline-none"
          onCloseAutoFocus={(event) => { event.preventDefault(); if (returnFocusRef.current instanceof HTMLElement) returnFocusRef.current.focus() }}
          onEscapeKeyDown={(event) => { if (submitting) event.preventDefault() }}
          onInteractOutside={(event) => event.preventDefault()}>
          <header className="flex shrink-0 items-start justify-between gap-3 border-b border-[hsl(var(--border)/0.68)] px-4 py-4 sm:px-6">
            <div className="min-w-0">
              <DialogPrimitive.Title className="text-[18px] font-semibold leading-6">Upload MRI</DialogPrimitive.Title>
              <DialogPrimitive.Description className="mt-1 text-[13px] leading-5 text-[hsl(var(--muted-foreground))]">One patient · Up to six visits · Four modalities per visit</DialogPrimitive.Description>
            </div>
            <DialogPrimitive.Close asChild><Button aria-label="Close upload" className="size-[44px] shrink-0" disabled={submitting} size="icon" title="Close upload" type="button" variant="outline"><X aria-hidden="true" className="size-5" /></Button></DialogPrimitive.Close>
          </header>
          <div className="min-h-0 overflow-y-auto overscroll-contain px-4 py-4 sm:px-6">
            <fieldset disabled={submitting || preparing} className="min-w-0 space-y-4">
              <label className="block text-[13px] font-medium">
                Case
                <select aria-label="Upload destination" className="mt-1 block min-h-[44px] w-full min-w-0 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-[14px]"
                  value={targetCaseId} onChange={(event) => { setTargetCaseId(event.target.value); changed() }}>
                  <option value="">New case</option>
                  {[...uploadedCases].sort((a, b) => Number(b.id === selectedCaseId) - Number(a.id === selectedCaseId)).map((item) =>
                    <option key={item.id} value={item.id} disabled={item.job?.status === "running" || item.job?.status === "queued" || (item.visit_count || 1) >= 6}>Add visits to {item.label} · {item.visit_count || 1} existing</option>)}
                </select>
              </label>
              {!submitting ? <details className="border-b border-[hsl(var(--border)/0.68)] pb-3"><summary className="cursor-pointer text-[13px] font-medium">Download example MRI</summary><div className="mt-3"><UploadExamples /></div></details> : null}
              <BulkNiftiInput disabled={submitting || preparing} inferenceRows={[]} onChange={prepare} archiveProgress={archiveProgress} />
              <section aria-label="Visit mapping" className="min-w-0">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-[14px] font-semibold">Visits <span className="font-normal text-[hsl(var(--muted-foreground))]">· {readyCount}/{visits.length} mapped</span></h3>
                  <Button className="min-h-[44px] gap-2 text-[13px]" variant="outline" disabled={visits.length + existingCount >= 6} type="button"
                    onClick={() => { changed(); setVisits((current) => [...current, emptyVisitDraft()]); setActiveIndex(visits.length); setArchiveProgress(null) }}><Plus className="size-4" />Add visit</Button>
                </div>
                {targetCase ? <p className="mb-2 text-[12px] text-[hsl(var(--muted-foreground))]">{existingCount} existing visits retained{existingDates.filter(Boolean).at(-1) ? ` · Last dated visit ${existingDates.filter(Boolean).at(-1)}` : ""}</p> : null}
                <div className="divide-y divide-[hsl(var(--border)/0.7)] border-y border-[hsl(var(--border)/0.7)]">
                  {visits.map((visit, index) => (
                    <div key={visit.id} className={cn("flex min-w-0 flex-wrap items-center gap-2 py-2", activeIndex === index && "bg-[hsl(var(--primary)/0.05)]")}>
                      <button aria-expanded={activeIndex === index} aria-controls="upload-visit-files" type="button"
                        className={cn("flex min-h-[44px] min-w-[100px] flex-1 items-center gap-2 rounded-md px-2 text-left text-[13px] focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]", activeIndex === index && "font-semibold text-[hsl(var(--primary))]")}
                        onClick={() => { setActiveIndex(index); setArchiveProgress(null) }}>
                        <ChevronRight aria-hidden="true" className={cn("size-4 shrink-0", activeIndex === index && "rotate-90")} />
                        <span className="min-w-0"><span className="block">Visit {index + existingCount + 1}</span><span className="block max-w-[190px] truncate text-[12px] font-normal text-[hsl(var(--muted-foreground))]" title={visit.folder}>{visit.folder || "No files selected"}</span></span>
                        <span className="ml-auto shrink-0 tabular-nums">{requiredModalities.filter((key) => visit.files[key]).length}/4</span>
                      </button>
                      <label className="min-w-0 text-[12px] text-[hsl(var(--muted-foreground))]">
                        Date (optional)
                        <input aria-label={`Visit ${index + existingCount + 1} date`} type="date" value={visit.date}
                          className="block h-[44px] w-[154px] max-w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-[13px] text-[hsl(var(--foreground))]"
                          onChange={(event) => updateVisit(index, { date: event.target.value })} />
                      </label>
                      <div className="flex shrink-0">
                        <Button aria-label={`Move visit ${index + 1} earlier`} title="Move earlier" size="icon" variant="ghost" className="size-[44px]" type="button" disabled={index === 0} onClick={() => reorder(index, -1)}><ArrowUp className="size-4" /></Button>
                        <Button aria-label={`Move visit ${index + 1} later`} title="Move later" size="icon" variant="ghost" className="size-[44px]" type="button" disabled={index === visits.length - 1} onClick={() => reorder(index, 1)}><ArrowDown className="size-4" /></Button>
                        <Button aria-label={`Remove visit ${index + 1}`} title="Remove visit" size="icon" variant="ghost" className="size-[44px]" type="button" disabled={visits.length === 1} onClick={() => { changed(); setVisits((current) => current.filter((_, i) => i !== index)); setActiveIndex(0) }}><X className="size-4" /></Button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
              {active ? <section id="upload-visit-files" aria-label={`Visit ${activeIndex + existingCount + 1} modalities`} className="min-w-0">
                <h3 className="mb-3 text-[13px] font-semibold">Visit {activeIndex + existingCount + 1} · Modality mapping</h3>
                {active.unassigned.map((file) => <label className="mb-3 flex min-w-0 flex-wrap items-center gap-2 text-[13px]" key={file.name}>
                  <span className="min-w-0 flex-1 break-all">{file.name}</span>
                  <select aria-label={`Assign ${file.name}`} value="" className="h-[44px] rounded-md border bg-[hsl(var(--background))] px-2" onChange={(event) => {
                    const key = event.target.value as ModalityKey
                    if (!key) return
                    updateVisit(activeIndex, { files: { ...active.files, [key]: file }, unassigned: [...active.unassigned.filter((item) => item !== file), ...(active.files[key] ? [active.files[key]!] : [])] })
                  }}><option value="">Choose modality</option>{requiredModalities.map((key) => <option key={key} value={key}>{modalityMeta[key].label}</option>)}</select>
                </label>)}
                <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                  {requiredModalities.map((key) => <FileInput disabled={submitting || preparing} key={`${active.id}:${key}`} label={modalityMeta[key].label} selectedFile={active.files[key]}
                    onChange={(file) => updateVisit(activeIndex, { files: { ...active.files, [key]: file || undefined } })} />)}
                </div>
              </section> : null}
              <p className="text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">350 MB per file · 1 GB per upload. Dates are entered by you; undated visits keep the confirmed order.</p>
              {validation && readyCount === visits.length ? <p role="alert" className="text-[13px] text-[hsl(var(--destructive))]">{validation}</p> : null}
              {needsSamePatient ? <label className="flex min-h-[44px] cursor-pointer items-start gap-3 border-t border-[hsl(var(--border)/0.68)] pt-3 text-[13px] leading-5">
                <input type="checkbox" checked={samePatient} onChange={(event) => setSamePatient(event.target.checked)} className="mt-0.5 size-4 shrink-0 accent-[hsl(var(--primary))]" />
                <span>I confirm these visits belong to the same patient and are in the correct order.</span>
              </label> : null}
              <label className="flex min-h-[44px] cursor-pointer items-start gap-3 text-[13px] leading-5">
                <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5 size-4 shrink-0 accent-[hsl(var(--primary))]" />
                <span>I confirm these images are de-identified and approved for this research preview.</span>
              </label>
            </fieldset>
            {errorText ? <div role="alert" className="mt-4 rounded-lg border border-[hsl(var(--destructive)/0.36)] bg-[hsl(var(--destructive)/0.08)] px-3 py-2 text-[13px] leading-5 text-[hsl(var(--destructive))] [overflow-wrap:anywhere]">{errorText}</div> : null}
            {submitting ? <div role="status" className="mt-4 space-y-2 text-[13px]">
              <div className="flex items-center justify-between gap-2"><span>{progress >= 100 ? "Validating MRI visits" : "Uploading files"}</span>{progress < 100 ? <span className="tabular-nums">{progress}%</span> : <Loader2 className="size-4 animate-spin" />}</div>
              <progress aria-label="File transfer" className="h-2 w-full accent-[hsl(var(--primary))]" max={100} value={progress} />
            </div> : null}
          </div>
          <footer className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-[hsl(var(--border)/0.68)] bg-[hsl(var(--background)/0.6)] px-4 py-3 sm:px-6">
            <span className="text-[13px] text-[hsl(var(--muted-foreground))]">{visits.length} {visits.length === 1 ? "visit" : "visits"} · {readyCount * 4} files mapped</span>
            <div className="flex gap-2">
              <Button className="min-h-[44px] px-4 text-[13px]" disabled={submitting} onClick={onClose} type="button" variant="outline">Cancel</Button>
              <Button className="min-h-[44px] gap-2 px-4 text-[13px]" disabled={submitting || preparing || Boolean(validation) || Boolean(errorText) || !confirmed || (needsSamePatient && !samePatient)}
                onClick={() => onSubmit(visits, targetCaseId)} type="button">
                {submitting ? <Loader2 className="animate-spin" /> : <Play />}
                {submitting ? progress >= 100 ? "Validating files" : "Uploading files" : "Start segmentation"}
              </Button>
            </div>
          </footer>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

function FileInput({
  disabled = false,
  label,
  onChange,
  selectedFile,
}: {
  disabled?: boolean
  label: string
  onChange: (file: File | null) => void
  selectedFile?: File
}) {
  return (
    <div className={cn("flex min-w-0 items-start rounded-lg border bg-[hsl(var(--background))] transition-colors focus-within:border-[hsl(var(--ring))] focus-within:ring-2 focus-within:ring-[hsl(var(--ring)/0.24)]", selectedFile ? "border-[hsl(var(--status-ok)/0.4)]" : "border-[hsl(var(--input))]", disabled && "opacity-60")}>
      <label className="relative flex min-h-[72px] min-w-0 flex-1 cursor-pointer gap-3 p-3 hover:bg-[hsl(var(--muted)/0.35)]">
        <input
          aria-label={`${label} NIfTI file`}
          className="sr-only"
          accept=".nii,.nii.gz"
          disabled={disabled}
          onChange={(event) => { const file = event.currentTarget.files?.[0]; if (file) onChange(file); event.currentTarget.value = "" }}
          type="file"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-[13px] font-semibold leading-5">{label}</span>
            {selectedFile ? <span className="text-[11px] tabular-nums text-[hsl(var(--muted-foreground))]">{(selectedFile.size / 1024 / 1024).toFixed(1)} MB</span> : null}
          </div>
          <span className={cn("mt-1 block text-[12px] leading-5 [overflow-wrap:anywhere]", selectedFile ? "text-[hsl(var(--foreground))]" : "text-[hsl(var(--muted-foreground))]")}>
            {selectedFile?.name ?? "Choose NIfTI file"}
          </span>
          {selectedFile ? <span className="mt-1 block text-[11px] text-[hsl(var(--muted-foreground))]">Replace file</span> : null}
        </div>
        {!selectedFile ? <FolderOpen aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-[hsl(var(--muted-foreground))]" /> : null}
      </label>
      {selectedFile ? <Button aria-label={`Remove ${label} file`} className="m-1 size-[32px] shrink-0" disabled={disabled} onClick={() => onChange(null)} size="icon" title={`Remove ${label} file`} type="button" variant="ghost"><X aria-hidden="true" className="size-4" /></Button> : null}
    </div>
  )
}

function TimepointInput({
  dateValue,
  onDateChange,
  onRoleChange,
  roleValue,
}: {
  dateValue: string
  onDateChange: (value: string) => void
  onRoleChange: (value: TimepointRole) => void
  roleValue: TimepointRole
}) {
  return (
    <div className="grid gap-2 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-2">
      <label className="block space-y-1">
        <span className="text-[11px] text-[hsl(var(--muted-foreground))]">Clinical node</span>
        <select
          className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-[12px] outline-none"
          onChange={(event) => onRoleChange(event.target.value as TimepointRole)}
          value={roleValue}
        >
          <option value="pre_treatment_baseline">Pre-treatment baseline</option>
          <option value="post_rt_baseline">Post-treatment baseline</option>
          <option value="follow_up">Follow-up</option>
          <option value="nadir">Nadir</option>
          <option value="screening_baseline">Screening baseline</option>
        </select>
      </label>
      <label className="block space-y-1">
        <span className="text-[11px] text-[hsl(var(--muted-foreground))]">Scan date</span>
        <input
          className="h-9 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 text-[12px] outline-none"
          onChange={(event) => onDateChange(event.target.value)}
          placeholder="YYYY-MM-DD"
          type="date"
          value={dateValue}
        />
      </label>
    </div>
  )
}

function InlineNotice({ icon: Icon, spin, text }: { icon: ComponentType<{ className?: string }>; spin?: boolean; text: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-2 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">
      <Icon className={cn("mt-0.5 h-3.5 w-3.5", spin && "animate-spin")} />
      <span>{text}</span>
    </div>
  )
}

const PANEL_OVERLAY_OPTIONS: Array<{ key: PanelOverlay; label: string }> = [
  { key: "off", label: "None" },
  { key: "fill", label: "Fill" },
  { key: "outline", label: "Outline" },
]

const PANEL_SELECT_CLASS = "h-7 min-w-0 flex-1 cursor-pointer rounded-lg border border-zinc-700 bg-zinc-900 px-1.5 text-[11px] font-medium text-zinc-200 outline-none transition hover:border-zinc-500 focus-visible:border-zinc-300 disabled:cursor-not-allowed disabled:opacity-50"

// Compact per-panel controls: two selects fit a column even in a six-panel row.
function ReviewPanelControls({
  available,
  canRemove,
  index,
  onChange,
  onRemove,
  overlayEnabled,
  panel,
}: {
  available: ModalityKey[]
  canRemove: boolean
  index: number
  onChange: (patch: Partial<Pick<ReviewPanel, "modality" | "overlay">>) => void
  onRemove: () => void
  overlayEnabled: boolean
  panel: ReviewPanel
}) {
  return (
    <div className="flex items-center gap-1">
      <select
        aria-label={`Panel ${index + 1} MRI sequence`}
        className={PANEL_SELECT_CLASS}
        onChange={(event) => onChange({ modality: event.target.value as ModalityKey })}
        value={panel.modality}
      >
        {modalityOrder.map((key) => (
          <option disabled={!available.includes(key)} key={key} value={key}>
            {modalityMeta[key].label}
          </option>
        ))}
      </select>
      <select
        aria-label={`Panel ${index + 1} overlay`}
        className={PANEL_SELECT_CLASS}
        disabled={!overlayEnabled}
        onChange={(event) => onChange({ overlay: event.target.value as PanelOverlay })}
        title={overlayEnabled ? undefined : "Run segmentation to enable the overlay."}
        value={overlayEnabled ? panel.overlay : "off"}
      >
        {PANEL_OVERLAY_OPTIONS.map((option) => (
          <option key={option.key} value={option.key}>
            {option.label}
          </option>
        ))}
      </select>
      {canRemove ? (
        <button
          aria-label={`Remove panel ${index + 1}`}
          className="h-7 shrink-0 rounded-lg px-1.5 text-[13px] leading-none text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100"
          onClick={onRemove}
          title="Remove this panel"
          type="button"
        >
          ×
        </button>
      ) : null}
    </div>
  )
}

function ModalityChipRow({
  ariaLabel,
  available,
  compact = false,
  onChange,
  value,
}: {
  ariaLabel: string
  available: ModalityKey[]
  compact?: boolean
  onChange: (key: ModalityKey) => void
  value: ModalityKey
}) {
  const options = modalityOrder.map((key) => ({
    key,
    label: modalityMeta[key].label,
    disabled: !available.includes(key),
  }))
  return (
    <div
      aria-label={ariaLabel}
      className={cn(
        "flex flex-wrap items-center gap-1 rounded-2xl border border-[hsl(var(--border)/0.58)] p-1",
        compact ? "bg-zinc-900/80" : "bg-[hsl(var(--background)/0.68)] shadow-[inset_0_1px_0_hsl(var(--card)/0.9)]",
      )}
      role="group"
    >
      {options.map((option) => (
        <button
          aria-pressed={value === option.key}
          className={cn(
            "rounded-xl font-medium transition duration-200 disabled:cursor-not-allowed disabled:opacity-40",
            compact ? "h-7 px-2.5 text-[11px]" : "h-8 px-3 text-[12px]",
            value === option.key
              ? compact
                ? "bg-zinc-200 text-zinc-950"
                : "bg-[hsl(var(--foreground))] text-[hsl(var(--background))] shadow-[0_8px_18px_hsl(var(--foreground)/0.13)]"
              : compact
                ? "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
                : "text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted)/0.72)] hover:text-[hsl(var(--foreground))]",
          )}
          disabled={option.disabled}
          key={option.key}
          onClick={() => onChange(option.key)}
          title={option.disabled ? "This sequence is not available for the selected visit." : undefined}
          type="button"
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function LegendChip({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--border))] px-2 py-1">
      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </span>
  )
}

function MetricLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span>{label}</span>
      <span className="truncate text-right font-medium text-[hsl(var(--foreground))]">{value}</span>
    </div>
  )
}

function ReportText({ text }: { text: string }) {
  const sections = parseReportSections(text)
  return (
    <div className="report-text">
      {sections.map((section, index) => (
        <section key={`${section.heading ?? "body"}-${index}`}>
          {section.heading ? <h3>{section.heading}</h3> : null}
          {section.paragraphs.map((paragraph, paragraphIndex) => (
            <p className="text-pretty" key={`${paragraph.slice(0, 24)}-${paragraphIndex}`}>{renderReportLine(paragraph)}</p>
          ))}
          {section.bullets.length ? (
            <ul className="report-list">
              {section.bullets.map((bullet, bulletIndex) => (
                <li key={`${bullet.slice(0, 24)}-${bulletIndex}`}>{renderReportLine(bullet)}</li>
              ))}
            </ul>
          ) : null}
        </section>
      ))}
    </div>
  )
}

function parseReportSections(text: string): Array<{ bullets: string[]; heading?: string; paragraphs: string[] }> {
  const normalized = text.replace(/\r\n/g, "\n").trim()
  if (!normalized) return [{ bullets: [], paragraphs: ["No report text is available yet."] }]
  const sections: Array<{ bullets: string[]; heading?: string; paragraphs: string[] }> = []
  let current: { bullets: string[]; heading?: string; paragraphs: string[] } = { bullets: [], paragraphs: [] }

  const pushCurrent = () => {
    if (current.paragraphs.length || current.bullets.length) {
      sections.push(current)
    }
  }

  normalized.split(/\n+/).map((line) => line.trim()).filter(Boolean).forEach((line) => {
    // Only section labels become headings; bold field labels stay with their values.
    const heading = line.match(/^#{1,4}\s+(.+?)\s*:?(?:\s+#+)?$/)
    const labeled = line.match(/^(?:\*\*)?([A-Za-z][A-Za-z /&-]{2,48}?)(?::\*\*|\*\*:|\*\*|:)\s*(.*)$/)
    const plainHeading = reportHeadingLabels.has(line.toLowerCase()) ? line : ""
    const knownHeading = labeled && reportHeadingLabels.has(labeled[1].toLowerCase())
    if (heading || knownHeading || plainHeading) {
      pushCurrent()
      current = { bullets: [], heading: (heading?.[1] || (knownHeading ? labeled[1] : plainHeading)).replace(/:$/, ""), paragraphs: [] }
      if (knownHeading && labeled[2]) current.paragraphs.push(labeled[2])
    } else if (/^(?:[-*]|\d+\.)\s+/.test(line)) {
      current.bullets.push(line.replace(/^(?:[-*]|\d+\.)\s+/, ""))
    } else {
      current.paragraphs.push(line)
    }
  })
  pushCurrent()
  return sections.length ? sections : [{ bullets: [], paragraphs: [normalized] }]
}

const reportHeadingLabels = new Set([
  "case context",
  "basic information",
  "findings",
  "impression",
  "key measurements",
  "quantitative summary",
  "reviewer note",
  "workflow status",
  "qc / provenance",
  "qc & provenance",
])

function renderReportLine(text: string): ReactNode {
  const normalized = text.trim()
  const match = normalized.match(/^\*\*([^*]+):\*\*\s*(.*)$/) ?? normalized.match(/^([A-Za-z][A-Za-z /-]{2,44}):\s+(.+)$/)
  if (!match) return renderInlineMarkdown(normalized)
  const label = match[1].trim()
  const value = match[2] ?? ""
  return (
    <>
      <strong className="font-semibold text-[hsl(var(--foreground))]">{label}:</strong>
      {value ? <span> {renderInlineMarkdown(value)}</span> : null}
    </>
  )
}

function renderInlineMarkdown(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean)
  if (parts.length === 1) return text
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong className="font-semibold text-[hsl(var(--foreground))]" key={`${part}-${index}`}>{part.slice(2, -2)}</strong>
    }
    return <span key={`${part}-${index}`}>{part}</span>
  })
}

function ReviewButton({
  active,
  disabled,
  icon: Icon,
  label,
  onClick,
}: {
  active: boolean
  disabled: boolean
  icon: ComponentType<{ className?: string }>
  label: string
  onClick: () => void
}) {
  return (
    <button
      className={cn(
        "inline-flex h-8 items-center justify-center gap-1.5 rounded-xl border px-2.5 text-[11px] font-medium transition duration-200 hover:-translate-y-0.5",
        active
          ? "border-[hsl(var(--primary)/0.58)] bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--primary))] shadow-[0_8px_22px_hsl(var(--primary)/0.08)]"
          : "border-[hsl(var(--border)/0.66)] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted)/0.72)] hover:text-[hsl(var(--foreground))] hover:shadow-[0_10px_24px_hsl(var(--foreground)/0.045)]",
      )}
      disabled={disabled}
      onClick={onClick}
      type="button"
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  )
}

function ExportLink({ href, label }: { href?: string; label: string }) {
  if (!href) {
    return (
      <button
        className="flex h-8 items-center justify-between rounded-md border border-[hsl(var(--border))] px-2 text-[11px] text-[hsl(var(--muted-foreground))] opacity-60"
        disabled
        type="button"
      >
        <span>{label}</span>
        <Download className="h-3.5 w-3.5" />
      </button>
    )
  }
  return (
    <Button asChild className="justify-between" size="lg" variant="outline">
      <a href={href}>
        <span>{label}</span>
        <Download />
      </a>
    </Button>
  )
}
