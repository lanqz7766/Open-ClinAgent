import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { Eye, Pin } from "lucide-react"
import { Popover } from "radix-ui"
import { tumorPalette } from "./brainTumor.constants"
import { formatCompactMm3, formatMm3 } from "./brainTumor.logic"
import { hitTestTrend, layoutVisitLabels } from "./brainTumor.chartLayout"
import { timelineScale, visitIntervalValues, visitTimeLabel } from "./brainTumor.timing"
import type { LongitudinalRow } from "./brainTumor.types"

const series = [
  { key: "etMl", label: "CE tumor", color: tumorPalette.et },
  { key: "flairMl", label: "T2/FLAIR", color: tumorPalette.wt },
] as const

type Inspection = { id: string; x: number; y: number; mode: "hover" | "pinned" | "keyboard"; seriesIndex?: number }

export function TumorTrendChart({ points, activePointId, baselinePointId, onSelectActive, onInspect }: {
  points: LongitudinalRow[]
  activePointId: string
  baselinePointId: string
  onSelectActive: (id: string) => void
  onInspect?: (id: string | null) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const pointerDown = useRef<{ x: number; y: number } | null>(null)
  const [width, setWidth] = useState(720)
  const [textWidths, setTextWidths] = useState<number[]>([])
  const [inspection, setInspection] = useState<Inspection | null>(null)
  const inspectedId = inspection?.id
  const time = timelineScale(points)
  const labels = points.map((point, index) => time.mode === "ordinal" ? `Visit ${index + 1}` : visitTimeLabel(point, index))
  const labelKey = labels.join("|")
  const visitKey = points.map(point => point.id).join("|")

  useLayoutEffect(() => {
    const element = container.current
    if (!element) return
    const update = () => setWidth(Math.max(180, Math.round(element.getBoundingClientRect().width)))
    update()
    const observer = new ResizeObserver(update)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useLayoutEffect(() => {
    let cancelled = false
    const measure = () => {
      if (cancelled) return
      const next = Array.from(svg.current?.querySelectorAll<SVGTextElement>("[data-visit-tick]") ?? [])
        .map(element => Math.ceil(element.getComputedTextLength()) + 8)
      setTextWidths(previous => previous.length === next.length && previous.every((value, index) => value === next[index]) ? previous : next)
    }
    measure()
    void document.fonts.ready.then(measure)
    return () => { cancelled = true }
  }, [labelKey])

  useEffect(() => {
    setInspection(null)
    onInspect?.(null)
    return () => onInspect?.(null)
  }, [visitKey, onInspect])

  const left = 52, right = width - 16, top = 28, bottom = 230
  const ticks = layoutVisitLabels(time.positions, textWidths, left, right, [8, width - 8])
  const lanes = Math.max(0, ...ticks.map(tick => tick.lane)) + 1
  const height = bottom + 30 + lanes * 48
  const maxVolume = Math.max(1, ...points.flatMap(point => [point.etMl, point.flairMl]))
  const xFor = (index: number) => left + time.positions[index] * (right - left)
  const yFor = (value: number) => bottom - Math.max(0, value) / maxVolume * (bottom - top - 8)
  const activeIndex = points.findIndex(point => point.id === activePointId)
  const referenceIndex = points.findIndex(point => point.id === baselinePointId)
  const inspectedIndex = points.findIndex(point => point.id === inspectedId)
  const inspected = points[inspectedIndex]
  const curves = series.map(metric => points.map((point, index) => ({ x: xFor(index), y: yFor(point[metric.key]) })))
  const inspect = (next: Inspection | null) => { setInspection(next); onInspect?.(next?.id ?? null) }
  const clear = () => inspect(null)
  const inspectPoint = (index: number, mode: Inspection["mode"], seriesIndex = 0) => inspect({ id: points[index].id, ...curves[seriesIndex][index], mode, seriesIndex })
  const select = (index: number, seriesIndex = 0) => { onSelectActive(points[index].id); inspectPoint(index, "pinned", seriesIndex) }
  const pointerPosition = (event: { clientX: number; clientY: number; currentTarget: SVGSVGElement }) => {
    const rect = event.currentTarget.getBoundingClientRect()
    return { x: (event.clientX - rect.left) * width / rect.width, y: (event.clientY - rect.top) * height / rect.height }
  }
  const anchor = { current: { getBoundingClientRect: () => {
    const rect = svg.current?.getBoundingClientRect()
    const position = inspection?.mode === "hover" ? inspection : curves[inspection?.seriesIndex ?? 0][inspectedIndex]
    return new DOMRect((rect?.left ?? 0) + (position?.x ?? 0) * (rect?.width ?? width) / width,
      (rect?.top ?? 0) + (position?.y ?? 0) * (rect?.height ?? height) / height, 0, 0)
  } } }

  return (
    <Popover.Root open={Boolean(inspected)} onOpenChange={open => { if (!open) clear() }}>
    <Popover.Anchor virtualRef={anchor} />
    <div className="tumor-trend" ref={container}
      onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) clear() }}
      onKeyDown={event => { if (event.key === "Escape") clear() }}>
      <div className="tumor-trend-heading">
        <span>Volume <span className="tumor-trend-unit">(mm³)</span></span>
        <div className="tumor-trend-roles"><span><Eye aria-hidden="true" />Viewing</span><span><Pin aria-hidden="true" />Reference</span></div>
      </div>
      <svg ref={svg} className="tumor-trend-plot" height={height} viewBox={`0 0 ${width} ${height}`}
        role="group" aria-label="Tumor burden trend chart" data-time-axis={time.mode} data-hovering={inspection?.mode === "hover"}
        onPointerDown={event => { pointerDown.current = { x: event.clientX, y: event.clientY } }}
        onPointerMove={event => {
          if (event.pointerType === "touch" || inspection?.mode === "pinned") return
          const position = pointerPosition(event)
          const hit = hitTestTrend(position, curves)
          if (hit) inspect({ id: points[hit.index].id, ...position, mode: "hover" })
          else if (inspection) clear()
        }}
        onPointerLeave={() => { if (inspection?.mode === "hover") clear() }}
        onClick={event => {
          const start = pointerDown.current
          pointerDown.current = null
          if (start && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5) return
          const hit = hitTestTrend(pointerPosition(event), curves)
          if (hit) select(hit.index, hit.seriesIndex)
          else clear()
        }}>
        <g pointerEvents="none">
          {[0, 1, 2, 3].map(tick => {
            const y = yFor(maxVolume * tick / 3)
            return <g key={tick} className="tumor-trend-grid"><line x1={left} x2={right} y1={y} y2={y} /><text x={left - 12} y={y + 4} textAnchor="end">{formatCompactMm3(maxVolume * tick / 3)}</text></g>
          })}
          {activeIndex >= 0 ? <g data-viewing-marker="" className="tumor-trend-viewing">
            <rect x={xFor(activeIndex) - 9} width={18} y={top - 8} height={bottom - top + 8} rx={4} />
            <line x1={xFor(activeIndex)} x2={xFor(activeIndex)} y1={top - 8} y2={bottom} />
          </g> : null}
          {referenceIndex >= 0 ? <line data-reference-marker="" className="tumor-trend-reference" x1={xFor(referenceIndex)} x2={xFor(referenceIndex)} y1={top - 8} y2={bottom} /> : null}
          {inspectedIndex >= 0 ? <g className="tumor-trend-inspected" data-inspected-guide={inspectedId}>
            <rect x={xFor(inspectedIndex) - 12} width={24} y={top - 8} height={bottom - top + 8} rx={5} />
            <line x1={xFor(inspectedIndex)} x2={xFor(inspectedIndex)} y1={top - 8} y2={bottom} />
          </g> : null}
          {series.map(metric => <g key={metric.key}>
            <path data-volume-series={metric.key} d={points.map((point, index) => `${index ? "L" : "M"} ${xFor(index)} ${yFor(point[metric.key])}`).join(" ")} fill="none" stroke={metric.color} strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round" />
            {points.map((point, index) => <g key={point.id}>
              {point.id === activePointId ? <circle className="tumor-trend-ring" cx={xFor(index)} cy={yFor(point[metric.key])} r={9} stroke={metric.color} /> : null}
              <circle data-visit-point={point.id} data-series={metric.key} cx={xFor(index)} cy={yFor(point[metric.key])} r={point.id === activePointId ? 6 : 5} fill={metric.color} stroke="hsl(var(--background))" strokeWidth={2} />
            </g>)}
          </g>)}
          {inspected ? series.map(metric => <g key={metric.key} className="tumor-trend-point-emphasis" data-inspected-point={inspected.id}>
            <circle cx={xFor(inspectedIndex)} cy={yFor(inspected[metric.key])} r={12} fill={metric.color} fillOpacity={0.18} />
            <circle cx={xFor(inspectedIndex)} cy={yFor(inspected[metric.key])} r={7} fill={metric.color} stroke="hsl(var(--background))" strokeWidth={2.5} />
          </g>) : null}
        </g>
        {ticks.map(tick => {
          const point = points[tick.index]
          const y = bottom + 48 + tick.lane * 48
          return <g key={point.id} className="tumor-trend-visit" role="button" tabIndex={0}
            data-inspected={inspectedId === point.id}
            aria-label={`View visit ${tick.index + 1}, ${labels[tick.index]}`} aria-pressed={point.id === activePointId}
            aria-describedby={inspectedId === point.id ? "tumor-trend-detail" : undefined}
            onFocus={event => { if (event.currentTarget.matches(":focus-visible")) inspectPoint(tick.index, "keyboard") }}
            onClick={event => { event.stopPropagation(); select(tick.index) }}
            onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(tick.index) } }}>
            <path className="tumor-trend-leader" pointerEvents="none" d={`M ${tick.anchorX} ${bottom + 4} V ${bottom + 10} L ${tick.x} ${y - 22}`} />
            <rect className="tumor-trend-label-hit" x={tick.x - tick.width / 2 - 5} y={y - 22} width={tick.width + 10} height={44} rx={4} />
            <text data-visit-tick="" data-anchor-x={tick.anchorX} className="tumor-trend-label" pointerEvents="none" x={tick.x} y={y + 3} textAnchor="middle">{labels[tick.index]}</text>
          </g>
        })}
      </svg>
      <div className="tumor-trend-footer"><span>{time.label}</span><div className="tumor-trend-series">{series.map(metric => <span key={metric.key}><i style={{ background: metric.color }} />{metric.label}</span>)}</div></div>
    </div>
    {inspected ? <Popover.Portal>
      <Popover.Content className="tumor-trend-detail" role="tooltip" id="tumor-trend-detail"
        side="top" align="start" sideOffset={16} alignOffset={12} collisionPadding={12}
        updatePositionStrategy="always" hideWhenDetached
        onOpenAutoFocus={event => event.preventDefault()} onCloseAutoFocus={event => event.preventDefault()}
        onInteractOutside={event => { if (container.current?.contains(event.target as Node)) event.preventDefault() }}>
        <TrendVisitDetail point={inspected} index={inspectedIndex} isReference={inspected.id === baselinePointId} isViewing={inspected.id === activePointId} />
      </Popover.Content>
    </Popover.Portal> : null}
    </Popover.Root>
  )
}

export function TrendVisitDetail({ point, index, isReference, isViewing }: {
  point: LongitudinalRow; index: number; isReference: boolean; isViewing: boolean
}) {
  const intervals = visitIntervalValues({ ...point, isReference })
  return <>
    <div className="tumor-trend-detail-title"><strong>{visitTimeLabel(point, index)}</strong><span>Visit {index + 1}{isViewing ? " · Viewing" : ""}{isReference ? " · Reference" : ""}</span></div>
    <dl className="tumor-trend-volumes">{series.map(metric => <div key={metric.key}><dt><i style={{ background: metric.color }} />{metric.label}</dt><dd>{formatMm3(point[metric.key])}</dd></div>)}</dl>
    {point.timingSamePatient !== false ? <dl className="trend-tooltip-intervals"><div><dt>Since previous visit</dt><dd>{intervals.previous}</dd></div><div><dt>From reference</dt><dd>{intervals.reference}</dd></div></dl> : null}
  </>
}
