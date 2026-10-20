import type { WorkflowDefinition } from '../types/workflow'

export interface WorkflowDiff {
  added: string[] // node names present only in `to`
  removed: string[] // node names present only in `from`
  changed: { name: string; what: string[] }[]
  edgesAdded: number
  edgesRemoved: number
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const edgeKey = (e: WorkflowDefinition['edges'][number]) =>
  `${e.source.node}:${e.source.port}>${e.target.node}:${e.target.port}`

/** What changed going from one workflow to another. Layout (node positions) is ignored on purpose. */
export function diffWorkflows(from: WorkflowDefinition, to: WorkflowDefinition): WorkflowDiff {
  const a = new Map(from.nodes.map((n) => [n.id, n]))
  const b = new Map(to.nodes.map((n) => [n.id, n]))
  const diff: WorkflowDiff = { added: [], removed: [], changed: [], edgesAdded: 0, edgesRemoved: 0 }
  for (const [id, node] of b) if (!a.has(id)) diff.added.push(node.name || node.id)
  for (const [id, node] of a) if (!b.has(id)) diff.removed.push(node.name || node.id)
  for (const [id, before] of a) {
    const after = b.get(id)
    if (!after) continue
    const what: string[] = []
    if (before.type !== after.type) what.push('type')
    if (before.name !== after.name) what.push('name')
    for (const key of new Set([...Object.keys(before.config), ...Object.keys(after.config)])) {
      if (!same(before.config[key], after.config[key])) what.push(key === 'source' ? 'code' : key)
    }
    if (what.length > 0) diff.changed.push({ name: after.name || id, what })
  }
  const ea = new Set(from.edges.map(edgeKey))
  const eb = new Set(to.edges.map(edgeKey))
  diff.edgesAdded = [...eb].filter((k) => !ea.has(k)).length
  diff.edgesRemoved = [...ea].filter((k) => !eb.has(k)).length
  return diff
}

export const isEmptyDiff = (d: WorkflowDiff) =>
  d.added.length + d.removed.length + d.changed.length + d.edgesAdded + d.edgesRemoved === 0
