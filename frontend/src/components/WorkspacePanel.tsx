import type { ReactNode } from "react"

import { RiskBadge, type RiskTier } from "@/components/RiskBadge"

type WorkspacePanelProps = {
  title: string
  subtitle?: string
  riskTier?: RiskTier
  actions?: ReactNode
  children: ReactNode
}

export function WorkspacePanel({
  actions,
  children,
  riskTier,
  subtitle,
  title,
}: WorkspacePanelProps) {
  return (
    <section className="overflow-hidden rounded-[1.5rem] border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--card))] shadow-[0_24px_60px_-38px_rgba(15,23,42,0.45)]">
      <div className="border-b border-[hsl(var(--border)/0.5)] px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">
              Workspace
            </p>
            <div className="flex items-center gap-2">
              <h2 className="text-[16px] font-medium tracking-[-0.03em]">{title}</h2>
              {riskTier ? <RiskBadge tier={riskTier} /> : null}
            </div>
            {subtitle ? (
              <p className="max-w-3xl text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">{subtitle}</p>
            ) : null}
          </div>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </div>
      </div>
      <div className="px-5 py-5">
        {children}
      </div>
    </section>
  )
}
