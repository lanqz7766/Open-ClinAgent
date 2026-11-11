import type { ReactNode } from "react"
import { useEffect, useEffectEvent, useId, useMemo, useRef, useState } from "react"
import { ChevronDown, Layers3, LoaderCircle, Move, ScanEye } from "lucide-react"
import {
  Enums as csEnums,
  RenderingEngine,
  cache,
  imageLoader,
  init as cornerstoneInit,
  registerImageLoader,
  setVolumesForViewports,
  volumeLoader,
  type VolumeViewport,
} from "@cornerstonejs/core"
import {
  cornerstoneNiftiImageLoader,
  createNiftiImageIdsAndCacheMetadata,
  init as niftiInit,
} from "@cornerstonejs/nifti-volume-loader"
import {
  Enums as csToolsEnums,
  PanTool,
  StackScrollTool,
  ToolGroupManager,
  WindowLevelTool,
  ZoomTool,
  addTool,
  init as cornerstoneToolsInit,
  segmentation,
  utilities as csToolsUtilities,
} from "@cornerstonejs/tools"

import { cn } from "@/lib/utils"
import { loadViewerImages, startViewerSetup } from "@/lib/viewerLifecycle"
import type {
  SegmentationLegendGroup,
  SegmentationOverlayModel,
  ViewerMode,
} from "@/lib/segmentationOverlay"

type LegendPanelProps = {
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
}
export type ViewportPlane = "axial" | "sagittal" | "coronal"

/** One panel of a configurable comparison row. */
export type ViewerPanelConfig = {
  /** Stable identity; adding, removing or re-planing panels rebuilds the viewports. */
  id: string
  imageAssetUrl: string
  plane: ViewportPlane
  label: string
  /** Short name drawn large inside the image (PACS style), e.g. the MRI sequence. */
  badge?: string
  showOverlay: boolean
  /** Overlay style for this panel; defaults to the shared `viewerMode`. */
  overlayMode?: ViewerMode
}

type CornerstoneStructuralViewerProps = {
  /** Volume shown in the three MPR planes when no `panels` are given. */
  imageAssetUrl: string
  segmentationAssetUrl: string | null
  overlayModel: SegmentationOverlayModel | null
  compact?: boolean
  /**
   * Comparison row: each panel picks its own volume, plane and overlay. Slice,
   * crosshair, zoom and pan stay linked; window/level is per panel.
   */
  panels?: ViewerPanelConfig[]
  /** Extra controls (for example a sequence selector) rendered under a panel header. */
  renderPanelControls?: (panelId: string) => ReactNode
  /** Overlay visibility for the MPR planes. */
  showOverlay: boolean
  setShowOverlay: (value: boolean) => void
  hideOverlayTemporarily?: boolean
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
  onInitializationError: (message: string) => void
}

type ViewportState = {
  sliceIndex: number
  crosshair: { x: number; y: number } | null
}

type ViewerView = { key: string; plane: ViewportPlane; title: string }

const VIEWER_MODES: ViewerMode[] = ["blend", "mask", "contour"]
const VIEWPORT_LAYOUT: Array<{ plane: ViewportPlane; title: string }> = [
  { plane: "axial", title: "Axial" },
  { plane: "sagittal", title: "Sagittal" },
  { plane: "coronal", title: "Coronal" },
]
const MPR_VIEWS: ViewerView[] = VIEWPORT_LAYOUT.map(({ plane, title }) => ({ key: plane, plane, title }))

const ANATOMY_ACTOR_UID = "anatomy-volume"

let cornerstoneSetupPromise: Promise<void> | null = null
let cornerstoneToolsRegistered = false
let niftiImageLoaderRegistered = false

function stableIdFragment(value: string) {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) | 0
  }
  return Math.abs(hash).toString(36)
}

function hexToRgb(hex: string) {
  const normalized = hex.replace("#", "")
  const value = normalized.length === 3
    ? normalized
        .split("")
        .map((character) => `${character}${character}`)
        .join("")
    : normalized
  const parsed = Number.parseInt(value, 16)
  return {
    r: (parsed >> 16) & 255,
    g: (parsed >> 8) & 255,
    b: parsed & 255,
  }
}

function buildCornerstoneColorLut(overlayModel: SegmentationOverlayModel) {
  const maxLabelId = Math.max(...Object.keys(overlayModel.labelById).map((value) => Number(value)))
  const lut = Array.from({ length: maxLabelId + 1 }, () => [0, 0, 0, 0] as [number, number, number, number])

  for (const label of Object.values(overlayModel.labelById)) {
    const color = hexToRgb(label.color)
    lut[label.labelId] = [color.r, color.g, color.b, 255]
  }

  return lut
}

function buildSegmentsConfig(overlayModel: SegmentationOverlayModel) {
  return Object.fromEntries(
    Object.values(overlayModel.labelById).map((label) => [
      label.labelId,
      {
        segmentIndex: label.labelId,
        label: label.displayName,
        active: false,
        locked: false,
        cachedStats: {},
      },
    ]),
  )
}

async function ensureCornerstoneStructuralSetup() {
  if (!cornerstoneSetupPromise) {
    cornerstoneSetupPromise = (async () => {
      await cornerstoneInit()
      cornerstoneToolsInit()
      niftiInit()

      if (!cornerstoneToolsRegistered) {
        addTool(PanTool)
        addTool(ZoomTool)
        addTool(StackScrollTool)
        addTool(WindowLevelTool)
        cornerstoneToolsRegistered = true
      }

      if (!niftiImageLoaderRegistered) {
        registerImageLoader("nifti", cornerstoneNiftiImageLoader)
        niftiImageLoaderRegistered = true
      }
    })()
  }

  return cornerstoneSetupPromise
}

