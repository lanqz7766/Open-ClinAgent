import { RiskBadge, type RiskTier } from "@/components/RiskBadge"
import { cn } from "@/lib/utils"

const accentClasses: Record<RiskTier, string> = {
  urgent: "border-l-[hsl(var(--status-alert))]",
  alert: "border-l-[hsl(var(--status-watch))]",
  watch: "border-l-[hsl(var(--border))]",
  ok: "border-l-[hsl(var(--status-ok))]",
}

type CaseCardProps = {
  id: string
  title: string
  status?: string
  riskTier: RiskTier
  patientLabel: string
  serviceLine?: string
  focusMetric?: string
  onClick?: () => void
  active?: boolean
}

export function CaseCard({
  active,
  focusMetric,
  onClick,
  patientLabel,
  riskTier,
  serviceLine,
  status,
  title,
}: CaseCardProps) {
  return (
    <button
      className={cn(
        "flex min-h-16 w-full items-center justify-between gap-3 rounded-md border border-[hsl(var(--border))] border-l-2 bg-[hsl(var(--card))] px-3 py-2 text-left",
        accentClasses[riskTier],
        active ? "bg-[hsl(var(--accent))]" : "hover:bg-[hsl(var(--accent))]",
      )}
      onClick={onClick}
      type="button"
    >
      <div className="min-w-0 space-y-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-[13px] font-medium text-[hsl(var(--foreground))]">{title}</p>
          <RiskBadge tier={riskTier} />
        </div>
        <p className="truncate text-[12px] text-[hsl(var(--muted-foreground))]">{patientLabel}</p>
        {serviceLine || status ? (
          <p className="truncate text-[12px] text-[hsl(var(--muted-foreground))]">
            {[serviceLine, status].filter(Boolean).join(" • ")}
          </p>
        ) : null}
      </div>
      {focusMetric ? (
        <div className="shrink-0 text-right text-[12px] font-medium text-[hsl(var(--foreground))]">
          {focusMetric}
        </div>
      ) : null}
    </button>
  )
}
