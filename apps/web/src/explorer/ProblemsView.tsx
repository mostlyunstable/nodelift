import { useMemo } from 'react'
import { useExplorer } from '../state/explorer'

const ICON: Record<string, string> = { error: '✕', warning: '⚠', info: 'ℹ' }

/** Every diagnostic found by analysis, grouped by file. Selecting one opens the file at that line. */
export function ProblemsView() {
  const all = useExplorer((s) => s.diagnostics)
  const diagnostics = useMemo(() => all.filter((d) => d.severity !== 'info'), [all])
  const notes = useMemo(() => all.filter((d) => d.severity === 'info'), [all])
  const status = useExplorer((s) => s.revision?.analysis_status)
  const goTo = useExplorer((s) => s.goTo)
  const setTab = useExplorer((s) => s.setTab)
  const groups = useMemo(() => {
    const m = new Map<string, typeof diagnostics>()
    for (const d of diagnostics) m.set(d.path, [...(m.get(d.path) ?? []), d])
    return [...m.entries()]
  }, [diagnostics])

  if (status === 'analyzing') return <div className="viewer-empty muted">Analyzing…</div>
  if (groups.length === 0 && notes.length === 0)
    return (
      <div className="viewer-empty muted">
        No problems found. Analysis only reports syntax errors and unresolved relative imports; it is not a
        linter or a test run.
      </div>
    )
  return (
    <div className="problems" role="region" tabIndex={0} aria-label="Problems">
      {groups.length === 0 && (
        <p className="muted small">
          No problems found. Analysis only reports syntax errors and unresolved relative imports; it is not a
          linter or a test run.
        </p>
      )}
      {groups.map(([path, list]) => (
        <section key={path}>
          <h2>
            {path} <span className="muted">{list.length}</span>
          </h2>
          <ul className="detail-list">
            {list.map((d, i) => (
              <li key={i}>
                <button
                  className="link-button"
                  onClick={() => {
                    setTab('code')
                    void goTo(path, d.line)
                  }}
                >
                  <span className={`sev sev-${d.severity}`}>{ICON[d.severity] ?? '•'}</span> line {d.line}
                </button>{' '}
                {d.message} <span className="muted">({d.source})</span>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {notes.length > 0 && (
        <details className="notes">
          <summary>
            {notes.length} note{notes.length === 1 ? '' : 's'} (not problems)
          </summary>
          <p className="muted small">
            Places the parser could not fully read (for example Flow or other non-standard syntax) and imports
            of files that are not in the repository, such as build output. They are shown for completeness.
          </p>
          <ul className="detail-list">
            {notes.slice(0, 300).map((d, i) => (
              <li key={i}>
                <button
                  className="link-button path-link"
                  onClick={() => {
                    setTab('code')
                    void goTo(d.path, d.line)
                  }}
                >
                  {d.path}:{d.line}
                </button>{' '}
                <span className="muted">{d.message}</span>
              </li>
            ))}
          </ul>
          {notes.length > 300 && <p className="muted small">and {notes.length - 300} more</p>}
        </details>
      )}
    </div>
  )
}
