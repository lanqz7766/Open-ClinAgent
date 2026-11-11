import { cn } from "@/lib/utils"

type SummaryMetricProps = {
  label: string
  value: string
  delta?: string
  tone?: "default" | "positive" | "warning" | "danger"
}

const deltaClasses = {
  default: "text-[hsl(var(--muted-foreground))]",
  positive: "text-[hsl(var(--status-ok))]",
  warning: "text-[hsl(var(--status-alert))]",
  danger: "text-[hsl(var(--destructive))]",
}

export function SummaryMetric({
  delta,
  label,
  tone = "default",
  value,
}: SummaryMetricProps) {
  return (
    <article className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
      <p className="text-[12px] text-[hsl(var(--muted-foreground))]">{label}</p>
      <p className="mt-2 text-[20px] font-medium tracking-[-0.03em] text-[hsl(var(--foreground))]">
        {value}
      </p>
      {delta ? <p className={cn("mt-2 text-[12px]", deltaClasses[tone])}>{delta}</p> : null}
    </article>
  )
}
