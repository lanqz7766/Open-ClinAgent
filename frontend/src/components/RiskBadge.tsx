import { cn } from "@/lib/utils"

export type RiskTier = "urgent" | "alert" | "watch" | "ok"

const riskClasses: Record<RiskTier, string> = {
  urgent: "bg-[hsl(var(--status-alert)/0.12)] text-[hsl(var(--foreground))]",
  alert: "bg-[hsl(var(--status-watch)/0.16)] text-[hsl(var(--foreground))]",
  watch: "bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]",
  ok: "bg-[hsl(var(--status-ok)/0.12)] text-[hsl(var(--foreground))]",
}

const riskLabels: Record<RiskTier, string> = {
  urgent: "Priority",
  alert: "Review",
  watch: "Monitor",
  ok: "Ready",
}

export function RiskBadge({ tier }: { tier: RiskTier }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-1 text-[11px] font-medium capitalize",
        riskClasses[tier],
      )}
    >
      {riskLabels[tier]}
    </span>
  )
}
