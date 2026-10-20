import { useRef, type KeyboardEvent, type ReactNode } from 'react'

export interface TabSpec {
  id: string
  label: ReactNode
}

/** Id helpers so a tab and the panel it controls always point at each other. */
export const tabId = (prefix: string, id: string) => `${prefix}-tab-${id}`
export const panelId = (prefix: string, id: string) => `${prefix}-panel-${id}`

/** Props for the element that shows the selected tab's content. */
export const panelProps = (prefix: string, id: string) => ({
  role: 'tabpanel' as const,
  id: panelId(prefix, id),
  'aria-labelledby': tabId(prefix, id),
})

/**
 * Tabs that follow the WAI-ARIA pattern: one tab stop, Left/Right/Home/End move between tabs (and select),
 * each tab names the panel it controls.
 */
export function Tabs({
  label,
  prefix,
  tabs,
  value,
  onChange,
  className,
  controls = true,
}: {
  label: string
  prefix: string
  tabs: TabSpec[]
  value: string
  onChange: (id: string) => void
  className?: string
  controls?: boolean // false when the tabs switch the whole screen rather than a panel next to them
}) {
  const list = useRef<HTMLDivElement>(null)
  const onKeyDown = (e: KeyboardEvent) => {
    const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End']
    if (!keys.includes(e.key)) return
    e.preventDefault()
    const at = tabs.findIndex((t) => t.id === value)
    const next =
      e.key === 'Home'
        ? 0
        : e.key === 'End'
          ? tabs.length - 1
          : (at + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
    onChange(tabs[next]!.id)
    list.current?.querySelector<HTMLElement>(`#${tabId(prefix, tabs[next]!.id)}`)?.focus()
  }
  return (
    <div ref={list} role="tablist" aria-label={label} className={className}>
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          id={tabId(prefix, t.id)}
          aria-selected={t.id === value}
          aria-controls={controls ? panelId(prefix, t.id) : undefined}
          tabIndex={t.id === value ? 0 : -1}
          onClick={() => onChange(t.id)}
          onKeyDown={onKeyDown}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}
