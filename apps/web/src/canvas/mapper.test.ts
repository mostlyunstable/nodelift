import { describe, expect, it } from 'vitest'
import { fromWorkflow, toWorkflow, type FlowNode } from './mapper'

const nodes: FlowNode[] = [
  { id: 'a', type: 'node', position: { x: 1, y: 2 }, data: { name: 'A', nodeType: 'code.python', config: { source: 'S' }, testInput: '{}', idempotent: false, maxAttempts: 1 } },
  { id: 'b', type: 'node', position: { x: 3, y: 4 }, data: { name: 'B', nodeType: 'http.request', config: { url: 'https://x.test' }, testInput: '{}', idempotent: false, maxAttempts: 1 } },
]

describe('mapper', () => {
  it('only emits retry settings for idempotent nodes', () => {
    const mk = (idempotent: boolean, maxAttempts: number): FlowNode[] => [
      { ...nodes[0], data: { ...nodes[0].data, idempotent, maxAttempts } },
    ]
    expect(toWorkflow(mk(false, 3), []).nodes[0].config).toEqual({ source: 'S' })
    expect(toWorkflow(mk(true, 1), []).nodes[0].config).toEqual({ source: 'S', idempotent: true })
    const cfg = toWorkflow(mk(true, 3), []).nodes[0].config
    expect(cfg.retry).toEqual({ max_attempts: 3, backoff_ms: 500 })
    const back = fromWorkflow(toWorkflow(mk(true, 3), []))
    expect([back.nodes[0].data.idempotent, back.nodes[0].data.maxAttempts]).toEqual([true, 3])
  })
  it('keeps layout out of nodes and in ui', () => {
    const wf = toWorkflow(nodes, [{ id: 'e1', source: 'a', target: 'b' }])
    expect(wf.nodes[0]).toEqual({ id: 'a', type: 'code.python', name: 'A', config: { source: 'S' } })
    expect(wf.nodes[1].type).toBe('http.request')
    expect(wf.ui.positions.b).toEqual({ x: 3, y: 4 })
    expect(wf.edges[0].source).toEqual({ node: 'a', port: 'out' })
  })
  it('round-trips', () => {
    const wf = toWorkflow(nodes, [{ id: 'e1', source: 'a', target: 'b' }])
    const back = fromWorkflow(wf)
    expect(back.nodes.map((n) => [n.id, n.position, n.data.nodeType, n.data.config])).toEqual([
      ['a', { x: 1, y: 2 }, 'code.python', { source: 'S' }],
      ['b', { x: 3, y: 4 }, 'http.request', { url: 'https://x.test' }],
    ])
    expect(back.edges[0]).toMatchObject({ source: 'a', target: 'b' })
  })
})

describe('mapper ports', () => {
  it('sends the connection handles as ports and defaults to out/in', () => {
    const wf = toWorkflow(nodes, [
      { id: 'e1', source: 'a', target: 'b', sourceHandle: 'true', targetHandle: 'in' },
      { id: 'e2', source: 'a', target: 'b' },
    ])
    expect(wf.edges[0]).toMatchObject({ source: { node: 'a', port: 'true' }, target: { node: 'b', port: 'in' } })
    expect(wf.edges[1]).toMatchObject({ source: { node: 'a', port: 'out' }, target: { node: 'b', port: 'in' } })
  })
  it('restores handles and labels branch edges when reopening', () => {
    const wf = toWorkflow(nodes, [{ id: 'e1', source: 'a', target: 'b', sourceHandle: 'false', targetHandle: 'in' }])
    const back = fromWorkflow(wf).edges[0]
    expect(back).toMatchObject({ sourceHandle: 'false', targetHandle: 'in', label: 'false' })
    const plain = fromWorkflow(toWorkflow(nodes, [{ id: 'e2', source: 'a', target: 'b' }])).edges[0]
    expect(plain.label).toBeUndefined() // ordinary connections stay unlabelled
  })
})
