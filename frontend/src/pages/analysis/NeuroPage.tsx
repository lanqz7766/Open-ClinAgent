import { useEffect, useMemo, useState } from "react"
import { useOutletContext, useSearchParams } from "react-router-dom"

import { ChatPanel } from "@/components/ChatPanel"
import { MarkdownContent } from "@/components/MarkdownContent"
import { Button } from "@/components/ui/button"
import { ReviewActions } from "@/components/ReviewActions"
import { SummaryMetric } from "@/components/SummaryMetric"
import { WorkspacePanel } from "@/components/WorkspacePanel"
import { useApi, postApi } from "@/hooks/useApi"
import type { DemoLayoutContext, IngestWorkspace } from "@/lib/ingestTypes"

type ComparisonPanel = {
  title?: string
  label?: string
  timepoint?: string
  date?: string
  preview_path?: string
  image_url?: string
  overlay_path?: string
}

type TimelinePoint = {
  study_id?: string
  study_date?: string
  timepoint?: string
  lesion_volume_ml?: number
}

type WorkspaceReport = {
  title?: string
  subtitle?: string
  risk_level?: string
  summary?: string
  structured_text?: string
  rendered_html?: string
  sections?: { title: string; body: string }[]
  physician_questions?: string[]
}

type WorkspacePayload = {
  id: string
  title: string
  patient: { display_name: string; diagnosis?: string }
  timeline: TimelinePoint[]
  analysis: { risk_level?: string; risk_reason?: string; lesion_count?: number | string; delta_pct?: number }
  report: WorkspaceReport
  review: { status?: string; comment?: string }
  evidence_review?: { claims?: { statement?: string; verdict?: string }[] }
  visualizations?: {
    timeline_svg?: string
    trend_svg?: string
    comparison_svg?: string
    comparison_panels?: ComparisonPanel[]
  }
  imaging_preview?: {
    title?: string
    caption?: string
    image_url?: string
  }
  viewer?: {
    enabled?: boolean
    timepoints?: { timepoint?: string; study_date?: string; label?: string }[]
  }
}

function formatPercent(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "—"
  }
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`
}

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
}

function buildTimelineSvg(points: TimelinePoint[]) {
  if (!points.length) {
    return ""
  }

  const width = 720
  const height = 180
  const padding = 48
  const step = points.length > 1 ? (width - padding * 2) / (points.length - 1) : 0

  const circles = points
    .map((point, index) => {
      const x = padding + step * index
      return `<circle cx="${x}" cy="88" r="6" fill="hsl(18 55% 55%)" />
        <text x="${x}" y="116" text-anchor="middle" font-size="11" fill="hsl(30 5% 45%)">${escapeHtml(point.timepoint ?? `T${index + 1}`)}</text>
        <text x="${x}" y="134" text-anchor="middle" font-size="10" fill="hsl(30 5% 45%)">${escapeHtml(point.study_date ?? "")}</text>`
    })
    .join("")

  const line = points
    .map((_, index) => `${padding + step * index},88`)
    .join(" ")

  return `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="100%" height="100%">
      <rect width="${width}" height="${height}" rx="18" fill="hsl(40 15% 95%)" />
      <text x="${padding}" y="34" font-size="14" font-weight="600" fill="hsl(30 5% 14%)">Follow-up timeline</text>
      <polyline points="${line}" fill="none" stroke="hsl(18 55% 55%)" stroke-width="2" stroke-linecap="round" />
      ${circles}
    </svg>
  `
}

function buildTrendSvg(points: TimelinePoint[]) {
  const numericPoints = points.filter((point) => typeof point.lesion_volume_ml === "number")
  if (!numericPoints.length) {
    return ""
  }

  const width = 720
  const height = 260
  const padding = 44
  const values = numericPoints.map((point) => point.lesion_volume_ml as number)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = Math.max(max - min, 1)
  const step = numericPoints.length > 1 ? (width - padding * 2) / (numericPoints.length - 1) : 0

  const linePoints = numericPoints
    .map((point, index) => {
      const x = padding + step * index
      const y = height - padding - (((point.lesion_volume_ml as number) - min) / range) * (height - padding * 2)
      return `${x},${y}`
    })
    .join(" ")

  const dots = numericPoints
    .map((point, index) => {
      const x = padding + step * index
      const y = height - padding - (((point.lesion_volume_ml as number) - min) / range) * (height - padding * 2)
      return `
        <circle cx="${x}" cy="${y}" r="4.5" fill="hsl(18 55% 55%)" />
        <text x="${x}" y="${height - 18}" text-anchor="middle" font-size="10" fill="hsl(30 5% 45%)">${escapeHtml(point.timepoint ?? `T${index + 1}`)}</text>
        <text x="${x}" y="${y - 10}" text-anchor="middle" font-size="10" fill="hsl(30 5% 30%)">${(point.lesion_volume_ml as number).toFixed(1)} ml</text>
      `
    })
    .join("")

  return `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="100%" height="100%">
      <rect width="${width}" height="${height}" rx="18" fill="hsl(40 15% 95%)" />
      <text x="${padding}" y="32" font-size="14" font-weight="600" fill="hsl(30 5% 14%)">Lesion burden trend</text>
      <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="hsl(35 8% 85%)" stroke-width="1" />
      <line x1="${padding}" y1="${padding}" x2="${padding}" y2="${height - padding}" stroke="hsl(35 8% 85%)" stroke-width="1" />
      <polyline points="${linePoints}" fill="none" stroke="hsl(18 55% 55%)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
      ${dots}
    </svg>
  `
}

function buildReportMarkdown(report?: WorkspaceReport | null) {
  if (!report) {
    return ""
  }

  const lines: string[] = []
  if (report.title) {
    lines.push(`# ${report.title}`)
  }
  if (report.subtitle) {
    lines.push(report.subtitle)
  }
  if (report.summary) {
    lines.push("", report.summary)
  }
  for (const section of report.sections ?? []) {
    lines.push("", `## ${section.title}`, section.body)
  }
  if ((report.physician_questions ?? []).length) {
    lines.push("", "## Physician questions", ...(report.physician_questions ?? []).map((item) => `- ${item}`))
  }
  return lines.join("\n")
}

