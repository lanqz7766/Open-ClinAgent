import { ArrowUpRight } from "lucide-react"

import { cn } from "@/lib/utils"

export interface RunResultCardProps {
  title: string
  subtitle: string
  riskLevel: "low" | "moderate" | "high" | "critical"
  metrics: { label: string; value: string }[]
  reportPreview: string
  trendSvg?: string
  planSummary?: string
  missingInputs?: string[]
  allowedAnalyses?: string[]
  capabilityStatus?: string[]
  intent?: string
  recommendedNextAction?: string
  executionReadiness?: "ready" | "intake_only" | string
  viewerType?: string
  policyMode?: string
  allowedTools?: string[]
  blockedTools?: string[]
  availableData?: string[]
  qaStatus: {
    privacy: boolean
    terminology: boolean
    completeness: boolean
  }
  claimsSummary: string
  workspaceUrl: string
  onOpenWorkspace: () => void
}

const riskClasses: Record<RunResultCardProps["riskLevel"], string> = {
  low: "border-l-[hsl(var(--status-ok))]",
  moderate: "border-l-[hsl(var(--status-watch))]",
  high: "border-l-[hsl(var(--primary))]",
  critical: "border-l-[hsl(var(--destructive))]",
}

const riskLabel: Record<RunResultCardProps["riskLevel"], string> = {
  low: "Low",
  moderate: "Alert",
  high: "High attention",
  critical: "Urgent",
}

function QaBadge({
  label,
  ok,
}: {
  label: string
  ok: boolean
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center rounded-full px-2 py-1 text-[11px] font-medium [overflow-wrap:anywhere]",
        ok
          ? "bg-[hsl(var(--status-ok)/0.12)] text-[hsl(var(--status-ok))]"
          : "bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--destructive))]",
      )}
    >
      {ok ? "✓" : "✗"} {label}
    </span>
  )
}

