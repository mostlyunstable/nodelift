export interface Link {
  source: string
  target: string
  sourceHandle?: string | null
  targetHandle?: string | null
}

/** True if adding source -> target would create a cycle (including a self-loop). */
export function wouldCreateCycle(edges: Link[], source: string, target: string): boolean {
  if (source === target) return true
  const next = new Map<string, string[]>()
  for (const e of edges) next.set(e.source, [...(next.get(e.source) ?? []), e.target])
  const seen = new Set<string>()
  const stack = [target]
  while (stack.length > 0) {
    const node = stack.pop() as string
    if (node === source) return true // target already leads back to source
    if (seen.has(node)) continue
    seen.add(node)
    stack.push(...(next.get(node) ?? []))
  }
  return false
}

export type ConnectionCheck = { ok: true } | { ok: false; reason: string }

export function checkConnection(
  edges: Link[],
  source: string | null,
  target: string | null,
  sourceHandle: string | null = null,
  targetHandle: string | null = null,
): ConnectionCheck {
  if (!source || !target) return { ok: false, reason: 'Connect an output to an input' }
  if (source === target) return { ok: false, reason: 'A node cannot connect to itself' }
  const handle = (h: string | null | undefined, fallback: string) => h ?? fallback
  const same = (e: Link) =>
    e.source === source &&
    e.target === target &&
    handle(e.sourceHandle, 'out') === handle(sourceHandle, 'out') &&
    handle(e.targetHandle, 'in') === handle(targetHandle, 'in')
  if (edges.some(same)) {
    return { ok: false, reason: 'That connection already exists' }
  }
  if (wouldCreateCycle(edges, source, target)) {
    return { ok: false, reason: 'That connection would create a loop' }
  }
  return { ok: true }
}

export interface Pos {
  x: number
  y: number
}

/**
 * Left-to-right layers for a workflow: every node sits one column to the right of the furthest node that feeds it, columns are
 * centred, and nodes within a column are ordered by where their inputs are (which keeps lines from crossing needlessly).
 * Nodes that are not connected to anything are set in a row underneath instead of being strewn across the first column.
 */
export function tidyLayout(
  nodes: { id: string }[],
  edges: Link[],
  size = { w: 240, h: 96, gapX: 90, gapY: 36 },
): Record<string, Pos> {
  const ids = nodes.map((n) => n.id)
  const incoming = new Map<string, string[]>(ids.map((i) => [i, []]))
  const outgoing = new Map<string, string[]>(ids.map((i) => [i, []]))
  for (const e of edges) {
    if (!incoming.has(e.source) || !incoming.has(e.target) || e.source === e.target) continue
    incoming.get(e.target)!.push(e.source)
    outgoing.get(e.source)!.push(e.target)
  }
  const connected = ids.filter((i) => incoming.get(i)!.length > 0 || outgoing.get(i)!.length > 0)
  const lonely = ids.filter((i) => !connected.includes(i))

  // depth = longest path from a node with no inputs (the graph is acyclic; guard anyway)
  const depth = new Map<string, number>()
  const visiting = new Set<string>()
  const depthOf = (id: string): number => {
    const known = depth.get(id)
    if (known !== undefined) return known
    if (visiting.has(id)) return 0
    visiting.add(id)
    const d = Math.max(-1, ...incoming.get(id)!.map(depthOf)) + 1
    visiting.delete(id)
    depth.set(id, d)
    return d
  }
  const layers: string[][] = []
  for (const id of connected) {
    const d = depthOf(id)
    ;(layers[d] ??= []).push(id)
  }
  const rowY = new Map<string, number>()
  const out: Record<string, Pos> = {}
  const colH = (n: number) => n * size.h + Math.max(0, n - 1) * size.gapY
  const tallest = Math.max(0, ...layers.map((l) => colH(l?.length ?? 0)))
  layers.forEach((layer, col) => {
    if (!layer) return
    const bary = (id: string) => {
      const ys = incoming.get(id)!.map((p) => rowY.get(p) ?? 0)
      return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : 0
    }
    const ordered = [...layer].sort((a, b) => bary(a) - bary(b) || ids.indexOf(a) - ids.indexOf(b))
    const top = (tallest - colH(ordered.length)) / 2
    ordered.forEach((id, i) => {
      const y = top + i * (size.h + size.gapY)
      rowY.set(id, y)
      out[id] = { x: col * (size.w + size.gapX), y }
    })
  })
  const baseY = tallest + (tallest > 0 ? size.gapY * 2 : 0)
  lonely.forEach((id, i) => {
    out[id] = { x: i * (size.w + size.gapX / 2), y: baseY }
  })
  return out
}
