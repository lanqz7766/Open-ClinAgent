import { AlertCircle, CheckCircle2, Database, FolderSearch, Upload } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { IngestController } from "@/lib/ingestTypes"

function SummaryPill({
  label,
  tone = "default",
}: {
  label: string
  tone?: "default" | "warning"
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center rounded-full border px-2.5 py-1 text-[11px] font-medium [overflow-wrap:anywhere]",
        tone === "warning"
          ? "border-amber-300/60 bg-amber-100/60 text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
          : "border-[hsl(var(--border))] bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))]",
      )}
    >
      {label}
    </span>
  )
}

export function IngestProfileCard({
  ingest,
}: {
  ingest: IngestController
}) {
  const profile = ingest.profile
  if (!profile) {
    return null
  }

  const totalTimepoints = profile.patients.reduce((sum, patient) => sum + patient.timepoints, 0)

  return (
    <div className="rounded-[1.1rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 shadow-[0_1px_0_hsl(var(--border)/0.35)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-[12px] font-medium text-[hsl(var(--muted-foreground))]">
            <Database className="size-4" />
            <span>Data profile</span>
          </div>
          <p className="text-[15px] font-medium text-[hsl(var(--foreground))] [overflow-wrap:anywhere]">{profile.detected_type}</p>
          <p className="text-[12px] leading-6 text-[hsl(var(--muted-foreground))] [overflow-wrap:anywhere]">{profile.source_path}</p>
        </div>

        <div className="flex flex-wrap gap-2">
          <SummaryPill label={`${profile.patients.length} patient${profile.patients.length === 1 ? "" : "s"}`} />
          <SummaryPill label={`${totalTimepoints} timepoints`} />
          {profile.missing_fields.length ? <SummaryPill label={`${profile.missing_fields.length} missing fields`} tone="warning" /> : null}
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="space-y-3">
          <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
            <div className="mb-2 flex items-center gap-2 text-[12px] font-medium text-[hsl(var(--muted-foreground))]">
              <FolderSearch className="size-4" />
              <span>Patients</span>
            </div>
            <div className="space-y-2">
              {profile.patients.map((patient) => {
                const active = patient.patient_uid === ingest.selectedPatientUid
                return (
                  <button
                    className={cn(
                      "w-full rounded-lg border px-3 py-2.5 text-left transition-colors",
                      active
                        ? "border-[hsl(var(--primary)/0.4)] bg-[hsl(var(--primary)/0.08)]"
                        : "border-[hsl(var(--border))] bg-[hsl(var(--card))] hover:border-[hsl(var(--primary)/0.2)] hover:bg-[hsl(var(--accent))]",
                    )}
                    key={patient.patient_uid}
                    onClick={() => ingest.setSelectedPatientUid(patient.patient_uid)}
                    type="button"
                  >
                    <div className="flex min-w-0 items-center justify-between gap-3">
                      <span className="min-w-0 flex-1 text-[13px] font-medium text-[hsl(var(--foreground))] [overflow-wrap:anywhere]">Patient {patient.patient_uid}</span>
                      <span className="shrink-0 text-[11px] text-[hsl(var(--muted-foreground))]">{patient.timepoints} timepoints</span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
                      {patient.has_imaging ? <span>imaging</span> : null}
                      {patient.has_reports ? <span>reports</span> : null}
                      {patient.has_segmentation ? <span>segmentation</span> : null}
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
            <p className="text-[12px] font-medium text-[hsl(var(--muted-foreground))]">Suggested workflows</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {profile.suggested_workflows.map((workflow) => (
                <Button
                  className="h-auto min-h-8 max-w-full rounded-full px-3 py-1.5 text-center text-[12px] whitespace-normal [overflow-wrap:anywhere]"
                  disabled={ingest.status === "confirming"}
                  key={workflow}
                  onClick={() => void ingest.confirmWorkflow(workflow)}
                  type="button"
                  variant={workflow === profile.suggested_workflows[0] ? "default" : "outline"}
                >
                  {workflow}
                </Button>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-3">
          <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
            <p className="text-[12px] font-medium text-[hsl(var(--muted-foreground))]">Inventory</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {Object.entries(profile.raw_inventory).map(([key, value]) => (
                <SummaryPill key={key} label={`${key}: ${value}`} />
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
            <div className="flex items-center gap-2 text-[12px] font-medium text-[hsl(var(--muted-foreground))]">
              {profile.missing_fields.length ? <AlertCircle className="size-4" /> : <CheckCircle2 className="size-4" />}
              <span>{profile.missing_fields.length ? "Missing fields" : "Ready to confirm"}</span>
            </div>
            {profile.missing_fields.length ? (
              <ul className="mt-3 space-y-1 text-[12px] leading-6 text-[hsl(var(--muted-foreground))] [overflow-wrap:anywhere]">
                {profile.missing_fields.map((field) => (
                  <li key={field}>- {field}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-[12px] leading-6 text-[hsl(var(--muted-foreground))] [overflow-wrap:anywhere]">
                Pick a patient and confirm one of the suggested workflows to assemble a real workspace.
              </p>
            )}
          </div>

          {ingest.workspaceId ? (
            <div className="rounded-xl border border-[hsl(var(--primary)/0.25)] bg-[hsl(var(--primary)/0.06)] p-3">
              <div className="flex items-center gap-2 text-[12px] font-medium text-[hsl(var(--primary))]">
                <Upload className="size-4" />
                <span>{ingest.status === "ready" ? "Workspace ready" : "Assembling workspace"}</span>
              </div>
              <p className="mt-2 text-[12px] leading-6 text-[hsl(var(--muted-foreground))] [overflow-wrap:anywhere]">{ingest.workspaceId}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <a
                  className="inline-flex h-auto min-h-8 max-w-full items-center justify-center rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-center text-[12px] font-medium whitespace-normal text-[hsl(var(--primary-foreground))] transition-opacity hover:opacity-90 [overflow-wrap:anywhere]"
                  href={`/demo/analysis/neuro?workspaceId=${encodeURIComponent(ingest.workspaceId)}`}
                >
                  Open workspace
                </a>
                <Button className="h-auto min-h-8 max-w-full px-3 py-1.5 text-[12px] whitespace-normal" onClick={ingest.clear} type="button" variant="outline">
                  Clear
                </Button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
