import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react"
import { ChevronDown, Expand, Layers3, Move, ScanEye } from "lucide-react"
import { Niivue, SLICE_TYPE } from "@niivue/niivue"

import { cn } from "@/lib/utils"
import { CornerstoneStructuralViewer } from "@/components/CornerstoneStructuralViewer"
import {
  buildFallbackNiivueLabelLut,
  buildNiivueLabelLut,
  resolveLabelAlpha,
  type SegmentationOverlayModel,
  type ViewerMode,
} from "@/lib/segmentationOverlay"

export type SliceEntry = {
  image_base64: string
  overlay_base64: string | null
  label_map_base64?: string | null
  label_shape?: [number, number] | null
  original_shape?: [number, number] | null
  render_shape?: [number, number] | null
  content_bbox?: {
    x: number
    y: number
    width: number
    height: number
  } | null
  padding?: {
    left: number
    right: number
    top: number
    bottom: number
  } | null
  slice_index: number
  slice_fraction: number
  description: string
  orientation_labels?: {
    left: string
    right: string
    top: string
    bottom: string
  }
  orientation_policy?: "radiological" | string
}

export type SlicePlaneSet = {
  axial: SliceEntry[]
  coronal: SliceEntry[]
  sagittal: SliceEntry[]
}

export type SliceManifest = {
  mode: "on_demand"
  orientation_policy?: "radiological" | string
  output_size?: [number, number]
  has_overlay: boolean
  planes: Record<ViewerPlane, { slice_count: number; default_index: number }>
}

export type StructuralSliceRequestContext =
  | {
      kind: "study"
      patientId: string
      studyId: string
    }
  | {
      kind: "session"
      sessionId: string
    }

export type ViewerAssets = {
  viewer_type: "dicomweb" | "nifti" | "png_fallback" | "cornerstone_structural"
  has_segmentation: boolean
  default_plane: "axial" | "coronal" | "sagittal" | string
  orientation_policy?: "radiological" | string
  study_uid?: string | null
  series_uid?: string | null
  dicomweb_base_url?: string | null
  image_asset_url?: string | null
  segmentation_asset_url?: string | null
  ohif_url?: string | null
}

type ViewerPlane = "axial" | "coronal" | "sagittal"

const VIEWER_PLANES: ViewerPlane[] = ["axial", "coronal", "sagittal"]
const VIEWER_MODES: ViewerMode[] = ["blend", "mask", "contour"]
const USE_EXPERIMENTAL_CORNERSTONE_STRUCTURAL_VIEWER = false

const SLICE_TYPE_BY_PLANE: Record<ViewerPlane, SLICE_TYPE> = {
  axial: SLICE_TYPE.AXIAL,
  coronal: SLICE_TYPE.CORONAL,
  sagittal: SLICE_TYPE.SAGITTAL,
}

type LoadVolumeOption = Parameters<Niivue["loadVolumes"]>[0][number]

const DEFAULT_VIEWER_OPTIONS = {
  show3Dcrosshair: false,
  isOrientCube: false,
  backColor: [0.02, 0.04, 0.07, 1] as [number, number, number, number],
  crosshairColor: [0.29, 0.63, 0.96, 1] as [number, number, number, number],
  showLegend: false,
}

const DEFAULT_ORIENTATION_LABELS: Record<ViewerPlane, { left: string; right: string; top: string; bottom: string }> = {
  axial: { left: "R", right: "L", top: "A", bottom: "P" },
  coronal: { left: "R", right: "L", top: "S", bottom: "I" },
  sagittal: { left: "A", right: "P", top: "S", bottom: "I" },
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function hexToRgb(hex: string) {
  const normalized = hex.replace("#", "")
  const parsed = Number.parseInt(normalized, 16)
  return {
    r: (parsed >> 16) & 255,
    g: (parsed >> 8) & 255,
    b: parsed & 255,
  }
}

function decodeLabelMap(base64: string, shape: [number, number] | null | undefined) {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  const data = new Uint16Array(bytes.buffer)
  const height = shape?.[0] ?? 0
  const width = shape?.[1] ?? 0
  return { data, width, height }
}

function loadImageElement(src: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error("Failed to decode slice preview."))
    image.src = src
  })
}

function contentBoxForEntry(entry: SliceEntry | null | undefined) {
  const renderHeight = entry?.render_shape?.[0] ?? 256
  const renderWidth = entry?.render_shape?.[1] ?? 256
  const bbox = entry?.content_bbox
  if (!bbox) {
    return {
      x: 0,
      y: 0,
      width: renderWidth,
      height: renderHeight,
      renderWidth,
      renderHeight,
    }
  }
  return {
    x: bbox.x,
    y: bbox.y,
    width: Math.max(1, bbox.width),
    height: Math.max(1, bbox.height),
    renderWidth,
    renderHeight,
  }
}

function sliceViewportBoxStyle(entry: SliceEntry | null | undefined): CSSProperties {
  const box = contentBoxForEntry(entry)
  return {
    left: `${(box.x / Math.max(box.renderWidth, 1)) * 100}%`,
    top: `${(box.y / Math.max(box.renderHeight, 1)) * 100}%`,
    width: `${(box.width / Math.max(box.renderWidth, 1)) * 100}%`,
    height: `${(box.height / Math.max(box.renderHeight, 1)) * 100}%`,
  }
}

function sliceViewportMediaStyle(entry: SliceEntry | null | undefined): CSSProperties {
  const box = contentBoxForEntry(entry)
  return {
    left: `${(-box.x / Math.max(box.width, 1)) * 100}%`,
    top: `${(-box.y / Math.max(box.height, 1)) * 100}%`,
    width: `${(box.renderWidth / Math.max(box.width, 1)) * 100}%`,
    height: `${(box.renderHeight / Math.max(box.height, 1)) * 100}%`,
  }
}

function normalizedFromAxisLabels({
  start,
  end,
  value,
}: {
  start: string
  end: string
  value: number
}) {
  const left = start.toUpperCase()
  const right = end.toUpperCase()
  if (
    (left === "R" && right === "L") ||
    (left === "P" && right === "A") ||
    (left === "I" && right === "S")
  ) {
    return 1 - value
  }
  return value
}

function screenFromAxisLabels({
  start,
  end,
  fraction,
}: {
  start: string
  end: string
  fraction: number
}) {
  return normalizedFromAxisLabels({ start, end, value: fraction })
}

function screenFromContentBox({
  fraction,
  start,
  end,
  entry,
  axis,
}: {
  fraction: number
  start: string
  end: string
  entry: SliceEntry | null | undefined
  axis: "x" | "y"
}) {
  const normalized = screenFromAxisLabels({ start, end, fraction })
  const box = contentBoxForEntry(entry)
  const offset = axis === "x" ? box.x : box.y
  const span = axis === "x" ? box.width : box.height
  const renderSize = axis === "x" ? box.renderWidth : box.renderHeight
  return (offset + normalized * span) / Math.max(renderSize, 1)
}

function fractionFromContentBox({
  value,
  start,
  end,
  entry,
  axis,
}: {
  value: number
  start: string
  end: string
  entry: SliceEntry | null | undefined
  axis: "x" | "y"
}) {
  const box = contentBoxForEntry(entry)
  const offset = axis === "x" ? box.x : box.y
  const span = axis === "x" ? box.width : box.height
  const renderSize = axis === "x" ? box.renderWidth : box.renderHeight
  const pixel = clamp(value, 0, 1) * renderSize
  const withinContent = clamp((pixel - offset) / Math.max(span, 1), 0, 1)
  return normalizedFromAxisLabels({ start, end, value: withinContent })
}

function OrientationOverlay({
  labels,
}: {
  labels: { left: string; right: string; top: string; bottom: string }
}) {
  return (
    <div className="pointer-events-none absolute inset-0 text-[10px] font-medium uppercase tracking-[0.14em] text-white/70">
      <div className="absolute left-1/2 top-2 -translate-x-1/2">{labels.top}</div>
      <div className="absolute bottom-2 left-1/2 -translate-x-1/2">{labels.bottom}</div>
      <div className="absolute left-2 top-1/2 -translate-y-1/2">{labels.left}</div>
      <div className="absolute right-2 top-1/2 -translate-y-1/2">{labels.right}</div>
    </div>
  )
}

function ModeExplainer() {
  return (
    <div className="grid gap-2 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3 text-[12px] leading-5 text-[hsl(var(--muted-foreground))] md:grid-cols-3">
      <div>
        <span className="font-medium text-[hsl(var(--foreground))]">Blend</span>: anatomy + colored structures.
      </div>
      <div>
        <span className="font-medium text-[hsl(var(--foreground))]">Mask</span>: segmentation only.
      </div>
      <div>
        <span className="font-medium text-[hsl(var(--foreground))]">Contour</span>: anatomy + structure boundaries.
      </div>
    </div>
  )
}

