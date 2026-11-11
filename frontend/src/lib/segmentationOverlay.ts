type OverlayRegion = {
  label_id?: number
  label_name?: string
  display_name: string
  group?: string | null
  hemisphere?: string | null
  volume_mm3: number
}

export type ViewerMode = "blend" | "mask" | "contour"

export type SegmentationLegendLabel = {
  labelId: number
  labelName: string
  displayName: string
  groupId: string
  groupDisplayName: string
  hemisphere: string | null
  volumeMm3: number
  color: string
  strokeColor: string
  fillOpacity: number
}

export type SegmentationLegendGroup = {
  id: string
  displayName: string
  color: string
  strokeColor: string
  labels: SegmentationLegendLabel[]
}

export type SegmentationOverlayModel = {
  groups: SegmentationLegendGroup[]
  labelById: Record<number, SegmentationLegendLabel>
}

const GROUP_ORDER = [
  "brain_parenchyma",
  "ventricular_system",
  "extra_axial_spaces",
  "deep_gray_matter",
  "cerebellum_brainstem",
  "other",
] as const

const GROUP_BASE_COLORS: Record<string, string> = {
  brain_parenchyma: "#f97316",
  ventricular_system: "#3b82f6",
  extra_axial_spaces: "#0ea5e9",
  deep_gray_matter: "#f59e0b",
  cerebellum_brainstem: "#22c55e",
  deep_gray: "#f59e0b",
  ventricles: "#3b82f6",
  white_matter: "#f97316",
  hippocampus: "#fb7185",
  cerebellum: "#22c55e",
  brainstem: "#16a34a",
  cortex: "#f97316",
  other: "#94a3b8",
}

const GROUP_BASE_HUES: Record<string, number> = {
  brain_parenchyma: 24,
  ventricular_system: 216,
  extra_axial_spaces: 195,
  deep_gray_matter: 40,
  cerebellum_brainstem: 142,
  deep_gray: 40,
  ventricles: 216,
  white_matter: 24,
  hippocampus: 348,
  cerebellum: 142,
  brainstem: 132,
  cortex: 24,
  other: 215,
}

const GROUP_DISPLAY_NAMES: Record<string, string> = {
  brain_parenchyma: "Brain Parenchyma",
  ventricular_system: "Ventricular System",
  extra_axial_spaces: "Extra-axial Spaces",
  deep_gray_matter: "Deep Gray Matter",
  cerebellum_brainstem: "Cerebellum & Brainstem",
  deep_gray: "Deep Gray Nuclei",
  ventricles: "Ventricular System",
  white_matter: "White Matter",
  hippocampus: "Hippocampus",
  cerebellum: "Cerebellum",
  brainstem: "Brainstem",
  cortex: "Cortex",
  other: "Other",
}

function humanize(value: string) {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (match) => match.toUpperCase())
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function hexToRgb(hex: string) {
  const normalized = hex.replace("#", "")
  const value = normalized.length === 3
    ? normalized
        .split("")
        .map((char) => `${char}${char}`)
        .join("")
    : normalized
  const parsed = Number.parseInt(value, 16)
  return {
    r: (parsed >> 16) & 255,
    g: (parsed >> 8) & 255,
    b: parsed & 255,
  }
}

function rgbToHex(red: number, green: number, blue: number) {
  return `#${[red, green, blue].map((channel) => clamp(Math.round(channel), 0, 255).toString(16).padStart(2, "0")).join("")}`
}

function blendHex(first: string, second: string, ratio: number) {
  const left = hexToRgb(first)
  const right = hexToRgb(second)
  const mix = clamp(ratio, 0, 1)
  return rgbToHex(
    left.r + (right.r - left.r) * mix,
    left.g + (right.g - left.g) * mix,
    left.b + (right.b - left.b) * mix,
  )
}

function hslToHex(hue: number, saturation: number, lightness: number) {
  const normalizedHue = ((hue % 360) + 360) % 360
  const s = clamp(saturation, 0, 100) / 100
  const l = clamp(lightness, 0, 100) / 100
  const chroma = (1 - Math.abs(2 * l - 1)) * s
  const segment = normalizedHue / 60
  const secondary = chroma * (1 - Math.abs((segment % 2) - 1))
  const match = l - chroma / 2

  let red = 0
  let green = 0
  let blue = 0

  if (segment >= 0 && segment < 1) {
    red = chroma
    green = secondary
  } else if (segment >= 1 && segment < 2) {
    red = secondary
    green = chroma
  } else if (segment >= 2 && segment < 3) {
    green = chroma
    blue = secondary
  } else if (segment >= 3 && segment < 4) {
    green = secondary
    blue = chroma
  } else if (segment >= 4 && segment < 5) {
    red = secondary
    blue = chroma
  } else {
    red = chroma
    blue = secondary
  }

  return rgbToHex((red + match) * 255, (green + match) * 255, (blue + match) * 255)
}

