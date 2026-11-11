import type {
  InputMode, ModalityKey, LongitudinalPoint, LongitudinalRow,
  ReviewState, QcReasonKey, TimepointRole, WorkflowStatus, TumorSession,
} from "./brainTumor.types"
import type { SegmentationOverlayModel } from "@/lib/segmentationOverlay"
import { qcReasonOptions, regionLabels, tumorPalette } from "./brainTumor.constants"
import { isRegistered, registrationLabel } from "./brainTumor.provenance"
import { annotateVisitTiming, formatDay, normalizeRelativeDay, timelineScale, timelineTicks, visitTimeLabel, visitTimingLabel } from "./brainTumor.timing.ts"

export function buildGbmTumorOverlayModel(volumes: Array<{ region: string; volume_ml: number; voxel_count?: number }>): SegmentationOverlayModel {
  const volumeByRegion = new Map(volumes.map((volume) => [volume.region, Number(volume.volume_ml) || 0]))
  const groups = [
    {
      id: "rano_target",
      displayName: "RANO target",
      color: tumorPalette.et,
      strokeColor: "#8f2e42",
      labels: [
        {
          labelId: 3,
          labelName: "enhancing_tumor",
          displayName: "Contrast-enhancing tumor",
          groupId: "rano_target",
          groupDisplayName: "RANO target",
          hemisphere: null,
          volumeMm3: (volumeByRegion.get("enhancing_tumor") ?? 0) * 1000,
          color: tumorPalette.et,
          strokeColor: "#8f2e42",
          fillOpacity: 0.7,
        },
      ],
    },
    {
      id: "flair_context",
      displayName: "T2/FLAIR context",
      color: tumorPalette.wt,
      strokeColor: "#1f5f86",
      labels: [
        {
          labelId: 2,
          labelName: "flair_abnormality",
          displayName: "T2/FLAIR abnormality",
          groupId: "flair_context",
          groupDisplayName: "T2/FLAIR context",
          hemisphere: null,
          volumeMm3: (volumeByRegion.get("flair_abnormality") ?? 0) * 1000,
          color: tumorPalette.wt,
          strokeColor: "#1f5f86",
          fillOpacity: 0.7,
        },
      ],
    },
    {
      id: "treatment_anatomy",
      displayName: "Cavity / exclusion",
      color: tumorPalette.rc,
      strokeColor: "#665232",
      labels: [
        {
          labelId: 4,
          labelName: "cavity_or_post_surgical_change",
          displayName: "Cavity / post-surgical candidate",
          groupId: "treatment_anatomy",
          groupDisplayName: "Cavity / exclusion",
          hemisphere: null,
          volumeMm3: (volumeByRegion.get("cavity_or_post_surgical_change") ?? 0) * 1000,
          color: tumorPalette.rc,
          strokeColor: "#665232",
          fillOpacity: 0.58,
        },
      ],
    },
    {
      id: "research_labels",
      displayName: "Research labels",
      color: tumorPalette.net,
      strokeColor: "#55468b",
      labels: [
        {
          labelId: 1,
          labelName: "non_enhancing_core_candidate",
          displayName: "Non-enhancing core candidate",
          groupId: "research_labels",
          groupDisplayName: "Research labels",
          hemisphere: null,
          volumeMm3: (volumeByRegion.get("non_enhancing_core_candidate") ?? 0) * 1000,
          color: tumorPalette.net,
          strokeColor: "#55468b",
          fillOpacity: 0.58,
        },
      ],
    },
  ]

  return {
    groups,
    labelById: Object.fromEntries(groups.flatMap((group) => group.labels.map((label) => [label.labelId, label]))),
  }
}

export function toAbsoluteAssetUrl(url: string | null | undefined) {
  if (!url) {
    return null
  }
  try {
    return new URL(url, window.location.origin).toString()
  } catch {
    return url
  }
}

export function buildRunSegmentationHint(inputMode: InputMode, hasRequired: boolean, hasLoadedCase: boolean): string {
  if (hasRequired) return "Run segmentation on the selected source."
  if (inputMode === "upload") return "Upload all four NIfTI modalities: T1c, FLAIR, T2, and T1."
  if (hasLoadedCase) return "This case already has segmentation outputs. Select Upload or map a study to run a new segmentation."
  return "Select a study and map all four required MRI modalities before running segmentation."
}

export function isNiftiFileName(fileName: string): boolean {
  return /\.nii(\.gz)?$/i.test(fileName)
}

export function inferModalityFromFileName(fileName: string): { modality: ModalityKey; reason: string } | null {
  const base = fileName.toLowerCase().replace(/\.nii(\.gz)?$/i, "")
  const compact = base.replace(/[^a-z0-9]+/g, "")
  if (/(^|[^0-9])0000($|[^0-9])/.test(base)) return { modality: "t1n", reason: "BraTS/Dataset channel 0000" }
  if (/(^|[^0-9])0001($|[^0-9])/.test(base)) return { modality: "t1c", reason: "BraTS/Dataset channel 0001" }
  if (/(^|[^0-9])0002($|[^0-9])/.test(base)) return { modality: "t2w", reason: "BraTS/Dataset channel 0002" }
  if (/(^|[^0-9])0003($|[^0-9])/.test(base)) return { modality: "t2f", reason: "BraTS/Dataset channel 0003" }
  if (compact.includes("flair") || compact.includes("t2flair") || compact.includes("t2f")) {
    return { modality: "t2f", reason: "Filename contains FLAIR/T2F" }
  }
  if (
    compact.includes("t1ce") ||
    compact.includes("t1c") ||
    compact.includes("t1gd") ||
    compact.includes("t1post") ||
    compact.includes("postcontrast") ||
    compact.includes("contrastt1") ||
    compact.includes("cet1")
  ) {
    return { modality: "t1c", reason: "Filename contains post-contrast T1 marker" }
  }
  if (compact.includes("t2w") || /\bt2\b/.test(base.replace(/[_-]+/g, " "))) {
    return { modality: "t2w", reason: "Filename contains T2 marker" }
  }
  if (
    compact.includes("t1n") ||
    compact.includes("t1pre") ||
    compact.includes("pret1") ||
    compact.includes("precontrast") ||
    compact.includes("t1native") ||
    /\bt1\b/.test(base.replace(/[_-]+/g, " "))
  ) {
    return { modality: "t1n", reason: "Filename contains pre-contrast/native T1 marker" }
  }
  return null
}

