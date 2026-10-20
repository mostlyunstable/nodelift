import { describe, expect, it } from 'vitest'
import type { WorkflowDefinition, WorkflowNode } from '../types/workflow'
import { diffWorkflows, isEmptyDiff } from './diff'

const node = (id: string, source = 'x', extra: Partial<WorkflowNode> = {}): WorkflowNode => ({
  id, type: 'code.python', name: id.toUpperCase(), config: { source }, ...extra,
})
const wf = (nodes: WorkflowNode[], edges: [string, string][] = [], positions = {}): WorkflowDefinition => ({
  schema_version: 1, id: '', name: 'w', nodes,
  edges: edges.map(([a, b]) => ({ id: '', source: { node: a, port: 'out' }, target: { node: b, port: 'in' } })),
  ui: { positions },
})

describe('diffWorkflows', () => {
  it('is empty for identical workflows, even when nodes were only moved', () => {
    const a = wf([node('a')], [], { a: { x: 0, y: 0 } })
    const b = wf([node('a')], [], { a: { x: 500, y: 90 } })
    expect(isEmptyDiff(diffWorkflows(a, b))).toBe(true)
  })
  it('reports added, removed and changed nodes by name', () => {
    const d = diffWorkflows(wf([node('a'), node('b')]), wf([node('b', 'y'), node('c')]))
    expect(d.added).toEqual(['C'])
    expect(d.removed).toEqual(['A'])
    expect(d.changed).toEqual([{ name: 'B', what: ['code'] }])
  })
  it('says which parts of a node changed', () => {
    const before = wf([node('a')])
    const after = wf([{ ...node('a'), name: 'Renamed', config: { source: 'x', idempotent: true } }])
    expect(diffWorkflows(before, after).changed).toEqual([{ name: 'Renamed', what: ['name', 'idempotent'] }])
  })
  it('counts edges added and removed', () => {
    const d = diffWorkflows(wf([node('a'), node('b'), node('c')], [['a', 'b']]), wf([node('a'), node('b'), node('c')], [['b', 'c'], ['a', 'c']]))
    expect(d).toMatchObject({ edgesAdded: 2, edgesRemoved: 1 })
  })
})
