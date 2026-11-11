import { useState } from "react"
import { Check, ChevronDown, Crosshair, FileCheck2, Layers, Loader2, Minus, Move3D, ScanLine, SlidersHorizontal, X } from "lucide-react"
import { cn } from "@/lib/utils"
import type { LongitudinalAlignJob, LongitudinalPoint, RegistrationQc } from "./brainTumor.types"

const icons = { inputs: ScanLine, intensity: SlidersHorizontal, within_visit: Layers, longitudinal: Move3D, outputs: FileCheck2 }

export function BrainTumorAlignment({ job, registration, points, referenceLabel, busy, error, activeSessionId }: {
  job: LongitudinalAlignJob | null
  registration?: RegistrationQc
  points: LongitudinalPoint[]
  referenceLabel: string
  busy: boolean
  error: string | null
  activeSessionId: string
}) {
  const [expanded, setExpanded] = useState(true)
  const visit = job?.visits.find((item) => item.status === "running")
    ?? job?.visits.find((item) => item.session_id === activeSessionId && item.status !== "reference")
    ?? job?.visits.find((item) => item.status === "failed")
    ?? job?.visits.filter((item) => item.status !== "reference").at(-1)
  const qc = visit ? visit.registration : registration
  const steps = visit?.steps ?? qc?.steps ?? []
  const label = points.find((point) => point.sessionId === visit?.session_id)?.dateLabel
  const failed = job?.status === "completed_with_errors" || job?.status === "failed" || Boolean(error)
  const runningStep = steps.find((step) => step.status === "running")
  const summary = busy ? runningStep?.label ?? "Preparing alignment" : failed ? "Alignment needs attention" : "Alignment complete"
  const count = job ? job.visits.filter((item) => item.status === "complete").length : registration ? 1 : 0
  const total = job ? job.visits.filter((item) => item.status !== "reference").length : 1
  return (
    <section aria-label="Alignment workflow" className="gbm-alignment">
      <button type="button" className="gbm-alignment-heading" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        <span className="gbm-alignment-title"><Crosshair size={18} /><strong>Alignment workflow</strong></span>
        <span className="gbm-alignment-status" role="status" aria-live="polite">
          {busy ? <Loader2 size={15} className="animate-spin motion-reduce:animate-none" /> : failed ? <X size={15} /> : <Check size={15} />}
          {summary}{job || registration ? <span className="tabular-nums">{count}/{total} follow-ups</span> : null}
        </span>
        <ChevronDown size={18} className={cn("shrink-0 transition-transform", expanded && "rotate-180")} />
      </button>
      {expanded ? <div className="gbm-alignment-body">
        <div className="gbm-alignment-context">
          <span><strong>{label || "Selected visit"}</strong> to <strong>{referenceLabel}</strong></span>
          <span>T1c reference · Rigid 6-DOF · No deformation</span>
        </div>
        <ol className="gbm-alignment-steps">
          {steps.map((step) => {
            const Icon = icons[step.id as keyof typeof icons] ?? ScanLine
            const StateIcon = step.status === "running" ? Loader2 : step.status === "complete" ? Check : step.status === "failed" ? X : Minus
            return <li key={step.id} data-state={step.status} aria-current={step.status === "running" ? "step" : undefined}>
              <div className="gbm-alignment-step-title"><Icon size={18} /><strong>{step.label}</strong>
                <StateIcon size={15} className={cn("shrink-0", step.status === "running" && "animate-spin motion-reduce:animate-none")} />
              </div>
              <div className="gbm-alignment-step-detail">{step.detail || "Waiting"}</div>
              <div className="gbm-alignment-step-state">{step.status === "complete" ? "Done" : step.status === "skipped" ? "Not applied" : step.status === "running" ? "Running" : step.status === "failed" ? "Failed" : "Pending"}
                {typeof step.duration_sec === "number" ? <span>{step.duration_sec.toFixed(1)} s</span> : null}
              </div>
            </li>
          })}
        </ol>
        {qc && !busy ? <div className="gbm-alignment-result">
          <span><strong>NCC change</strong> {typeof qc.ncc_delta === "number" ? `${qc.ncc_delta >= 0 ? "+" : ""}${qc.ncc_delta.toFixed(3)}` : "Unavailable"}</span>
          <span>{qc.registration_runtime_sec?.toFixed(1)} s</span>
          <span>Native volumes unchanged</span>
          {qc.warnings?.length ? <strong>Review alignment QC</strong> : null}
        </div> : null}
        {error || visit?.error ? <p role="alert" className="gbm-alignment-error">{error || visit?.error}</p> : null}
      </div> : null}
    </section>
  )
}
