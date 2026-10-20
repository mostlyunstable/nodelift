import { describe, expect, it } from 'vitest'
import { checkConnection, tidyLayout, wouldCreateCycle } from './graph'

const chain = [
  { source: 'a', target: 'b' },
  { source: 'b', target: 'c' },
  { source: 'c', target: 'd' },
]

describe('wouldCreateCycle', () => {
  it('rejects self-loops', () => expect(wouldCreateCycle([], 'a', 'a')).toBe(true))
  it('rejects an edge that closes a loop, however long', () => {
    expect(wouldCreateCycle(chain, 'd', 'a')).toBe(true)
    expect(wouldCreateCycle(chain, 'c', 'a')).toBe(true)
    expect(wouldCreateCycle(chain, 'b', 'a')).toBe(true)
  })
  it('allows forward, parallel and diamond-shaped connections', () => {
    expect(wouldCreateCycle(chain, 'a', 'd')).toBe(false) // shortcut
    expect(wouldCreateCycle(chain, 'a', 'c')).toBe(false)
    expect(wouldCreateCycle([{ source: 'a', target: 'b' }], 'a', 'c')).toBe(false) // fan-out
    expect(wouldCreateCycle([{ source: 'a', target: 'c' }], 'b', 'c')).toBe(false) // fan-in
  })
  it('handles disconnected graphs and diamonds without looping forever', () => {
    const diamond = [
      { source: 'a', target: 'b' },
      { source: 'a', target: 'c' },
      { source: 'b', target: 'd' },
      { source: 'c', target: 'd' },
    ]
    expect(wouldCreateCycle(diamond, 'x', 'a')).toBe(false)
    expect(wouldCreateCycle(diamond, 'd', 'a')).toBe(true)
  })
  it('copes with an already-cyclic input without hanging', () => {
    const cyclic = [
      { source: 'a', target: 'b' },
      { source: 'b', target: 'a' },
    ]
    expect(wouldCreateCycle(cyclic, 'x', 'a')).toBe(false)
  })
})

describe('checkConnection', () => {
  it('explains each refusal', () => {
    expect(checkConnection([], null, 'a')).toMatchObject({ ok: false })
    expect(checkConnection([], 'a', 'a')).toEqual({ ok: false, reason: 'A node cannot connect to itself' })
    expect(checkConnection(chain, 'a', 'b')).toEqual({ ok: false, reason: 'That connection already exists' })
    expect(checkConnection(chain, 'd', 'a')).toEqual({
      ok: false,
      reason: 'That connection would create a loop',
    })
    expect(checkConnection(chain, 'a', 'd')).toEqual({ ok: true })
  })
})

describe('checkConnection with ports', () => {
  const branchEdges = [{ source: 'b', target: 't', sourceHandle: 'true', targetHandle: 'in' }]
  it('allows the two outputs of a branch to feed the same node', () => {
    expect(checkConnection(branchEdges, 'b', 't', 'false', 'in')).toEqual({ ok: true })
  })
  it('still refuses an exact duplicate, treating missing handles as the defaults', () => {
    expect(checkConnection(branchEdges, 'b', 't', 'true', 'in')).toMatchObject({ ok: false })
    expect(checkConnection([{ source: 'a', target: 'c' }], 'a', 'c', 'out', 'in')).toMatchObject({
      ok: false,
    })
    expect(checkConnection([{ source: 'a', target: 'c' }], 'a', 'c', null, null)).toMatchObject({ ok: false })
  })
  it('still refuses loops regardless of ports', () => {
    expect(checkConnection(branchEdges, 't', 'b', 'out', 'in')).toMatchObject({ ok: false })
  })
})

describe('tidyLayout', () => {
  const ids = (...a: string[]) => a.map((id) => ({ id }))
  const link = (source: string, target: string) => ({ source, target }) as never
  const overlaps = (p: Record<string, { x: number; y: number }>) => {
    const k = Object.keys(p)
    return k.some((a, i) =>
      k.slice(i + 1).some((b) => Math.abs(p[a].x - p[b].x) < 240 && Math.abs(p[a].y - p[b].y) < 96),
    )
  }

  it('puts each node in a column by depth, left to right', () => {
    const p = tidyLayout(ids('a', 'b', 'c'), [link('a', 'b'), link('b', 'c')])
    expect(p.a.x).toBeLessThan(p.b.x)
    expect(p.b.x).toBeLessThan(p.c.x)
  })

  it('never overlaps nodes, including fan-out and fan-in', () => {
    const p = tidyLayout(ids('a', 'b', 'c', 'd', 'e'), [
      link('a', 'b'),
      link('a', 'c'),
      link('a', 'd'),
      link('b', 'e'),
      link('c', 'e'),
    ])
    expect(Object.keys(p)).toHaveLength(5)
    expect(overlaps(p)).toBe(false)
  })

  it('sets unconnected nodes in a row below the graph', () => {
    const p = tidyLayout(ids('a', 'b', 'x', 'y'), [link('a', 'b')])
    expect(p.x.y).toBe(p.y.y)
    expect(p.x.y).toBeGreaterThan(p.a.y)
    expect(p.x.x).not.toBe(p.y.x)
  })

  it('survives a cycle and ignores unknown edges', () => {
    const p = tidyLayout(ids('a', 'b'), [link('a', 'b'), link('b', 'a'), link('a', 'zzz')])
    expect(Object.keys(p).sort()).toEqual(['a', 'b'])
  })
})