function CornerstoneLegendPanel({
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
}: LegendPanelProps) {
  const visibleSet = useMemo(() => new Set(visibleLabelIds), [visibleLabelIds])

  return (
    <div className="min-w-0 rounded-[1rem] border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
      <div className="mb-3">
        <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">Segmentation legend</div>
        <div className="mt-1 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
          Click any label to focus it in all three views. Group sections keep the full structural set readable without flooding the panel.
        </div>
      </div>
      <div className="max-h-[18rem] space-y-2 overflow-y-auto pr-1">
        {overlayModel.groups.map((group: SegmentationLegendGroup) => {
          const expanded = expandedGroups.includes(group.id)
          const groupActive = activeGroup === group.id && activeLabelId == null
          const allVisible = group.labels.every((label) => visibleSet.has(label.labelId))
          const someVisible = group.labels.some((label) => visibleSet.has(label.labelId))

          return (
            <div className="overflow-hidden rounded-xl border border-[hsl(var(--border)/0.75)]" key={group.id}>
              <div className="flex items-center gap-2 px-3 py-2.5">
                <button className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={() => onSelectGroup(groupActive ? null : group.id)} type="button">
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
                        <button className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={() => onSelectLabel(active ? null : label.labelId)} type="button">
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

function CompactSegmentationLabelDropdown({
  activeGroup,
  activeLabelId,
  overlayModel,
  onSelectGroup,
  onSelectLabel,
  onToggleGroupVisibility,
  onToggleLabelVisibility,
  showOverlay,
  setShowOverlay,
  visibleLabelIds,
}: {
  activeGroup: string | null
  activeLabelId: number | null
  overlayModel: SegmentationOverlayModel
  onSelectGroup: (groupId: string | null) => void
  onSelectLabel: (labelId: number | null) => void
  onToggleGroupVisibility: (groupId: string) => void
  onToggleLabelVisibility: (labelId: number) => void
  showOverlay: boolean
  setShowOverlay: (value: boolean) => void
  visibleLabelIds: number[]
}) {
  const visibleSet = useMemo(() => new Set(visibleLabelIds), [visibleLabelIds])
  const labelCount = Object.keys(overlayModel.labelById).length
  const visibleCount = Object.values(overlayModel.labelById).filter((label) => visibleSet.has(label.labelId)).length
  const [labelsExpanded, setLabelsExpanded] = useState(true)

  return (
    <details open={labelsExpanded} onToggle={(event) => setLabelsExpanded(event.currentTarget.open)} className="group rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[12px] text-[hsl(var(--muted-foreground))]">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 [&::-webkit-details-marker]:hidden">
        <span className="inline-flex min-w-0 items-center gap-2">
          <Layers3 className="h-3.5 w-3.5 shrink-0" />
          <span className="font-medium text-[hsl(var(--foreground))]">Labels</span>
          <span className="truncate text-[11px]">{visibleCount}/{labelCount} visible</span>
        </span>
        <span className="inline-flex items-center gap-3">
          <label className="inline-flex items-center gap-2 text-[11px]" onClick={(event) => event.stopPropagation()}>
            <input
              checked={showOverlay}
              className="size-4 accent-[hsl(var(--primary))]"
              onChange={(event) => setShowOverlay(event.target.checked)}
              type="checkbox"
            />
            Overlay
          </label>
          <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
        </span>
      </summary>
      <div className="border-t border-[hsl(var(--border))] px-2 py-2">
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {overlayModel.groups.map((group) => {
            const groupActive = activeGroup === group.id && activeLabelId == null
            const allVisible = group.labels.every((label) => visibleSet.has(label.labelId))
            const someVisible = group.labels.some((label) => visibleSet.has(label.labelId))

            return (
              <div className="rounded-lg border border-[hsl(var(--border)/0.72)] bg-[hsl(var(--card))] p-2" key={group.id}>
                <div className="flex items-center gap-2">
                  <button
                    className={cn(
                      "flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1 text-left transition",
                      groupActive ? "bg-[hsl(var(--muted))] text-[hsl(var(--foreground))]" : "hover:bg-[hsl(var(--muted))]",
                    )}
                    onClick={() => onSelectGroup(groupActive ? null : group.id)}
                    type="button"
                  >
                    <span className="h-2.5 w-2.5 rounded-full border border-black/15" style={{ backgroundColor: group.color }} />
                    <span className="truncate text-[11px] font-medium">{group.displayName}</span>
                  </button>
                  <input
                    aria-label={`Toggle ${group.displayName}`}
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
                </div>
                <div className="mt-1 space-y-1">
                  {group.labels.map((label) => {
                    const active = activeLabelId === label.labelId
                    return (
                      <div className="flex items-center gap-2" key={label.labelId}>
                        <button
                          className={cn(
                            "flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-1.5 py-1 text-left transition",
                            active ? "bg-[hsl(var(--muted))] text-[hsl(var(--foreground))]" : "hover:bg-[hsl(var(--muted))]",
                          )}
                          onClick={() => onSelectLabel(active ? null : label.labelId)}
                          type="button"
                        >
                          <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: label.color }} />
                          <span className="truncate text-[11px]">{label.displayName}</span>
                        </button>
                        <input
                          aria-label={`Toggle ${label.displayName}`}
                          checked={visibleSet.has(label.labelId)}
                          className="size-4 accent-[hsl(var(--primary))]"
                          onChange={() => onToggleLabelVisibility(label.labelId)}
                          type="checkbox"
                        />
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </details>
  )
}

export function CornerstoneStructuralViewer(props: CornerstoneStructuralViewerProps) {
  // A new segmentation or a different set of viewports (panel ids / planes) rebuilds
  // the rendering engine and GPU resources, while Cornerstone's decoded image cache
  // remains reusable. Volume, overlay and label changes are applied in place.
  const assetKey = JSON.stringify([props.segmentationAssetUrl, props.panels?.map((panel) => [panel.id, panel.plane]) ?? "mpr"])
  return <CornerstoneViewerSession key={assetKey} {...props} />
}

type AnatomyVolumeEntry = {
  volumeId: string
  ready: Promise<void>
  users: Set<string>
}

// Anatomy volumes belong to one setup run (one rendering engine). A cancelled or
// superseded run releases only its own volumes, never those of the run that
// replaced it, while the decoded NIfTI frames stay shared in Cornerstone's image cache.
type AnatomyVolumeSession = {
  nonce: string
  registry: Map<string, AnatomyVolumeEntry>
  loadedUrls: Record<string, string | null>
}

let anatomySessionCounter = 0

function createAnatomySession(): AnatomyVolumeSession {
  anatomySessionCounter += 1
  return { nonce: anatomySessionCounter.toString(36), registry: new Map(), loadedUrls: {} }
}

function collectUnusedVolumes(session: AnatomyVolumeSession) {
  for (const [url, entry] of session.registry) {
    if (entry.users.size) continue
    session.registry.delete(url)
    releaseCachedVolume(entry.volumeId)
  }
}

function releaseAllVolumes(session: AnatomyVolumeSession) {
  for (const entry of session.registry.values()) entry.users.clear()
  collectUnusedVolumes(session)
  session.loadedUrls = {}
}

function releaseCachedVolume(volumeId: string) {
  const volume = cache.getVolume(volumeId)
  if (!volume) return
  volume.vtkOpenGLTexture.releaseGraphicsResources()
  volume.vtkOpenGLTexture.delete()
  cache.removeVolumeLoadObject(volumeId)
}

function labelmapStyleFor(mode: ViewerMode) {
  if (mode === "mask") {
    return { renderFill: true, fillAlpha: 1, renderFillInactive: true, fillAlphaInactive: 1, renderOutline: false, renderOutlineInactive: false }
  }
  if (mode === "contour") {
    return {
      renderFill: false,
      renderFillInactive: false,
      renderOutline: true,
      renderOutlineInactive: true,
      outlineWidth: 2,
      outlineWidthInactive: 2,
      outlineOpacity: 1,
      outlineOpacityInactive: 0.45,
    }
  }
  return { renderFill: true, fillAlpha: 0.8, renderFillInactive: true, fillAlphaInactive: 0.8, renderOutline: false, renderOutlineInactive: false }
}

function CornerstoneViewerSession({
  imageAssetUrl,
  segmentationAssetUrl,
  overlayModel,
  panels,
  renderPanelControls,
  showOverlay,
  hideOverlayTemporarily = false,
  setShowOverlay,
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
  onInitializationError,
  compact = false,
}: CornerstoneStructuralViewerProps) {
  const reactId = useId().replaceAll(":", "-")
  const layoutKey = panels ? panels.map((panel) => `${panel.id}:${panel.plane}`).join("|") : "mpr"
  const assetId = useMemo(
    () => stableIdFragment(`${segmentationAssetUrl ?? "no-segmentation"}|${layoutKey}`),
    [segmentationAssetUrl, layoutKey],
  )
  const renderingEngineId = `cornerstone-engine-${reactId}-${assetId}`
  const toolGroupId = `cornerstone-toolgroup-${reactId}-${assetId}`
  const segmentationVolumeId = `cornerstone-volume-${reactId}-${assetId}-segmentation`
  const segmentationId = `cornerstone-segmentation-${reactId}-${assetId}`
  const views = useMemo<ViewerView[]>(
    () => (panels ? panels.map((panel) => ({ key: panel.id, plane: panel.plane, title: panel.label })) : MPR_VIEWS),
    // Only identity and plane rebuild the viewports; titles are read from `panels` at render time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [layoutKey],
  )
  const viewportIdFor = (key: string) => `viewport-${reactId}-${key}`
  const panelById = useMemo(() => new Map((panels ?? []).map((panel) => [panel.id, panel])), [panels])

  const elementsRef = useRef<Record<string, HTMLDivElement | null>>({})
  const renderingEngineRef = useRef<RenderingEngine | null>(null)
  const reportInitializationError = useEffectEvent(onInitializationError)
  const syncingRef = useRef(false)
  const activeViewportRef = useRef<string>(views[0]?.key ?? "axial")
  const sharedWorldRef = useRef<[number, number, number] | null>(null)
  const anatomySessionRef = useRef<AnatomyVolumeSession | null>(null)
  const [viewerReady, setViewerReady] = useState(false)
  const [viewerError, setViewerError] = useState<string | null>(null)
  const [viewportState, setViewportState] = useState<Record<string, ViewportState>>({})
  const [swappingPanels, setSwappingPanels] = useState<string[]>([])
  const [volumeGeneration, setVolumeGeneration] = useState(0)
  const panelUrlKey = views.map(({ key }) => panelById.get(key)?.imageAssetUrl ?? imageAssetUrl).join("\n")
  const panelUrls = useMemo<Record<string, string>>(
    () => Object.fromEntries(views.map(({ key }) => [key, panelById.get(key)?.imageAssetUrl ?? imageAssetUrl])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [panelUrlKey, views],
  )
  const readPanelUrls = useEffectEvent(() => panelUrls)
  const overlayVisibleFor = (key: string) => (panelById.get(key)?.showOverlay ?? showOverlay) && !hideOverlayTemporarily
  const overlayModeFor = (key: string) => panelById.get(key)?.overlayMode ?? viewerMode
  const overlayKey = views.map(({ key }) => `${overlayVisibleFor(key) ? 1 : 0}${overlayModeFor(key)}`).join("")

  const colorLut = useMemo(() => (overlayModel ? buildCornerstoneColorLut(overlayModel) : null), [overlayModel])
  const segmentsConfig = useMemo(() => (overlayModel ? buildSegmentsConfig(overlayModel) : null), [overlayModel])

  const effectiveVisibleLabels = useMemo(() => {
    if (!overlayModel) {
      return new Set<number>()
    }
    if (activeLabelId != null) {
      return new Set([activeLabelId])
    }
    if (activeGroup) {
      const group = overlayModel.groups.find((candidate) => candidate.id === activeGroup)
      return new Set(group?.labels.map((label) => label.labelId) ?? [])
    }
    return new Set(visibleLabelIds)
  }, [activeGroup, activeLabelId, overlayModel, visibleLabelIds])

  // Anatomy volumes are keyed by asset URL and shared by every panel showing the same volume.
  function acquireAnatomyVolume(session: AnatomyVolumeSession, url: string): AnatomyVolumeEntry {
    const { registry } = session
    const existing = registry.get(url)
    if (existing) return existing
    const volumeId = `cornerstone-volume-${reactId}-${session.nonce}-anatomy-${stableIdFragment(url)}`
    const entry: AnatomyVolumeEntry = { volumeId, users: new Set(), ready: Promise.resolve() }
    const dropped = () => registry.get(url) !== entry
    entry.ready = (async () => {
      try {
        const imageIds = await createNiftiImageIdsAndCacheMetadata({ url })
        if (dropped()) return
        if (!imageIds.length) {
          throw new Error("The MRI volume did not resolve any image frames.")
        }
        await loadViewerImages(imageIds, (id) => imageLoader.loadAndCacheImage(id), dropped)
        if (dropped()) return
        if (!cache.getVolume(volumeId)) {
          await volumeLoader.createAndCacheVolumeFromImages(volumeId, imageIds)
        }
      } catch (error) {
        if (registry.get(url) === entry) registry.delete(url)
        throw error
      } finally {
        // Released while loading: nobody owns the volume any more, so drop it.
        if (!registry.has(url)) releaseCachedVolume(volumeId)
      }
    })()
    registry.set(url, entry)
    return entry
  }

  function syncCrosshairsAndSlices() {
    const renderingEngine = renderingEngineRef.current
    if (!renderingEngine || renderingEngine.hasBeenDestroyed) {
      return
    }

    const nextState: Record<string, ViewportState> = {}
    for (const { key } of views) {
      const viewport = renderingEngine.getViewport(viewportIdFor(key)) as any
      if (!viewport) continue
      const state: ViewportState = { sliceIndex: typeof viewport.getSliceIndex === "function" ? viewport.getSliceIndex() : 0, crosshair: null }
      if (sharedWorldRef.current) {
        try {
          const point = viewport.worldToCanvas(sharedWorldRef.current)
          state.crosshair = { x: point[0], y: point[1] }
        } catch {
          state.crosshair = null
        }
      }
      nextState[key] = state
    }

    setViewportState(nextState)
  }

  function jumpAllToWorld(world: [number, number, number], sourceKey?: string) {
    const renderingEngine = renderingEngineRef.current
    if (!renderingEngine || renderingEngine.hasBeenDestroyed) {
      return
    }

    syncingRef.current = true
    sharedWorldRef.current = world

    for (const { key } of views) {
      const viewport = renderingEngine.getViewport(viewportIdFor(key)) as any
      if (!viewport) continue
      viewport.jumpToWorld(world)
      if (!sourceKey || sourceKey !== key) {
        viewport.render()
      }
    }

    renderingEngine.render()
    syncingRef.current = false
    syncCrosshairsAndSlices()
  }

  useEffect(() => {
    let ownedEngine: RenderingEngine | null = null
    let resizeObserver: ResizeObserver | null = null
    let unbindEvents: (() => void) | null = null
    let ownsSegmentationVolume = false
    const initialUrls = readPanelUrls()
    const anatomySession = createAnatomySession()
    anatomySessionRef.current = anatomySession
    const elementFor = (key: string) => elementsRef.current[key]

    async function setup(isCancelled: () => boolean) {
      if (views.some(({ key }) => !elementFor(key))) {
        return
      }

      setViewerError(null)
      setViewerReady(false)
      await ensureCornerstoneStructuralSetup()
      if (isCancelled()) return

      const uniqueUrls = [...new Set(views.map(({ key }) => initialUrls[key]))]
      const anatomyEntries = uniqueUrls.map((url) => acquireAnatomyVolume(anatomySession, url))
      const hasSegmentation = Boolean(segmentationAssetUrl && overlayModel && colorLut && segmentsConfig)
      const segmentationImageIds = hasSegmentation && segmentationAssetUrl
        ? await createNiftiImageIdsAndCacheMetadata({ url: segmentationAssetUrl })
        : []
      if (isCancelled()) return

      await Promise.all(anatomyEntries.map((entry) => entry.ready))
      if (isCancelled()) return
      if (anatomyEntries.some((entry) => !cache.getVolume(entry.volumeId))) {
        throw new Error("The MRI volume could not be loaded.")
      }
      await loadViewerImages(segmentationImageIds, (id) => imageLoader.loadAndCacheImage(id), isCancelled)
      if (isCancelled()) return
      if (hasSegmentation) {
        await volumeLoader.createAndCacheVolumeFromImages(segmentationVolumeId, segmentationImageIds)
        ownsSegmentationVolume = true
      }

      if (isCancelled()) {
        return
      }

      const renderingEngine = new RenderingEngine(renderingEngineId)
      ownedEngine = renderingEngine
      renderingEngineRef.current = renderingEngine
      const orientations = { axial: csEnums.OrientationAxis.AXIAL, sagittal: csEnums.OrientationAxis.SAGITTAL, coronal: csEnums.OrientationAxis.CORONAL }
      renderingEngine.setViewports(views.map(({ plane, key }) => ({
        element: elementFor(key)!,
        viewportId: viewportIdFor(key),
        type: csEnums.ViewportType.ORTHOGRAPHIC,
        defaultOptions: { orientation: orientations[plane], background: [0, 0, 0] as [number, number, number] },
      })))

      for (const [index, entry] of anatomyEntries.entries()) {
        const url = uniqueUrls[index]
        const keys = views.filter(({ key }) => initialUrls[key] === url).map(({ key }) => key)
        await setVolumesForViewports(
          renderingEngine,
          [
            {
              volumeId: entry.volumeId,
              actorUID: ANATOMY_ACTOR_UID,
              callback: ({ volumeActor }) => {
                volumeActor.getProperty().setInterpolationTypeToLinear()
              },
            },
          ],
          keys.map((key) => viewportIdFor(key)),
          true,
        )
        for (const key of keys) {
          entry.users.add(key)
          anatomySession.loadedUrls[key] = url
        }
      }
      if (isCancelled()) return

      let toolGroup = ToolGroupManager.getToolGroup(toolGroupId)
      if (!toolGroup) {
        toolGroup = ToolGroupManager.createToolGroup(toolGroupId)
      }
      if (!toolGroup) {
        throw new Error("Failed to create Cornerstone tool group.")
      }

      toolGroup.addTool(PanTool.toolName)
      toolGroup.addTool(ZoomTool.toolName)
      toolGroup.addTool(StackScrollTool.toolName)
      toolGroup.addTool(WindowLevelTool.toolName)
      for (const { key } of views) toolGroup.addViewport(viewportIdFor(key), renderingEngineId)
      toolGroup.setToolActive(WindowLevelTool.toolName, {
        bindings: [{ mouseButton: csToolsEnums.MouseBindings.Primary }],
      })
      toolGroup.setToolActive(StackScrollTool.toolName, {
        bindings: [{ mouseButton: csToolsEnums.MouseBindings.Wheel }],
      })
      toolGroup.setToolActive(PanTool.toolName, {
        bindings: [{ mouseButton: csToolsEnums.MouseBindings.Auxiliary }],
      })
      toolGroup.setToolActive(ZoomTool.toolName, {
        bindings: [{ mouseButton: csToolsEnums.MouseBindings.Secondary }],
      })

      if (hasSegmentation && colorLut && segmentsConfig) {
        try {
          // A remounted viewer (case switch) can reuse the same useId-derived
          // segmentationId; clear any stale registration before re-adding it.
          segmentation.removeSegmentation(segmentationId)
        } catch {
          // no existing segmentation under this id
        }
        segmentation.addSegmentations(
          [
            {
              segmentationId,
              representation: {
                type: csToolsEnums.SegmentationRepresentations.Labelmap,
                data: {
                  volumeId: segmentationVolumeId,
                  referencedVolumeId: anatomyEntries[0].volumeId,
                },
              },
              config: {
                label: "Structural segmentation",
                segments: segmentsConfig,
              },
            },
          ],
          true,
        )

        // Every panel carries the labelmap; per-panel visibility decides whether it shows.
        for (const { key } of views) {
          segmentation.addLabelmapRepresentationToViewport(viewportIdFor(key), [
            {
              segmentationId,
              config: {
                colorLUTOrIndex: colorLut,
              },
            },
          ])
          segmentation.activeSegmentation.setActiveSegmentation(viewportIdFor(key), segmentationId)
        }
      }

      const sliceCounts = views.map(({ key }) => {
        const viewport = renderingEngine.getViewport(viewportIdFor(key)) as any
        viewport.resetCamera?.()
        viewport.render?.()
        return Number(viewport.getNumberOfSlices?.() ?? 0)
      })

      const firstViewport = renderingEngine.getViewport(viewportIdFor(views[0].key)) as any
      const focalPoint = firstViewport.getCamera().focalPoint as [number, number, number]
      sharedWorldRef.current = focalPoint
      renderingEngine.render()
      syncCrosshairsAndSlices()

      // Reformatted coronal/sagittal slices have no acquisition image ID.
      // The loaded volume and valid slice counts establish readiness for MPR.
      if (sliceCounts.some((count) => !Number.isFinite(count) || count <= 0)) {
        throw new Error("Cornerstone structural viewer did not resolve valid slices. Falling back to the slice-based viewer.")
      }

      resizeObserver = new ResizeObserver(() => {
        if (isCancelled() || renderingEngine.hasBeenDestroyed) return
        renderingEngine.resize(true, true)
        syncCrosshairsAndSlices()
      })
      for (const { key } of views) resizeObserver.observe(elementFor(key)!)

      const bindViewportEvents = (view: ViewerView, element: HTMLDivElement) => {
        const viewportId = viewportIdFor(view.key)
        const syncFromViewport = () => {
          if (isCancelled() || renderingEngine.hasBeenDestroyed) return
          if (syncingRef.current) return
          if (activeViewportRef.current !== view.key) {
            syncCrosshairsAndSlices()
            return
          }
          const viewport = renderingEngine.getViewport(viewportId) as VolumeViewport
          const camera = viewport.getCamera()
          const focal = camera.focalPoint as [number, number, number]
          syncingRef.current = true
          try {
            sharedWorldRef.current = focal
            for (const other of views) {
              if (other.key === view.key) continue
              const target = renderingEngine.getViewport(viewportIdFor(other.key)) as VolumeViewport
              if (other.plane === view.plane) {
                // Same plane: slice, zoom and pan follow. Window/level follows only
                // between panels that show the same volume; other sequences keep their own.
                target.setCamera(camera)
                if (anatomySession.loadedUrls[view.key] === anatomySession.loadedUrls[other.key]) {
                  const { voiRange, invert } = viewport.getProperties()
                  target.setProperties({ voiRange, invert })
                }
              } else {
                target.jumpToWorld(focal)
              }
              target.render()
            }
          } finally {
            syncingRef.current = false
          }
          syncCrosshairsAndSlices()
        }

        const onCameraModified = () => syncFromViewport()
        const onNewImage = () => syncFromViewport()
        const onPointerEnter = () => {
          activeViewportRef.current = view.key
        }

        element.addEventListener(csEnums.Events.CAMERA_MODIFIED, onCameraModified as EventListener)
        element.addEventListener(csEnums.Events.VOLUME_NEW_IMAGE, onNewImage as EventListener)
        element.addEventListener(csEnums.Events.VOI_MODIFIED, onCameraModified as EventListener)
        element.addEventListener("pointerenter", onPointerEnter)

        return () => {
          element.removeEventListener(csEnums.Events.CAMERA_MODIFIED, onCameraModified as EventListener)
          element.removeEventListener(csEnums.Events.VOLUME_NEW_IMAGE, onNewImage as EventListener)
          element.removeEventListener(csEnums.Events.VOI_MODIFIED, onCameraModified as EventListener)
          element.removeEventListener("pointerenter", onPointerEnter)
        }
      }

      const unbind = views.map((view) => bindViewportEvents(view, elementFor(view.key)!))
      unbindEvents = () => unbind.forEach((remove) => remove())

      if (!isCancelled()) {
        setViewerReady(true)
      }
    }

    const lifecycle = startViewerSetup(setup, () => {
      resizeObserver?.disconnect()
      unbindEvents?.()
      if (renderingEngineRef.current === ownedEngine) renderingEngineRef.current = null
      ownedEngine?.destroy()
      ToolGroupManager.destroyToolGroup(toolGroupId)
      try {
        segmentation.removeSegmentation(segmentationId)
      } catch {
        // segmentation already removed
      }
      releaseAllVolumes(anatomySession)
      if (anatomySessionRef.current === anatomySession) anatomySessionRef.current = null
      if (ownsSegmentationVolume) releaseCachedVolume(segmentationVolumeId)
    }, (error) => {
      const message = error instanceof Error ? error.message : "Cornerstone structural viewer failed to initialize."
      setViewerError(message)
      reportInitializationError(message)
    })

    return () => {
      lifecycle.cancel()
      if (renderingEngineRef.current === ownedEngine) renderingEngineRef.current = null
    }
  }, [
    colorLut,
    overlayModel,
    reactId,
    renderingEngineId,
    segmentationAssetUrl,
    segmentationId,
    segmentationVolumeId,
    segmentsConfig,
    toolGroupId,
    views,
  ])

  // Swap anatomy volumes in place when a panel's asset changes, keeping the
  // other panels, the camera and the shared crosshair untouched.
  useEffect(() => {
    if (!viewerReady) return
    const renderingEngine = renderingEngineRef.current
    const anatomySession = anatomySessionRef.current
    if (!renderingEngine || renderingEngine.hasBeenDestroyed || !anatomySession) return
    const pending = views.filter(({ key }) => anatomySession.loadedUrls[key] !== panelUrls[key]).map(({ key }) => key)
    if (!pending.length) {
      collectUnusedVolumes(anatomySession)
      setSwappingPanels((current) => (current.length ? [] : current))
      return
    }
    setSwappingPanels(pending)
    let cancelled = false

    const swaps = pending.map(async (key) => {
      const url = panelUrls[key]
      const entry = acquireAnatomyVolume(anatomySession, url)
      await entry.ready
      if (cancelled || renderingEngine.hasBeenDestroyed || anatomySession.registry.get(url) !== entry) return
      if (!cache.getVolume(entry.volumeId)) {
        throw new Error("The MRI volume could not be loaded.")
      }
      const viewport = renderingEngine.getViewport(viewportIdFor(key)) as VolumeViewport
      const camera = viewport.getCamera()
      const previousUrl = anatomySession.loadedUrls[key]
      entry.users.add(key)
      anatomySession.loadedUrls[key] = url
      syncingRef.current = true
      try {
        // setVolumes resets the camera and drops the labelmap actor; restore the
        // camera here and let the segmentation render re-attach the labelmap.
        await viewport.setVolumes([
          {
            volumeId: entry.volumeId,
            actorUID: ANATOMY_ACTOR_UID,
            callback: ({ volumeActor }) => {
              volumeActor.getProperty().setInterpolationTypeToLinear()
            },
          },
        ])
        viewport.setCamera(camera)
      } finally {
        syncingRef.current = false
      }
      if (previousUrl && previousUrl !== url) {
        anatomySession.registry.get(previousUrl)?.users.delete(key)
      }
      if (segmentationAssetUrl) csToolsUtilities.segmentation.triggerSegmentationRender(viewportIdFor(key))
      viewport.render()
      // The viewport changed even if this run was superseded; let the next pass reconcile.
      setVolumeGeneration((generation) => generation + 1)
    })

    void Promise.allSettled(swaps).then((results) => {
      const failure = results.find((result): result is PromiseRejectedResult => result.status === "rejected")
      if (!failure || cancelled || renderingEngine.hasBeenDestroyed) return
      const message = failure.reason instanceof Error ? failure.reason.message : "The MRI volume could not be loaded."
      setViewerError(message)
      reportInitializationError(message)
    })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panelUrls, reactId, segmentationAssetUrl, viewerReady, views, volumeGeneration])

  useEffect(() => {
    const renderingEngine = renderingEngineRef.current
    if (!renderingEngine || renderingEngine.hasBeenDestroyed || !viewerReady || !segmentationAssetUrl || !overlayModel || !colorLut) {
      return
    }

    for (const { key } of views) {
      const viewportId = viewportIdFor(key)
      const viewport = renderingEngine.getViewport(viewportId)
      if (!viewport) continue
      const overlayVisible = overlayVisibleFor(key)
      const mode = overlayModeFor(key)

      segmentation.config.visibility.setSegmentationRepresentationVisibility(
        viewportId,
        {
          segmentationId,
          type: csToolsEnums.SegmentationRepresentations.Labelmap,
        },
        overlayVisible,
      )

      segmentation.segmentationStyle.setStyle(
        {
          viewportId,
          segmentationId,
          type: csToolsEnums.SegmentationRepresentations.Labelmap,
        },
        labelmapStyleFor(mode),
        true,
      )

      for (const label of Object.values(overlayModel.labelById)) {
        const rgb = hexToRgb(label.color)
        segmentation.config.color.setSegmentIndexColor(viewportId, segmentationId, label.labelId, [rgb.r, rgb.g, rgb.b, 255])
        segmentation.config.visibility.setSegmentIndexVisibility(
          viewportId,
          {
            segmentationId,
            type: csToolsEnums.SegmentationRepresentations.Labelmap,
          },
          label.labelId,
          overlayVisible && effectiveVisibleLabels.has(label.labelId),
        )
      }

      const anatomyActor = viewport.getActor(ANATOMY_ACTOR_UID) as { actor?: { setVisibility?: (visible: boolean) => void } } | undefined
      anatomyActor?.actor?.setVisibility?.(!overlayVisible || mode !== "mask")
      viewport.render()
    }

    syncCrosshairsAndSlices()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    colorLut,
    effectiveVisibleLabels,
    overlayModel,
    overlayKey,
    reactId,
    segmentationId,
    viewerReady,
    segmentationAssetUrl,
    views,
    volumeGeneration,
  ])

  if (viewerError) {
    return null
  }

  const bindElement = (key: string) => (node: HTMLDivElement | null) => {
    elementsRef.current[key] = node
  }

  const handleViewportClick = (key: string, event: { clientX: number; clientY: number }) => {
    const renderingEngine = renderingEngineRef.current
    const element = elementsRef.current[key]
    if (!viewerReady || !renderingEngine || renderingEngine.hasBeenDestroyed || !element) {
      return
    }
    const viewport = renderingEngine.getViewport(viewportIdFor(key))
    const rect = element.getBoundingClientRect()
    const point = viewport.canvasToWorld([event.clientX - rect.left, event.clientY - rect.top])
    activeViewportRef.current = key
    jumpAllToWorld(point as [number, number, number], key)
  }

  const renderCrosshair = (key: string) => {
    const crosshair = viewportState[key]?.crosshair
    if (!crosshair) return null
    return (
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute top-0 h-full w-px bg-[#6aa9ff]/80" style={{ left: crosshair.x }} />
        <div className="absolute left-0 h-px w-full bg-[#6aa9ff]/80" style={{ top: crosshair.y }} />
      </div>
    )
  }

  const renderViewport = (view: ViewerView) => {
    const { key } = view
    const panel = panelById.get(key)
    const title = panel?.label ?? view.title
    const loading = !viewerReady || swappingPanels.includes(key)
    return (
      <div className="min-w-0 space-y-2" key={key} data-viewer-panel={key}>
        <div className="flex items-center justify-between gap-2 px-0.5">
          <div className={cn("min-w-0 truncate", panel ? "text-[12px] text-zinc-400" : "text-[13px] font-medium text-zinc-200")} title={title}>{title}</div>
          <div className="shrink-0 text-[12px] text-zinc-400">{loading ? "Loading" : `Slice ${viewportState[key]?.sliceIndex ?? 0}`}</div>
        </div>
        {panel && renderPanelControls ? renderPanelControls(key) : null}
        <div
          className="relative aspect-square overflow-hidden rounded-[0.9rem] border border-[hsl(var(--border))] bg-black shadow-[0_12px_32px_rgba(0,0,0,0.18)]"
          onClick={(event) => handleViewportClick(key, event)}
        >
          <div className="absolute inset-0" ref={bindElement(key)} />
          {panel?.badge ? (
            <div aria-hidden="true" className="pointer-events-none absolute left-2.5 top-2 z-20 text-lg font-semibold leading-none tracking-wide text-white [text-shadow:0_1px_3px_rgba(0,0,0,0.9)]">{panel.badge}</div>
          ) : null}
          {loading ? (
            <div role="status" className={cn("absolute inset-0 z-10 flex items-center justify-center gap-2 text-sm text-zinc-200", viewerReady ? "bg-zinc-950/70" : "bg-zinc-950")}>
              <LoaderCircle aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" />
              {panel || !segmentationAssetUrl ? "Loading MRI" : "Loading MRI and overlay"}
            </div>
          ) : null}
          {renderCrosshair(key)}
        </div>
      </div>
    )
  }

  if (compact) {
    const dropdownOverlay = panels ? panels.some((panel) => panel.showOverlay) : showOverlay
    return (
      <div className="space-y-3">
        <div
          className={cn("grid gap-3", panels ? "" : "lg:grid-cols-3")}
          // Panels share one row while each column keeps room for its controls; narrower windows wrap.
          style={panels ? { gridTemplateColumns: "repeat(auto-fit, minmax(11rem, 1fr))" } : undefined}
        >
          {(panels ? views : [views[0], views[2], views[1]].filter(Boolean)).map((view) => renderViewport(view))}
        </div>
        {overlayModel ? (
          <CompactSegmentationLabelDropdown
            activeGroup={activeGroup}
            activeLabelId={activeLabelId}
            onSelectGroup={onSelectGroup}
            onSelectLabel={onSelectLabel}
            onToggleGroupVisibility={onToggleGroupVisibility}
            onToggleLabelVisibility={onToggleLabelVisibility}
            overlayModel={overlayModel}
            setShowOverlay={setShowOverlay}
            showOverlay={dropdownOverlay}
            visibleLabelIds={visibleLabelIds}
          />
        ) : null}
      </div>
    )
  }

  const renderFullViewport = (view: ViewerView) => (
    <div className="min-w-0 space-y-3" key={view.key}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">{view.title}</div>
        <div className="text-[11px] text-[hsl(var(--muted-foreground))]">Slice {viewportState[view.key]?.sliceIndex ?? 0}</div>
      </div>
      <div
        className="relative aspect-square overflow-hidden rounded-[1rem] border border-[hsl(var(--border))] bg-black"
        onClick={(event) => handleViewportClick(view.key, event)}
      >
        <div className="absolute inset-0" ref={bindElement(view.key)} />
        {renderCrosshair(view.key)}
      </div>
    </div>
  )

  const [axialView, sagittalView, coronalView] = views

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        {renderFullViewport(axialView)}
        {sagittalView ? renderFullViewport(sagittalView) : null}

        <div className="min-w-0 space-y-4 rounded-[1rem] border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-4">
          <div>
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Control panel</div>
            <div className="mt-1 text-[15px] font-medium text-[hsl(var(--foreground))]">Linked structural viewer</div>
            <div className="mt-2 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">
              Click inside any viewport to move the shared anatomical position. Left drag adjusts window/level intensity, wheel scroll changes slices, right drag zooms, and middle drag pans.
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-3">
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--border))] px-2.5 py-1">
                <ScanEye className="size-3.5" />
                cornerstone_structural
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--border))] px-2.5 py-1">
                <Move className="size-3.5" />
                Linked MPR
              </span>
            </div>
            <label className="inline-flex items-center gap-2 text-[12px] text-[hsl(var(--muted-foreground))]">
              <input
                checked={showOverlay}
                className="size-4 accent-[hsl(var(--primary))]"
                onChange={(event) => setShowOverlay(event.target.checked)}
                type="checkbox"
              />
              <Layers3 className="size-3.5" />
                Segmentation overlay
            </label>
          </div>

          <div className="grid gap-2 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">
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
                  {mode === "mask" ? "Mask only" : mode === "contour" ? "Contour" : "Blend"}
                </button>
              ))}
            </div>
            <div>
              <span className="font-medium text-[hsl(var(--foreground))]">Blend</span>: anatomy plus color-filled structures at alpha 0.8.
            </div>
            <div>
              <span className="font-medium text-[hsl(var(--foreground))]">Mask only</span>: segmentation without the structural image.
            </div>
            <div>
              <span className="font-medium text-[hsl(var(--foreground))]">Contour</span>: anatomy with structure outlines.
            </div>
          </div>

          {overlayModel ? (
            <CornerstoneLegendPanel
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

        {coronalView ? renderFullViewport(coronalView) : null}
      </div>
    </div>
  )
}
