import { Check, CircleX } from "lucide-react"
import { useEffect, useState } from "react"

import { cn } from "@/lib/utils"

export type ToolCallStatus = "pending" | "running" | "done" | "error"

export type ToolCallItem = {
  id: string
  name: string
  status: ToolCallStatus
  preview?: string
  durationMs?: number
  error?: string
  startedAt?: number
}

function formatDuration(durationMs?: number) {
  if (!durationMs || durationMs < 0) {
    return null
  }
  if (durationMs < 1000) {
    return `${durationMs}ms`
  }
  return `${(durationMs / 1000).toFixed(1)}s`
}

export function ToolCallCard({ durationMs, error, name, preview, status }: ToolCallItem) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const frame = requestAnimationFrame(() => setVisible(true))
    return () => cancelAnimationFrame(frame)
  }, [])

  const durationLabel = formatDuration(durationMs)
  const line = status === "error" ? error ?? preview : preview

  return (
    <div
      className={cn(
        "flex min-h-12 items-center gap-3 border-b border-[hsl(var(--border))] px-3 py-2 transition-all duration-150",
        visible ? "translate-y-0 opacity-100" : "translate-y-1 opacity-0",
      )}
    >
      <div className="flex size-6 shrink-0 items-center justify-center">
        {status === "running" ? (
          <span className="size-2.5 rounded-full bg-[hsl(var(--primary))] animate-pulse" />
        ) : null}
        {status === "done" ? (
          <Check className="size-4 text-[hsl(var(--status-ok))]" />
        ) : null}
        {status === "error" ? (
          <CircleX className="size-4 text-[hsl(var(--destructive))]" />
        ) : null}
        {status === "pending" ? (
          <span className="size-2 rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--muted))]" />
        ) : null}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <p className="truncate font-mono text-[13px] text-[hsl(var(--foreground))]">{name}</p>
          <p className="shrink-0 text-[11px] text-[hsl(var(--muted-foreground))]">
            {status === "running" ? "Running..." : durationLabel ?? status}
          </p>
        </div>
        {line ? (
          <p className="truncate text-[12px] text-[hsl(var(--muted-foreground))]">{line}</p>
        ) : null}
      </div>
    </div>
  )
}
