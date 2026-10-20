import { useMemo, useState, type KeyboardEvent } from 'react'
import { filterCommands, type Command } from '../app/commands'
import { Dialog } from './Dialog'

/** ⌘K: type to find any action. */
export function CommandPalette({ commands, onClose }: { commands: Command[]; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const results = useMemo(() => filterCommands(commands, query).slice(0, 12), [commands, query])
  const current = Math.min(active, Math.max(results.length - 1, 0))

  const choose = (cmd: Command | undefined) => {
    if (!cmd) return
    onClose()
    cmd.run()
  }

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      choose(results[current])
    }
  }

  return (
    <Dialog title="Command palette" onClose={onClose}>
      <input
        data-autofocus
        className="palette-input"
        placeholder="Type a command…"
        aria-label="Search commands"
        role="combobox"
        aria-expanded="true"
        aria-controls="palette-results"
        aria-activedescendant={results[current] ? `cmd-${results[current].id}` : undefined}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value)
          setActive(0)
        }}
        onKeyDown={onKeyDown}
      />
      <ul id="palette-results" role="listbox" className="palette-results">
        {results.length === 0 && <li className="muted pad">Nothing matches “{query}”.</li>}
        {results.map((cmd, i) => (
          // Options are chosen with the keyboard through the combobox input (aria-activedescendant).
          // eslint-disable-next-line jsx-a11y/click-events-have-key-events
          <li
            key={cmd.id}
            id={`cmd-${cmd.id}`}
            role="option"
            aria-selected={i === current}
            className={i === current ? 'active' : undefined}
            onMouseMove={() => setActive(i)}
            onClick={() => choose(cmd)}
          >
            <span className="palette-group">{cmd.group}</span>
            <span className="palette-title">{cmd.title}</span>
            {cmd.hint && <kbd>{cmd.hint}</kbd>}
          </li>
        ))}
      </ul>
    </Dialog>
  )
}
