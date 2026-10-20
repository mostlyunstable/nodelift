import { describe, expect, it } from 'vitest'
import { matchShortcut } from './shortcuts'

const key = (k: string, mods: Partial<{ meta: boolean; ctrl: boolean; shift: boolean; alt: boolean }> = {}, target?: EventTarget) => ({
  key: k,
  metaKey: !!mods.meta,
  ctrlKey: !!mods.ctrl,
  shiftKey: !!mods.shift,
  altKey: !!mods.alt,
  target,
})

describe('matchShortcut', () => {
  it('maps the documented shortcuts on Cmd and on Ctrl', () => {
    expect(matchShortcut(key('z', { meta: true }))).toBe('undo')
    expect(matchShortcut(key('Z', { meta: true, shift: true }))).toBe('redo')
    expect(matchShortcut(key('y', { ctrl: true }))).toBe('redo')
    expect(matchShortcut(key('s', { meta: true }))).toBe('save')
    expect(matchShortcut(key('Enter', { meta: true }))).toBe('run')
    expect(matchShortcut(key('.', { ctrl: true }))).toBe('cancel')
    expect(matchShortcut(key('k', { meta: true }))).toBe('palette')
  })
  it('ignores plain keys and Alt combinations', () => {
    expect(matchShortcut(key('z'))).toBeNull()
    expect(matchShortcut(key('s', { meta: true, alt: true }))).toBeNull()
  })
  it('leaves undo and redo to text fields and the code editor, but not palette/save/run', () => {
    const input = document.createElement('input')
    const editor = document.createElement('div')
    editor.className = 'monaco-editor'
    const inside = document.createElement('span')
    editor.appendChild(inside)
    expect(matchShortcut(key('z', { meta: true }, input))).toBeNull()
    expect(matchShortcut(key('z', { meta: true, shift: true }, inside))).toBeNull()
    expect(matchShortcut(key('k', { meta: true }, input))).toBe('palette')
    expect(matchShortcut(key('s', { meta: true }, inside))).toBe('save')
    expect(matchShortcut(key('Enter', { meta: true }, input))).toBe('run')
  })
})
