import { useMemo } from "react"
import { useOutletContext } from "react-router-dom"

import { ChatPanel } from "@/components/ChatPanel"
import { ExecutionProfilePanel } from "@/components/ExecutionProfilePanel"
import { RunTracePanel } from "@/components/RunTracePanel"
import { useApi } from "@/hooks/useApi"
import type { DevLayoutContext } from "@/lib/ingestTypes"
import type { DevConsoleSnapshot, HealthSnapshot } from "@/types/api"

export function DevConsolePage() {
  const { chat } = useOutletContext<DevLayoutContext>()
  const snapshot = useApi<DevConsoleSnapshot>("/api/dev/console")
  const health = useApi<HealthSnapshot>("/health")

  const activeProfile = useMemo(() => {
    const workflowId = chat.latestRoute?.profile?.workflow_id ?? chat.latestDone?.profile?.workflow_id
    if (!workflowId) {
      return snapshot.data?.profiles[0] ?? null
    }
    return snapshot.data?.profiles.find((profile) => profile.workflow_id === workflowId) ?? null
  }, [chat.latestDone?.profile?.workflow_id, chat.latestRoute?.profile?.workflow_id, snapshot.data?.profiles])

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <div className="max-w-3xl space-y-2">
          <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">
            Developer Surface
          </p>
          <h1 className="text-[24px] font-medium tracking-[-0.04em] text-[hsl(var(--foreground))]">
            Inspect routing, execution policy, and live runtime traces without exposing internals to `/demo`.
          </h1>
          <p className="text-[14px] leading-7 text-[hsl(var(--muted-foreground))]">
            This console is the Phase 1 inspection surface. Send a request on the left, then use the right panels to see the selected workflow, tool policy, subagent declarations, and the latest run trace.
          </p>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(22rem,0.9fr)]">
        <ChatPanel className="min-h-[44rem]" controller={chat} endpoint="/api/dev/execute-stream" />

        <div className="space-y-6">
          <ExecutionProfilePanel
            activeProfile={activeProfile}
            health={health.data ?? undefined}
            snapshot={snapshot.data ?? undefined}
          />
          <RunTracePanel
            latestDone={chat.latestDone}
            latestError={chat.latestError}
            recentTrace={snapshot.data?.recent_trace_summary ?? { status: "idle", tool_calls: [], errors: [] }}
            route={chat.latestRoute}
            toolCalls={chat.toolCalls}
          />
        </div>
      </section>
    </div>
  )
}
