import { SummaryMetric } from "@/components/SummaryMetric"
import { WorkspacePanel } from "@/components/WorkspacePanel"
import { useApi } from "@/hooks/useApi"
import type { HealthSnapshot, WorkflowSnapshot } from "@/types/api"

export function DashboardPage() {
  const findings = useApi<WorkflowSnapshot>("/api/findings/workspace")
  const queue = useApi<WorkflowSnapshot>("/api/queue/workspace")
  const diagnosis = useApi<WorkflowSnapshot>("/api/diagnosis/workspace")
  const screening = useApi<WorkflowSnapshot>("/api/screening/workspace")
  const safety = useApi<WorkflowSnapshot>("/api/safety/workspace")
  const health = useApi<HealthSnapshot>("/health")

  const snapshots = [findings.data, queue.data, diagnosis.data, screening.data, safety.data].filter(Boolean)
  const totalCases = snapshots.reduce((sum, snapshot) => sum + (snapshot?.cases.length ?? 0), 0)
  const priorityCount = snapshots.reduce(
    (sum, snapshot) =>
      sum + snapshot!.cases.filter((item) => item.risk_tier === "urgent").length,
    0,
  )
  const reviewedToday = snapshots.reduce(
    (sum, snapshot) =>
      sum + snapshot!.cases.filter((item) => item.status_label?.toLowerCase().includes("review")).length,
    0,
  )

  return (
    <div className="space-y-6">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <SummaryMetric label="Total open cases" value={String(totalCases)} />
        <SummaryMetric label="Priority count" tone="warning" value={String(priorityCount)} />
        <SummaryMetric label="Cases reviewed today" tone="positive" value={String(reviewedToday)} />
        <SummaryMetric
          label="System uptime"
          tone={health.data?.status === "ok" ? "positive" : "danger"}
          value={health.data?.status === "ok" ? "Healthy" : "Degraded"}
        />
      </div>

      <WorkspacePanel subtitle="Placeholder feed until backend activity aggregation lands." title="Recent activity">
        <div className="space-y-2 text-[13px] text-[hsl(var(--muted-foreground))]">
          <p>Workflow cases aggregated across findings, queue, diagnosis, screening, and safety.</p>
          <p>Latest provider: {health.data?.provider ?? "…"}</p>
          <p>Current model: {health.data?.model ?? "…"}</p>
        </div>
      </WorkspacePanel>

      <WorkspacePanel subtitle="Live status from GET /health." title="System health">
        <div className="grid gap-3 md:grid-cols-3">
          <SummaryMetric label="Provider" value={health.data?.provider ?? "—"} />
          <SummaryMetric label="Model" value={health.data?.model ?? "—"} />
          <SummaryMetric label="Scenario count" value={String(health.data?.clinagent.scenario_count ?? 0)} />
        </div>
      </WorkspacePanel>
    </div>
  )
}
