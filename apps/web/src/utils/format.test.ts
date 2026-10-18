import { describe, expect, it } from 'vitest'
import { formatTime } from './format'

describe('formatTime', () => {
  it('converts UTC to the requested zone instead of showing UTC as local', () => {
    expect(formatTime('2026-10-18T17:05:56Z', 'UTC')).toBe('17:05:56')
    expect(formatTime('2026-10-18T17:05:56Z', 'Asia/Kolkata')).toBe('22:35:56') // the bug we had: 17:05
    expect(formatTime('2026-10-18T17:05:56.750041Z', 'America/New_York')).toBe('13:05:56')
  })
  it('treats legacy timestamps without a zone as UTC', () => {
    expect(formatTime('2026-10-18T17:05:56.750041', 'Asia/Kolkata')).toBe('22:35:56')
  })
  it('honours explicit offsets and survives garbage', () => {
    expect(formatTime('2026-10-18T22:35:56+05:30', 'UTC')).toBe('17:05:56')
    expect(formatTime('not a date')).toBe('not a date')
  })
})
