import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react'

export interface MenuItem {
  label: string
  onSelect: () => void
  hint?: string
  disabled?: boolean
  danger?: boolean
  separatorBefore?: boolean
  heading?: string // a small title shown above this item (and the ones after it)
}

/** A button that opens a list of actions. Arrow keys move, Enter picks, Esc and outside clicks close. */
export function Menu({
  label,
  ariaLabel,
  items,
  align = 'left',
}: {
  label: string
  ariaLabel: string
  items: MenuItem[]
  align?: 'left' | 'right'
}) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const [place, setPlace] = useState<CSSProperties>({})

  // The list is positioned against the window, not its parent: the toolbar scrolls sideways in narrow windows, and a
  // list inside it would be clipped (and scroll the toolbar) instead of floating over the page.
  useLayoutEffect(() => {
    if (!open) return
    const at = root.current?.querySelector('button')?.getBoundingClientRect()
    if (!at) return
    const top = at.bottom + 4
    setPlace({
      top,
      maxHeight: Math.max(160, window.innerHeight - top - 12),
      ...(align === 'right'
        ? { right: Math.max(8, window.innerWidth - at.right) }
        : { left: Math.max(8, at.left) }),
    })
  }, [open, align])

  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    window.addEventListener('resize', close)
    return () => window.removeEventListener('resize', close)
  }, [open])

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', away)
    root.current?.querySelector<HTMLElement>('[role="menuitem"]:not([disabled])')?.focus()
    return () => document.removeEventListener('mousedown', away)
  }, [open])

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      setOpen(false)
      root.current?.querySelector<HTMLElement>('button')?.focus()
      return
    }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
    e.preventDefault()
    const entries = [
      ...(root.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? []),
    ]
    const at = entries.indexOf(document.activeElement as HTMLElement)
    const next =
      e.key === 'ArrowDown' ? (at + 1) % entries.length : (at - 1 + entries.length) % entries.length
    entries[next]?.focus()
  }

  return (
    <div className="menu" role="presentation" ref={root} onKeyDown={onKeyDown}>
      <button
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => setOpen((o) => !o)}
      >
        {label}
      </button>
      {open && (
        <div role="menu" aria-label={ariaLabel} className="menu-list" style={place}>
          {items.map((item, i) => (
            <div key={`${item.label}-${i}`}>
              {item.separatorBefore && <hr />}
              {item.heading && <div className="menu-heading">{item.heading}</div>}
              <button
                role="menuitem"
                disabled={item.disabled}
                className={item.danger ? 'danger' : undefined}
                onClick={() => {
                  setOpen(false)
                  item.onSelect()
                }}
              >
                <span>{item.label}</span>
                {item.hint && <kbd>{item.hint}</kbd>}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
