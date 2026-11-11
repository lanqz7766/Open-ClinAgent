import { Clock3, Eye, Pin } from "lucide-react"
import { timelineScale, visitDisplayLabel, visitIntervalValues, visitTimeDetail } from "./brainTumor.timing"
import type { LongitudinalRow } from "./brainTumor.types"

export function VisitTimingSummary({ points, activePointId, baselinePointId, samePatient = true }: {
  points: LongitudinalRow[]
  activePointId: string
  baselinePointId: string
  samePatient?: boolean
}) {
  const index = points.findIndex(point => point.id === activePointId)
  if (index < 0) return null
  const point = points[index]
  const referenceIndex = points.findIndex(row => row.id === baselinePointId)
  const intervals = visitIntervalValues({ ...point, isReference: point.id === baselinePointId })
  // Without dates or numeric days no interval can be computed, so those lines are omitted rather than shown as unknown.
  const timed = samePatient && timelineScale(points).mode !== "ordinal"
  const context = (position: number) => {
    const visit = points[position]
    const time = visitDisplayLabel(visit)
    return `Visit ${position + 1}${time ? ` · ${time}` : ""}`
  }
  const primary = visitDisplayLabel(point)
  const detail = point.scanDate ? "Scan date"
    : point.relativeDay != null ? `Days from ${point.relativeDayOrigin || "unspecified origin"}`
      : point.stageLabel && point.stageLabel !== primary ? point.stageLabel : null
  return (
    <div className="visit-timing-summary" aria-label="Selected visit timing" aria-live="polite">
      <div className="visit-timing-current" title={timed || point.relativeDay != null ? visitTimeDetail(point) : undefined}>
        <span className="visit-timing-label"><Eye aria-hidden="true" />Viewing {samePatient ? "Visit" : "Scan"} {index + 1} of {points.length}</span>
        <strong>{primary ?? point.stageLabel ?? `${samePatient ? "Visit" : "Scan"} ${index + 1}`}</strong>
        {detail ? <span className="visit-timing-detail">{detail}</span> : null}
      </div>
      {samePatient && points.length > 1 ? <dl className="visit-timing-intervals">
        {timed ? <div className="visit-timing-previous">
          <dt><Clock3 aria-hidden="true" />Since previous visit</dt>
          <dd>{intervals.previous}<span className="visit-timing-detail">{index > 0 ? context(index - 1) : "No previous examination"}</span></dd>
        </div> : null}
        <div className="visit-timing-reference">
          <dt><Pin aria-hidden="true" />{timed ? "From reference" : "Reference"}</dt>
          <dd>
            {timed ? intervals.reference : point.id === baselinePointId ? "Selected reference" : referenceIndex >= 0 ? `Visit ${referenceIndex + 1}` : "None"}
            <span className="visit-timing-detail">{referenceIndex >= 0 ? context(referenceIndex) : "No reference selected"}</span>
          </dd>
        </div>
      </dl> : null}
    </div>
  )
}