export function buildActiveArtifactUrls(activePoint: LongitudinalRow | undefined, session: TumorSession | null): Record<string, string> {
  if (!activePoint) {
    return session?.artifact_urls ?? {}
  }
  const baseUrl = activePoint.segmentationUrl?.replace(/\/seg\.nii\.gz$/, "")
  return {
    overlay_preview: baseUrl ? `${baseUrl}/overlay_preview.png` : activePoint.overlayUrl ?? "",
    volumes_csv: baseUrl ? `${baseUrl}/volumes.csv` : "",
    tumor_regions: baseUrl ? `${baseUrl}/tumor_regions.json` : "",
    seg: activePoint.segmentationUrl ?? "",
    overlay_gt: baseUrl ? `${baseUrl}/overlay_gt.png` : activePoint.groundTruthOverlayUrl ?? "",
    volumes_gt_csv: baseUrl ? `${baseUrl}/volumes_gt.csv` : "",
    tumor_regions_gt: baseUrl ? `${baseUrl}/tumor_regions_gt.json` : "",
    gt_seg: activePoint.groundTruthSegmentationUrl ?? "",
  }
}

export function buildWorkflowSteps({
  canReview,
  hasRequired,
  intakeReady,
  reviewState,
  running,
  serviceReady,
  sessionComplete,
}: {
  canReview: boolean
  hasRequired: boolean
  intakeReady: boolean
  reviewState: ReviewState
  running: boolean
  serviceReady: boolean
  sessionComplete: boolean
}) {
  const reviewAccepted = sessionComplete && reviewState === "accepted"
  const reviewBlocked = sessionComplete && (reviewState === "needs_revision" || reviewState === "excluded")
  return [
    {
      label: "Intake",
      detail: intakeReady ? "Study selected" : "Choose source",
      status: intakeReady ? "complete" : "active",
    },
    {
      label: "Map",
      detail: hasRequired ? "4 MRI channels ready" : "Confirm required modalities",
      status: hasRequired ? "complete" : intakeReady ? "active" : "pending",
    },
    {
      label: "QC gate",
      detail: sessionComplete ? "Model result available" : serviceReady ? "Model ready" : "Model warming or offline",
      status: sessionComplete ? "complete" : hasRequired ? (serviceReady ? "complete" : "blocked") : "pending",
    },
    {
      label: "Segment",
      detail: running ? "Running inference" : sessionComplete ? "Completed" : "Ready to run",
      status: running ? "active" : sessionComplete ? "complete" : hasRequired && serviceReady ? "active" : "pending",
    },
    {
      label: "Review",
      detail: reviewAccepted
        ? "QC passed"
        : reviewState === "needs_revision" && sessionComplete
          ? "Rerun required"
          : reviewState === "excluded" && sessionComplete
            ? "Excluded"
            : canReview
              ? "Review overlay"
              : "Awaiting overlay",
      status: reviewAccepted ? "complete" : reviewBlocked ? "blocked" : canReview ? "active" : "pending",
    },
    {
      label: "Handoff",
      detail: reviewAccepted ? "Ready to export" : reviewBlocked ? "Blocked by QC" : sessionComplete ? "Needs QC pass" : "Awaiting review",
      status: reviewAccepted ? "complete" : reviewBlocked ? "blocked" : "pending",
    },
  ] satisfies Array<{ label: string; detail: string; status: WorkflowStatus }>
}


export function buildLongitudinalRows(points: LongitudinalPoint[], baselineId: string, samePatient = true): LongitudinalRow[] {
  const timedPoints = annotateVisitTiming(points, baselineId, samePatient)
  const baseline = timedPoints.find((point) => point.id === baselineId) ?? timedPoints[0]
  const baselineEt = getRegionVolume(baseline, "enhancing_tumor")
  const baselineFlair = getRegionVolume(baseline, "flair_abnormality")
  const baselineWt = getRegionVolume(baseline, "whole_tumor")
  let nadirEt = Number.POSITIVE_INFINITY
  return timedPoints.map((point) => {
    const measured = (target: LongitudinalPoint | undefined, region: string) => target?.volumes.some((volume) => volume.region === region && Number.isFinite(volume.volume_ml)) === true
    const etMl = getRegionVolume(point, "enhancing_tumor")
    const flairMl = getRegionVolume(point, "flair_abnormality")
    const wtMl = getRegionVolume(point, "whole_tumor")
    if (measured(point, "enhancing_tumor")) nadirEt = Math.min(nadirEt, etMl)
    return {
      ...point,
      isReference: point.id === baseline?.id,
      etMl,
      flairMl,
      wtMl,
      tcMl: getRegionVolume(point, "tumor_core"),
      netMl: getRegionVolume(point, "non_enhancing_core_candidate"),
      rcMl: getRegionVolume(point, "cavity_or_post_surgical_change"),
      etChangePct: measured(point, "enhancing_tumor") && measured(baseline, "enhancing_tumor") ? percentChange(etMl, baselineEt) : null,
      flairChangePct: measured(point, "flair_abnormality") && measured(baseline, "flair_abnormality") ? percentChange(flairMl, baselineFlair) : null,
      wtChangePct: measured(point, "whole_tumor") && measured(baseline, "whole_tumor") ? percentChange(wtMl, baselineWt) : null,
      etNadirChangePct: measured(point, "enhancing_tumor") && Number.isFinite(nadirEt) ? percentChange(etMl, nadirEt) : null,
    }
  })
}

export function activePointReport(point: LongitudinalRow | undefined): string {
  if (!point) return "Load a case or run segmentation to generate report-ready tumor burden language."
  const cavityFinding = point.rcMl > 0
    ? `cavity/exclusion candidate ${formatMm3(point.rcMl)}`
    : "no cavity/exclusion candidate volume detected"
  return `Contrast-enhancing tumor measures ${formatMm3(point.etMl)}; T2/FLAIR abnormality measures ${formatMm3(point.flairMl)}. Whole abnormality: ${formatMm3(point.wtMl)}; ${cavityFinding}.`
}

export function activePointImpression(point: LongitudinalRow | undefined, samePatientLongitudinal = true): string {
  if (!point) return "QC warnings and longitudinal context will be included after a case is loaded."
  if (!samePatientLongitudinal) {
    return "Cohort example measurement loaded. Do not interpret percent deltas as treatment response unless same-patient provenance is confirmed."
  }
  if (point.isReference) {
    return "This scan is the selected reference. No interval change is reported for the reference scan itself."
  }
  const change = formatPct(point.etChangePct)
  return point.etChangePct === null
    ? "Reference measurement loaded. Confirm imaging provenance before clinical use."
    : `Enhancing tumor change is ${change} versus the selected reference. Confirm same-patient provenance before applying response rules.`
}

export function getRegionVolume(point: LongitudinalPoint | undefined, region: string): number {
  const value = point?.volumes.find((row) => row.region === region)?.volume_ml
  return Number.isFinite(Number(value)) ? Number(value) : 0
}

export function percentChange(value: number, reference: number): number | null {
  if (!Number.isFinite(value) || !Number.isFinite(reference) || reference <= 0) return null
  return ((value - reference) / reference) * 100
}