function stableHash(value: string) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function normalizeColorIdentity(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "")
}

function labelColorForIdentity({
  groupId,
  labelId,
  labelIdentity,
  hemisphere,
}: {
  groupId: string
  labelId: number
  labelIdentity: string
  hemisphere?: string | null
}) {
  const groupHue = GROUP_BASE_HUES[groupId] ?? stableHash(groupId) % 360
  const hash = stableHash(`${groupId}|${labelIdentity}|${labelId}`)
  const hueOffset = ((hash % 57) - 28) * 0.72
  const hemisphereOffset = hemisphere === "left" ? -5 : hemisphere === "right" ? 5 : 0
  const hue = groupHue + hueOffset + hemisphereOffset
  const saturation = 70 + ((hash >>> 8) % 20)
  const lightness = 44 + ((hash >>> 16) % 18)
  return hslToHex(hue, saturation, lightness)
}

function labelColorFor(region: OverlayRegion) {
  const labelId = region.label_id ?? 0
  const { groupId } = groupMetaForRegion(region)
  return labelColorForIdentity({
    groupId,
    labelId,
    labelIdentity: normalizeColorIdentity(region.label_name || region.display_name || `label_${labelId}`),
    hemisphere: region.hemisphere,
  })
}

function fallbackLabelColorFor(labelId: number) {
  const hash = stableHash(`fallback_label_index|${labelId}`)
  const hue = (labelId * 137.508 + (hash % 29)) % 360
  const saturation = 72 + ((hash >>> 8) % 18)
  const lightness = 43 + ((hash >>> 16) % 20)
  return hslToHex(hue, saturation, lightness)
}

function strokeFor(color: string) {
  return blendHex(color, "#111827", 0.34)
}

function groupSortIndex(groupId: string) {
  const index = GROUP_ORDER.indexOf(groupId as (typeof GROUP_ORDER)[number])
  return index >= 0 ? index : GROUP_ORDER.length
}

function fallbackCategoryForRegion(region: OverlayRegion) {
  const sourceGroup = region.group?.trim() || "other"
  const label = `${region.label_name || ""} ${region.display_name}`.toLowerCase()

  if (sourceGroup === "ventricles" || label.includes("ventricle")) {
    return "ventricular_system"
  }
  if (sourceGroup === "deep_gray") {
    return "deep_gray_matter"
  }
  if (sourceGroup === "cerebellum" || sourceGroup === "brainstem" || label.includes("brainstem") || label.includes("cerebell")) {
    return "cerebellum_brainstem"
  }
  if (
    sourceGroup === "white_matter" ||
    sourceGroup === "cortex" ||
    sourceGroup === "hippocampus" ||
    label.includes("cortex") ||
    label.includes("white matter") ||
    label.includes("hippoc")
  ) {
    return "brain_parenchyma"
  }
  if (
    label.includes("sulc") ||
    label.includes("cistern") ||
    label.includes("csf") ||
    label.includes("subarachnoid") ||
    label.includes("extra-axial")
  ) {
    return "extra_axial_spaces"
  }
  return "other"
}

function normalizeGroupId(value: string) {
  return value.trim().toLowerCase().replace(/[\s-]+/g, "_")
}

function groupMetaForRegion(region: OverlayRegion) {
  const sourceGroup = region.group?.trim()
  if (sourceGroup) {
    const groupId = normalizeGroupId(sourceGroup)
    return {
      groupId,
      groupDisplayName: displayNameForGroup(groupId) ?? humanize(sourceGroup),
    }
  }
  const groupId = fallbackCategoryForRegion(region)
  return {
    groupId,
    groupDisplayName: displayNameForGroup(groupId),
  }
}

function displayNameForGroup(groupId: string) {
  return GROUP_DISPLAY_NAMES[groupId] ?? humanize(groupId)
}

export function buildSegmentationOverlayModel(regions: OverlayRegion[] | null | undefined): SegmentationOverlayModel | null {
  if (!regions?.length) {
    return null
  }

  const grouped = new Map<string, OverlayRegion[]>()
  for (const region of regions) {
    if (typeof region.label_id !== "number") {
      continue
    }
    const { groupId } = groupMetaForRegion(region)
    const bucket = grouped.get(groupId)
    if (bucket) {
      bucket.push(region)
    } else {
      grouped.set(groupId, [region])
    }
  }

  const groups: SegmentationLegendGroup[] = [...grouped.entries()]
    .sort((left, right) => {
      const groupDelta = groupSortIndex(left[0]) - groupSortIndex(right[0])
      if (groupDelta !== 0) {
        return groupDelta
      }
      return left[0].localeCompare(right[0])
    })
    .map(([groupId, groupRegions]) => {
      const baseColor = GROUP_BASE_COLORS[groupId] ?? GROUP_BASE_COLORS.other
      const groupDisplayName = groupMetaForRegion(groupRegions[0] as OverlayRegion).groupDisplayName
      const labels = [...groupRegions]
        .sort((left, right) => left.display_name.localeCompare(right.display_name))
        .map((region) => {
          const color = labelColorFor(region)
          const meta = groupMetaForRegion(region)
          return {
            labelId: region.label_id as number,
            labelName: region.label_name || region.display_name,
            displayName: region.display_name,
            groupId: meta.groupId,
            groupDisplayName: meta.groupDisplayName,
            hemisphere: region.hemisphere?.trim() || null,
            volumeMm3: region.volume_mm3,
            color,
            strokeColor: strokeFor(color),
            fillOpacity: 0.7,
          }
        })
      return {
        id: groupId,
        displayName: groupDisplayName,
        color: baseColor,
        strokeColor: strokeFor(baseColor),
        labels,
      }
    })

  const labelById = Object.fromEntries(
    groups.flatMap((group) => group.labels.map((label) => [label.labelId, label])),
  ) as Record<number, SegmentationLegendLabel>

  return { groups, labelById }
}

