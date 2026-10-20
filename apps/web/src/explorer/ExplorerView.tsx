import { useEffect } from 'react'
import { useExplorer } from '../state/explorer'
import { ExplorerGraph } from './ExplorerGraph'
import { FileTree } from './FileTree'
import { FilePanel } from './FilePanel'
import { ProblemsView } from './ProblemsView'
import { RunView } from './RunView'
import { formatBytes } from './tree'

const EXAMPLES = [
  { label: 'octocat/Spoon-Knife (3 files)', url: 'https://github.com/octocat/Spoon-Knife' },
  { label: 'pallets/flask (a Python web framework)', url: 'https://github.com/pallets/flask' },
]

export function ExplorerView({ theme }: { theme: 'dark' | 'light' }) {
  const e = useExplorer()
  useEffect(() => {
    void useExplorer.getState().loadRevisions()
  }, [])
  const rev = e.revision

  return (
    <main className={`explorer${e.sidebarOpen ? '' : ' side-collapsed'}`}>
      <aside className="explorer-side" hidden={!e.sidebarOpen}>
        <form
          className="import-form"
          onSubmit={(ev) => {
            ev.preventDefault()
            void e.showNodes()
          }}
        >
          <label htmlFor="repo-url">GitHub repository</label>
          <input
            id="repo-url"
            type="url"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            placeholder="https://github.com/owner/repo"
            value={e.url}
            onChange={(ev) => e.setUrl(ev.target.value)}
            onPaste={(ev) => {
              // pasting a repository link starts the import straight away
              const text = ev.clipboardData.getData('text').trim()
              if (/^(https:\/\/)?(www\.)?github\.com\/[^/\s]+\/[^/\s]+/i.test(text)) {
                ev.preventDefault()
                e.setUrl(text)
                void useExplorer.getState().showNodes()
              }
            }}
          />
          <button className="primary" type="submit" disabled={e.starting || !e.url.trim()}>
            {e.starting ? 'Checking…' : 'Show Nodes'}
          </button>
          <p className="muted small">
            Paste a link and the nodes are made. Public repositories only; nothing from the repository is ever
            run.
          </p>
        </form>

        {e.error && (
          <div className="explorer-error" role="alert">
            {e.error}
          </div>
        )}

        {rev && (
          <section className="rev-card" aria-label="Repository">
            <strong>{rev.full_name}</strong>
            <div className="muted small">
              {rev.branch} @ <code title={rev.commit_sha}>{rev.commit_sha.slice(0, 7)}</code>
            </div>
            {rev.description && <div className="small">{rev.description}</div>}
            <div className="row-actions">
              <button className="link-button" onClick={() => e.closeRevision()}>
                ◂ All imports
              </button>
              <button
                className="link-button"
                title="Look for a newer commit of this branch and open it"
                disabled={e.starting}
                onClick={() => void e.refreshLatest()}
              >
                Check for newer commit
              </button>
            </div>
            {e.notice && (
              <div className="small" role="status">
                {e.notice}
              </div>
            )}
            {rev.status === 'importing' && (
              <div className="small" role="status" aria-live="polite">
                {rev.phase}
                {rev.file_count > 0 ? ` · ${rev.file_count} files` : ''}
                <button className="link-button" onClick={() => void e.cancelImport()}>
                  Cancel
                </button>
              </div>
            )}
            {rev.status === 'failed' && (
              <div className="explorer-error" role="alert">
                {rev.error_message ?? 'The import failed.'}
              </div>
            )}
            {rev.status === 'cancelled' && <div className="muted small">Import cancelled.</div>}
            {rev.status === 'ready' && (
              <dl className="stats small">
                <dt>Files</dt>
                <dd>{rev.file_count}</dd>
                <dt>Text (readable)</dt>
                <dd>{rev.text_count}</dd>
                <dt>Binary</dt>
                <dd>{rev.binary_count}</dd>
                <dt>Too large</dt>
                <dd>{rev.skipped_count}</dd>
                <dt>Analyzed</dt>
                <dd>
                  {rev.analysis_status === 'analyzing'
                    ? 'working…'
                    : rev.analysis_status === 'failed'
                      ? 'failed'
                      : `${rev.analyzed_count} of ${rev.text_count}`}
                </dd>
                <dt>Dependencies</dt>
                <dd>{rev.edge_count}</dd>
                <dt>Problems</dt>
                <dd>{rev.diagnostic_count}</dd>
                <dt>Download</dt>
                <dd>{formatBytes(rev.total_bytes)}</dd>
              </dl>
            )}
          </section>
        )}

        {rev?.status === 'ready' && (
          <FileTree files={e.files} selected={e.selectedPath} onSelect={(p) => void e.reveal(p)} />
        )}

        {e.revisions.length > 0 && (!rev || rev.status !== 'ready') && (
          <section className="recent" aria-label="Recent imports">
            <h4>Recent</h4>
            <ul>
              {e.revisions.map((r) => (
                <li key={r.id}>
                  <button className="row-button" onClick={() => void e.openRevision(r.id)}>
                    <span>{r.full_name}</span>
                    <span className="muted small">
                      {r.commit_sha.slice(0, 7)} · {r.status}
                    </span>
                  </button>
                  <button
                    className="icon-button"
                    aria-label={`Remove ${r.full_name} ${r.commit_sha.slice(0, 7)}`}
                    disabled={r.status === 'importing'}
                    onClick={() => void e.removeRevision(r.id)}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </aside>
      <section className="explorer-main">
        {rev?.status === 'ready' ? (
          <>
            <div className="tabs" role="tablist" aria-label="View">
              <button
                className="icon-button"
                aria-label={e.sidebarOpen ? 'Hide the file list' : 'Show the file list'}
                aria-pressed={!e.sidebarOpen}
                onClick={() => e.toggleSidebar()}
                title={e.sidebarOpen ? 'Hide the file list' : 'Show the file list'}
              >
                ◧
              </button>
              <button role="tab" aria-selected={e.tab === 'graph'} onClick={() => e.setTab('graph')}>
                Graph
              </button>
              <button role="tab" aria-selected={e.tab === 'code'} onClick={() => e.setTab('code')}>
                Code
              </button>
              <button role="tab" aria-selected={e.tab === 'run'} onClick={() => e.setTab('run')}>
                Run
              </button>
              <button role="tab" aria-selected={e.tab === 'problems'} onClick={() => e.setTab('problems')}>
                Problems
                {rev.diagnostic_count > 0 && <span className="xn-problems"> ⚠ {rev.diagnostic_count}</span>}
              </button>
            </div>
            {e.tab === 'graph' ? (
              <div className={`graph-split${e.selectedPath ? ' with-viewer' : ''}`}>
                <div className="graph-pane">
                  <ExplorerGraph repoName={rev.full_name} theme={theme} />
                </div>
                {e.selectedPath && (
                  <div className="graph-viewer">
                    <FilePanel theme={theme} />
                  </div>
                )}
              </div>
            ) : e.tab === 'problems' ? (
              <ProblemsView />
            ) : e.tab === 'run' ? (
              <RunView />
            ) : (
              <FilePanel theme={theme} />
            )}
          </>
        ) : (
          <div className="viewer-empty">
            {rev?.status === 'importing' ? (
              <span className="muted">Importing…</span>
            ) : (
              <div className="explorer-welcome">
                <h2>See a codebase as nodes</h2>
                <p className="muted">
                  Paste the link of a public GitHub repository. Every file becomes a node, and the imports,
                  links and calls between them become lines. Nothing from the repository is run.
                </p>
                <div className="boot-actions">
                  <span className="muted small">Or try one:</span>
                  {EXAMPLES.map((x) => (
                    <button
                      key={x.url}
                      onClick={() => {
                        e.setUrl(x.url)
                        void useExplorer.getState().showNodes()
                      }}
                    >
                      {x.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </main>
  )
}
