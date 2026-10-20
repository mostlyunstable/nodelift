import { describe, expect, it } from 'vitest'
import { checkConnection, wouldCreateCycle } from './graph'

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
      { source: 'a', target: 'b' }, { source: 'a', target: 'c' },
      { source: 'b', target: 'd' }, { source: 'c', target: 'd' },
    ]
    expect(wouldCreateCycle(diamond, 'x', 'a')).toBe(false)
    expect(wouldCreateCycle(diamond, 'd', 'a')).toBe(true)
  })
  it('copes with an already-cyclic input without hanging', () => {
    const cyclic = [{ source: 'a', target: 'b' }, { source: 'b', target: 'a' }]
    expect(wouldCreateCycle(cyclic, 'x', 'a')).toBe(false)
  })
})

describe('checkConnection', () => {
  it('explains each refusal', () => {
    expect(checkConnection([], null, 'a')).toMatchObject({ ok: false })
    expect(checkConnection([], 'a', 'a')).toEqual({ ok: false, reason: 'A node cannot connect to itself' })
    expect(checkConnection(chain, 'a', 'b')).toEqual({ ok: false, reason: 'These nodes are already connected' })
    expect(checkConnection(chain, 'd', 'a')).toEqual({ ok: false, reason: 'That connection would create a loop' })
    expect(checkConnection(chain, 'a', 'd')).toEqual({ ok: true })
  })
})
