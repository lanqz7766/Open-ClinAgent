// Only full calendar dates from explicit visit metadata are accepted.
// No timestamps, partial dates, filenames, or filesystem times are inferred.
export function normalizeScanDate(value: unknown): string | null {
  if (typeof value !== "string") return null
  if (!/^(?:\d{8}|\d{4}-\d{2}-\d{2})$/.test(value.trim())) return null
  const match = /^(\d{4})-?(\d{2})-?(\d{2})$/.exec(value.trim())
  if (!match) return null
  const [, year, month, day] = match
  const iso = `${year}-${month}-${day}`
  const time = Date.parse(`${iso}T00:00:00Z`)
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === iso ? iso : null
}

type VisitTime = { id?: string; dateLabel?: string; label?: string; scanDate?: string | null; relativeDay?: number | null; relativeDayOrigin?: string | null; timingSamePatient?: boolean; stageLabel?: string }

export function normalizeRelativeDay(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

export function formatDay(value: number): string {
  return Number(value.toFixed(1)).toString()
}

function calendarDay(point: VisitTime) {
  const date = normalizeScanDate(point.scanDate === undefined ? point.dateLabel : point.scanDate)
  return date ? Date.parse(`${date}T00:00:00Z`) / 86400000 : null
}

function relativeOrigin(point: VisitTime) { return point.relativeDayOrigin?.trim() || null }

function intervalBetween(a: VisitTime | undefined, b: VisitTime): number | null {
  if (!a) return null
  const firstDate = calendarDay(a), secondDate = calendarDay(b)
  if (firstDate !== null && secondDate !== null) return secondDate - firstDate
  const firstDay = normalizeRelativeDay(a.relativeDay), secondDay = normalizeRelativeDay(b.relativeDay)
  return firstDay !== null && secondDay !== null && relativeOrigin(a) !== null && relativeOrigin(a) === relativeOrigin(b)
    ? secondDay - firstDay : null
}

export function timelineScale(points: VisitTime[]) {
  const samePatient = points.every(point => point.timingSamePatient !== false)
  const dates = points.map(calendarDay)
  const days = points.map(point => normalizeRelativeDay(point.relativeDay))
  const origin = relativeOrigin(points[0] ?? {})
  const mode = samePatient && points.length && dates.every(value => value !== null) ? "date"
    : samePatient && points.length && origin && points.every(point => relativeOrigin(point) === origin) && days.every(value => value !== null) ? "day" : "ordinal"
  const values = mode === "date" ? dates : mode === "day" ? days : points.map((_, index) => index)
  const numbers = values as number[]
  const min = Math.min(...numbers), max = Math.max(...numbers)
  return {
    mode,
    label: mode === "date" ? "Scan date · actual time intervals" : mode === "day" ? `Days from ${origin}`
      : samePatient ? "Visit order · timing unavailable" : "Case order · not a patient timeline",
    values,
    positions: numbers.map(value => max === min ? 0.5 : (value - min) / (max - min)),
  }
}

export function timelineTicks(points: VisitTime[], plotWidth = 620, fontSize = 12) {
  const scale = timelineScale(points)
  const laneEnds: number[] = []
  // Keep every visit at its measured time; stagger labels rather than dropping
  // nearby visits or spreading their measurement positions apart.
  return points.map((point, index) => ({
    position: scale.positions[index],
    label: scale.mode === "ordinal" ? `Visit ${index + 1}` : scale.mode === "day" ? `Day ${formatDay(scale.values[index]!)}` : visitTimeLabel(point, index),
  })).sort((a, b) => a.position - b.position).map(tick => {
    const x = tick.position * plotWidth
    const halfWidth = tick.label.length * fontSize * 0.32
    let lane = laneEnds.findIndex(end => x - halfWidth >= end + 12)
    if (lane < 0) lane = laneEnds.length
    laneEnds[lane] = x + halfWidth
    return { ...tick, lane }
  })
}

export function visitTimeLabel(point: VisitTime, index = 0): string {
  const date = normalizeScanDate(point.scanDate === undefined ? point.dateLabel : point.scanDate)
  const day = normalizeRelativeDay(point.relativeDay)
  return date ?? (day !== null ? `Day ${formatDay(day)}` : point.dateLabel || point.label || `Visit ${index + 1}`)
}

// Generic fallbacks the backend or tests use when a visit carries no timing text at all.
const GENERIC_VISIT_LABEL = /^(?:time|timepoint|visit|scan)\s*\d+$/i

/**
 * Text shown for a visit's time: a real date, a numeric day, or otherwise the
 * supplied label verbatim (for example "Day 102" from a curated manifest). A
 * supplied label is display text only: it is never parsed into dates or intervals.
 * Returns null when nothing beyond the visit number is known.
 */
export function visitDisplayLabel(point: VisitTime): string | null {
  const date = normalizeScanDate(point.scanDate === undefined ? point.dateLabel : point.scanDate)
  if (date) return date
  const day = normalizeRelativeDay(point.relativeDay)
  if (day !== null) return `Day ${formatDay(day)}`
  const label = point.dateLabel?.trim() ?? ""
  if (!label || label === point.id || label === point.label || GENERIC_VISIT_LABEL.test(label)) return null
  return label
}

export function visitTimeDetail(point: VisitTime): string {
  const date = normalizeScanDate(point.scanDate === undefined ? point.dateLabel : point.scanDate)
  const day = normalizeRelativeDay(point.relativeDay)
  return date ? `Scan date: ${date}` : day !== null ? `Day ${formatDay(day)}${relativeOrigin(point) ? ` from ${relativeOrigin(point)}` : " (origin unspecified)"}` : "Scan date unknown"
}

export function annotateVisitTiming<T extends VisitTime & { id: string; dateLabel: string }>(points: T[], referenceId: string, samePatient = true) {
  const dated = points.map((point) => ({ ...point, scanDate: normalizeScanDate(point.scanDate === undefined ? point.dateLabel : point.scanDate), relativeDay: normalizeRelativeDay(point.relativeDay), timingSamePatient: samePatient }))
  // Missing dates have no known chronological position: preserve supplied order.
  if (samePatient && dated.every((point) => point.scanDate !== null)) {
    dated.sort((a, b) => a.scanDate!.localeCompare(b.scanDate!))
  } else if (timelineScale(dated).mode === "day") {
    dated.sort((a, b) => a.relativeDay! - b.relativeDay!)
  }
  const reference = dated.find((point) => point.id === referenceId) ?? dated[0]
  return dated.map((point, index) => {
    const interval = samePatient && index > 0 ? intervalBetween(dated[index - 1], point) : null
    return {
      ...point,
      dateLabel: visitTimeLabel(point, index),
      timingSamePatient: samePatient,
      firstVisit: index === 0,
      intervalDays: interval !== null && interval >= 0 ? interval : null,
      // Signed offset preserves a reference selected later in the timeline.
      daysFromReference: samePatient ? intervalBetween(reference, point) : null,
    }
  })
}

export function visitTimingLabel(point: { firstVisit?: boolean; intervalDays?: number | null; timingSamePatient?: boolean }, samePatient = true): string {
  if (!samePatient || point.timingSamePatient === false) return "Interval: unavailable (different patients)"
  if (point.firstVisit) return "First visit · no previous visit"
  return point.intervalDays == null ? "Since previous visit: unavailable" : `Since previous visit: ${formatDay(point.intervalDays)} ${point.intervalDays === 1 ? "day" : "days"}`
}

export function visitIntervalValues(point: { firstVisit?: boolean; intervalDays?: number | null; daysFromReference?: number | null; isReference?: boolean; timingSamePatient?: boolean }) {
  if (point.timingSamePatient === false) return { previous: "Unavailable", reference: "Unavailable" }
  const duration = (days: number) => `${formatDay(Math.abs(days))} ${Math.abs(days) === 1 ? "day" : "days"}`
  const previous = point.firstVisit ? "First visit"
    : point.intervalDays == null ? "Unknown" : duration(point.intervalDays)
  const reference = point.isReference ? "Selected reference"
    : point.daysFromReference == null ? "Unknown"
      : point.daysFromReference === 0 ? "Same day"
        : `${duration(point.daysFromReference)} ${point.daysFromReference < 0 ? "before" : "after"}`
  return { previous, reference }
}
