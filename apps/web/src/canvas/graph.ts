export interface Link {
  source: string
  target: string
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

export function checkConnection(edges: Link[], source: string | null, target: string | null): ConnectionCheck {
  if (!source || !target) return { ok: false, reason: 'Connect an output to an input' }
  if (source === target) return { ok: false, reason: 'A node cannot connect to itself' }
  if (edges.some((e) => e.source === source && e.target === target)) {
    return { ok: false, reason: 'These nodes are already connected' }
  }
  if (wouldCreateCycle(edges, source, target)) {
    return { ok: false, reason: 'That connection would create a loop' }
  }
  return { ok: true }
}
