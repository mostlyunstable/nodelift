export type ShortcutAction = 'undo' | 'redo' | 'save' | 'run' | 'cancel' | 'palette'

interface KeyLike {
  key: string
  metaKey: boolean
  ctrlKey: boolean
  shiftKey: boolean
  altKey: boolean
  target?: EventTarget | null
}

/** Typing in a text field or the code editor must keep its own undo and shortcuts. */
export function isTextTarget(target: EventTarget | null | undefined): boolean {
  const el = target as HTMLElement | null
  if (!el || typeof el.closest !== 'function') return false
  if (el.closest('.monaco-editor')) return true
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

/** Maps a keydown to an app action. Cmd on macOS, Ctrl elsewhere. */
export function matchShortcut(e: KeyLike): ShortcutAction | null {
  const mod = e.metaKey || e.ctrlKey
  if (!mod || e.altKey) return null
  const key = e.key.toLowerCase()
  const text = isTextTarget(e.target)
  if (key === 'k') return 'palette' // works everywhere, including inside text fields
  if (key === 's') return 'save'
  if (key === 'enter') return 'run'
  if (key === '.') return 'cancel'
  if (text) return null // let inputs and Monaco handle undo/redo themselves
  if (key === 'z') return e.shiftKey ? 'redo' : 'undo'
  if (key === 'y') return 'redo'
  return null
}