export function buildVisitTimingText(points: LongitudinalRow[], samePatient = true): string {
  return ["Visit timing:", ...points.map((point, index) =>
    `Visit ${index + 1}: ${localVisitTimingDetail(point, samePatient)}`,
  )].join("\n")
}

function localVisitTimingDetail(point: LongitudinalRow, samePatient = true): string {
  const relativeDay = normalizeRelativeDay(point.relativeDay)
  return [
    `Scan date: ${point.scanDate ?? "Unknown"}`,
    visitTimingLabel(point, samePatient),
    `Relative day: ${relativeDay === null ? "Unknown" : `Day ${formatDay(relativeDay)}`}`,
    `Relative day origin: ${point.relativeDayOrigin?.trim() || "Unknown"}`,
    ...(samePatient && point.timingSamePatient !== false && point.daysFromReference != null
      ? [`Offset from selected reference: ${formatDay(point.daysFromReference)} days`] : []),
  ].join("; ")
}

export function buildReportExportText(
  caseLabel: string,
  dateLabel: string,
  reviewState: ReviewState,
  qcReasons: QcReasonKey[],
  point: LongitudinalRow | undefined,
  session: TumorSession | null,
  points: LongitudinalRow[] = [],
  samePatientLongitudinal = true,
): string {
  const timingPoints = points.length ? points : point ? [point] : []
  return [
    "Basic information:",
    `Case: ${caseLabel}`,
    `Scan: ${point ? visitTimeLabel(point) : dateLabel}`,
    ...(timingPoints.length ? ["", buildVisitTimingText(timingPoints, samePatientLongitudinal)] : []),
    "",
    "Findings:",
    point ? [
      `- CE tumor: ${formatMm3(point.etMl)}`,
      `- T2/FLAIR abnormality: ${formatMm3(point.flairMl)}`,
      `- Whole abnormality: ${formatMm3(point.wtMl)}`,
      `- Cavity / exclusion candidate: ${formatMm3(point.rcMl)}`,
    ].join("\n") : session?.report_snippet.findings ?? activePointReport(point),
    "",
    "Impression:",
    point ? activePointImpression(point, samePatientLongitudinal) : session?.report_snippet.impression ?? activePointImpression(point),
    "",
    "QC / provenance:",
    "Measurement source: Model segmentation",
    `Mask review: ${reviewStateLabel(reviewState)}`,
    ...(qcReasons.length ? [`QC reasons: ${qcReasons.map(qcReasonLabel).join("; ")}`] : []),
    ...(points.length > 1 && samePatientLongitudinal ? [
      `Alignment: ${points.filter((item) => item.isReference || isRegistered(item.registration)).length}/${points.length} visits, including the reference.`,
    ] : []),
    "Research preview. Not a diagnostic report.",
  ].join("\n")
}

export function buildReportPayload(
  caseLabel: string,
  dateLabel: string,
  reviewState: ReviewState,
  qcReasons: QcReasonKey[],
  activePoint: LongitudinalRow | undefined,
  points: LongitudinalRow[],
  session: TumorSession | null,
  progress?: {
    alignment?: { completed_count: number; total_count: number }
    segmentation?: { completed_count: number; total_count: number }
  },
  samePatientLongitudinal = true,
) {
  const fallbackSegmentation = {
    completed_count: points.filter((point) => Boolean(point.segmentationUrl)).length,
    total_count: points.length,
  }
  const fallbackAlignment = {
    completed_count: points.filter((point) => point.isReference || isRegistered(point.registration)).length,
    total_count: points.length,
  }
  return {
    session_id: activePoint?.sessionId || session?.session_id || "",
    measurement_source: "model_segmentation",
    case_label: caseLabel,
    date: activePoint ? visitTimeLabel(activePoint) : dateLabel,
    qc_state: reviewStateLabel(reviewState),
    qc_reasons: qcReasons.map(qcReasonLabel),
    findings: activePointReport(activePoint),
    impression: activePoint ? activePointImpression(activePoint, samePatientLongitudinal) : session?.report_snippet.impression ?? activePointImpression(activePoint),
    active_measurements: activePoint ? measurementPayload(activePoint) : null,
    alignment: progress?.alignment ?? fallbackAlignment,
    segmentation: progress?.segmentation ?? fallbackSegmentation,
    timepoints: points.map(measurementPayload),
    intended_use: "research quantitative imaging draft; not a standalone diagnosis",
  }
}

export function measurementPayload(point: LongitudinalRow, index = 0) {
  return {
    case_id: point.sessionId || point.id,
    label: point.label,
    role: roleLabel(point.role),
    is_reference: point.isReference,
    date: visitTimeLabel(point, index),
    scan_date: point.scanDate ?? null,
    relative_day: normalizeRelativeDay(point.relativeDay),
    relative_day_origin: point.relativeDayOrigin?.trim() || null,
    interval_days: point.intervalDays ?? null,
    days_from_reference: point.daysFromReference ?? null,
    WT_mm3: mm3Integer(point.wtMl),
    FLAIR_abnormality_mm3: mm3Integer(point.flairMl),
    TC_mm3: mm3Integer(point.tcMl),
    ET_mm3: mm3Integer(point.etMl),
    NET_mm3: mm3Integer(point.netMl),
    RC_mm3: mm3Integer(point.rcMl),
    ET_change_pct: csvNumber(point.etChangePct, 2),
    FLAIR_change_pct: csvNumber(point.flairChangePct, 2),
    WT_change_pct: csvNumber(point.wtChangePct, 2),
    registration_status: point.isReference ? "Reference" : registrationLabel(point.registration),
    registration_ncc_delta: csvNumber(point.registration?.ncc_delta, 4),
  }
}

