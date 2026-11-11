import { useEffect, useMemo, useState } from "react"
import {
  Check,
  ChevronDown,
  ChevronUp,
  Database,
  FileText,
  GitMerge,
  Layers,
  LayoutDashboard,
  Scan,
  TrendingDown,
} from "lucide-react"

import { cn } from "@/lib/utils"
import { NEURO_STAGES, buildStageStates, type DemoStageState, type StageToolCall } from "@/lib/stageMapping"

const ICONS = {
  Database,
  Layers,
  Scan,
  TrendingDown,
  GitMerge,
  FileText,
  LayoutDashboard,
}

function formatDuration(durationMs?: number) {
  if (!durationMs || durationMs < 0) {
    return undefined
  }
  if (durationMs < 1000) {
    return `${durationMs}ms`
  }
  return `${(durationMs / 1000).toFixed(1)}s`
}

function totalDuration(stages: DemoStageState[]) {
  return stages.reduce((sum, stage) => sum + (stage.durationMs ?? 0), 0)
}

function StageIndicator({ status }: { status: DemoStageState["status"] }) {
  if (status === "done") {
    return <Check className="size-4 text-[hsl(var(--status-ok))]" />
  }

  if (status === "active") {
    return <span className="size-2.5 rounded-full bg-[hsl(var(--primary))] animate-pulse" />
  }

  if (status === "error") {
    return <span className="size-2.5 rounded-full bg-[hsl(var(--destructive))]" />
  }

  return <span className="size-2 rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--muted))]" />
}

function StageRow({ stage }: { stage: DemoStageState }) {
  const Icon = ICONS[stage.icon as keyof typeof ICONS] ?? LayoutDashboard
  const collapsed = stage.status === "done"
  const durationLabel = formatDuration(stage.durationMs)

  return (
    <div
      className={cn(
        "overflow-hidden rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 transition-all duration-150",
        collapsed ? "min-h-12" : "min-h-[4.5rem]",
        stage.status === "active" && "border-[hsl(var(--primary)/0.45)]",
        stage.status === "error" && "border-[hsl(var(--destructive)/0.4)]",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex h-5 w-5 shrink-0 items-center justify-center pt-0.5">
          <StageIndicator status={stage.status} />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Icon
              className={cn(
                "size-4 shrink-0 text-[hsl(var(--muted-foreground))]",
                stage.status === "active" && "text-[hsl(var(--primary))]",
                stage.status === "done" && "text-[hsl(var(--foreground))]",
              )}
            />
            <p
              className={cn(
                "min-w-0 flex-1 truncate text-[13px] font-medium",
                stage.status === "pending" && "text-[hsl(var(--muted-foreground))]",
              )}
            >
              {stage.label}
            </p>
            <p className="shrink-0 text-[11px] text-[hsl(var(--muted-foreground))]">
              {stage.status === "active" ? "..." : durationLabel ?? ""}
            </p>
          </div>

          {collapsed ? null : (
            <div className="space-y-2 pt-1">
              <p className="text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">
                {stage.description}
              </p>

              {stage.status === "active" ? (
                <div className="h-1 overflow-hidden rounded-full bg-[hsl(var(--muted))]">
                  <div className="agent-stage-progress h-full w-2/5 rounded-full bg-[hsl(var(--primary))]" />
                </div>
              ) : null}

              {stage.status === "done" && stage.summary ? (
                <p className="text-[11px] leading-5 text-[hsl(var(--muted-foreground))]">{stage.summary}</p>
              ) : null}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export function AgentStageFlow({
  calls,
  runComplete = false,
}: {
  calls: StageToolCall[]
  runComplete?: boolean
}) {
  const stages = useMemo(() => buildStageStates(calls, { stages: NEURO_STAGES, runComplete }), [calls, runComplete])
  const completedCount = stages.filter((stage) => stage.status === "done").length
  const allDone = stages.length > 0 && stages.every((stage) => stage.status === "done")
  const [expanded, setExpanded] = useState(true)

  useEffect(() => {
    if (allDone) {
      setExpanded(false)
    } else if (calls.length > 0) {
      setExpanded(true)
    }
  }, [allDone, calls.length])

  if (!calls.length) {
    return null
  }

  if (allDone && !expanded) {
    return (
      <section className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2">
        <div className="flex items-center justify-between gap-3">
          <p className="text-[12px] text-[hsl(var(--muted-foreground))]">
            {completedCount} steps completed in {formatDuration(totalDuration(stages)) ?? "0.0s"}
          </p>
          <button
            className="inline-flex items-center gap-1 text-[12px] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            onClick={() => setExpanded(true)}
            type="button"
          >
            Expand
            <ChevronDown className="size-3.5" />
          </button>
        </div>
      </section>
    )
  }

  return (
    <section className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">
            Agent progress
          </p>
          <p className="text-[12px] text-[hsl(var(--muted-foreground))]">
            Clinical review stages rendered from live tool activity.
          </p>
        </div>
        {allDone ? (
          <button
            className="inline-flex items-center gap-1 text-[12px] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            onClick={() => setExpanded(false)}
            type="button"
          >
            Collapse
            <ChevronUp className="size-3.5" />
          </button>
        ) : null}
      </div>

      <div className="space-y-2">
        {stages.map((stage) => (
          <StageRow key={stage.id} stage={stage} />
        ))}
      </div>
    </section>
  )
}
