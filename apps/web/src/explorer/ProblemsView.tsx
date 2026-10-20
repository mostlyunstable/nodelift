import { useMemo } from 'react'
import { useExplorer } from '../state/explorer'

const ICON: Record<string, string> = { error: '✕', warning: '⚠', info: 'ℹ' }

/** Every diagnostic found by analysis, grouped by file. Selecting one opens the file at that line. */
export function ProblemsView() {
  const diagnostics = useExplorer((s) => s.diagnostics)
  const status = useExplorer((s) => s.revision?.analysis_status)
  const goTo = useExplorer((s) => s.goTo)
  const setTab = useExplorer((s) => s.setTab)
  const groups = useMemo(() => {
    const m = new Map<string, typeof diagnostics>()
    for (const d of diagnostics) m.set(d.path, [...(m.get(d.path) ?? []), d])
    return [...m.entries()]
  }, [diagnostics])

  if (status === 'analyzing') return <div className="viewer-empty muted">Analyzing…</div>
  if (groups.length === 0)
    return (
      <div className="viewer-empty muted">
        No problems found. Analysis only reports syntax errors and unresolved relative imports; it is not a
        linter or a test run.
      </div>
    )
  return (
    <div className="problems">
      {groups.map(([path, list]) => (
        <section key={path}>
          <h4>
            {path} <span className="muted">{list.length}</span>
          </h4>
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
    </div>
  )
}