export function buildReportHtml({
  activePoint,
  caseLabel,
  dateLabel,
  draftSource,
  draftText,
  exportedAtLabel,
  figureSvg,
  findingsText,
  logoDataUrl,
  measurementsCsv,
  points,
  qcReasons,
  reviewState,
  summaryText,
}: {
  activePoint?: LongitudinalRow
  caseLabel: string
  dateLabel: string
  draftSource?: "none" | "local" | "ai"
  draftText?: string
  exportedAtLabel?: string
  figureSvg: string
  findingsText: string
  logoDataUrl?: string
  measurementsCsv: string
  points: LongitudinalRow[]
  qcReasons: QcReasonKey[]
  reviewState: ReviewState
  summaryText: string
}) {
  const selectedPoint = activePoint ?? points[0]
  const selectedTimeLabel = selectedPoint ? visitTimeLabel(selectedPoint, Math.max(0, points.findIndex(point => point.id === selectedPoint.id))) : dateLabel
  const referencePoint = points.find((point) => point.isReference) ?? points[0]
  const latestPoint = points[points.length - 1]
  const qcLabel = reviewStateLabel(reviewState)
  const qcText = qcReasons.length ? qcReasons.map(qcReasonLabel).join("; ") : "No QC exceptions recorded"
  const primaryChange = selectedPoint ? formatPct(selectedPoint.etChangePct) : "baseline"
  const volumeCards = buildHtmlVolumeCards(selectedPoint)
  const measurementRows = buildHtmlMeasurementRows(points, selectedPoint?.id)
  const workflowRows = buildHtmlWorkflowRows(points, reviewState)
  const logoMarkup = buildHtmlLogoMarkup(logoDataUrl)
  const draftLabel = draftSource === "none" ? "Measurement preview" : draftSource === "ai" ? "AI-assisted draft" : "Structured draft"
  const generatedLabel = exportedAtLabel?.trim() || "Local export"
  const trendCaption = selectedPoint
    ? `Figure 1. Longitudinal segmentation-derived tumor burden with ${escapeHtml(selectedPoint.label)} selected. Values are spacing-aware volumes in mm³.`
    : "Figure 1. Longitudinal segmentation-derived tumor burden."
  const draftPanel = draftText?.trim()
    ? `<section class="block">
        <div class="section-kicker">Generated narrative</div>
        <h2>Report draft for reviewer handoff</h2>
        <div class="narrative-stack">${renderReportSectionCards(draftText)}</div>
      </section>`
    : ""

  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapeHtml(caseLabel)} GBM report</title>
  <style>
    :root {
      color-scheme: light;
      --page: #f6f4f0;
      --paper: #ffffff;
      --ink: #2f2a24;
      --muted: #78716a;
      --faint: #a8a29e;
      --line: #e7e1d8;
      --line-soft: #f0ebe4;
      --surface: #fbfaf8;
      --surface-strong: #fffdf9;
      --callout: #f7f0e5;
      --callout-blue: #eff5f6;
      --accent: #8f5d46;
      --accent-soft: #f1e6dd;
      --red: #a44f4f;
      --green: #4f765f;
      --yellow: #9a6a2f;
      --shadow: 0 24px 70px rgba(68, 58, 47, 0.10);
      --shadow-soft: 0 14px 36px rgba(68, 58, 47, 0.08);
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      background:
        radial-gradient(circle at 18% -8%, rgba(210, 146, 70, 0.16), transparent 34%),
        linear-gradient(180deg, #fbfaf7 0%, var(--page) 42%, #f1eee8 100%);
      color: var(--ink);
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.55;
    }
    .page {
      width: min(1060px, calc(100vw - 48px));
      margin: 36px auto 58px;
      background: var(--paper);
      border: 1px solid rgba(225, 218, 209, 0.82);
      border-radius: 28px;
      box-shadow: var(--shadow);
      padding: 34px;
    }
    .brandbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 30px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--line-soft);
    }
    .brand {
      display: inline-flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .logo-shell {
      width: 88px;
      height: 58px;
      display: grid;
      place-items: center;
      border-radius: 16px;
      background: linear-gradient(145deg, #fff8ef, #f2e4d4);
      border: 1px solid rgba(210, 146, 70, 0.28);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82), 0 10px 22px rgba(143, 93, 70, 0.12);
    }
    .logo-shell img { width: 72px; height: 48px; object-fit: contain; display: block; }
    .logo-fallback {
      color: #d29246;
      font-family: ui-serif, Georgia, serif;
      font-size: 22px;
      font-weight: 700;
      line-height: 1;
    }
    .brand-title {
      font-size: 13px;
      font-weight: 720;
      letter-spacing: 0.01em;
    }
    .brand-subtitle {
      margin-top: 2px;
      color: var(--muted);
      font-size: 11px;
    }
    .export-meta {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
    }
    .meta-pill {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      border-radius: 999px;
      border: 1px solid var(--line-soft);
      background: rgba(255, 253, 249, 0.82);
      padding: 4px 10px;
      color: var(--muted);
      font-size: 11px;
      box-shadow: 0 5px 14px rgba(68, 58, 47, 0.04);
    }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(280px, .85fr);
      gap: 24px;
      align-items: end;
      padding: 8px 2px 22px;
    }
    .breadcrumb {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 16px;
      color: var(--faint);
      font-size: 12px;
    }
    .breadcrumb span:not(:last-child)::after {
      content: "/";
      margin-left: 6px;
      color: #c8c0b6;
    }
    h1 {
      margin: 0 0 12px;
      max-width: 780px;
      font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif;
      font-size: clamp(34px, 5vw, 52px);
      line-height: 1.12;
      font-weight: 650;
      letter-spacing: -0.02em;
    }
    .subtitle {
      margin: 0;
      max-width: 760px;
      color: var(--muted);
      font-size: 14px;
    }
    .hero-card {
      border-radius: 22px;
      background: linear-gradient(145deg, #fffdf9, #f8f2eb);
      border: 1px solid rgba(231, 225, 216, 0.88);
      box-shadow: var(--shadow-soft);
      padding: 18px;
    }
    .hero-card-label {
      color: var(--muted);
      font-size: 10px;
      font-weight: 720;
      letter-spacing: 0.13em;
      text-transform: uppercase;
    }
    .hero-card-value {
      margin-top: 10px;
      font-size: 30px;
      line-height: 1;
      font-weight: 720;
      letter-spacing: -0.02em;
      font-variant-numeric: tabular-nums;
    }
    .hero-card-sub {
      margin-top: 9px;
      color: var(--muted);
      font-size: 12px;
    }
    .hero-status {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 16px;
    }
    .status-item {
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.58);
      border: 1px solid rgba(231, 225, 216, 0.72);
      padding: 9px 10px;
    }
    .status-item span {
      display: block;
      color: var(--faint);
      font-size: 10px;
      font-weight: 650;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .status-item strong {
      display: block;
      margin-top: 3px;
      font-size: 12px;
      font-weight: 680;
    }
    .properties {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
      margin: 10px 0 28px;
    }
    .property-label, .property-value {
      display: block;
      border-bottom: 0;
      font-size: 13px;
    }
    .property {
      min-width: 0;
      border: 1px solid var(--line-soft);
      border-radius: 16px;
      background: rgba(251, 250, 248, 0.76);
      padding: 12px 13px;
    }
    .property-label {
      color: var(--muted);
      font-size: 10px;
      font-weight: 680;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .property-value {
      margin-top: 5px;
      color: var(--ink);
      font-weight: 560;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .callout {
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(240px, .9fr);
      gap: 16px;
      margin-bottom: 26px;
    }
    .callout-panel {
      border-radius: 18px;
      background: var(--callout);
      border: 1px solid #ede5d8;
      padding: 17px 18px;
      box-shadow: 0 10px 26px rgba(68, 58, 47, 0.045);
    }
    .callout-panel.blue {
      background: var(--callout-blue);
      border-color: #e2e8eb;
    }
    .callout-title {
      margin: 0 0 6px;
      font-size: 13px;
      font-weight: 680;
    }
    .small {
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.65;
    }
    .block {
      margin-top: 28px;
      padding: 24px;
      border: 1px solid var(--line-soft);
      border-radius: 22px;
      background: rgba(255, 255, 255, 0.72);
      box-shadow: 0 12px 32px rgba(68, 58, 47, 0.045);
    }
    .section-kicker, .block-label {
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 10px;
      font-weight: 650;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    h2 {
      margin: 0 0 14px;
      font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif;
      font-size: 23px;
      line-height: 1.2;
      font-weight: 620;
      letter-spacing: -0.01em;
    }
    h3 {
      margin: 0 0 6px;
      font-size: 13px;
      font-weight: 650;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }
    .metric {
      min-width: 0;
      border: 1px solid rgba(231, 225, 216, 0.82);
      border-radius: 18px;
      background: linear-gradient(180deg, #fffefa, #fbf7f1);
      padding: 15px 15px;
      box-shadow: 0 10px 22px rgba(68, 58, 47, 0.045);
    }
    .metric-label {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 620;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 99px;
      flex: 0 0 auto;
    }
    .metric-value {
      margin-top: 10px;
      font-size: 24px;
      line-height: 1;
      font-weight: 680;
      letter-spacing: -0.015em;
      font-variant-numeric: tabular-nums;
    }
    .metric-sub {
      margin-top: 7px;
      color: var(--faint);
      font-size: 12px;
    }
    .workflow {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }
    .workflow-row {
      display: grid;
      grid-template-columns: 18px minmax(0, 1fr);
      gap: 8px;
      align-items: start;
      padding: 13px;
      border: 1px solid var(--line-soft);
      border-radius: 16px;
      background: var(--surface-strong);
      font-size: 13px;
    }
    .check {
      width: 16px;
      height: 16px;
      border-radius: 99px;
      border: 1px solid rgba(79, 118, 95, 0.3);
      background: #eef5ef;
      display: inline-grid;
      place-items: center;
      color: var(--green);
      font-size: 11px;
      line-height: 1;
    }
    .workflow-row strong { font-weight: 600; }
    .workflow-row em {
      grid-column: 2;
      color: var(--muted);
      font-style: normal;
      font-size: 12px;
    }
    .visual {
      overflow-x: auto;
      border: 1px solid rgba(231, 225, 216, 0.86);
      border-radius: 20px;
      background: linear-gradient(180deg, #fffefa, #faf6ef);
      padding: 14px;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
    }
    .visual svg {
      display: block;
      width: 100%;
      max-width: 920px;
      height: auto;
      margin: 0 auto;
    }
    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--line-soft);
      border-radius: 18px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line-soft);
      text-align: left;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      background: #fbfaf8;
      font-size: 10px;
      font-weight: 650;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    tbody tr:last-child td { border-bottom: 0; }
    td span {
      display: block;
      color: var(--faint);
      font-size: 11px;
    }
    td.num, th.num {
      text-align: right;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }
    tr.active-row td { background: #fff8f5; }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      border-radius: 999px;
      background: #f5f1eb;
      padding: 2px 7px;
      color: var(--muted);
      font-size: 11px;
      white-space: nowrap;
    }
    .delta-up { color: var(--red); }
    .delta-down { color: var(--green); }
    .delta-flat { color: var(--muted); }
    .narrative {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    .narrative-panel {
      border: 1px solid var(--line-soft);
      border-radius: 18px;
      background: var(--surface-strong);
      padding: 16px 17px;
    }
    .prose {
      color: #3f3a34;
      font-size: 13px;
      line-height: 1.72;
    }
    .narrative-stack {
      display: grid;
      gap: 12px;
    }
    .draft-section {
      border: 1px solid var(--line-soft);
      border-radius: 18px;
      background: linear-gradient(180deg, #fffefa, #fbf7f1);
      padding: 16px 18px 16px 16px;
      box-shadow: 0 8px 20px rgba(68, 58, 47, 0.04);
    }
    .draft-section h3 {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
      font-size: 14px;
    }
    .draft-section h3::before {
      content: "";
      width: 3px;
      height: 18px;
      border-radius: 99px;
      background: var(--accent);
      box-shadow: 0 0 0 4px rgba(143, 93, 70, 0.08);
    }
    .caption {
      margin: 10px 2px 0;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.55;
    }
    .note-body {
      color: #3f3a34;
      font-size: 13px;
      line-height: 1.72;
    }
    details {
      margin-top: 28px;
      border-top: 1px solid var(--line);
    }
    summary {
      cursor: pointer;
      padding: 14px 0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    pre {
      margin: 0;
      overflow-x: auto;
      border: 1px solid var(--line-soft);
      border-radius: 10px;
      background: #fffdfb;
      padding: 14px;
      font-size: 11px;
      line-height: 1.5;
    }
    .footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      margin-top: 30px;
      padding-top: 18px;
      border-top: 1px solid var(--line-soft);
      color: var(--faint);
      font-size: 11px;
    }
    .footer-brand { display: inline-flex; align-items: center; gap: 8px; color: var(--muted); font-weight: 650; }
    .footer-brand .logo-shell { width: 52px; height: 34px; border-radius: 10px; box-shadow: none; }
    .footer-brand .logo-shell img { width: 42px; height: 28px; }
    @media (max-width: 820px) {
      .page { width: 100%; margin: 0; border-radius: 0; padding: 28px 20px; }
      .brandbar, .footer { align-items: flex-start; flex-direction: column; }
      .export-meta { justify-content: flex-start; }
      .hero, .properties, .callout, .metrics, .narrative, .workflow { grid-template-columns: 1fr; }
    }
    @media print {
      body { background: #fff; }
      .page { width: 100%; margin: 0; border: 0; box-shadow: none; padding: 24px; }
      .block, .callout-panel, .metric, details { break-inside: avoid; }
    }
  </style>
</head>
<body>
  <main class="page">
    <section class="brandbar" aria-label="Report brand">
      <div class="brand">
        ${logoMarkup}
        <div>
          <div class="brand-title">ClinAgent GBM quantitative handoff</div>
          <div class="brand-subtitle">Segmentation · alignment · QC · report draft</div>
        </div>
      </div>
      <div class="export-meta">
        <span class="meta-pill">${escapeHtml(draftLabel)}</span>
        <span class="meta-pill">${escapeHtml(generatedLabel)}</span>
      </div>
    </section>

    <section class="hero">
      <header>
        <nav class="breadcrumb" aria-label="Report location"><span>ClinAgent</span><span>GBM Care</span><span>Quantitative report</span></nav>
        <h1>${escapeHtml(caseLabel)}</h1>
        <p class="subtitle">Reviewer-facing summary of the selected scan, longitudinal tumor burden, processing readiness, and report language. This export is standalone and contains embedded ClinAgent branding.</p>
      </header>
      <aside class="hero-card" aria-label="Primary report target">
        <div class="hero-card-label">Primary report target</div>
        <div class="hero-card-value">${formatMm3Number(selectedPoint?.etMl ?? Number.NaN)} mm³</div>
        <div class="hero-card-sub">CE tumor · ${escapeHtml(primaryChange)} vs reference</div>
        <div class="hero-status">
          <div class="status-item"><span>Selected</span><strong>${escapeHtml(selectedTimeLabel)}</strong></div>
          <div class="status-item"><span>QC</span><strong>${escapeHtml(qcLabel)}</strong></div>
          <div class="status-item"><span>Visits</span><strong>${points.length}</strong></div>
          <div class="status-item"><span>Draft</span><strong>${escapeHtml(draftLabel)}</strong></div>
        </div>
      </aside>
    </section>

    <section class="properties" aria-label="Case properties">
      <div class="property"><span class="property-label">Selected scan</span><span class="property-value">${escapeHtml(selectedTimeLabel)}</span></div>
      <div class="property"><span class="property-label">Reference</span><span class="property-value">${escapeHtml(referencePoint ? visitTimeLabel(referencePoint, points.indexOf(referencePoint)) : "Not available")}</span></div>
      <div class="property"><span class="property-label">Latest</span><span class="property-value">${escapeHtml(latestPoint ? visitTimeLabel(latestPoint, points.length - 1) : "Not available")}</span></div>
      <div class="property"><span class="property-label">CE change</span><span class="property-value">${escapeHtml(primaryChange)}</span></div>
      <div class="property"><span class="property-label">Segmentation QC</span><span class="property-value">${escapeHtml(qcLabel)}</span></div>
    </section>

    <section class="callout" aria-label="Review notes">
      <div class="callout-panel">
        <p class="callout-title">QC notes</p>
        <p class="small">${escapeHtml(qcText)}</p>
      </div>
      <div class="callout-panel blue">
        <p class="callout-title">Use boundary</p>
        <p class="small">Research-use quantitative draft. Confirm source imaging, registration, segmentation overlay, and clinical context before final clinical reporting.</p>
      </div>
    </section>

    <section class="block">
      <p class="section-kicker">Selected scan</p>
      <h2>Key measurements</h2>
      <div class="metrics">${volumeCards}</div>
    </section>

    <section class="block">
      <p class="section-kicker">Agent workflow</p>
      <h2>Processing chain</h2>
      <div class="workflow">${workflowRows}</div>
    </section>

    <section class="block">
      <p class="section-kicker">Visual summary</p>
      <h2>Figure 1 · Longitudinal trend and composition</h2>
      <div class="visual">${figureSvg}</div>
      <p class="caption">${trendCaption}</p>
    </section>

    <section class="block">
      <p class="section-kicker">Measurements</p>
      <h2>Longitudinal table</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>Scan</th><th>Role</th><th class="num">CE tumor</th><th class="num">T2/FLAIR</th><th class="num">Whole abnormality</th><th class="num">CE change</th><th>Registration</th></tr></thead>
        <tbody>${measurementRows}</tbody>
      </table></div>
    </section>

    <section class="block">
      <p class="section-kicker">Report language</p>
      <h2>Findings and summary</h2>
      <div class="narrative">
        <div class="narrative-panel"><h3>Findings</h3><div class="prose">${renderPlainTextBlock(findingsText)}</div></div>
        <div class="narrative-panel"><h3>Summary</h3><div class="prose">${renderPlainTextBlock(summaryText)}</div></div>
      </div>
    </section>

    ${draftPanel}

    <details><summary>Measurement CSV appendix</summary><pre>${escapeHtml(measurementsCsv)}</pre></details>
    <footer class="footer">
      <div class="footer-brand">${logoMarkup}<span>ClinAgent</span></div>
      <div>Reviewer handoff artifact. Confirm imaging, registration, segmentation overlay, and clinical context before final reporting.</div>
    </footer>
  </main>
</body>
</html>`
}

function buildHtmlLogoMarkup(logoDataUrl: string | undefined): string {
  if (logoDataUrl) {
    return `<span class="logo-shell"><img alt="ClinAgent logo" src="${escapeHtml(logoDataUrl)}" /></span>`
  }
  return `<span class="logo-shell"><span class="logo-fallback">C</span></span>`
}

function buildHtmlVolumeCards(point: LongitudinalRow | undefined): string {
  const cards = [
    {
      color: tumorPalette.et,
      label: regionLabels.enhancing_tumor,
      sub: point ? `vs reference ${formatPct(point.etChangePct)}` : "No selected scan",
      value: point?.etMl,
    },
    {
      color: tumorPalette.wt,
      label: regionLabels.flair_abnormality,
      sub: point ? `vs reference ${formatPct(point.flairChangePct)}` : "No selected scan",
      value: point?.flairMl,
    },
    {
      color: tumorPalette.tc,
      label: regionLabels.whole_tumor,
      sub: point ? `vs reference ${formatPct(point.wtChangePct)}` : "No selected scan",
      value: point?.wtMl,
    },
    {
      color: tumorPalette.rc,
      label: regionLabels.cavity_or_post_surgical_change,
      sub: "Cavity / exclusion context",
      value: point?.rcMl,
    },
  ]
  return cards
    .map((card) => `
      <article class="metric">
        <div class="metric-label"><span class="dot" style="background:${card.color}"></span>${escapeHtml(card.label)}</div>
        <div class="metric-value">${formatMm3Number(card.value ?? Number.NaN)} mm³</div>
        <div class="metric-sub">${escapeHtml(card.sub)}</div>
      </article>
    `)
    .join("")
}

function buildHtmlWorkflowRows(points: LongitudinalRow[], reviewState: ReviewState): string {
  const alignedCount = points.filter((point) => point.isReference || isRegistered(point.registration)).length
  const rows = [
    {
      detail: points.length ? `${points.length} visit${points.length === 1 ? "" : "s"} loaded` : "No visit loaded",
      label: "Raw MRI loaded",
    },
    {
      detail: points.some((point) => point.segmentationUrl) ? "Mask and volumes available" : "Waiting for segmentation",
      label: "Segmentation",
    },
    {
      detail: points.length > 1 ? `${alignedCount}/${points.length} visits aligned` : "Reference visit only",
      label: "Alignment",
    },
    {
      detail: reviewStateLabel(reviewState),
      label: "QC review",
    },
    {
      detail: "Narrative and table exported",
      label: "Report output",
    },
  ]
  return rows.map((row) => `
    <div class="workflow-row">
      <span class="check">✓</span>
      <strong>${escapeHtml(row.label)}</strong>
      <em>${escapeHtml(row.detail)}</em>
    </div>
  `).join("")
}

function buildHtmlMeasurementRows(points: LongitudinalRow[], activePointId: string | undefined): string {
  if (!points.length) {
    return `<tr><td colspan="7">No longitudinal measurements available.</td></tr>`
  }
  return points
    .map((point, index) => {
      const registration = point.isReference
        ? "Reference"
        : registrationLabel(point.registration)
      return `<tr class="${point.id === activePointId ? "active-row" : ""}">
        <td><strong>${escapeHtml(visitTimeLabel(point, index))}</strong><br/><span class="small">${escapeHtml(point.label)}</span><br/><span class="small">${escapeHtml(localVisitTimingDetail(point))}</span></td>
        <td><span class="pill">${escapeHtml(roleLabel(point.role))}</span></td>
        <td class="num">${escapeHtml(formatMm3(point.etMl))}</td>
        <td class="num">${escapeHtml(formatMm3(point.flairMl))}</td>
        <td class="num">${escapeHtml(formatMm3(point.wtMl))}</td>
        <td class="num ${htmlDeltaClass(point.etChangePct)}">${escapeHtml(formatPct(point.etChangePct))}</td>
        <td>${escapeHtml(registration)}</td>
      </tr>`
    })
    .join("")
}

function htmlDeltaClass(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value) || Math.abs(value) < 0.1) return "delta-flat"
  return value > 0 ? "delta-up" : "delta-down"
}

function renderPlainTextBlock(text: string): string {
  const normalized = text
    .trim()
    .replace(/(^|\n)\s*#{1,6}\s+/g, "$1")
    .replace(/\r\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
  return renderInlineMarkdownHtml(normalized || "No report text available.").replace(/\n\n/g, "<br/><br/>").replace(/\n/g, "<br/>")
}

function renderReportSectionCards(text: string): string {
  const normalized = text
    .replace(/\r\n/g, "\n")
    .replace(/\s+-\s+(?=Visit\s+\d+\b)/g, "\n- ")
    .replace(/(^|\n)\s*#{2,4}\s+([^\n]+)\s*/g, "\n**$2:**\n")
    .replace(/(^|\n)\s*\*\*([^*\n:]+)\*\*\s*/g, "\n**$2:**\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
  if (!normalized) {
    return `<article class="draft-section"><h3>Generated narrative</h3><div class="prose">No report text available.</div></article>`
  }
  const pieces = normalized.split(/(\*\*[^*]+:\*\*)/g).filter(Boolean)
  const sections: Array<{ body: string[]; heading: string }> = []
  let current: { body: string[]; heading: string } = { body: [], heading: "Generated narrative" }

  const pushCurrent = () => {
    if (current.body.length || current.heading !== "Generated narrative") {
      sections.push(current)
    }
  }

  pieces.forEach((piece) => {
    const headingMatch = piece.match(/^\*\*([^*]+):\*\*$/)
    if (headingMatch) {
      pushCurrent()
      current = { body: [], heading: headingMatch[1].trim() }
      return
    }
    const lines = piece
      .split(/\n+/)
      .map((line) => line.trim())
      .filter(Boolean)
    current.body.push(...lines)
  })
  pushCurrent()

  return (sections.length ? sections : [{ body: [normalized], heading: "Generated narrative" }])
    .map((section) => `
      <article class="draft-section">
        <h3>${escapeHtml(section.heading)}</h3>
        <div class="prose">${renderPlainTextBlock(section.body.join("\n\n"))}</div>
      </article>
    `)
    .join("")
}

function renderInlineMarkdownHtml(text: string): string {
  return escapeHtml(text).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
}

export function buildReportFigureSvg(points: LongitudinalRow[], activePointId: string | undefined): string {
  const width = 920
  const chartLeft = 70
  const chartTop = 105
  const chartWidth = 500
  const chartHeight = 250
  const scale = timelineScale(points)
  const timeTicks = timelineTicks(points, chartWidth, 11)
  const tickExtraHeight = Math.max(0, ...timeTicks.map(tick => tick.lane)) * 20
  const height = 460 + tickExtraHeight
  const xPosition = (index: number) => chartLeft + scale.positions[index] * chartWidth
  const active = points.find((point) => point.id === activePointId) ?? points[0]
  const maxVolume = Math.max(1, ...points.flatMap((point) => [point.etMl, point.flairMl]).filter(Number.isFinite))
  const yPosition = (value: number) => chartTop + chartHeight - (Math.max(0, value) / maxVolume) * chartHeight
  const trend = (values: number[], color: string, strokeWidth: number) => {
    const path = values.map((value, index) => `${index ? "L" : "M"} ${xPosition(index)} ${yPosition(value)}`).join(" ")
    const markers = values.map((value, index) => `<circle cx="${xPosition(index)}" cy="${yPosition(value)}" r="4" fill="${color}"><title>${escapeHtml(visitTimeLabel(points[index], index))}: ${escapeHtml(formatMm3(value))}</title></circle>`).join("")
    return `<path fill="none" d="${path}" stroke="${color}" stroke-width="${strokeWidth}" stroke-linecap="round" stroke-linejoin="round"/>${markers}`
  }
  const donut = buildSvgDonut([
    { color: tumorPalette.et, label: "CE tumor", value: active?.etMl ?? 0 },
    { color: tumorPalette.wt, label: "T2/FLAIR", value: active?.flairMl ?? 0 },
    { color: tumorPalette.rc, label: "Cavity", value: active?.rcMl ?? 0 },
  ])
  const xTicks = timeTicks
    .map(({ position, label, lane }) => `<text x="${chartLeft + position * chartWidth}" y="${chartTop + chartHeight + 34 + lane * 20}" data-visit-tick="" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="11" fill="#767676">${escapeHtml(label)}</text>`)
    .join("")
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="GBM volume trend and composition">
  <rect width="${width}" height="${height}" fill="#ffffff"/>
  <text x="40" y="34" font-family="Arial, Helvetica, sans-serif" font-size="20" font-weight="700" fill="#272727">GBM volume trend and composition</text>
  <text x="40" y="55" font-family="Arial, Helvetica, sans-serif" font-size="12" fill="#767676">RANO-oriented view: enhancing disease primary, T2/FLAIR abnormality contextual</text>
  <line x1="${chartLeft}" y1="${chartTop + chartHeight}" x2="${chartLeft + chartWidth}" y2="${chartTop + chartHeight}" stroke="#272727" stroke-width="2"/>
  <line x1="${chartLeft}" y1="${chartTop}" x2="${chartLeft}" y2="${chartTop + chartHeight}" stroke="#272727" stroke-width="2"/>
  ${trend(points.map((point) => point.etMl), tumorPalette.et, 4)}
  ${trend(points.map((point) => point.flairMl), tumorPalette.wt, 3)}
  ${xTicks}
  <text x="${chartLeft + chartWidth / 2}" y="${chartTop + chartHeight + 62 + tickExtraHeight}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="12" fill="#272727">X-axis basis: ${escapeHtml(scale.label)}</text>
  <text x="${chartLeft}" y="${chartTop - 18}" font-family="Arial, Helvetica, sans-serif" font-size="13" font-weight="700" fill="#272727">Volume (mm³)</text>
  ${svgLegend(615, 86, "CE tumor", tumorPalette.et)}
  ${svgLegend(615, 116, "T2/FLAIR abnormality", tumorPalette.wt)}
  ${svgLegend(615, 146, "Cavity/exclusion", tumorPalette.rc)}
  <g transform="translate(735 280)">${donut}</g>
</svg>`
}

export function buildMeasurementsCsv(points: LongitudinalRow[]): string {
  const header = [
    "case_id",
    "case_label",
    "role",
    "date",
    "scan_date",
    "relative_day",
    "relative_day_origin",
    "interval_days_since_previous_visit",
    "days_from_selected_reference",
    "WT_mm3",
    "FLAIR_abnormality_mm3",
    "TC_mm3",
    "ET_mm3",
    "NET_mm3",
    "RC_mm3",
    "ET_change_pct",
    "FLAIR_change_pct",
    "WT_change_pct",
    "registration_status",
    "registration_ncc_delta",
  ]
  const rows = points.map((point, index) => [
    point.sessionId || point.id,
    point.label,
    roleLabel(point.role),
    visitTimeLabel(point, index),
    point.scanDate ?? "",
    normalizeRelativeDay(point.relativeDay) ?? "",
    point.relativeDayOrigin?.trim() || "",
    point.intervalDays ?? "",
    point.daysFromReference ?? "",
    mm3Integer(point.wtMl),
    mm3Integer(point.flairMl),
    mm3Integer(point.tcMl),
    mm3Integer(point.etMl),
    mm3Integer(point.netMl),
    mm3Integer(point.rcMl),
    csvNumber(point.etChangePct, 2),
    csvNumber(point.flairChangePct, 2),
    csvNumber(point.wtChangePct, 2),
    point.registration?.status ?? "",
    csvNumber(point.registration?.ncc_delta, 4),
  ])
  return [header, ...rows].map((row) => row.map(csvEscape).join(",")).join("\n")
}

export function buildSvgDonut(items: Array<{ color: string; label: string; value: number }>): string {
  const total = items.reduce((sum, item) => sum + Math.max(0, item.value), 0)
  if (total <= 0) {
    return `<circle cx="0" cy="0" r="72" fill="none" stroke="#CFCECE" stroke-width="28"/>`
  }
  let cursor = -Math.PI / 2
  const paths = items
    .filter((item) => item.value > 0)
    .map((item) => {
      const angle = (item.value / total) * Math.PI * 2
      const start = cursor
      const end = cursor + angle
      cursor = end
      const largeArc = angle > Math.PI ? 1 : 0
      const r = 72
      const sx = Math.cos(start) * r
      const sy = Math.sin(start) * r
      const ex = Math.cos(end) * r
      const ey = Math.sin(end) * r
      return `<path d="M ${sx.toFixed(2)} ${sy.toFixed(2)} A ${r} ${r} 0 ${largeArc} 1 ${ex.toFixed(2)} ${ey.toFixed(2)}" fill="none" stroke="${item.color}" stroke-width="28" stroke-linecap="butt"/>`
    })
    .join("")
  return `${paths}<circle cx="0" cy="0" r="45" fill="#ffffff"/><text x="0" y="-2" text-anchor="middle" font-size="13" font-weight="700" fill="#272727">${formatMm3Number(total)}</text><text x="0" y="16" text-anchor="middle" font-size="10" fill="#767676">mm³</text>`
}

export function svgLegend(x: number, y: number, label: string, color: string): string {
  return `<rect x="${x}" y="${y - 9}" width="12" height="12" rx="2" fill="${color}"/><text x="${x + 20}" y="${y + 1}" font-family="Arial, Helvetica, sans-serif" font-size="12" fill="#272727">${escapeHtml(label)}</text>`
}

export function escapeHtml(value: string | number): string {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
}

export function downloadTextFile(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function safeFilePart(value: string): string {
  const normalized = value.toLowerCase().replace(/[^a-z0-9]+/gi, "-").replace(/^-+|-+$/g, "").slice(0, 80)
  return normalized || "case"
}

export function mm3Integer(valueMl: number): number | "" {
  return Number.isFinite(valueMl) ? Math.round(valueMl * 1000) : ""
}

export function csvNumber(value: number | null | undefined, digits: number): string {
  return value === null || value === undefined || !Number.isFinite(value) ? "" : value.toFixed(digits)
}

export function csvEscape(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? "" : String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export function reviewStateLabel(state: ReviewState): string {
  if (state === "accepted") return "QC passed"
  if (state === "needs_revision") return "Needs rerun"
  if (state === "excluded") return "Excluded from report"
  return "Pending"
}

export function reviewStateDetail(state: ReviewState): string {
  if (state === "accepted") return "Report/export can use this segmentation as a reviewed quantitative result."
  if (state === "needs_revision") return "Flag the case for remapping, registration check, or segmentation rerun before final handoff."
  if (state === "excluded") return "Keep the case visible for audit, but do not include it in final quantitative reporting."
  return "Load/review imaging and overlay before marking this case as passed."
}

export function qcReasonLabel(reason: QcReasonKey): string {
  return qcReasonOptions.find((item) => item.key === reason)?.label ?? reason
}
export function roleLabel(role: TimepointRole): string {
  if (role === "pre_treatment_baseline") return "Reference scan"
  if (role === "post_rt_baseline") return "Treatment reference"
  if (role === "screening_baseline") return "Reference scan"
  if (role === "nadir") return "Nadir"
  return "Follow-up"
}

export function formatMm3(valueMl: number): string {
  return Number.isFinite(valueMl) ? `${formatMm3Number(valueMl)} mm³` : "--"
}

export function formatMm3Number(valueMl: number): string {
  if (!Number.isFinite(valueMl)) return "--"
  return Math.round(valueMl * 1000).toLocaleString("en-US")
}

export function formatCompactMm3(valueMl: number): string {
  if (!Number.isFinite(valueMl)) return "--"
  const value = Math.round(valueMl * 1000)
  if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`
  if (value >= 1000) return `${Math.round(value / 1000)}k`
  return String(value)
}

export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "baseline"
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`
}

export function formatSignedNumber(value: number | null | undefined, digits: number): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "--"
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`
}

export function changeTone(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value) || Math.abs(value) < 0.1) {
    return "text-[hsl(var(--muted-foreground))]"
  }
  return value > 0 ? "text-[hsl(var(--destructive))]" : "text-[hsl(var(--status-ok))]"
}
