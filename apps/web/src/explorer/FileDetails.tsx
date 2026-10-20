import { useState } from 'react'
import type { FileAnalysis, RepoEdge } from '../api/client'
import { useExplorer } from '../state/explorer'
import { NodeFromFunctionDialog } from './NodeFromFunctionDialog'

const SEVERITY_ICON: Record<string, string> = { error: '✕', warning: '⚠', info: 'ℹ' }

function Rel({ e, to }: { e: RepoEdge; to: 'dst' | 'src' }) {
  const goTo = useExplorer((s) => s.goTo)
  const path = to === 'dst' ? e.dst : e.src
  if (!path) return null
  return (
    <li>
      <button
        className="link-button path-link"
        onClick={() => void goTo(path, to === 'src' ? e.line : undefined)}
        title={`Open ${path}`}
      >
        {path}
      </button>{' '}
      <span className="muted">
        line {e.line} · {e.kind.replace('_', ' ')}
        {e.confidence !== 'resolved' && <span className={`conf conf-${e.confidence}`}> {e.confidence}</span>}
        {e.note ? ` · ${e.note}` : ''}
      </span>
    </li>
  )
}

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="detail-section">
      <h2>
        {title}
        {count !== undefined && <span className="muted"> {count}</span>}
      </h2>
      {children}
    </section>
  )
}

