export type VisitAxisLabel = { index: number; anchorX: number; x: number; width: number; lane: number }

export type ChartPosition = { x: number; y: number }

// Inspect measured visits only: narrow point/segment hit areas never interpolate
// a volume or let empty space in the same time column trigger a detail.
export function hitTestTrend(pointer: ChartPosition, curves: ChartPosition[][]): { index: number; seriesIndex: number } | null {
  const distanceSquared = (a: ChartPosition, b: ChartPosition) => (a.x - b.x) ** 2 + (a.y - b.y) ** 2
  let hit: { index: number; seriesIndex: number } | null = null
  let nearest = 8 ** 2
  curves.forEach((curve, seriesIndex) => curve.forEach((point, index) => {
    const distance = distanceSquared(pointer, point)
    if (distance <= nearest) { nearest = distance; hit = { index, seriesIndex } }
  }))
  if (hit) return hit
  nearest = 6 ** 2
  curves.forEach((curve, seriesIndex) => curve.slice(1).forEach((end, index) => {
    const start = curve[index]
    const lengthSquared = distanceSquared(start, end)
    const t = lengthSquared ? Math.max(0, Math.min(1, ((pointer.x - start.x) * (end.x - start.x) + (pointer.y - start.y) * (end.y - start.y)) / lengthSquared)) : 0
    const distance = distanceSquared(pointer, { x: start.x + t * (end.x - start.x), y: start.y + t * (end.y - start.y) })
    if (distance <= nearest) { nearest = distance; hit = { index: t <= 0.5 ? index : index + 1, seriesIndex } }
  }))
  return hit
}

// Pack text independently of measurement coordinates. Close visits share a
// centered label cluster; narrow plots add rows instead of shrinking text.
export function layoutVisitLabels(positions: number[], widths: number[], left: number, right: number, labelBounds: [number, number] = [left, right]): VisitAxisLabel[] {
  const gap = 16
  const [labelLeft, labelRight] = labelBounds
  const available = labelRight - labelLeft
  const items = positions.map((position, index) => ({ index, anchorX: left + position * (right - left), width: widths[index] ?? 64 }))
    .sort((a, b) => a.anchorX - b.anchorX)
  if (!items.length) return []
  let lanes = 1
  while (lanes < items.length && Array.from({ length: lanes }, (_, lane) => items.filter((_, i) => i % lanes === lane))
    .some(row => row.reduce((sum, item) => sum + item.width, 0) + gap * (row.length - 1) > available)) lanes++
  const result: VisitAxisLabel[] = []
  for (let lane = 0; lane < lanes; lane++) {
    type Cluster = { items: typeof items; start: number; width: number }
    const clusters: Cluster[] = []
    const cluster = (members: typeof items): Cluster => {
      const width = members.reduce((sum, item) => sum + item.width, 0) + gap * (members.length - 1)
      let offset = 0, idealStart = 0
      for (const item of members) {
        idealStart += item.anchorX - offset - item.width / 2
        offset += item.width + gap
      }
      return { items: members, width, start: Math.max(labelLeft, Math.min(labelRight - width, idealStart / members.length)) }
    }
    for (const item of items.filter((_, i) => i % lanes === lane)) {
      let next = cluster([item])
      while (clusters.length && clusters[clusters.length - 1].start + clusters[clusters.length - 1].width + gap > next.start) {
        next = cluster([...clusters.pop()!.items, ...next.items])
      }
      clusters.push(next)
    }
    for (const group of clusters) {
      let x = group.start
      for (const item of group.items) {
        result.push({ ...item, x: x + item.width / 2, lane })
        x += item.width + gap
      }
    }
  }
  return result.sort((a, b) => a.index - b.index)
}