export function NeuroPage() {
  const { chat } = useOutletContext<DemoLayoutContext>()
  const snapshot = useApi<{
    cases: { id: string; patient: { display_name: string } }[]
    default_case_id: string
    workspace: WorkspacePayload
  }>("/api/demo/workspace")
  const [searchParams] = useSearchParams()
  const [caseId, setCaseId] = useState<string>("")
  const [workspace, setWorkspace] = useState<WorkspacePayload | null>(null)
  const [report, setReport] = useState<{ report?: WorkspaceReport } | null>(null)
  const [evidence, setEvidence] = useState<{ evidence_review?: { claims?: { statement?: string; verdict?: string }[] } } | null>(null)
  const [contractWorkspace, setContractWorkspace] = useState<IngestWorkspace | null>(null)

  useEffect(() => {
    if (!snapshot.data) return
    setCaseId(searchParams.get("caseId") || snapshot.data.default_case_id)
    setWorkspace(snapshot.data.workspace)
  }, [searchParams, snapshot.data])

  useEffect(() => {
    const workspaceId = searchParams.get("workspaceId")
    if (!workspaceId) {
      setContractWorkspace(null)
      return
    }

    let cancelled = false

    fetch(`/api/ingest/workspace/${workspaceId}`)
      .then((response) => response.json())
      .then((payload) => {
        if (!cancelled && payload.ok) {
          setContractWorkspace(payload.data as IngestWorkspace)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setContractWorkspace(null)
        }
      })

    return () => {
      cancelled = true
    }
  }, [searchParams])

  useEffect(() => {
    async function loadDetails(activeCaseId: string) {
      const [casePayload, evidencePayload, reportPayload] = await Promise.all([
        fetch(`/api/demo/cases/${activeCaseId}`).then((res) => res.json()),
        fetch(`/api/demo/cases/${activeCaseId}/evidence-board`).then((res) => res.json()),
        fetch(`/api/demo/cases/${activeCaseId}/report`).then((res) => res.json()),
      ])
      setWorkspace(casePayload)
      setEvidence(evidencePayload)
      setReport(reportPayload)
    }

    if (caseId) {
      void loadDetails(caseId)
    }
  }, [caseId])

  async function handleReview(action: string) {
    if (!caseId) return
    const payload = await postApi<WorkspacePayload>("/api/demo/review", {
      case_id: caseId,
      action,
      comment: workspace?.review?.comment ?? "",
    })
    setWorkspace(payload)
  }

  function handleLaunchViewer() {
    window.open(`/demo/analysis/neuro?caseId=${caseId}&viewer=1`, "_blank", "noopener,noreferrer")
  }

  const activeReport = report?.report ?? workspace?.report

  const timelineSvg = useMemo(() => {
    return workspace?.visualizations?.timeline_svg || buildTimelineSvg(workspace?.timeline ?? [])
  }, [workspace])

  const trendSvg = useMemo(() => {
    return workspace?.visualizations?.trend_svg || buildTrendSvg(workspace?.timeline ?? [])
  }, [workspace])

  const comparisonPanels = workspace?.visualizations?.comparison_panels ?? []
  const fallbackPreview = workspace?.imaging_preview?.image_url
  const markdownReport = buildReportMarkdown(activeReport)

  if (contractWorkspace) {
    return (
      <div className="space-y-6">
        <WorkspacePanel
          subtitle={`Patient ${contractWorkspace.patient_id} · ${contractWorkspace.timepoints.length} timepoints`}
          title={contractWorkspace.workflow_type}
        >
          <div className="grid gap-3 md:grid-cols-3">
            <SummaryMetric label="Patient" value={contractWorkspace.patient_id} />
            <SummaryMetric label="Timepoints" value={String(contractWorkspace.timepoints.length)} />
            <SummaryMetric label="Created" value={contractWorkspace.created_at || "—"} />
          </div>
        </WorkspacePanel>

        <WorkspacePanel title="Assembled longitudinal timeline">
          <div className="space-y-3">
            {contractWorkspace.timepoints.map((timepoint) => (
              <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3" key={`${timepoint.label}-${timepoint.date}`}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-[13px] font-medium">{timepoint.label}</p>
                    <p className="text-[12px] text-[hsl(var(--muted-foreground))]">{timepoint.date}</p>
                  </div>
                  <div className="flex flex-wrap gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
                    <span>{timepoint.imaging_paths.length} imaging refs</span>
                    {timepoint.segmentation_path ? <span>segmentation linked</span> : null}
                  </div>
                </div>
                {timepoint.report_text ? (
                  <div className="mt-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
                    <MarkdownContent content={timepoint.report_text} />
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </WorkspacePanel>

        <WorkspacePanel title="Review and chat">
          <ChatPanel controller={chat} endpoint="/api/demo/execute-stream" />
        </WorkspacePanel>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <WorkspacePanel
        subtitle={workspace?.analysis.risk_reason}
        title={workspace?.title ?? "Neuro review"}
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-[13px] text-[hsl(var(--muted-foreground))]">Case</label>
            <select
              className="h-9 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 text-[13px]"
              onChange={(event) => setCaseId(event.target.value)}
              value={caseId}
            >
              {(snapshot.data?.cases ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.patient.display_name}
                </option>
              ))}
            </select>
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            <SummaryMetric label="Patient" value={workspace?.patient.display_name ?? "—"} />
            <SummaryMetric label="Lesions" value={String(workspace?.analysis.lesion_count ?? 0)} />
            <SummaryMetric label="Delta %" value={formatPercent(workspace?.analysis.delta_pct)} />
          </div>
        </div>
      </WorkspacePanel>

      <WorkspacePanel title="Timeline visualization">
        {timelineSvg ? (
          <div
            className="overflow-hidden rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))]"
            dangerouslySetInnerHTML={{ __html: timelineSvg }}
          />
        ) : (
          <p className="text-[13px] text-[hsl(var(--muted-foreground))]">No timeline available.</p>
        )}
      </WorkspacePanel>

      <WorkspacePanel title="Trend chart">
        {trendSvg ? (
          <div
            className="overflow-hidden rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))]"
            dangerouslySetInnerHTML={{ __html: trendSvg }}
          />
        ) : (
          <p className="text-[13px] text-[hsl(var(--muted-foreground))]">No trend available.</p>
        )}
      </WorkspacePanel>

      <WorkspacePanel title="Comparison panels">
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-[13px] text-[hsl(var(--muted-foreground))]">
              Privacy-preserving axial slice previews from the rendered longitudinal workspace.
            </p>
            {workspace?.viewer?.enabled ? (
              <Button onClick={handleLaunchViewer} type="button" variant="outline">
                Launch volume viewer
              </Button>
            ) : (
              <span className="text-[12px] text-[hsl(var(--muted-foreground))]">Volume viewer - coming soon</span>
            )}
          </div>

          {workspace?.visualizations?.comparison_svg ? (
            <div
              className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3"
              dangerouslySetInnerHTML={{ __html: workspace.visualizations.comparison_svg }}
            />
          ) : null}

          {comparisonPanels.length ? (
            <div className="grid gap-4 xl:grid-cols-3">
              {comparisonPanels.map((panel, index) => {
                const src = panel.preview_path || panel.image_url
                const label = panel.label || panel.title || `Panel ${index + 1}`
                const date = panel.date || panel.timepoint

                return (
                  <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3" key={`${label}-${index}`}>
                    <p className="mb-2 text-[13px] font-medium">{label}</p>
                    {src ? (
                      <img
                        alt={`${label} axial slice`}
                        className="w-full rounded-md border border-[hsl(var(--border))]"
                        src={src}
                        style={{ maxHeight: "280px", objectFit: "contain", background: "#000" }}
                      />
                    ) : (
                      <p className="text-[12px] text-[hsl(var(--muted-foreground))]">No image</p>
                    )}
                    {date ? <p className="mt-2 text-[12px] text-[hsl(var(--muted-foreground))]">{date}</p> : null}
                  </div>
                )
              })}
            </div>
          ) : fallbackPreview ? (
            <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
              <p className="mb-2 text-[13px] font-medium">{workspace?.imaging_preview?.title ?? "Representative preview"}</p>
              <img
                alt="Representative longitudinal imaging preview"
                className="w-full rounded-md border border-[hsl(var(--border))]"
                src={fallbackPreview}
                style={{ maxHeight: "320px", objectFit: "contain", background: "#000" }}
              />
              {workspace?.imaging_preview?.caption ? (
                <p className="mt-2 text-[12px] text-[hsl(var(--muted-foreground))]">{workspace.imaging_preview.caption}</p>
              ) : null}
            </div>
          ) : (
            <p className="text-[13px] text-[hsl(var(--muted-foreground))]">No comparison preview available.</p>
          )}
        </div>
      </WorkspacePanel>

      <WorkspacePanel title="Evidence board">
        <div className="space-y-2">
          {(evidence?.evidence_review?.claims ?? []).map((claim, index) => (
            <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3" key={`${claim.statement}-${index}`}>
              <p className="text-[13px] font-medium">{claim.statement ?? "Claim"}</p>
              <p className="mt-1 text-[12px] text-[hsl(var(--muted-foreground))]">{claim.verdict ?? "pending"}</p>
            </div>
          ))}
        </div>
      </WorkspacePanel>

      <WorkspacePanel title={activeReport?.title ?? "Report"}>
        {activeReport?.rendered_html ? (
          <div
            className="prose max-w-none text-[hsl(var(--foreground))]"
            dangerouslySetInnerHTML={{ __html: activeReport.rendered_html }}
          />
        ) : markdownReport ? (
          <MarkdownContent content={markdownReport} className="max-w-none" />
        ) : activeReport?.summary || (activeReport?.sections ?? []).length ? (
          <div className="space-y-3">
            {activeReport?.summary ? (
              <p className="text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">{activeReport.summary}</p>
            ) : null}
            {(activeReport?.sections ?? []).map((section) => (
              <section key={section.title}>
                <h3 className="text-[14px] font-medium">{section.title}</h3>
                <p className="mt-1 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">{section.body}</p>
              </section>
            ))}
          </div>
        ) : (
          <p className="text-[13px] text-[hsl(var(--muted-foreground))]">No report generated yet.</p>
        )}
      </WorkspacePanel>

      <WorkspacePanel title="Review and chat">
        <div className="grid gap-6 xl:grid-cols-[20rem_1fr]">
          <ReviewActions
            comment={workspace?.review?.comment}
            onApprove={() => void handleReview("approve")}
            onReject={() => void handleReview("reject")}
            status={workspace?.review?.status}
          />
          <ChatPanel controller={chat} endpoint="/api/demo/execute-stream" />
        </div>
      </WorkspacePanel>
    </div>
  )
}
