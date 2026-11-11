import { useEffect, useMemo, useState } from "react"

import { CaseCard } from "@/components/CaseCard"
import { EvidenceGrid } from "@/components/EvidenceGrid"
import { ReviewActions } from "@/components/ReviewActions"
import { SummaryMetric } from "@/components/SummaryMetric"
import { Button } from "@/components/ui/button"
import { WorkspacePanel } from "@/components/WorkspacePanel"
import { useApi, postApi } from "@/hooks/useApi"
import type { RiskTier, WorkflowSnapshot, WorkflowWorkspace } from "@/types/api"

type WorkflowModulePageProps = {
  apiPrefix: string
  title: string
}

type TabKey = "evidence" | "actions" | "review"

export function WorkflowModulePage({ apiPrefix, title }: WorkflowModulePageProps) {
  const { data, error, loading, refetch } = useApi<WorkflowSnapshot>(`${apiPrefix}/workspace`)
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null)
  const [selectedWorkspace, setSelectedWorkspace] = useState<WorkflowWorkspace | null>(null)
  const [tab, setTab] = useState<TabKey>("evidence")
  const [comment, setComment] = useState("")

  useEffect(() => {
    if (!data) {
      return
    }

    setSelectedCaseId((current) => current ?? data.default_case_id)
    setSelectedWorkspace((current) =>
      current && current.id === (current?.id ?? "")
        ? current
        : data.workspace,
    )
    setComment(data.workspace.review?.comment ?? "")
  }, [data])

  useEffect(() => {
    async function loadCase(caseId: string) {
      const response = await fetch(`${apiPrefix}/cases/${caseId}`)
      const payload = (await response.json()) as WorkflowWorkspace
      setSelectedWorkspace(payload)
      setComment(payload.review?.comment ?? "")
    }

    if (selectedCaseId && selectedCaseId !== selectedWorkspace?.id) {
      void loadCase(selectedCaseId)
    }
  }, [apiPrefix, selectedCaseId, selectedWorkspace?.id])

  const cases = data?.cases ?? []
  const workspace = selectedWorkspace ?? data?.workspace ?? null
  const metrics = workspace?.summary_cards?.slice(0, 4) ?? []
  const evidenceItems = workspace?.evidence_grid ?? []
  const actions = workspace?.recommended_actions ?? workspace?.rationale ?? []

  const activeRiskTier = useMemo<RiskTier>(() => {
    const tier = workspace?.risk_tier
    return tier === "urgent" || tier === "alert" || tier === "watch" || tier === "ok"
      ? tier
      : "watch"
  }, [workspace?.risk_tier])

  async function handleReview(action: string) {
    if (!workspace?.id) {
      return
    }

    const payload = await postApi<WorkflowWorkspace>(`${apiPrefix}/review`, {
      case_id: workspace.id,
      action,
      comment,
    })
    setSelectedWorkspace(payload)
  }

  async function handleRerun() {
    if (!workspace?.id) {
      return
    }

    const payload = await postApi<WorkflowWorkspace>(`${apiPrefix}/rerun`, { case_id: workspace.id })
    setSelectedWorkspace(payload)
    refetch()
  }

  if (loading && !data) {
    return <div className="text-[13px] text-[hsl(var(--muted-foreground))]">Loading {title.toLowerCase()}…</div>
  }

  if (error) {
    return <div className="text-[13px] text-[hsl(var(--destructive))]">{error}</div>
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[22rem_1fr]">
      <aside className="space-y-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
        <div className="space-y-1">
          <p className="text-[12px] text-[hsl(var(--muted-foreground))]">Cases</p>
          <h1 className="text-[16px] font-medium">{title}</h1>
        </div>
        <div className="space-y-2">
          {cases.map((item) => (
            <CaseCard
              active={item.id === selectedCaseId}
              focusMetric={item.queue}
              id={item.id}
              key={item.id}
              onClick={() => setSelectedCaseId(item.id)}
              patientLabel={item.patient_label ?? item.owner ?? item.workflow_title ?? "Case"}
              riskTier={(item.risk_tier as RiskTier) ?? "watch"}
              serviceLine={item.service_line ?? item.risk_label}
              status={item.owner}
              title={item.title}
            />
          ))}
        </div>
      </aside>

      <WorkspacePanel
        actions={
          <Button onClick={handleRerun} variant="outline">
            Rerun
          </Button>
        }
        riskTier={activeRiskTier}
        subtitle={workspace?.risk_reason ?? workspace?.queue ?? undefined}
        title={workspace?.title ?? title}
      >
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {metrics.map((metric) => (
              <SummaryMetric key={`${metric.label}-${metric.value}`} label={metric.label} value={metric.value} />
            ))}
          </div>

          <div className="flex gap-2">
            {(["evidence", "actions", "review"] as TabKey[]).map((item) => (
              <Button
                key={item}
                onClick={() => setTab(item)}
                variant={tab === item ? "default" : "outline"}
              >
                {item}
              </Button>
            ))}
          </div>

          {tab === "evidence" ? (
            <EvidenceGrid items={evidenceItems} />
          ) : null}

          {tab === "actions" ? (
            <div className="space-y-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
              {actions.length ? (
                actions.map((action) => (
                  <p key={action} className="text-[13px] leading-6 text-[hsl(var(--foreground))]">
                    {action}
                  </p>
                ))
              ) : (
                <p className="text-[13px] text-[hsl(var(--muted-foreground))]">No recommended actions yet.</p>
              )}
            </div>
          ) : null}

          {tab === "review" ? (
            <div className="space-y-4">
              <textarea
                className="min-h-28 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] p-3 text-[13px] outline-none"
                onChange={(event) => setComment(event.target.value)}
                placeholder="Add review comment"
                value={comment}
              />
              <ReviewActions
                comment={workspace?.review?.comment}
                onAcknowledge={() => void handleReview("acknowledge")}
                onApprove={() => void handleReview("approve")}
                onReject={() => void handleReview("reject")}
                status={workspace?.review?.status ?? workspace?.status}
              />
            </div>
          ) : null}
        </div>
      </WorkspacePanel>
    </div>
  )
}
