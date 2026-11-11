type EvidenceItem = {
  label: string
  value: string
}

export function EvidenceGrid({ items }: { items: EvidenceItem[] }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-3">
      {items.map((item) => (
        <div key={`${item.label}-${item.value}`} className="space-y-1 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
          <p className="text-[12px] text-[hsl(var(--muted-foreground))]">{item.label}</p>
          <p className="text-[14px] text-[hsl(var(--foreground))]">{item.value}</p>
        </div>
      ))}
    </div>
  )
}
