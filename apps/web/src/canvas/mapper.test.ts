import { describe, expect, it } from 'vitest'
import { fromWorkflow, toWorkflow, type FlowNode } from './mapper'

const nodes: FlowNode[] = [
  { id: 'a', type: 'code', position: { x: 1, y: 2 }, data: { name: 'A', source: 'S', testInput: '{}' } },
  { id: 'b', type: 'code', position: { x: 3, y: 4 }, data: { name: 'B', source: 'T', testInput: '{}' } },
]

describe('mapper', () => {
  it('keeps layout out of nodes and in ui', () => {
    const wf = toWorkflow(nodes, [{ id: 'e1', source: 'a', target: 'b' }])
    expect(wf.nodes[0]).toEqual({ id: 'a', type: 'code.python', name: 'A', config: { source: 'S' } })
    expect(wf.ui.positions.b).toEqual({ x: 3, y: 4 })
    expect(wf.edges[0].source).toEqual({ node: 'a', port: 'out' })
  })
  it('round-trips', () => {
    const wf = toWorkflow(nodes, [{ id: 'e1', source: 'a', target: 'b' }])
    const back = fromWorkflow(wf)
    expect(back.nodes.map((n) => [n.id, n.position, n.data.source])).toEqual([
      ['a', { x: 1, y: 2 }, 'S'],
      ['b', { x: 3, y: 4 }, 'T'],
    ])
    expect(back.edges[0]).toMatchObject({ source: 'a', target: 'b' })
  })
})