export function FileDetails({ analysis, path }: { analysis: FileAnalysis | null; path: string }) {
  const goTo = useExplorer((s) => s.goTo)
  const meta = useExplorer((s) => s.files.find((f) => f.path === path))
  const rev = useExplorer((s) => s.revision)
  const [symbolFilter, setSymbolFilter] = useState('')
  const [makeNode, setMakeNode] = useState<string | null>(null)
  if (!analysis) return <div className="viewer-empty muted">Analysis for this file is not available yet.</div>

  const calls = analysis.references
  const callers = analysis.called_by
  const internal = analysis.imports.filter((e) => e.dst && e.kind !== 'tests')
  const external = analysis.imports.filter((e) => !e.dst && e.confidence === 'external')
  const unresolved = analysis.imports.filter((e) => !e.dst && e.confidence === 'unresolved')
  const testsOf = analysis.imports.filter((e) => e.kind === 'tests')
  const importedBy = analysis.dependents.filter((e) => e.kind !== 'tests')
  const testedBy = analysis.dependents.filter((e) => e.kind === 'tests')
  const q = symbolFilter.trim().toLowerCase()
  const symbols = analysis.symbols.filter((s) => !q || s.name.toLowerCase().includes(q))

  return (
    <div className="details" role="region" tabIndex={0} aria-label="File details">
      <Section title="File">
        <dl className="stats small">
          <dt>Language</dt>
          <dd>{meta?.language}</dd>
          <dt>Analysis</dt>
          <dd>{analysis.status.replace('_', ' ')}</dd>
          <dt>Revision</dt>
          <dd>
            <code>{rev?.commit_sha.slice(0, 7)}</code>
          </dd>
        </dl>
        {analysis.status === 'unsupported' && (
          <p className="muted small">No analyzer for this language yet; it is shown but not analyzed.</p>
        )}
      </Section>

      {analysis.diagnostics.length > 0 && (
        <Section title="Problems" count={analysis.diagnostics.length}>
          <ul className="detail-list">
            {analysis.diagnostics.map((d, i) => (
              <li key={i}>
                <button className="link-button" onClick={() => void goTo(path, d.line)}>
                  <span className={`sev sev-${d.severity}`}>{SEVERITY_ICON[d.severity] ?? '•'}</span> line{' '}
                  {d.line}
                </button>{' '}
                {d.message} <span className="muted">({d.source})</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {analysis.symbols.length > 0 && (
        <Section title="Symbols" count={analysis.symbols.length}>
          {analysis.symbols.length > 12 && (
            <input
              type="search"
              aria-label="Filter symbols"
              placeholder="Filter symbols…"
              value={symbolFilter}
              onChange={(e) => setSymbolFilter(e.target.value)}
            />
          )}
          <ul className="detail-list">
            {symbols.map((s, i) => (
              <li key={`${s.name}:${s.line}:${i}`}>
                <button className="link-button" onClick={() => void goTo(path, s.line)}>
                  {s.parent ? `${s.parent}.` : ''}
                  {s.name}
                </button>{' '}
                <span className="muted">
                  {s.kind} · line {s.line}
                  {s.exported ? '' : ' · private'}
                </span>
                {s.kind === 'function' && !s.parent && meta?.language === 'python' && (
                  <>
                    {' '}
                    <button className="link-button" onClick={() => setMakeNode(s.name)}>
                      Make node…
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {calls.length > 0 && (
        <Section title="Calls to definitions in this repository" count={calls.length}>
          <ul className="detail-list">
            {calls.map((r, i) => (
              <li key={i}>
                <button className="link-button" onClick={() => void goTo(path, r.line)}>
                  line {r.line}
                </button>{' '}
                <span className="muted">{r.scope ?? 'module'}</span> →{' '}
                <button className="link-button path-link" onClick={() => void goTo(r.dst_path, r.dst_line)}>
                  {r.dst_symbol}
                </button>{' '}
                <span className="muted">
                  {r.dst_path}:{r.dst_line}
                  {r.confidence !== 'resolved' && (
                    <span className={`conf conf-${r.confidence}`}> {r.confidence}</span>
                  )}
                  {r.note ? ` · ${r.note}` : ''}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {callers.length > 0 && (
        <Section title="Called from other files" count={callers.length}>
          <ul className="detail-list">
            {callers.map((r, i) => (
              <li key={i}>
                <button className="link-button path-link" onClick={() => void goTo(r.path, r.line)}>
                  {r.path}:{r.line}
                </button>{' '}
                <span className="muted">
                  in {r.scope ?? 'module'} calls {r.dst_symbol}
                  {r.confidence !== 'resolved' && (
                    <span className={`conf conf-${r.confidence}`}> {r.confidence}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Imports (in this repository)" count={internal.length}>
        {internal.length === 0 ? (
          <p className="muted small">None found.</p>
        ) : (
          <ul className="detail-list">
            {internal.map((e, i) => (
              <Rel key={i} e={e} to="dst" />
            ))}
          </ul>
        )}
      </Section>

      <Section title="Imported by" count={importedBy.length}>
        {importedBy.length === 0 ? (
          <p className="muted small">
            Nothing in the repository imports this file (as far as static analysis can tell).
          </p>
        ) : (
          <ul className="detail-list">
            {importedBy.map((e, i) => (
              <Rel key={i} e={e} to="src" />
            ))}
          </ul>
        )}
      </Section>

      {(testedBy.length > 0 || testsOf.length > 0) && (
        <Section title="Tests (matched by file name)" count={testedBy.length + testsOf.length}>
          <ul className="detail-list">
            {testedBy.map((e, i) => (
              <Rel key={`t${i}`} e={e} to="src" />
            ))}
            {testsOf.map((e, i) => (
              <Rel key={`o${i}`} e={e} to="dst" />
            ))}
          </ul>
        </Section>
      )}

      {unresolved.length > 0 && (
        <Section title="Could not be resolved" count={unresolved.length}>
          <ul className="detail-list">
            {unresolved.map((e, i) => (
              <li key={i}>
                <button className="link-button" onClick={() => void goTo(path, e.line)}>
                  line {e.line}
                </button>{' '}
                <code>{e.raw || '(computed at runtime)'}</code> <span className="muted">{e.note}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {external.length > 0 && (
        <Section title="External (not in the repository)" count={external.length}>
          <ul className="detail-list">
            {external.map((e, i) => (
              <li key={i}>
                <button className="link-button" onClick={() => void goTo(path, e.line)}>
                  line {e.line}
                </button>{' '}
                <code>{e.raw}</code> <span className="muted">{e.note}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {makeNode && rev && (
        <NodeFromFunctionDialog
          revisionId={rev.id}
          path={path}
          symbol={makeNode}
          onClose={() => setMakeNode(null)}
        />
      )}
    </div>
  )
}
