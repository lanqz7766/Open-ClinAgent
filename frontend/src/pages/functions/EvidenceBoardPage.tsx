import { useState } from "react"

import { Button } from "@/components/ui/button"
import { WorkspacePanel } from "@/components/WorkspacePanel"
import { postApi } from "@/hooks/useApi"

export function EvidenceBoardPage() {
  const [draftReport, setDraftReport] = useState("")
  const [result, setResult] = useState<{
    claims?: { statement?: string; status?: string; verdict?: string }[]
  } | null>(null)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const payload = await postApi<{
      claims?: { statement?: string; status?: string; verdict?: string }[]
    }>("/api/demo/evidence-board/verify", {
      current_study: { accession: "demo-study", findings: "Demo findings payload" },
      prior_study: { accession: "prior-study", findings: "Prior comparison payload" },
      draft_report: draftReport,
      prior_report: "Prior report text",
    })
    setResult(payload)
  }

  return (
    <WorkspacePanel
      subtitle="Submit a draft report to the evidence board verifier."
      title="Evidence board"
    >
      <div className="space-y-4">
        <form className="space-y-3" onSubmit={handleSubmit}>
          <textarea
            className="min-h-40 w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] p-3 text-[13px] outline-none"
            onChange={(event) => setDraftReport(event.target.value)}
            placeholder="Paste draft report text to verify claims."
            value={draftReport}
          />
          <Button type="submit">Verify evidence</Button>
        </form>

        <div className="space-y-2">
          {(result?.claims ?? []).map((claim, index) => (
            <div
              className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3"
              key={`${claim.statement}-${index}`}
            >
              <p className="text-[13px] font-medium">{claim.statement ?? "Claim"}</p>
              <p className="mt-1 text-[12px] text-[hsl(var(--muted-foreground))]">
                {claim.status ?? claim.verdict ?? "pending"}
              </p>
            </div>
          ))}
        </div>
      </div>
    </WorkspacePanel>
  )
}
