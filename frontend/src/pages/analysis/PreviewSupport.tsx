import { useEffect, useState } from "react"
import * as Dialog from "@radix-ui/react-dialog"
import { CheckCircle2, Download, Loader2, MessageSquare, RefreshCw, X } from "lucide-react"
import { Button } from "@/components/ui/button"

type Example = { id: string; label: string; visit_count: number; size_bytes: number; download_url: string }

export function UploadExamples() {
  const [examples, setExamples] = useState<Example[]>([])
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(true)
  async function load() {
    setLoading(true)
    setError(false)
    try {
      const response = await fetch("/api/demo/brain-tumor/upload-examples", { credentials: "include" })
      if (!response.ok) throw new Error()
      const payload = await response.json()
      setExamples(payload.examples)
    } catch { setError(true) } finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])
  if (loading) return <div role="status" className="mb-4 text-[13px] text-[hsl(var(--muted-foreground))]">Loading upload examples…</div>
  if (error) return <div role="alert" className="mb-4 flex flex-wrap items-center gap-2 text-[13px]">Examples unavailable<Button onClick={() => void load()} size="sm" variant="outline"><RefreshCw />Retry</Button></div>
  if (!examples.length) return null
  return (
    <section aria-label="Download example MRI" className="mb-5 border-b border-[hsl(var(--border))] pb-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[13px]">
        <h3 className="font-semibold">Example MRI</h3>
        <span className="text-[hsl(var(--muted-foreground))]">Four modalities per visit · ZIP</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {examples.map((example) => <a key={example.id} download href={example.download_url} className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-[13px] hover:border-[hsl(var(--primary)/0.6)] hover:bg-[hsl(var(--primary)/0.06)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]">
          <Download aria-hidden="true" className="size-4 text-[hsl(var(--primary))]" />
          <span className="font-medium">{example.label}</span>
          <span className="text-[12px]">{example.visit_count} {example.visit_count === 1 ? "visit" : "visits"}</span>
          <span className="text-[12px] tabular-nums text-[hsl(var(--muted-foreground))]">{(example.size_bytes / 1024 / 1024).toFixed(1)} MB</span>
        </a>)}
      </div>
    </section>
  )
}

export function PreviewFeedback({ caseId, step }: { caseId?: string; step: string }) {
  const [open, setOpen] = useState(false)
  const [context, setContext] = useState({ case_id: caseId || null, workflow_step: step })
  const [category, setCategory] = useState("issue")
  const [comment, setComment] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [saved, setSaved] = useState(false)
  async function submit() {
    setBusy(true)
    setError("")
    try {
      const response = await fetch("/api/demo/brain-tumor/feedback", { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...context, category, comment }) })
      if (!response.ok) throw new Error(response.status === 401 ? "Sign in again before sending feedback." : "Feedback was not saved. Please retry.")
      setSaved(true)
      setComment("")
    } catch (err) { setError(err instanceof Error ? err.message : "Feedback was not saved.") } finally { setBusy(false) }
  }
  return <Dialog.Root open={open} onOpenChange={(next) => {
    if (busy) return
    setOpen(next)
    if (next) { setContext({ case_id: caseId || null, workflow_step: step }); setSaved(false); setError("") }
  }}>
    <Dialog.Trigger asChild><Button className="min-h-[44px] text-[13px]" variant="ghost"><MessageSquare />Feedback</Button></Dialog.Trigger>
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-50 bg-black/48 backdrop-blur-sm" />
      <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[calc(100dvh-32px)] w-[calc(100%-32px)] max-w-[480px] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 shadow-xl" onInteractOutside={(event) => event.preventDefault()} onEscapeKeyDown={(event) => { if (busy) event.preventDefault() }}>
        <div className="flex items-start justify-between gap-3">
          <div><Dialog.Title className="text-[18px] font-semibold">Preview feedback</Dialog.Title><Dialog.Description className="mt-1 text-[13px] text-[hsl(var(--muted-foreground))]">No patient names, identifiers or screenshots.</Dialog.Description></div>
          <Dialog.Close asChild><Button aria-label="Close feedback" title="Close feedback" disabled={busy} className="size-[44px] shrink-0" size="icon" variant="outline"><X /></Button></Dialog.Close>
        </div>
        {saved ? <div role="status" className="flex items-center gap-2 py-6 text-[14px]"><CheckCircle2 className="size-5 text-[hsl(var(--status-ok))]" />Feedback saved</div> : <form className="mt-5 space-y-4" onSubmit={(event) => { event.preventDefault(); void submit() }}>
          <label className="block space-y-1 text-[13px]"><span className="font-medium">Category</span><select disabled={busy} value={category} onChange={(event) => setCategory(event.target.value)} className="h-[44px] w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3"><option value="issue">Something did not work</option><option value="suggestion">Suggestion</option><option value="question">Question</option></select></label>
          <label className="block space-y-1 text-[13px]"><span className="font-medium">Comment</span><textarea required maxLength={2000} disabled={busy} value={comment} onChange={(event) => setComment(event.target.value)} rows={5} className="w-full resize-y rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] p-3 leading-5" /></label>
          {error ? <p role="alert" className="text-[13px] text-[hsl(var(--destructive))]">{error}</p> : null}
          <div className="flex justify-end"><Button className="min-h-[44px]" disabled={busy || !comment.trim()} type="submit">{busy ? <Loader2 className="animate-spin" /> : <MessageSquare />}Send feedback</Button></div>
        </form>}
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
}