export function buildNiivueLabelLut({
  overlayModel,
  visibleLabelIds,
  activeLabelId,
  activeGroup,
  viewerMode,
}: {
  overlayModel: SegmentationOverlayModel | null
  visibleLabelIds: number[]
  activeLabelId: number | null
  activeGroup: string | null
  viewerMode: ViewerMode
}) {
  if (!overlayModel) {
    return null
  }

  const maxLabelId = Math.max(...Object.keys(overlayModel.labelById).map((value) => Number(value)))
  const lut = new Uint8ClampedArray((maxLabelId + 1) * 4)
  const labels = Array.from({ length: maxLabelId + 1 }, () => "")
  const visible = new Set(visibleLabelIds)

  for (const label of Object.values(overlayModel.labelById)) {
    const offset = label.labelId * 4
    const rgb = hexToRgb(label.color)
    const isVisible = visible.has(label.labelId)
    const isActiveLabel = activeLabelId === label.labelId
    const isActiveGroup = !activeLabelId && activeGroup != null && label.groupId === activeGroup
    const isHighlighted = isActiveLabel || isActiveGroup
    const dimmed = (activeLabelId != null || activeGroup != null) && !isHighlighted
    const alpha = !isVisible
      ? 0
      : viewerMode === "mask"
        ? (isHighlighted ? 255 : dimmed ? 72 : 235)
        : viewerMode === "contour"
          ? (isHighlighted ? 255 : dimmed ? 46 : 228)
          : (isHighlighted ? 235 : dimmed ? 76 : 178)
    lut[offset] = rgb.r
    lut[offset + 1] = rgb.g
    lut[offset + 2] = rgb.b
    lut[offset + 3] = alpha
    labels[label.labelId] = label.displayName
  }

  return {
    lut,
    min: 0,
    max: maxLabelId,
    labels,
  }
}

export function buildFallbackNiivueLabelLut({
  maxLabelId = 4096,
  viewerMode,
}: {
  maxLabelId?: number
  viewerMode: ViewerMode
}) {
  const lut = new Uint8ClampedArray((maxLabelId + 1) * 4)
  const labels = Array.from({ length: maxLabelId + 1 }, () => "")
  const alpha = viewerMode === "mask" ? 235 : viewerMode === "contour" ? 228 : 178

  for (let labelId = 1; labelId <= maxLabelId; labelId += 1) {
    const offset = labelId * 4
    const rgb = hexToRgb(fallbackLabelColorFor(labelId))
    lut[offset] = rgb.r
    lut[offset + 1] = rgb.g
    lut[offset + 2] = rgb.b
    lut[offset + 3] = alpha
    labels[labelId] = `Label ${labelId}`
  }

  return {
    lut,
    min: 0,
    max: maxLabelId,
    labels,
  }
}

export function defaultExpandedGroups(overlayModel: SegmentationOverlayModel | null) {
  void overlayModel
  return []
}

export function resolveLabelAlpha({
  label,
  visibleLabelIds,
  activeLabelId,
  activeGroup,
  viewerMode,
}: {
  label: SegmentationLegendLabel
  visibleLabelIds: Set<number>
  activeLabelId: number | null
  activeGroup: string | null
  viewerMode: ViewerMode
}) {
  const isVisible = visibleLabelIds.has(label.labelId)
  const isActiveLabel = activeLabelId === label.labelId
  const isActiveGroup = !activeLabelId && activeGroup != null && label.groupId === activeGroup
  const isHighlighted = isActiveLabel || isActiveGroup
  const dimmed = (activeLabelId != null || activeGroup != null) && !isHighlighted
  if (!isVisible) {
    return 0
  }
  if (viewerMode === "mask") {
    return isHighlighted ? 1 : dimmed ? 0.28 : 0.92
  }
  if (viewerMode === "contour") {
    return isHighlighted ? 1 : dimmed ? 0.18 : 0.9
  }
  return isHighlighted ? 0.82 : dimmed ? 0.28 : 0.7
}
