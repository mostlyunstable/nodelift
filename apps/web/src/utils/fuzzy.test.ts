import { describe, expect, it } from 'vitest'
import { fuzzyScore, rank } from './fuzzy'

describe('fuzzyScore', () => {
  it('matches subsequences in order and rejects everything else', () => {
    expect(fuzzyScore('rw', 'Run workflow')).not.toBeNull()
    expect(fuzzyScore('wr', 'Run workflow')).not.toBeNull() // w..r exists later in the word
    expect(fuzzyScore('xyz', 'Run workflow')).toBeNull()
    expect(fuzzyScore('nur', 'Run workflow')).toBeNull() // letters exist but not in that order
  })
  it('an empty query matches everything equally', () => expect(fuzzyScore('  ', 'anything')).toBe(0))
  it('is case-insensitive and ignores spaces in the query', () => {
    expect(fuzzyScore('RUN WORK', 'run workflow')).not.toBeNull()
  })
  it('ranks prefix and word-start matches above scattered ones', () => {
    const ordered = rank(['Open workflow', 'Run workflow', 'Undo', 'Save version', 'Show versions'], 'run', (s) => s)
    expect(ordered[0]).toBe('Run workflow')
    const sv = rank(['Show versions', 'Save version', 'Validate workflow'], 'sv', (s) => s)
    expect(sv.slice(0, 2).sort()).toEqual(['Save version', 'Show versions'])
  })
  it('keeps the original order for equal scores and drops non-matches', () => {
    expect(rank(['aa', 'ab', 'zz'], 'a', (s) => s)).toEqual(['aa', 'ab'])
  })
})
