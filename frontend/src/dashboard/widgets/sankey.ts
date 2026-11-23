import type { Flow, FlowKind, FlowLink, FlowNode } from '../api.ts'

/** SVG geometry of the flow diagram, in viewBox units. */
export const SANKEY = {
  width: 960,
  nodeWidth: 10,
  /** Room left of the last column's nodes for their labels. */
  labelRoom: 120,
  /** Vertical space between two nodes of a column. */
  gap: 10,
  /** A node never takes less height than this, so its label has a line to itself. */
  minSlot: 18,
  /** Thinnest band drawn, so tiny flows next to big ones stay visible. */
  minBand: 2,
  /** Height the widest column (everything scored) is scaled to. */
  plotHeight: 260,
} as const

export type LaidNode = FlowNode & { x: number; y: number; height: number; value: number; share: string }
export type LaidLink = FlowLink & {
  path: string
  kind: FlowKind
  share: string
  sourceLabel: string
  targetLabel: string
}
export type Layout = { nodes: LaidNode[]; links: LaidLink[]; height: number }

const percent = (part: number, whole: number) => (whole > 0 ? `${Math.round((part / whole) * 100)}%` : '')

/**
 * Places the nodes in their columns, top-down in the order given (the stage the search
 * continues through first), with band thickness proportional to the count flowing through.
 * Each node is fed by one stage node, so bands stack without crossing.
 */
export function layoutSankey(flow: Flow): Layout {
  const { width, nodeWidth, labelRoom, gap, minSlot, minBand, plotHeight } = SANKEY
  const columns = Math.max(1, ...flow.nodes.map((n) => n.column + 1))
  const step = columns > 1 ? (width - labelRoom - nodeWidth) / (columns - 1) : 0

  const outgoing = new Map<string, FlowLink[]>()
  const incoming = new Map<string, FlowLink[]>()
  for (const link of flow.links) {
    outgoing.set(link.source, [...(outgoing.get(link.source) ?? []), link])
    incoming.set(link.target, [...(incoming.get(link.target) ?? []), link])
  }
  const sum = (links: FlowLink[] | undefined) => (links ?? []).reduce((total, l) => total + l.value, 0)
  const valueOf = (id: string) => Math.max(sum(incoming.get(id)), sum(outgoing.get(id)))

  const root = Math.max(1, ...flow.nodes.filter((n) => n.column === 0).map((n) => valueOf(n.id)))
  const scale = plotHeight / root
  const band = (value: number) => Math.max(minBand, value * scale)

  const byId = new Map<string, LaidNode>()
  const nextY = new Map<number, number>()
  for (const node of flow.nodes) {
    // Tall enough for what flows in and for the (possibly widened) bands flowing out.
    const outBands = (outgoing.get(node.id) ?? []).reduce((h, l) => h + band(l.value), 0)
    const height = Math.max(band(valueOf(node.id)), outBands)
    const y = nextY.get(node.column) ?? 0
    nextY.set(node.column, y + Math.max(height, minSlot) + gap)
    const parent = incoming.get(node.id)?.[0]?.source
    byId.set(node.id, {
      ...node,
      x: node.column * step,
      y,
      height,
      value: valueOf(node.id),
      share: parent ? percent(valueOf(node.id), valueOf(parent)) : '',
    })
  }

  // Bands leave their source stacked top-down and enter their target at its top.
  const sourceOffset = new Map<string, number>()
  const links: LaidLink[] = flow.links.flatMap((link) => {
    const source = byId.get(link.source)
    const target = byId.get(link.target)
    if (!source || !target) return []
    const h = band(link.value)
    const sy = source.y + (sourceOffset.get(source.id) ?? 0)
    sourceOffset.set(source.id, (sourceOffset.get(source.id) ?? 0) + h)
    const x0 = source.x + nodeWidth
    const x1 = target.x
    const ty = target.y
    const mid = (x0 + x1) / 2
    const path = [
      `M${x0},${sy}`,
      `C${mid},${sy} ${mid},${ty} ${x1},${ty}`,
      `L${x1},${ty + h}`,
      `C${mid},${ty + h} ${mid},${sy + h} ${x0},${sy + h}`,
      'Z',
    ].join(' ')
    return [
      {
        ...link,
        path,
        kind: target.kind,
        share: percent(link.value, source.value),
        sourceLabel: source.label,
        targetLabel: target.label,
      },
    ]
  })

  const nodes = [...byId.values()]
  const height = Math.max(0, ...nodes.map((n) => n.y + Math.max(n.height, minSlot)))
  return { nodes, links, height }
}