export function RunResultCard({
  claimsSummary,
  metrics,
  onOpenWorkspace,
  planSummary,
  qaStatus,
  reportPreview,
  intent,
  recommendedNextAction,
  executionReadiness,
  viewerType,
  policyMode,
  allowedTools,
  blockedTools,
  availableData,
  riskLevel,
  subtitle,
  title,
  trendSvg,
  missingInputs,
  allowedAnalyses,
  capabilityStatus,
  workspaceUrl,
}: RunResultCardProps) {
  const previewMetrics = metrics.length
    ? metrics
    : [{ label: "Claims", value: claimsSummary }]

  return (
    <article
      className={cn(
        "rounded-md border border-[hsl(var(--border))] border-l-4 bg-[hsl(var(--card))] p-4 shadow-sm",
        riskClasses[riskLevel],
      )}
    >
      <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-4 py-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <h3 className="text-[15px] font-medium tracking-[-0.02em] text-[hsl(var(--foreground))] [overflow-wrap:anywhere]">
              {title}
            </h3>
            <p className="text-[12px] text-[hsl(var(--muted-foreground))] [overflow-wrap:anywhere]">{subtitle}</p>
          </div>
          <span className="max-w-full shrink-0 rounded-full bg-[hsl(var(--muted))] px-2.5 py-1 text-[11px] font-medium text-[hsl(var(--foreground))] [overflow-wrap:anywhere]">
            {riskLabel[riskLevel]}
          </span>
        </div>
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-4">
        {previewMetrics.map((metric) => (
          <div
            className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2"
            key={`${metric.label}-${metric.value}`}
          >
            <p className="text-[11px] uppercase tracking-[0.12em] text-[hsl(var(--muted-foreground))]">
              {metric.label}
            </p>
            <p className="mt-1 text-[13px] font-medium text-[hsl(var(--foreground))] [overflow-wrap:anywhere]">
              {metric.value}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-4 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-4 py-3">
        <p className="mb-2 text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">
          Report preview
        </p>
        <p
          className="text-[13px] leading-6 italic text-[hsl(var(--muted-foreground))]"
          style={{
            display: "-webkit-box",
            WebkitBoxOrient: "vertical",
            WebkitLineClamp: 3,
            overflow: "hidden",
          }}
        >
          {reportPreview}
        </p>
      </div>

      {planSummary ? (
        <div className="mt-4 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-4 py-3">
          <p className="mb-2 text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">
            Analysis plan
          </p>
          {intent ? (
            <p className="mb-2 text-[12px] font-medium text-[hsl(var(--foreground))]">{intent}</p>
          ) : null}
          <p className="text-[13px] leading-6 text-[hsl(var(--foreground))] [overflow-wrap:anywhere]">{planSummary}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {executionReadiness ? (
              <span
                className={cn(
                  "max-w-full rounded-full border px-2.5 py-1 text-[11px] [overflow-wrap:anywhere]",
                  executionReadiness === "ready"
                    ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                    : "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300",
                )}
              >
                {executionReadiness === "ready" ? "Ready to execute" : "Intake only"}
              </span>
            ) : null}
            {viewerType ? (
              <span className="max-w-full rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] text-[hsl(var(--foreground))] [overflow-wrap:anywhere]">
                Viewer {viewerType}
              </span>
            ) : null}
            {policyMode ? (
              <span className="max-w-full rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] text-[hsl(var(--foreground))] [overflow-wrap:anywhere]">
                Mode {policyMode.replaceAll("_", " ")}
              </span>
            ) : null}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {(capabilityStatus ?? []).slice(0, 4).map((value) => (
              <span
                className="max-w-full rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-2.5 py-1 text-[11px] text-[hsl(var(--foreground))] [overflow-wrap:anywhere]"
                key={`capability-${value}`}
              >
                {value.replaceAll("_", " ")}
              </span>
            ))}
            {(allowedAnalyses ?? []).slice(0, 3).map((value) => (
              <span
                className="max-w-full rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-1 text-[11px] text-emerald-600 dark:text-emerald-400 [overflow-wrap:anywhere]"
                key={`allowed-${value}`}
              >
                {value.replaceAll("_", " ")}
              </span>
            ))}
            {(missingInputs ?? []).slice(0, 3).map((value) => (
              <span
                className="max-w-full rounded-full border border-amber-500/25 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-700 dark:text-amber-300 [overflow-wrap:anywhere]"
                key={`missing-${value}`}
              >
                Missing {value.replaceAll("_", " ")}
              </span>
            ))}
            {(availableData ?? []).slice(0, 3).map((value) => (
              <span
                className="max-w-full rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-2.5 py-1 text-[11px] text-[hsl(var(--foreground))] [overflow-wrap:anywhere]"
                key={`available-${value}`}
              >
                {value.replaceAll("_", " ")}
              </span>
            ))}
            {(allowedTools ?? []).slice(0, 3).map((value) => (
              <span
                className="max-w-full rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-1 text-[11px] text-emerald-600 dark:text-emerald-400 [overflow-wrap:anywhere]"
                key={`tool-${value}`}
              >
                Tool {value.replaceAll("_", " ")}
              </span>
            ))}
            {(blockedTools ?? []).slice(0, 2).map((value) => (
              <span
                className="max-w-full rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-2.5 py-1 text-[11px] text-[hsl(var(--muted-foreground))] [overflow-wrap:anywhere]"
                key={`blocked-tool-${value}`}
              >
                Blocked {value.replaceAll("_", " ")}
              </span>
            ))}
          </div>
          {recommendedNextAction ? (
            <p className="mt-3 text-[12px] leading-6 text-[hsl(var(--muted-foreground))] [overflow-wrap:anywhere]">
              Next: {recommendedNextAction}
            </p>
          ) : null}
        </div>
      ) : null}

      {trendSvg ? (
        <div className="mt-4 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-3">
          <p className="mb-2 text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">
            Visual preview
          </p>
          <div
            className="[&>svg]:h-auto [&>svg]:max-h-[120px] [&>svg]:w-full"
            dangerouslySetInnerHTML={{ __html: trendSvg }}
          />
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-[11px] uppercase tracking-[0.12em] text-[hsl(var(--muted-foreground))]">
          QA
        </span>
        <QaBadge label="Privacy" ok={qaStatus.privacy} />
        <QaBadge label="Terminology" ok={qaStatus.terminology} />
        <QaBadge label="Completeness" ok={qaStatus.completeness} />
      </div>

      <button
        className="mt-4 inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-[hsl(var(--primary))] text-[13px] font-medium text-[hsl(var(--primary-foreground))] transition-opacity hover:opacity-90"
        onClick={() => {
          window.location.assign(workspaceUrl)
          onOpenWorkspace()
        }}
        type="button"
      >
        Open review workspace
        <ArrowUpRight className="size-4" />
      </button>
    </article>
  )
}
