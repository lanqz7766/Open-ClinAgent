import { useEffect, useState } from "react"

import { RiskBadge } from "@/components/RiskBadge"
import { SummaryMetric } from "@/components/SummaryMetric"
import { WorkspacePanel } from "@/components/WorkspacePanel"
import { useApi } from "@/hooks/useApi"

export function ReportQualityPage() {
  type ReportQualityWorkspace = {
    id: string
    title: string
    summary: string
    analysis_plan_summary?: {
      family?: string
      track?: string
      dashboard_profile?: string
      summary: string
      detected_inputs: string[]
      missing_info: string[]
      runtime_mode: string
    }
    status_tone: "urgent" | "alert" | "watch" | "ok"
    status_label: string
    score: number
    summary_cards: { label: string; value: string }[]
    report_html: string
    findings_groups: {
      category: string
      items: { title: string; detail: string }[]
    }[]
  }

  const { data, loading } = useApi<{
    default_case_id: string
    workspace: ReportQualityWorkspace
  }>("/api/report-quality/workspace")
  const [workspace, setWorkspace] = useState<ReportQualityWorkspace | null>(null)

  useEffect(() => {
    if (data?.workspace) {
      setWorkspace(data.workspace)
    }
  }, [data])

  if (loading && !workspace) {
    return <div className="text-[13px] text-[hsl(var(--muted-foreground))]">Loading report quality…</div>
  }

  return (
    <WorkspacePanel
      riskTier={workspace?.status_tone}
      subtitle={workspace?.summary}
      title={workspace?.title ?? "Report quality"}
    >
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          {workspace?.status_tone ? <RiskBadge tier={workspace.status_tone} /> : null}
          <span className="text-[13px] text-[hsl(var(--muted-foreground))]">{workspace?.status_label}</span>
        </div>
        {workspace?.analysis_plan_summary ? (
          <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Harness summary</div>
            <p className="mt-2 text-[13px] leading-6 text-[hsl(var(--foreground))]">{workspace.analysis_plan_summary.summary}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px]">
                Mode {workspace.analysis_plan_summary.runtime_mode}
              </span>
              {workspace.analysis_plan_summary.track ? (
                <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px]">
                  Track {workspace.analysis_plan_summary.track}
                </span>
              ) : null}
              {workspace.analysis_plan_summary.dashboard_profile ? (
                <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px]">
                  Dashboard {workspace.analysis_plan_summary.dashboard_profile.replaceAll("_", " ")}
                </span>
              ) : null}
              {workspace.analysis_plan_summary.detected_inputs.map((item: string) => (
                <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px]" key={item}>
                  {item.replaceAll("_", " ")}
                </span>
              ))}
            </div>
          </div>
        ) : null}
        <div className="grid gap-3 md:grid-cols-4">
          {(workspace?.summary_cards ?? []).slice(0, 4).map((item) => (
            <SummaryMetric key={item.label} label={item.label} value={item.value} />
          ))}
        </div>
        <div
          className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4 text-[13px] leading-6"
          dangerouslySetInnerHTML={{ __html: workspace?.report_html ?? "" }}
        />
        <div className="space-y-3">
          {(workspace?.findings_groups ?? []).map((group) => (
            <section
              className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4"
              key={group.category}
            >
              <h3 className="text-[14px] font-medium capitalize">{group.category}</h3>
              <div className="mt-3 space-y-2">
                {group.items.map((item) => (
                  <div key={item.title}>
                    <p className="text-[13px] font-medium">{item.title}</p>
                    <p className="text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">{item.detail}</p>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </WorkspacePanel>
  )
}