function LegendSidebar({
  overlayModel,
  visibleLabelIds,
  activeLabelId,
  activeGroup,
  expandedGroups,
  maxHeightClassName,
  showBulkControls = false,
  hideIntro = false,
  scrollable = true,
  onSelectAll,
  onDeselectAll,
  onToggleGroupExpanded,
  onToggleGroupVisibility,
  onToggleLabelVisibility,
  onSelectGroup,
  onSelectLabel,
}: {
  overlayModel: SegmentationOverlayModel
  visibleLabelIds: number[]
  activeLabelId: number | null
  activeGroup: string | null
  expandedGroups: string[]
  onToggleGroupExpanded: (groupId: string) => void
  onToggleGroupVisibility: (groupId: string) => void
  onToggleLabelVisibility: (labelId: number) => void
  onSelectGroup: (groupId: string | null) => void
  onSelectLabel: (labelId: number | null) => void
  maxHeightClassName?: string
  showBulkControls?: boolean
  hideIntro?: boolean
  scrollable?: boolean
  onSelectAll?: () => void
  onDeselectAll?: () => void
}) {
  const visibleSet = useMemo(() => new Set(visibleLabelIds), [visibleLabelIds])

  return (
    <div className="flex h-full min-w-0 flex-col">
      {!hideIntro ? (
        <div className="mb-3 shrink-0">
          <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Detailed legend</div>
          <div className="mt-1 text-[12px] leading-6 text-[hsl(var(--muted-foreground))]">
            Use checkboxes to show or hide masks. Click a group or label name to focus that anatomy without changing visibility.
          </div>
        </div>
      ) : null}
      {showBulkControls ? (
        <div className="mb-3 flex shrink-0 flex-wrap gap-2">
          <button
            className="rounded-full border border-[hsl(var(--border))] px-3 py-1.5 text-[11px] text-[hsl(var(--muted-foreground))] transition-colors hover:text-[hsl(var(--foreground))]"
            onClick={() => onSelectAll?.()}
            type="button"
          >
            Select All
          </button>
          <button
            className="rounded-full border border-[hsl(var(--border))] px-3 py-1.5 text-[11px] text-[hsl(var(--muted-foreground))] transition-colors hover:text-[hsl(var(--foreground))]"
            onClick={() => onDeselectAll?.()}
            type="button"
          >
            Deselect All
          </button>
        </div>
      ) : null}
      <div
        className={cn(
          scrollable === false
            ? "space-y-2"
            : "min-h-0 flex-1 space-y-2 overflow-y-auto pr-1",
          maxHeightClassName ?? "",
        )}
      >
        {overlayModel.groups.map((group) => {
          const expanded = expandedGroups.includes(group.id)
          const allVisible = group.labels.every((label) => visibleSet.has(label.labelId))
          const someVisible = group.labels.some((label) => visibleSet.has(label.labelId))
          const groupActive = activeGroup === group.id && activeLabelId == null
          return (
            <div className="overflow-hidden rounded-xl border border-[hsl(var(--border)/0.75)]" key={group.id}>
              <div className="flex items-center gap-2 px-3 py-2.5">
                <button
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  onClick={() => onSelectGroup(groupActive ? null : group.id)}
                  type="button"
                >
                  <span className="h-3.5 w-3.5 rounded-full border border-black/15" style={{ backgroundColor: group.color }} />
                  <span
                    className={cn(
                      "truncate text-[12px] font-medium",
                      groupActive ? "text-[hsl(var(--foreground))]" : "text-[hsl(var(--muted-foreground))]",
                    )}
                  >
                    {group.displayName}
                  </span>
                </button>
                <input
                  checked={allVisible}
                  className="size-4 accent-[hsl(var(--primary))]"
                  onChange={() => onToggleGroupVisibility(group.id)}
                  ref={(node) => {
                    if (node) {
                      node.indeterminate = !allVisible && someVisible
                    }
                  }}
                  type="checkbox"
                />
                <button
                  className="rounded-full border border-[hsl(var(--border))] p-1 text-[hsl(var(--muted-foreground))] transition-colors hover:text-[hsl(var(--foreground))]"
                  onClick={() => onToggleGroupExpanded(group.id)}
                  type="button"
                >
                  <ChevronDown className={cn("size-3.5 transition-transform", expanded ? "rotate-180" : "")} />
                </button>
              </div>
              {expanded ? (
                <div className="border-t border-[hsl(var(--border)/0.75)] bg-[hsl(var(--card))]/20 px-2 py-2">
                  {group.labels.map((label) => {
                    const active = activeLabelId === label.labelId
                    return (
                      <div className="flex items-center gap-2 rounded-lg px-2 py-2" key={label.labelId}>
                        <button
                          className="flex min-w-0 flex-1 items-center gap-2 text-left"
                          onClick={() => onSelectLabel(active ? null : label.labelId)}
                          type="button"
                        >
                          <span className="h-3 w-3 rounded-sm border border-black/15" style={{ backgroundColor: label.color }} />
                          <span className={cn("truncate text-[12px]", active ? "text-[hsl(var(--foreground))]" : "text-[hsl(var(--muted-foreground))]")}>
                            {label.displayName}
                          </span>
                        </button>
                        <input
                          checked={visibleSet.has(label.labelId)}
                          className="size-4 accent-[hsl(var(--primary))]"
                          onChange={() => onToggleLabelVisibility(label.labelId)}
                          type="checkbox"
                        />
                      </div>
                    )
                  })}
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function RenderedSliceCanvas({
  entry,
  overlayModel,
  visibleLabelIds,
  activeLabelId,
  activeGroup,
  viewerMode,
  showOverlay,
  className,
  style,
}: {
  entry: SliceEntry
  overlayModel: SegmentationOverlayModel | null
  visibleLabelIds: number[]
  activeLabelId: number | null
  activeGroup: string | null
  viewerMode: ViewerMode
  showOverlay: boolean
  className?: string
  style?: CSSProperties
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    let cancelled = false

    async function render() {
      const canvas = canvasRef.current
      if (!canvas) {
        return
      }
      const anatomyImage = await loadImageElement(`data:image/png;base64,${entry.image_base64}`)
      if (cancelled) {
        return
      }

      const width = anatomyImage.naturalWidth || anatomyImage.width
      const height = anatomyImage.naturalHeight || anatomyImage.height
      canvas.width = width
      canvas.height = height

      const context = canvas.getContext("2d")
      if (!context) {
        return
      }
      context.clearRect(0, 0, width, height)
      context.drawImage(anatomyImage, 0, 0, width, height)

      if (!showOverlay || !entry.label_map_base64 || !overlayModel) {
        return
      }

      const base = context.getImageData(0, 0, width, height)
      const anatomy = new Uint8ClampedArray(base.data)
      const output = viewerMode === "mask" ? new Uint8ClampedArray(base.data.length) : base.data
      const { data: labelMap } = decodeLabelMap(entry.label_map_base64, entry.label_shape)
      const visibleSet = new Set(visibleLabelIds)

      for (let index = 0; index < width * height; index += 1) {
        const labelId = labelMap[index]
        if (!labelId) {
          if (viewerMode === "mask") {
            const offset = index * 4
            output[offset] = 5
            output[offset + 1] = 8
            output[offset + 2] = 12
            output[offset + 3] = 255
          }
          continue
        }
        const label = overlayModel.labelById[labelId]
        if (!label) {
          continue
        }
        const alpha = resolveLabelAlpha({
          label,
          visibleLabelIds: visibleSet,
          activeLabelId,
          activeGroup,
          viewerMode,
        })
        if (alpha <= 0) {
          continue
        }
        const offset = index * 4
        const fill = hexToRgb(label.color)
        const stroke = hexToRgb(label.strokeColor)

        if (viewerMode === "contour") {
          const x = index % width
          const y = Math.floor(index / width)
          const neighbors = [
            x > 0 ? labelMap[index - 1] : 0,
            x < width - 1 ? labelMap[index + 1] : 0,
            y > 0 ? labelMap[index - width] : 0,
            y < height - 1 ? labelMap[index + width] : 0,
          ]
          const boundary = neighbors.some((neighbor) => neighbor !== labelId)
          if (!boundary) {
            continue
          }
          output[offset] = Math.round(anatomy[offset] * (1 - alpha) + stroke.r * alpha)
          output[offset + 1] = Math.round(anatomy[offset + 1] * (1 - alpha) + stroke.g * alpha)
          output[offset + 2] = Math.round(anatomy[offset + 2] * (1 - alpha) + stroke.b * alpha)
          output[offset + 3] = 255
          continue
        }

        if (viewerMode === "mask") {
          output[offset] = fill.r
          output[offset + 1] = fill.g
          output[offset + 2] = fill.b
          output[offset + 3] = 255
          continue
        }

        output[offset] = Math.round(anatomy[offset] * (1 - alpha) + fill.r * alpha)
        output[offset + 1] = Math.round(anatomy[offset + 1] * (1 - alpha) + fill.g * alpha)
        output[offset + 2] = Math.round(anatomy[offset + 2] * (1 - alpha) + fill.b * alpha)
        output[offset + 3] = 255
      }

      context.putImageData(new ImageData(output, width, height), 0, 0)
    }

    void render()
    return () => {
      cancelled = true
    }
  }, [activeGroup, activeLabelId, entry.image_base64, entry.label_map_base64, entry.label_shape, overlayModel, showOverlay, viewerMode, visibleLabelIds])

  return (
    <canvas
      className={cn("block max-h-none max-w-none", className)}
      ref={canvasRef}
      style={style}
    />
  )
}

function SliceViewportMedia({
  entry,
  children,
}: {
  entry: SliceEntry | null | undefined
  children: (styles: { box: CSSProperties; media: CSSProperties }) => ReactNode
}) {
  return children({
    box: sliceViewportBoxStyle(entry),
    media: sliceViewportMediaStyle(entry),
  })
}

function nearestSliceIndex(entries: SliceEntry[], fraction: number) {
  if (!entries.length) {
    return 0
  }
  let bestIndex = 0
  let bestDelta = Number.POSITIVE_INFINITY
  entries.forEach((entry, index) => {
    const delta = Math.abs((entry.slice_fraction ?? 0) - fraction)
    if (delta < bestDelta) {
      bestDelta = delta
      bestIndex = index
    }
  })
  return bestIndex
}

function PngSliceFallbackViewer({
  slices,
  overlaySlices,
  plane,
  viewerMode,
  showOverlay,
  overlayModel,
  visibleLabelIds,
  activeLabelId,
  activeGroup,
}: {
  slices: SlicePlaneSet | null
  overlaySlices: SlicePlaneSet | null
  plane: ViewerPlane
  viewerMode: ViewerMode
  showOverlay: boolean
  overlayModel: SegmentationOverlayModel | null
  visibleLabelIds: number[]
  activeLabelId: number | null
  activeGroup: string | null
}) {
  const [indices, setIndices] = useState<Record<ViewerPlane, number>>({
    axial: 0,
    coronal: 0,
    sagittal: 0,
  })

  const activeSlices = showOverlay && overlaySlices ? overlaySlices : slices
  const planeSlices = activeSlices?.[plane] ?? []
  const activeIndex = Math.min(indices[plane] ?? 0, Math.max(planeSlices.length - 1, 0))
  const current = planeSlices[activeIndex] ?? null
  const orientationLabels = current?.orientation_labels ?? DEFAULT_ORIENTATION_LABELS[plane]

  return (
    <div className="space-y-4">
      {current ? (
        <div className="relative mx-auto w-full max-w-[52rem] overflow-hidden rounded-[1rem] border border-[hsl(var(--border))] bg-black">
          {showOverlay && current.label_map_base64 && overlayModel ? (
            <RenderedSliceCanvas
              activeGroup={activeGroup}
              activeLabelId={activeLabelId}
              entry={current}
              overlayModel={overlayModel}
              showOverlay={showOverlay}
              viewerMode={viewerMode}
              visibleLabelIds={visibleLabelIds}
            />
          ) : showOverlay && current.overlay_base64 ? (
            <img
              alt={`${plane} overlay slice`}
              className="h-[30rem] w-full object-contain"
              src={`data:image/png;base64,${current.overlay_base64}`}
            />
          ) : (
            <img
              alt={`${plane} slice`}
              className="h-[30rem] w-full object-contain"
              src={`data:image/png;base64,${current.image_base64}`}
            />
          )}
          <div className="pointer-events-none absolute inset-0">
            <div className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-white/20" />
            <div className="absolute left-0 top-1/2 h-px w-full -translate-y-1/2 bg-white/20" />
          </div>
          <OrientationOverlay labels={orientationLabels} />
        </div>
      ) : (
        <div className="flex h-[30rem] items-center justify-center rounded-[1rem] border border-[hsl(var(--border))] bg-black text-[13px] text-white/60">
          Select a study to load slice previews.
        </div>
      )}

      {planeSlices.length > 0 ? (
        <>
          <input
            className="w-full accent-[hsl(var(--primary))]"
            max={Math.max(planeSlices.length - 1, 0)}
            min={0}
            onChange={(event) =>
              setIndices((currentIndices) => ({
                ...currentIndices,
                [plane]: Number(event.target.value),
              }))
            }
            type="range"
            value={activeIndex}
          />
        </>
      ) : null}
    </div>
  )
}

function buildStructuralSliceRequestUrl(
  request: StructuralSliceRequestContext,
  plane: ViewerPlane,
  index: number,
  overlay: boolean,
) {
  const params = new URLSearchParams({
    plane,
    index: String(index),
    overlay: overlay ? "true" : "false",
  })
  if (request.kind === "session") {
    return `/api/demo/neuro-report/sessions/${request.sessionId}/slice?${params.toString()}`
  }
  return `/api/demo/neuro-report/patients/${request.patientId}/studies/${request.studyId}/slice?${params.toString()}`
}

function clampIndexForPlane(manifest: SliceManifest, plane: ViewerPlane, index: number) {
  const sliceCount = manifest.planes[plane]?.slice_count ?? 1
  return Math.max(0, Math.min(index, Math.max(sliceCount - 1, 0)))
}

function fractionForPlaneIndex(manifest: SliceManifest, plane: ViewerPlane, index: number) {
  const sliceCount = manifest.planes[plane]?.slice_count ?? 1
  return clampIndexForPlane(manifest, plane, index) / Math.max(sliceCount - 1, 1)
}

function allGroupIdsForModel(overlayModel: SegmentationOverlayModel | null | undefined) {
  return overlayModel?.groups.map((group) => group.id) ?? []
}

function allLabelIdsForModel(overlayModel: SegmentationOverlayModel | null | undefined) {
  return overlayModel ? Object.keys(overlayModel.labelById).map((value) => Number(value)) : []
}

function labelIdsForGroupIds(
  overlayModel: SegmentationOverlayModel | null | undefined,
  groupIds: string[],
) {
  if (!overlayModel) {
    return []
  }
  const selected = new Set(groupIds)
  return overlayModel.groups
    .filter((group) => selected.has(group.id))
    .flatMap((group) => group.labels.map((label) => label.labelId))
}

function usePlaneWheelNavigator(
  onNudgePlaneSlice: (plane: ViewerPlane, direction: -1 | 1) => void,
) {
  const frameRef = useRef<Record<ViewerPlane, number | null>>({
    axial: null,
    coronal: null,
    sagittal: null,
  })
  const lastWheelAtRef = useRef<Record<ViewerPlane, number>>({
    axial: 0,
    coronal: 0,
    sagittal: 0,
  })
  const latestDeltaRef = useRef<Record<ViewerPlane, number>>({
    axial: 0,
    coronal: 0,
    sagittal: 0,
  })

  useEffect(() => {
    const frameState = frameRef.current
    return () => {
      VIEWER_PLANES.forEach((plane) => {
        const frame = frameState[plane]
        if (frame != null) {
          window.cancelAnimationFrame(frame)
        }
      })
    }
  }, [])

  return (plane: ViewerPlane, isHovered: boolean, event: React.WheelEvent<HTMLDivElement>) => {
    if (!isHovered) {
      return
    }
    event.preventDefault()
    event.stopPropagation()
    latestDeltaRef.current[plane] = event.deltaY
    if (frameRef.current[plane] != null) {
      return
    }
    frameRef.current[plane] = window.requestAnimationFrame(() => {
      frameRef.current[plane] = null
      const now = performance.now()
      if (now - lastWheelAtRef.current[plane] < 50) {
        return
      }
      const delta = latestDeltaRef.current[plane]
      if (delta === 0) {
        return
      }
      lastWheelAtRef.current[plane] = now
      latestDeltaRef.current[plane] = 0
      onNudgePlaneSlice(plane, delta > 0 ? 1 : -1)
    })
  }
}

function TriViewTileHeader({
  title,
  meta,
}: {
  title: string
  meta?: string | null
}) {
  return (
    <div className="flex min-h-5 items-center justify-between gap-2">
      <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">{title}</div>
      <div className="text-[11px] text-[hsl(var(--muted-foreground))]">{meta ?? "\u00a0"}</div>
    </div>
  )
}

function LegendGroupSelector({
  overlayModel,
  selectedGroupIds,
  onChange,
}: {
  overlayModel: SegmentationOverlayModel
  selectedGroupIds: string[]
  onChange: (groupIds: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const containerRef = useRef<HTMLDivElement | null>(null)
  const allGroupIds = useMemo(() => allGroupIdsForModel(overlayModel), [overlayModel])
  const allSelected = allGroupIds.length > 0 && selectedGroupIds.length === allGroupIds.length
  const filteredGroups = useMemo(() => {
    const query = search.trim().toLowerCase()
    return overlayModel.groups.filter((group) =>
      !query ? true : group.displayName.toLowerCase().includes(query),
    )
  }, [overlayModel.groups, search])

  useEffect(() => {
    if (!open) {
      return
    }
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("pointerdown", onPointerDown)
    return () => document.removeEventListener("pointerdown", onPointerDown)
  }, [open])

  const selectionSummary = allSelected
    ? "All groups"
    : selectedGroupIds.length === 0
      ? "No groups selected"
      : `${selectedGroupIds.length} group${selectedGroupIds.length === 1 ? "" : "s"} selected`

  return (
    <div className="relative" ref={containerRef}>
      <button
        className="flex w-full items-center justify-between gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-left"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <div className="min-w-0">
          <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Legend selector</div>
          <div className="mt-1 truncate text-[13px] text-[hsl(var(--foreground))]">{selectionSummary}</div>
        </div>
        <ChevronDown className={cn("size-4 shrink-0 text-[hsl(var(--muted-foreground))] transition-transform", open ? "rotate-180" : "")} />
      </button>

      {open ? (
        <div className="mt-2 rounded-[1rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3 shadow-[0_18px_60px_-32px_rgba(15,23,42,0.5)]">
          <input
            className="w-full rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-[13px] text-[hsl(var(--foreground))] outline-none placeholder:text-[hsl(var(--muted-foreground))]"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search groups"
            type="text"
            value={search}
          />
          <div className="mt-3 max-h-56 space-y-2 overflow-y-auto pr-1">
            <label className="flex items-center gap-3 rounded-lg border border-[hsl(var(--border)/0.8)] px-3 py-2 text-[12px] text-[hsl(var(--foreground))]">
              <input
                checked={allSelected}
                className="size-4 accent-[hsl(var(--primary))]"
                onChange={(event) => onChange(event.target.checked ? allGroupIds : [])}
                type="checkbox"
              />
              <span className="font-medium">All groups</span>
            </label>
            {filteredGroups.map((group) => {
              const checked = selectedGroupIds.includes(group.id)
              return (
                <label
                  className="flex items-center gap-3 rounded-lg border border-[hsl(var(--border)/0.8)] px-3 py-2 text-[12px] text-[hsl(var(--foreground))]"
                  key={group.id}
                >
                  <input
                    checked={checked}
                    className="size-4 accent-[hsl(var(--primary))]"
                    onChange={(event) =>
                      onChange(
                        event.target.checked
                          ? [...selectedGroupIds, group.id]
                          : selectedGroupIds.filter((groupId) => groupId !== group.id),
                      )
                    }
                    type="checkbox"
                  />
                  <span className="h-3.5 w-3.5 rounded-full border border-black/15" style={{ backgroundColor: group.color }} />
                  <span className="truncate">{group.displayName}</span>
                </label>
              )
            })}
            {!filteredGroups.length ? (
              <div className="rounded-lg border border-dashed border-[hsl(var(--border))] px-3 py-3 text-[12px] text-[hsl(var(--muted-foreground))]">
                No groups match this search.
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function TriViewLegendTile({
  overlayModel,
  showOverlay,
  setShowOverlay,
  onReplaceVisibleLabelIds,
  visibleLabelIds,
  activeLabelId,
  activeGroup,
  expandedGroups,
  onToggleGroupExpanded,
  onToggleGroupVisibility,
  onToggleLabelVisibility,
  onSelectGroup,
  onSelectLabel,
  onSelectAllLabels,
  onDeselectAllLabels,
}: {
  activePlane: ViewerPlane
  overlayModel: SegmentationOverlayModel | null
  showOverlay: boolean
  setShowOverlay: (value: boolean) => void
  onReplaceVisibleLabelIds: (labelIds: number[]) => void
  visibleLabelIds: number[]
  activeLabelId: number | null
  activeGroup: string | null
  expandedGroups: string[]
  onToggleGroupExpanded: (groupId: string) => void
  onToggleGroupVisibility: (groupId: string) => void
  onToggleLabelVisibility: (labelId: number) => void
  onSelectGroup: (groupId: string | null) => void
  onSelectLabel: (labelId: number | null) => void
  onSelectAllLabels: () => void
  onDeselectAllLabels: () => void
}) {
  const allGroupIds = useMemo(() => allGroupIdsForModel(overlayModel), [overlayModel])
  const [selectedLegendGroupIds, setSelectedLegendGroupIds] = useState<string[]>(() => allGroupIds)

  useEffect(() => {
    setSelectedLegendGroupIds(allGroupIds)
  }, [allGroupIds])

  function applySelectedGroups(groupIds: string[]) {
    setSelectedLegendGroupIds(groupIds)
    if (!overlayModel || groupIds.length === 0) {
      onReplaceVisibleLabelIds([])
      return
    }
    if (groupIds.length === allGroupIds.length) {
      onReplaceVisibleLabelIds(allLabelIdsForModel(overlayModel))
      return
    }
    onReplaceVisibleLabelIds(labelIdsForGroupIds(overlayModel, groupIds).sort((left, right) => left - right))
  }

  return (
    <div className="min-w-0 space-y-3 md:col-start-1 md:row-start-2">
      <TriViewTileHeader title="Legend and controls" />
      <div className="flex aspect-square flex-col overflow-hidden rounded-[1rem] border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
        {overlayModel ? (
          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            <div className="space-y-4">
              <label className="inline-flex items-center gap-2 text-[12px] text-[hsl(var(--muted-foreground))]">
                <input
                  checked={showOverlay}
                  className="size-4 accent-[hsl(var(--primary))]"
                  disabled={!overlayModel}
                  onChange={(event) => setShowOverlay(event.target.checked)}
                  type="checkbox"
                />
                <Layers3 className="size-3.5" />
                Structural segmentation visible
              </label>

              <LegendGroupSelector
                onChange={applySelectedGroups}
                overlayModel={overlayModel}
                selectedGroupIds={selectedLegendGroupIds}
              />

              <div className="rounded-[1rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]/30 p-3">
                <LegendSidebar
                  activeGroup={activeGroup}
                  activeLabelId={activeLabelId}
                  expandedGroups={expandedGroups}
                  hideIntro
                  onDeselectAll={() => {
                    setSelectedLegendGroupIds([])
                    onDeselectAllLabels()
                  }}
                  onSelectAll={() => {
                    setSelectedLegendGroupIds(allGroupIds)
                    onSelectAllLabels()
                  }}
                  onSelectGroup={onSelectGroup}
                  onSelectLabel={onSelectLabel}
                  onToggleGroupExpanded={onToggleGroupExpanded}
                  onToggleGroupVisibility={onToggleGroupVisibility}
                  onToggleLabelVisibility={onToggleLabelVisibility}
                  overlayModel={overlayModel}
                  scrollable={false}
                  showBulkControls
                  visibleLabelIds={visibleLabelIds}
                />
              </div>
            </div>
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-dashed border-[hsl(var(--border))] px-4 py-4 text-[12px] leading-6 text-[hsl(var(--muted-foreground))]">
            This study does not currently expose segmentation label metadata for the legend.
          </div>
        )}
      </div>
    </div>
  )
}

function OnDemandTriViewSliceViewer({
  sliceManifest,
  sliceRequest,
  viewerMode,
  showOverlay,
  setShowOverlay,
  overlayModel,
  visibleLabelIds,
  activeLabelId,
  activeGroup,
  expandedGroups,
  onToggleGroupExpanded,
  onToggleGroupVisibility,
  onToggleLabelVisibility,
  onSelectGroup,
  onSelectLabel,
  onSelectAllLabels,
  onDeselectAllLabels,
  onReplaceVisibleLabelIds,
}: {
  sliceManifest: SliceManifest
  sliceRequest: StructuralSliceRequestContext | null
  viewerMode: ViewerMode
  showOverlay: boolean
  setShowOverlay: (value: boolean) => void
  overlayModel: SegmentationOverlayModel | null
  visibleLabelIds: number[]
  activeLabelId: number | null
  activeGroup: string | null
  expandedGroups: string[]
  onToggleGroupExpanded: (groupId: string) => void
  onToggleGroupVisibility: (groupId: string) => void
  onToggleLabelVisibility: (labelId: number) => void
  onSelectGroup: (groupId: string | null) => void
  onSelectLabel: (labelId: number | null) => void
  onSelectAllLabels: () => void
  onDeselectAllLabels: () => void
  onReplaceVisibleLabelIds: (labelIds: number[]) => void
}) {
  const [currentIndices, setCurrentIndices] = useState<Record<ViewerPlane, number>>({
    axial: sliceManifest.planes.axial.default_index,
    coronal: sliceManifest.planes.coronal.default_index,
    sagittal: sliceManifest.planes.sagittal.default_index,
  })
  const [currentSlices, setCurrentSlices] = useState<Partial<Record<ViewerPlane, SliceEntry | null>>>({})
  const [activePlane, setActivePlane] = useState<ViewerPlane>("axial")
  const [draggingPlane, setDraggingPlane] = useState<ViewerPlane | null>(null)
  const [hoveredPlanes, setHoveredPlanes] = useState<Record<ViewerPlane, boolean>>({
    axial: false,
    coronal: false,
    sagittal: false,
  })
  const [pendingPlanes, setPendingPlanes] = useState<Partial<Record<ViewerPlane, boolean>>>({})
  const [loadError, setLoadError] = useState<string | null>(null)
  const cacheRef = useRef(new Map<string, SliceEntry>())
  const requestVersionRef = useRef<Record<ViewerPlane, number>>({ axial: 0, coronal: 0, sagittal: 0 })

  useEffect(() => {
    cacheRef.current.clear()
    setLoadError(null)
    setCurrentSlices({})
    setPendingPlanes({})
    setCurrentIndices({
      axial: sliceManifest.planes.axial.default_index,
      coronal: sliceManifest.planes.coronal.default_index,
      sagittal: sliceManifest.planes.sagittal.default_index,
    })
  }, [sliceManifest, sliceRequest])

  useEffect(() => {
    if (!draggingPlane) {
      return
    }
    const onPointerUp = () => setDraggingPlane(null)
    window.addEventListener("pointerup", onPointerUp)
    return () => window.removeEventListener("pointerup", onPointerUp)
  }, [draggingPlane])

  useEffect(() => {
    if (!sliceRequest) {
      return
    }
    const overlay = sliceManifest.has_overlay
    VIEWER_PLANES.forEach((plane) => {
      const index = clampIndexForPlane(sliceManifest, plane, currentIndices[plane])
      const cacheKey = `${plane}:${index}:${overlay ? "1" : "0"}`
      const cached = cacheRef.current.get(cacheKey)
      if (cached) {
        setCurrentSlices((current) => {
          if (current[plane]?.slice_index === cached.slice_index) {
            return current
          }
          return { ...current, [plane]: cached }
        })
        return
      }

      const version = (requestVersionRef.current[plane] ?? 0) + 1
      requestVersionRef.current[plane] = version
      setPendingPlanes((current) => ({ ...current, [plane]: true }))
      const url = buildStructuralSliceRequestUrl(sliceRequest, plane, index, overlay)
      void fetch(url)
        .then(async (response) => {
          if (!response.ok && overlay) {
            const rawResponse = await fetch(buildStructuralSliceRequestUrl(sliceRequest, plane, index, false))
            if (rawResponse.ok) {
              return (await rawResponse.json()) as SliceEntry
            }
          }
          if (!response.ok) {
            throw new Error(`Failed to load ${plane} slice ${index}.`)
          }
          return (await response.json()) as SliceEntry
        })
        .then((payload) => {
          if (requestVersionRef.current[plane] !== version) {
            return
          }
          cacheRef.current.set(cacheKey, payload)
          setCurrentSlices((current) => ({ ...current, [plane]: payload }))
          setLoadError(null)
        })
        .catch((error) => {
          if (requestVersionRef.current[plane] !== version) {
            return
          }
          setLoadError(error instanceof Error ? error.message : "Failed to load structural slice.")
        })
        .finally(() => {
          if (requestVersionRef.current[plane] !== version) {
            return
          }
          setPendingPlanes((current) => ({ ...current, [plane]: false }))
        })
    })
  }, [currentIndices, sliceManifest, sliceRequest])

  function crosshairForPlane(
    plane: ViewerPlane,
    labels: { left: string; right: string; top: string; bottom: string },
    entry: SliceEntry | null | undefined,
  ) {
    if (plane === "axial") {
      return {
        x: screenFromContentBox({
          start: labels.left,
          end: labels.right,
          fraction: fractionForPlaneIndex(sliceManifest, "sagittal", currentIndices.sagittal),
          entry,
          axis: "x",
        }),
        y: screenFromContentBox({
          start: labels.top,
          end: labels.bottom,
          fraction: fractionForPlaneIndex(sliceManifest, "coronal", currentIndices.coronal),
          entry,
          axis: "y",
        }),
      }
    }
    if (plane === "coronal") {
      return {
        x: screenFromContentBox({
          start: labels.left,
          end: labels.right,
          fraction: fractionForPlaneIndex(sliceManifest, "sagittal", currentIndices.sagittal),
          entry,
          axis: "x",
        }),
        y: screenFromContentBox({
          start: labels.top,
          end: labels.bottom,
          fraction: fractionForPlaneIndex(sliceManifest, "axial", currentIndices.axial),
          entry,
          axis: "y",
        }),
      }
    }
    return {
      x: screenFromContentBox({
        start: labels.left,
        end: labels.right,
        fraction: fractionForPlaneIndex(sliceManifest, "coronal", currentIndices.coronal),
        entry,
        axis: "x",
      }),
      y: screenFromContentBox({
        start: labels.top,
        end: labels.bottom,
        fraction: fractionForPlaneIndex(sliceManifest, "axial", currentIndices.axial),
        entry,
        axis: "y",
      }),
    }
  }

  function indexFromFraction(plane: ViewerPlane, fraction: number) {
    const count = sliceManifest.planes[plane]?.slice_count ?? 1
    return clampIndexForPlane(sliceManifest, plane, Math.round(fraction * Math.max(count - 1, 1)))
  }

  function updateFromPlanePoint(
    plane: ViewerPlane,
    point: { x: number; y: number },
    labels: { left: string; right: string; top: string; bottom: string },
    entry: SliceEntry | null | undefined,
  ) {
    const horizontalFraction = fractionFromContentBox({
      start: labels.left,
      end: labels.right,
      value: point.x,
      entry,
      axis: "x",
    })
    const verticalFraction = fractionFromContentBox({
      start: labels.top,
      end: labels.bottom,
      value: point.y,
      entry,
      axis: "y",
    })
    setCurrentIndices((current) => {
      if (plane === "axial") {
        return {
          ...current,
          sagittal: indexFromFraction("sagittal", horizontalFraction),
          coronal: indexFromFraction("coronal", verticalFraction),
        }
      }
      if (plane === "coronal") {
        return {
          ...current,
          sagittal: indexFromFraction("sagittal", horizontalFraction),
          axial: indexFromFraction("axial", verticalFraction),
        }
      }
      return {
        ...current,
        coronal: indexFromFraction("coronal", horizontalFraction),
        axial: indexFromFraction("axial", verticalFraction),
      }
    })
  }

  function updateFromPointerEvent(
    plane: ViewerPlane,
    event: Pick<PointerEvent | React.PointerEvent<HTMLDivElement>, "clientX" | "clientY">,
    element: HTMLDivElement,
    labels: { left: string; right: string; top: string; bottom: string },
    entry: SliceEntry | null | undefined,
  ) {
    const rect = element.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) {
      return
    }
    updateFromPlanePoint(
      plane,
      {
        x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
        y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
      },
      labels,
      entry,
    )
  }

  function nudgePlaneSlice(plane: ViewerPlane, direction: -1 | 1) {
    setCurrentIndices((current) => ({
      ...current,
      [plane]: clampIndexForPlane(sliceManifest, plane, current[plane] + direction),
    }))
  }
  const handlePlaneWheel = usePlaneWheelNavigator(nudgePlaneSlice)

  const triViewPanels: Array<{ plane: ViewerPlane; layoutClassName: string }> = [
    { plane: "axial", layoutClassName: "md:col-start-1 md:row-start-1" },
    { plane: "sagittal", layoutClassName: "md:col-start-2 md:row-start-1" },
    { plane: "coronal", layoutClassName: "md:col-start-2 md:row-start-2" },
  ]

  return (
    <div className="space-y-4">
      {loadError ? (
        <div className="rounded-xl border border-red-400/35 bg-red-500/10 px-4 py-3 text-[13px] text-red-100">
          {loadError}
        </div>
      ) : null}
      <div className="grid gap-4 md:grid-cols-2">
        {triViewPanels.map(({ plane, layoutClassName }) => {
          const current = currentSlices[plane] ?? null
          const orientationLabels = current?.orientation_labels ?? DEFAULT_ORIENTATION_LABELS[plane]
          const crosshair = crosshairForPlane(plane, orientationLabels, current)
          return (
            <div className={cn("min-w-0 space-y-3", layoutClassName)} key={plane}>
              <TriViewTileHeader
                meta={`Slice ${currentIndices[plane] + 1} / ${sliceManifest.planes[plane].slice_count}`}
                title={plane}
              />
              <div
                className={cn(
                  "relative aspect-square cursor-crosshair overflow-hidden rounded-[1rem] border bg-black transition-colors",
                  "overscroll-contain",
                  activePlane === plane
                    ? "border-[hsl(var(--primary))] shadow-[0_0_0_1px_hsl(var(--primary)/0.45)]"
                    : "border-[hsl(var(--border))]",
                )}
                onPointerDown={(event) => {
                  setActivePlane(plane)
                  setDraggingPlane(plane)
                  updateFromPointerEvent(plane, event, event.currentTarget, orientationLabels, current)
                }}
                onPointerMove={(event) => {
                  if (draggingPlane !== plane) {
                    return
                  }
                  updateFromPointerEvent(plane, event, event.currentTarget, orientationLabels, current)
                }}
                onMouseEnter={() => setHoveredPlanes((current) => ({ ...current, [plane]: true }))}
                onMouseLeave={() => setHoveredPlanes((current) => ({ ...current, [plane]: false }))}
                onWheel={(event) => handlePlaneWheel(plane, hoveredPlanes[plane], event)}
              >
                {current ? (
                  <SliceViewportMedia entry={current}>
                    {({ box, media }) => (
                      <div className="absolute overflow-hidden rounded-[0.85rem]" style={box}>
                        {showOverlay && current.label_map_base64 && overlayModel ? (
                          <RenderedSliceCanvas
                            activeGroup={activeGroup}
                            activeLabelId={activeLabelId}
                            className="absolute"
                            entry={current}
                            overlayModel={overlayModel}
                            showOverlay={showOverlay}
                            style={media}
                            viewerMode={viewerMode}
                            visibleLabelIds={visibleLabelIds}
                          />
                        ) : showOverlay && current.overlay_base64 ? (
                          <img
                            alt={`${plane} overlay slice`}
                            className="absolute block max-h-none max-w-none"
                            src={`data:image/png;base64,${current.overlay_base64}`}
                            style={media}
                          />
                        ) : (
                          <img
                            alt={`${plane} slice`}
                            className="absolute block max-h-none max-w-none"
                            src={`data:image/png;base64,${current.image_base64}`}
                            style={media}
                          />
                        )}
                      </div>
                    )}
                  </SliceViewportMedia>
                ) : null}
                {pendingPlanes[plane] ? (
                  <div className="absolute right-2 top-2 rounded-full bg-black/70 px-2 py-1 text-[10px] uppercase tracking-[0.12em] text-white/70">
                    loading
                  </div>
                ) : null}
                <div className="pointer-events-none absolute bottom-2 right-2 rounded-full bg-black/72 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.12em] text-white/80">
                  Slice {currentIndices[plane] + 1} / {sliceManifest.planes[plane].slice_count}
                </div>
                <div className="pointer-events-none absolute inset-0">
                  <div
                    className="absolute top-0 h-full w-px bg-[#6aa9ff]/80 shadow-[0_0_0_1px_rgba(16,24,40,0.25)]"
                    style={{ left: `${crosshair.x * 100}%`, transform: "translateX(-0.5px)" }}
                  />
                  <div
                    className="absolute left-0 h-px w-full bg-[#6aa9ff]/80 shadow-[0_0_0_1px_rgba(16,24,40,0.25)]"
                    style={{ top: `${crosshair.y * 100}%`, transform: "translateY(-0.5px)" }}
                  />
                  <div
                    className="absolute h-3.5 w-3.5 rounded-full border border-[#c7ddff]/80 bg-[#6aa9ff]/20"
                    style={{
                      left: `${crosshair.x * 100}%`,
                      top: `${crosshair.y * 100}%`,
                      transform: "translate(-50%, -50%)",
                    }}
                  />
                </div>
                <OrientationOverlay labels={orientationLabels} />
              </div>
            </div>
          )
        })}

        <TriViewLegendTile
          key={allGroupIdsForModel(overlayModel).join("|") || "legend-empty"}
          activeGroup={activeGroup}
          activeLabelId={activeLabelId}
          activePlane={activePlane}
          expandedGroups={expandedGroups}
          onDeselectAllLabels={onDeselectAllLabels}
          onReplaceVisibleLabelIds={onReplaceVisibleLabelIds}
          onSelectAllLabels={onSelectAllLabels}
          onSelectGroup={onSelectGroup}
          onSelectLabel={onSelectLabel}
          onToggleGroupExpanded={onToggleGroupExpanded}
          onToggleGroupVisibility={onToggleGroupVisibility}
          onToggleLabelVisibility={onToggleLabelVisibility}
          overlayModel={overlayModel}
          setShowOverlay={setShowOverlay}
          showOverlay={showOverlay}
          visibleLabelIds={visibleLabelIds}
        />
      </div>
    </div>
  )
}

function TriViewSliceViewer({
  slices,
  overlaySlices,
  viewerMode,
  showOverlay,
  setShowOverlay,
  overlayModel,
  visibleLabelIds,
  activeLabelId,
  activeGroup,
  expandedGroups,
  onToggleGroupExpanded,
  onToggleGroupVisibility,
  onToggleLabelVisibility,
  onSelectGroup,
  onSelectLabel,
  onSelectAllLabels,
  onDeselectAllLabels,
  onReplaceVisibleLabelIds,
}: {
  slices: SlicePlaneSet | null
  overlaySlices: SlicePlaneSet | null
  viewerMode: ViewerMode
  showOverlay: boolean
  setShowOverlay: (value: boolean) => void
  overlayModel: SegmentationOverlayModel | null
  visibleLabelIds: number[]
  activeLabelId: number | null
  activeGroup: string | null
  expandedGroups: string[]
  onToggleGroupExpanded: (groupId: string) => void
  onToggleGroupVisibility: (groupId: string) => void
  onToggleLabelVisibility: (labelId: number) => void
  onSelectGroup: (groupId: string | null) => void
  onSelectLabel: (labelId: number | null) => void
  onSelectAllLabels: () => void
  onDeselectAllLabels: () => void
  onReplaceVisibleLabelIds: (labelIds: number[]) => void
}) {
  const [linkedPosition, setLinkedPosition] = useState<Record<ViewerPlane, number>>({
    axial: 0.5,
    coronal: 0.5,
    sagittal: 0.5,
  })
  const [activePlane, setActivePlane] = useState<ViewerPlane>("axial")
  const [draggingPlane, setDraggingPlane] = useState<ViewerPlane | null>(null)
  const [hoveredPlanes, setHoveredPlanes] = useState<Record<ViewerPlane, boolean>>({
    axial: false,
    coronal: false,
    sagittal: false,
  })

  const planeData = useMemo(
    () =>
      VIEWER_PLANES.map((plane) => {
        const planeSlices = slices?.[plane] ?? []
        const planeOverlaySlices = overlaySlices?.[plane] ?? []
        const activeSlices = showOverlay && planeOverlaySlices.length ? planeOverlaySlices : planeSlices
        const activeIndex = nearestSliceIndex(activeSlices, linkedPosition[plane])
        const current = activeSlices[activeIndex] ?? null
        return {
          plane,
          activeSlices,
          current,
          activeIndex,
          orientationLabels: current?.orientation_labels ?? DEFAULT_ORIENTATION_LABELS[plane],
        }
      }),
    [linkedPosition, overlaySlices, showOverlay, slices],
  )

  useEffect(() => {
      setLinkedPosition((current) => {
      const next = { ...current }
      let changed = false
      for (const plane of VIEWER_PLANES) {
        const activeSlices =
          showOverlay && (overlaySlices?.[plane] ?? []).length ? overlaySlices?.[plane] ?? [] : slices?.[plane] ?? []
        if (!activeSlices.length) {
          continue
        }
        const nearest = activeSlices[nearestSliceIndex(activeSlices, current[plane])]
        const fraction = nearest?.slice_fraction ?? current[plane]
        if (Math.abs(fraction - current[plane]) > 0.001) {
          next[plane] = fraction
          changed = true
        }
      }
      return changed ? next : current
    })
  }, [overlaySlices, showOverlay, slices])

  function crosshairForPlane(
    plane: ViewerPlane,
    labels: { left: string; right: string; top: string; bottom: string },
    entry: SliceEntry | null | undefined,
  ) {
    if (plane === "axial") {
      return {
        x: screenFromContentBox({
          start: labels.left,
          end: labels.right,
          fraction: linkedPosition.sagittal,
          entry,
          axis: "x",
        }),
        y: screenFromContentBox({
          start: labels.top,
          end: labels.bottom,
          fraction: linkedPosition.coronal,
          entry,
          axis: "y",
        }),
      }
    }
    if (plane === "coronal") {
      return {
        x: screenFromContentBox({
          start: labels.left,
          end: labels.right,
          fraction: linkedPosition.sagittal,
          entry,
          axis: "x",
        }),
        y: screenFromContentBox({
          start: labels.top,
          end: labels.bottom,
          fraction: linkedPosition.axial,
          entry,
          axis: "y",
        }),
      }
    }
    return {
      x: screenFromContentBox({
        start: labels.left,
        end: labels.right,
        fraction: linkedPosition.coronal,
        entry,
        axis: "x",
      }),
      y: screenFromContentBox({
        start: labels.top,
        end: labels.bottom,
        fraction: linkedPosition.axial,
        entry,
        axis: "y",
      }),
    }
  }

  function updateFromPlaneClick(
    plane: ViewerPlane,
    point: { x: number; y: number },
    labels: { left: string; right: string; top: string; bottom: string },
    entry: SliceEntry | null | undefined,
  ) {
    const horizontalFraction = fractionFromContentBox({
      start: labels.left,
      end: labels.right,
      value: point.x,
      entry,
      axis: "x",
    })
    const verticalFraction = fractionFromContentBox({
      start: labels.top,
      end: labels.bottom,
      value: point.y,
      entry,
      axis: "y",
    })
    setLinkedPosition((current) => {
      if (plane === "axial") {
        return {
          ...current,
          sagittal: horizontalFraction,
          coronal: verticalFraction,
        }
      }
      if (plane === "coronal") {
        return {
          ...current,
          sagittal: horizontalFraction,
          axial: verticalFraction,
        }
      }
      return {
        ...current,
        coronal: horizontalFraction,
        axial: verticalFraction,
      }
    })
  }

  function updateFromPointerEvent(
    plane: ViewerPlane,
    event: Pick<PointerEvent | React.PointerEvent<HTMLDivElement>, "clientX" | "clientY">,
    element: HTMLDivElement,
    labels: { left: string; right: string; top: string; bottom: string },
    entry: SliceEntry | null | undefined,
  ) {
    const rect = element.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) {
      return
    }
    updateFromPlaneClick(
      plane,
      {
        x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
        y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
      },
      labels,
      entry,
    )
  }

  function nudgePlaneSlice(plane: ViewerPlane, direction: -1 | 1) {
    const activeSlices =
      showOverlay && (overlaySlices?.[plane] ?? []).length ? overlaySlices?.[plane] ?? [] : slices?.[plane] ?? []
    if (!activeSlices.length) {
      return
    }
    const currentIndex = nearestSliceIndex(activeSlices, linkedPosition[plane])
    const nextIndex = Math.min(activeSlices.length - 1, Math.max(0, currentIndex + direction))
    const nextSlice = activeSlices[nextIndex]
    if (!nextSlice) {
      return
    }
    setLinkedPosition((current) => ({
      ...current,
      [plane]: nextSlice.slice_fraction ?? current[plane],
    }))
  }
  const handlePlaneWheel = usePlaneWheelNavigator(nudgePlaneSlice)

  const triViewPanels: Array<{ plane: ViewerPlane; layoutClassName: string }> = [
    { plane: "axial", layoutClassName: "md:col-start-1 md:row-start-1" },
    { plane: "sagittal", layoutClassName: "md:col-start-2 md:row-start-1" },
    { plane: "coronal", layoutClassName: "md:col-start-2 md:row-start-2" },
  ]

  useEffect(() => {
    if (!draggingPlane) {
      return
    }

    const onPointerUp = () => setDraggingPlane(null)
    window.addEventListener("pointerup", onPointerUp)
    return () => {
      window.removeEventListener("pointerup", onPointerUp)
    }
  }, [draggingPlane])

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        {triViewPanels.map(({ plane, layoutClassName }) => {
          const planeState = planeData.find((candidate) => candidate.plane === plane)
          const current = planeState?.current ?? null
          const orientationLabels = planeState?.orientationLabels ?? DEFAULT_ORIENTATION_LABELS[plane]
          const crosshair = crosshairForPlane(plane, orientationLabels, current)

          return (
            <div className={cn("min-w-0 space-y-3", layoutClassName)} key={plane}>
              <TriViewTileHeader
                meta={current ? `Slice ${planeState ? planeState.activeIndex + 1 : 0} / ${planeState?.activeSlices.length ?? 0}` : "No slice available"}
                title={plane}
              />
              {current ? (
                <div
                  className={cn(
                    "relative aspect-square cursor-crosshair overflow-hidden rounded-[1rem] border bg-black transition-colors",
                    "overscroll-contain",
                    activePlane === plane
                      ? "border-[hsl(var(--primary))] shadow-[0_0_0_1px_hsl(var(--primary)/0.45)]"
                      : "border-[hsl(var(--border))]",
                  )}
                  onMouseEnter={() => setHoveredPlanes((currentHover) => ({ ...currentHover, [plane]: true }))}
                  onMouseLeave={() => setHoveredPlanes((currentHover) => ({ ...currentHover, [plane]: false }))}
                  onPointerDown={(event) => {
                    setActivePlane(plane)
                    setDraggingPlane(plane)
                    updateFromPointerEvent(plane, event, event.currentTarget, orientationLabels, current)
                  }}
                  onPointerMove={(event) => {
                    if (draggingPlane !== plane) {
                      return
                    }
                    updateFromPointerEvent(plane, event, event.currentTarget, orientationLabels, current)
                  }}
                  onWheel={(event) => handlePlaneWheel(plane, hoveredPlanes[plane], event)}
                >
                  <SliceViewportMedia entry={current}>
                    {({ box, media }) => (
                      <div className="absolute overflow-hidden rounded-[0.85rem]" style={box}>
                        {showOverlay && current.label_map_base64 && overlayModel ? (
                          <RenderedSliceCanvas
                            activeGroup={activeGroup}
                            activeLabelId={activeLabelId}
                            className="absolute"
                            entry={current}
                            overlayModel={overlayModel}
                            showOverlay={showOverlay}
                            style={media}
                            viewerMode={viewerMode}
                            visibleLabelIds={visibleLabelIds}
                          />
                        ) : showOverlay && current.overlay_base64 ? (
                          <img
                            alt={`${plane} overlay slice`}
                            className="absolute block max-h-none max-w-none"
                            src={`data:image/png;base64,${current.overlay_base64}`}
                            style={media}
                          />
                        ) : (
                          <img
                            alt={`${plane} slice`}
                            className="absolute block max-h-none max-w-none"
                            src={`data:image/png;base64,${current.image_base64}`}
                            style={media}
                          />
                        )}
                      </div>
                    )}
                  </SliceViewportMedia>
                  <div className="pointer-events-none absolute inset-0">
                    <div
                      className="absolute top-0 h-full w-px bg-[#6aa9ff]/80 shadow-[0_0_0_1px_rgba(16,24,40,0.25)]"
                      style={{ left: `${crosshair.x * 100}%`, transform: "translateX(-0.5px)" }}
                    />
                    <div
                      className="absolute left-0 h-px w-full bg-[#6aa9ff]/80 shadow-[0_0_0_1px_rgba(16,24,40,0.25)]"
                      style={{ top: `${crosshair.y * 100}%`, transform: "translateY(-0.5px)" }}
                    />
                    <div
                      className="absolute h-3.5 w-3.5 rounded-full border border-[#c7ddff]/80 bg-[#6aa9ff]/20"
                      style={{
                        left: `${crosshair.x * 100}%`,
                        top: `${crosshair.y * 100}%`,
                        transform: "translate(-50%, -50%)",
                      }}
                    />
                  </div>
                  <div className="pointer-events-none absolute bottom-2 right-2 rounded-full bg-black/72 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.12em] text-white/80">
                    Slice {planeState ? planeState.activeIndex + 1 : 0} / {planeState?.activeSlices.length ?? 0}
                  </div>
                  <OrientationOverlay labels={orientationLabels} />
                </div>
              ) : (
                <div className="flex aspect-square items-center justify-center rounded-[1rem] border border-[hsl(var(--border))] bg-black text-[13px] text-white/60">
                  No {plane} slice available.
                </div>
              )}
            </div>
          )
        })}

        <TriViewLegendTile
          key={allGroupIdsForModel(overlayModel).join("|") || "legend-empty"}
          activeGroup={activeGroup}
          activeLabelId={activeLabelId}
          activePlane={activePlane}
          expandedGroups={expandedGroups}
          onDeselectAllLabels={onDeselectAllLabels}
          onReplaceVisibleLabelIds={onReplaceVisibleLabelIds}
          onSelectAllLabels={onSelectAllLabels}
          onSelectGroup={onSelectGroup}
          onSelectLabel={onSelectLabel}
          onToggleGroupExpanded={onToggleGroupExpanded}
          onToggleGroupVisibility={onToggleGroupVisibility}
          onToggleLabelVisibility={onToggleLabelVisibility}
          overlayModel={overlayModel}
          setShowOverlay={setShowOverlay}
          showOverlay={showOverlay}
          visibleLabelIds={visibleLabelIds}
        />
      </div>
    </div>
  )
}

function OhifEmbed({
  viewerAssets,
}: {
  viewerAssets: ViewerAssets
}) {
  if (viewerAssets.ohif_url) {
    return (
      <iframe
        className="h-[38rem] w-full rounded-[1rem] border border-[hsl(var(--border))] bg-black"
        src={viewerAssets.ohif_url}
        title="OHIF viewer"
      />
    )
  }

  return (
    <div className="flex h-[38rem] flex-col items-center justify-center gap-3 rounded-[1rem] border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--background))] px-6 text-center">
      <div className="text-[16px] font-medium text-[hsl(var(--foreground))]">OHIF embed is ready for DICOMweb cases</div>
      <div className="max-w-xl text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
        This case resolved to the `dicomweb` viewer path, but no `CLINAGENT_OHIF_BASE_URL` is configured yet.
        Once an OHIF deployment is available, the workspace will embed it here without leaving the report flow.
      </div>
    </div>
  )
}

export function HybridImagingViewer({
  viewerAssets,
  slices,
  overlaySlices,
  sliceManifest,
  sliceRequest,
  showOverlay,
  setShowOverlay,
  overlayModel,
  viewerMode,
  setViewerMode,
  visibleLabelIds,
  activeLabelId,
  activeGroup,
  expandedGroups,
  onToggleGroupExpanded,
  onToggleGroupVisibility,
  onToggleLabelVisibility,
  onSelectGroup,
  onSelectLabel,
  onSelectAllLabels,
  onDeselectAllLabels,
  onReplaceVisibleLabelIds,
  preferTriView,
  segmentationLabelSourceLabel,
  segmentationLabelMappingPath,
}: {
  viewerAssets: ViewerAssets | null
  slices: SlicePlaneSet | null
  overlaySlices: SlicePlaneSet | null
  sliceManifest?: SliceManifest | null
  sliceRequest?: StructuralSliceRequestContext | null
  showOverlay: boolean
  setShowOverlay: (value: boolean) => void
  overlayModel?: SegmentationOverlayModel | null
  viewerMode: ViewerMode
  setViewerMode: (mode: ViewerMode) => void
  visibleLabelIds: number[]
  activeLabelId: number | null
  activeGroup: string | null
  expandedGroups: string[]
  onToggleGroupExpanded: (groupId: string) => void
  onToggleGroupVisibility: (groupId: string) => void
  onToggleLabelVisibility: (labelId: number) => void
  onSelectGroup: (groupId: string | null) => void
  onSelectLabel: (labelId: number | null) => void
  onSelectAllLabels: () => void
  onDeselectAllLabels: () => void
  onReplaceVisibleLabelIds: (labelIds: number[]) => void
  preferTriView?: boolean
  segmentationLabelSourceLabel?: string | null
  segmentationLabelMappingPath?: string | null
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const viewerRef = useRef<Niivue | null>(null)
  const mountedRef = useRef(false)
  const [plane, setPlane] = useState<ViewerPlane>("axial")
  const [loadError, setLoadError] = useState<string | null>(null)
  const [cornerstoneError, setCornerstoneError] = useState<string | null>(null)
  const [viewerReady, setViewerReady] = useState(0)
  const orientationLabels = DEFAULT_ORIENTATION_LABELS[plane]
  const niivueLabelLut = useMemo(
    () =>
      buildNiivueLabelLut({
        overlayModel: overlayModel ?? null,
        visibleLabelIds,
        activeLabelId,
        activeGroup,
        viewerMode,
      }),
    [activeGroup, activeLabelId, overlayModel, viewerMode, visibleLabelIds],
  )
  const fallbackNiivueLabelLut = useMemo(
    () =>
      !niivueLabelLut && viewerAssets?.has_segmentation
        ? buildFallbackNiivueLabelLut({ viewerMode })
        : null,
    [niivueLabelLut, viewerAssets?.has_segmentation, viewerMode],
  )
  const hasLegend = Boolean(overlayModel?.groups.length && viewerAssets?.has_segmentation)
  const imageId = viewerAssets?.series_uid ?? viewerAssets?.study_uid ?? null
  const showTriView =
    Boolean(
      preferTriView &&
        ((sliceManifest?.mode === "on_demand" && sliceRequest) ||
          (slices && VIEWER_PLANES.some((candidate) => (slices[candidate] ?? []).length > 0))),
    )
  const preferCornerstoneStructural = Boolean(
    USE_EXPERIMENTAL_CORNERSTONE_STRUCTURAL_VIEWER &&
      preferTriView &&
      overlayModel &&
      viewerAssets?.image_asset_url &&
      viewerAssets?.segmentation_asset_url &&
      (viewerAssets.viewer_type === "cornerstone_structural" || viewerAssets.viewer_type === "nifti"),
  )

  useEffect(() => {
    const candidate = viewerAssets?.default_plane
    if (candidate === "axial" || candidate === "coronal" || candidate === "sagittal") {
      setPlane(candidate)
    }
  }, [viewerAssets?.default_plane])

  useEffect(() => {
    setCornerstoneError(null)
  }, [viewerAssets?.image_asset_url, viewerAssets?.segmentation_asset_url, preferTriView])

  useEffect(() => {
    if (!viewerAssets || viewerAssets.viewer_type !== "nifti" || !viewerAssets.image_asset_url || !canvasRef.current) {
      return
    }

    async function attach() {
      try {
        if (viewerRef.current) {
          return
        }
        const viewer = new Niivue(DEFAULT_VIEWER_OPTIONS)
        await viewer.attachToCanvas(canvasRef.current as HTMLCanvasElement)
        if (typeof viewer.setRadiologicalConvention === "function") {
          viewer.setRadiologicalConvention(true)
        }
        if (typeof viewer.setInterpolation === "function") {
          viewer.setInterpolation(true)
        }
        viewerRef.current = viewer
        if (mountedRef.current) {
          setViewerReady((current) => current + 1)
          setLoadError(null)
        }
      } catch (error) {
        viewerRef.current = null
        if (mountedRef.current) {
          setLoadError(error instanceof Error ? error.message : "Viewer failed to load.")
        }
      }
    }

    void attach()
  }, [viewerAssets?.viewer_type, viewerAssets?.image_asset_url])

  useEffect(() => {
    if (!viewerAssets || viewerAssets.viewer_type !== "nifti" || !viewerAssets.image_asset_url) {
      return
    }
    const viewer = viewerRef.current
    if (!viewer) {
      return
    }
    const assets = viewerAssets

    let cancelled = false

    async function loadVolumes() {
      try {
        const activeViewer = viewer as Niivue
        const volumes: LoadVolumeOption[] = [
          {
            url: assets.image_asset_url as string,
            opacity: showOverlay && viewerMode === "mask" ? 0.08 : 1,
          },
        ]
        if (showOverlay && assets.segmentation_asset_url) {
          const labelLut = niivueLabelLut ?? fallbackNiivueLabelLut
          volumes.push(
            labelLut
              ? {
                  url: assets.segmentation_asset_url,
                  opacity: viewerMode === "mask" ? 1 : viewerMode === "contour" ? 0.06 : 0.72,
                  cal_min: 0,
                  cal_max: labelLut.max ?? 0,
                  alphaThreshold: true,
                  colormapLabel: labelLut,
                }
              : {
                  url: assets.segmentation_asset_url,
                  opacity: 0.35,
                  colormap: "red",
                  cal_min: 0.5,
                  cal_max: 1.5,
                },
          )
        }
        await activeViewer.loadVolumes(volumes)
        activeViewer.setDefaults(DEFAULT_VIEWER_OPTIONS, false)
        activeViewer.setSliceType(SLICE_TYPE_BY_PLANE[plane])
        if (typeof activeViewer.setAtlasOutline === "function") {
          activeViewer.setAtlasOutline(showOverlay && viewerMode === "contour" ? 1 : 0)
        }
        if (!cancelled && mountedRef.current) {
          setLoadError(null)
        }
      } catch (error) {
        if (!cancelled && mountedRef.current) {
          setLoadError(error instanceof Error ? error.message : "Viewer failed to load.")
        }
      }
    }

    void loadVolumes()
    return () => {
      cancelled = true
    }
  }, [
    activeGroup,
    activeLabelId,
    niivueLabelLut,
    fallbackNiivueLabelLut,
    plane,
    showOverlay,
    viewerAssets?.image_asset_url,
    viewerAssets?.segmentation_asset_url,
    viewerAssets?.viewer_type,
    viewerMode,
    viewerReady,
    visibleLabelIds,
  ])

  useEffect(() => {
    const viewer = viewerRef.current
    if (!viewer || !viewerAssets || viewerAssets.viewer_type !== "nifti") {
      return
    }
    viewer.setDefaults(DEFAULT_VIEWER_OPTIONS, false)
    viewer.setSliceType(SLICE_TYPE_BY_PLANE[plane])
  }, [plane, viewerAssets?.viewer_type])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      viewerRef.current = null
    }
  }, [])

  return (
    <div className="min-w-0 rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[hsl(var(--border)/0.7)] px-5 py-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-[hsl(var(--muted-foreground))]">Viewer</div>
          <div className="mt-1 text-[16px] font-medium text-[hsl(var(--foreground))]">Imaging workspace</div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--border))] px-2.5 py-1">
            <ScanEye className="size-3.5" />
            {viewerAssets?.viewer_type ?? "png_fallback"}
          </span>
          {imageId ? (
            <span
              className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[hsl(var(--border))] px-2.5 py-1"
              title={imageId}
            >
              <span className="shrink-0">Image ID</span>
              <span className="max-w-48 truncate text-[hsl(var(--foreground))]">{imageId}</span>
            </span>
          ) : null}
          {segmentationLabelSourceLabel ? (
            <span
              className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--border))] px-2.5 py-1"
              title={segmentationLabelMappingPath ?? undefined}
            >
              <Layers3 className="size-3.5" />
              {segmentationLabelSourceLabel}
            </span>
          ) : null}
          <span className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--border))] px-2.5 py-1">
            <Move className="size-3.5" />
            {showTriView ? "Hover wheel slice" : "Pan + scroll"}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--border))] px-2.5 py-1">
            <Expand className="size-3.5" />
            {showTriView ? "Linked crosshair" : "Wheel zoom"}
          </span>
        </div>
      </div>
      <div className="space-y-4 px-5 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2">
            {showTriView ? (
              <span className="rounded-full border border-[hsl(var(--primary)/0.25)] bg-[hsl(var(--primary)/0.08)] px-3 py-1.5 text-[12px] text-[hsl(var(--foreground))]">
                Tri-view structural layout
              </span>
            ) : (
              VIEWER_PLANES.map((item) => (
                <button
                  className={cn(
                    "rounded-full px-3 py-1.5 text-[12px] transition-colors",
                    plane === item
                      ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                      : "border border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]",
                  )}
                  key={item}
                  onClick={() => setPlane(item)}
                  type="button"
                >
                  {item}
                </button>
              ))
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {!showTriView ? (
              <label className="inline-flex items-center gap-2 text-[12px] text-[hsl(var(--muted-foreground))]">
                <input
                  checked={showOverlay}
                  className="size-4 accent-[hsl(var(--primary))]"
                  disabled={!viewerAssets?.has_segmentation}
                  onChange={(event) => setShowOverlay(event.target.checked)}
                  type="checkbox"
                />
                <Layers3 className="size-3.5" />
                Structural segmentation
              </label>
            ) : null}
            {viewerAssets?.has_segmentation ? (
              <div className="flex flex-wrap gap-2">
                {VIEWER_MODES.map((mode) => (
                  <button
                    className={cn(
                      "rounded-full px-3 py-1.5 text-[11px] transition-colors",
                      viewerMode === mode
                        ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                        : "border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]",
                    )}
                    key={mode}
                    onClick={() => setViewerMode(mode)}
                    type="button"
                  >
                    {mode}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </div>

        {viewerAssets?.has_segmentation ? <ModeExplainer /> : null}

        {showTriView ? (
          <div className="space-y-4">
            {preferCornerstoneStructural && !cornerstoneError ? (
              <CornerstoneStructuralViewer
                activeGroup={activeGroup}
                activeLabelId={activeLabelId}
                expandedGroups={expandedGroups}
                imageAssetUrl={viewerAssets?.image_asset_url as string}
                onInitializationError={(message) => {
                  setCornerstoneError(message)
                  setLoadError((current) => current ?? `Cornerstone structural viewer fell back: ${message}`)
                }}
                onSelectGroup={onSelectGroup}
                onSelectLabel={onSelectLabel}
                onToggleGroupExpanded={onToggleGroupExpanded}
                onToggleGroupVisibility={onToggleGroupVisibility}
                onToggleLabelVisibility={onToggleLabelVisibility}
                overlayModel={overlayModel ?? null}
                segmentationAssetUrl={viewerAssets?.segmentation_asset_url ?? null}
                setShowOverlay={setShowOverlay}
                setViewerMode={setViewerMode}
                showOverlay={showOverlay}
                viewerMode={viewerMode}
                visibleLabelIds={visibleLabelIds}
              />
            ) : (
              <>
                {preferCornerstoneStructural && cornerstoneError ? (
                  <div className="rounded-xl border border-amber-400/40 bg-amber-500/10 px-4 py-3 text-[13px] leading-6 text-amber-100">
                    Structural linked viewer is temporarily unavailable. Falling back to the slice-based tri-view so the study remains readable.
                  </div>
                ) : null}
                {sliceManifest?.mode === "on_demand" && sliceRequest ? (
                  <OnDemandTriViewSliceViewer
                    activeGroup={activeGroup}
                    activeLabelId={activeLabelId}
                    expandedGroups={expandedGroups}
                    onSelectGroup={onSelectGroup}
                    onSelectLabel={onSelectLabel}
                    onToggleGroupExpanded={onToggleGroupExpanded}
                    onToggleGroupVisibility={onToggleGroupVisibility}
                    onToggleLabelVisibility={onToggleLabelVisibility}
                    overlayModel={overlayModel ?? null}
                    showOverlay={showOverlay}
                    setShowOverlay={setShowOverlay}
                    sliceManifest={sliceManifest}
                    sliceRequest={sliceRequest}
                    viewerMode={viewerMode}
                    visibleLabelIds={visibleLabelIds}
                    onSelectAllLabels={onSelectAllLabels}
                    onDeselectAllLabels={onDeselectAllLabels}
                    onReplaceVisibleLabelIds={onReplaceVisibleLabelIds}
                  />
                ) : (
                  <TriViewSliceViewer
                    activeGroup={activeGroup}
                    activeLabelId={activeLabelId}
                    expandedGroups={expandedGroups}
                    onSelectGroup={onSelectGroup}
                    onSelectLabel={onSelectLabel}
                    onToggleGroupExpanded={onToggleGroupExpanded}
                    onToggleGroupVisibility={onToggleGroupVisibility}
                    onToggleLabelVisibility={onToggleLabelVisibility}
                    overlayModel={overlayModel ?? null}
                    overlaySlices={overlaySlices}
                    showOverlay={showOverlay}
                    setShowOverlay={setShowOverlay}
                    slices={slices}
                    viewerMode={viewerMode}
                    visibleLabelIds={visibleLabelIds}
                    onSelectAllLabels={onSelectAllLabels}
                    onDeselectAllLabels={onDeselectAllLabels}
                    onReplaceVisibleLabelIds={onReplaceVisibleLabelIds}
                  />
                )}
              </>
            )}
          </div>
        ) : (
          <div className={cn("grid gap-4", hasLegend ? "xl:grid-cols-[minmax(0,1fr)_18rem]" : "grid-cols-1")}>
            <div className="min-w-0">
              {viewerAssets?.viewer_type === "dicomweb" ? (
                <OhifEmbed viewerAssets={viewerAssets} />
              ) : viewerAssets?.viewer_type === "nifti" && viewerAssets.image_asset_url && !loadError ? (
                <div className="relative mx-auto w-full max-w-[52rem] overflow-hidden rounded-[1rem] border border-[hsl(var(--border))] bg-black">
                  <canvas className="mx-auto block h-[30rem] w-full max-w-full" ref={canvasRef} />
                  <OrientationOverlay labels={orientationLabels} />
                </div>
              ) : (
                <PngSliceFallbackViewer
                  activeGroup={activeGroup}
                  activeLabelId={activeLabelId}
                  overlayModel={overlayModel ?? null}
                  overlaySlices={overlaySlices}
                  plane={plane}
                  showOverlay={showOverlay}
                  slices={slices}
                  viewerMode={viewerMode}
                  visibleLabelIds={visibleLabelIds}
                />
              )}
            </div>

            {hasLegend && overlayModel ? (
              <LegendSidebar
                activeGroup={activeGroup}
                activeLabelId={activeLabelId}
                expandedGroups={expandedGroups}
                onSelectGroup={onSelectGroup}
                onSelectLabel={onSelectLabel}
                onToggleGroupExpanded={onToggleGroupExpanded}
                onToggleGroupVisibility={onToggleGroupVisibility}
                onToggleLabelVisibility={onToggleLabelVisibility}
                overlayModel={overlayModel}
                visibleLabelIds={visibleLabelIds}
              />
            ) : null}
          </div>
        )}

        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-4 py-3 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
          {loadError
            ? `The interactive viewer fell back to slice previews: ${loadError}`
            : showTriView
              ? `Tri-view structural segmentation is shown in ${viewerMode} mode with ${viewerAssets?.orientation_policy ?? "radiological"} orientation. Hover any panel to scroll that plane, and each panel uses the true label map when overlay slices are available.`
              : `Use the mouse wheel to zoom, drag to pan, and switch planes without leaving the report workspace. Structural segmentation is shown in ${viewerMode} mode with ${viewerAssets?.orientation_policy ?? "radiological"} orientation.`}
        </div>
      </div>
    </div>
  )
}
