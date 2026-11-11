type PageShellProps = {
  title: string
  description: string
}

export function PageShell({ description, title }: PageShellProps) {
  return (
    <section className="flex min-h-[calc(100vh-5rem)] flex-col gap-4 rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-8 shadow-[0_1px_0_rgba(255,255,255,0.03),0_16px_48px_rgba(0,0,0,0.16)]">
      <div className="space-y-2">
        <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">
          Route Shell
        </p>
        <h1 className="text-[22px] font-medium tracking-[-0.04em] text-[hsl(var(--foreground))]">
          {title}
        </h1>
        <p className="max-w-2xl text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
          {description}
        </p>
      </div>
      <div className="flex flex-1 items-center justify-center rounded-xl border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[13px] text-[hsl(var(--muted-foreground))]">
        Page content intentionally left empty for Phase 2.
      </div>
    </section>
  )
}
