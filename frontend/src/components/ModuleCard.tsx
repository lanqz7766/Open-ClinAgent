import type { LucideIcon } from "lucide-react"
import { Link } from "react-router-dom"

import { RiskBadge, type RiskTier } from "@/components/RiskBadge"

type ModuleCardProps = {
  icon: LucideIcon
  title: string
  description: string
  caseCount?: number
  riskLevel?: RiskTier
  href: string
}

export function ModuleCard({
  caseCount,
  description,
  href,
  icon: Icon,
  riskLevel,
  title,
}: ModuleCardProps) {
  return (
    <Link
      className="rounded-xl border border-[hsl(var(--border)/0.72)] bg-[hsl(var(--card))] p-4 shadow-[0_14px_36px_-30px_rgba(15,23,42,0.22)] transition-[background-color,box-shadow,border-color] hover:border-[hsl(var(--border)/0.92)] hover:bg-[hsl(var(--accent))] hover:shadow-[0_22px_56px_-34px_rgba(15,23,42,0.3)] focus-visible:shadow-[0_22px_56px_-34px_rgba(15,23,42,0.3)]"
      to={href}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex size-9 items-center justify-center rounded-lg border border-[hsl(var(--border)/0.72)] bg-[hsl(var(--background))] shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
          <Icon className="size-4 text-[hsl(var(--foreground))]" />
        </div>
        <div className="flex items-center gap-2">
          {typeof caseCount === "number" ? (
            <span className="rounded-full bg-[hsl(var(--muted))] px-2 py-1 text-[11px] text-[hsl(var(--muted-foreground))]">
              {caseCount} cases
            </span>
          ) : null}
          {riskLevel ? <RiskBadge tier={riskLevel} /> : null}
        </div>
      </div>
      <div className="mt-4 space-y-1">
        <h3 className="text-[14px] font-medium">{title}</h3>
        <p className="text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">{description}</p>
      </div>
    </Link>
  )
}
