import { useEffect, useState } from 'react'
import { api, type CommandRun, type RepoPatch, type Suggestion } from '../api/client'
import { useExplorer } from '../state/explorer'
import { useRunner } from '../state/runner'
import { Dialog } from '../ui/Dialog'

function shellQuote(argv: string[]): string {
  return argv.map((a) => (/^[\w@%+=:,./-]+$/.test(a) ? a : `'${a.replace(/'/g, `'\\''`)}'`)).join(' ')
}

interface Pending {
  command: string
  cwd: string
  notes: string[]
}

/** The only way to start a command: show exactly what will run and how it is confined, then ask. */
function ApprovalDialog({ pending, onClose }: { pending: Pending; onClose: () => void }) {
  const ws = useRunner((s) => s.workspace)
  const confined = useRunner((s) => s.sandboxActive)
  const run = useRunner((s) => s.run)
  const [network, setNetwork] = useState(false)
  const [home, setHome] = useState(false)
  const [unconfined, setUnconfined] = useState(false)
  const [busy, setBusy] = useState(false)
  const needsAck = confined === false
  return (
    <Dialog title="Run this command?" onClose={onClose}>
      <p>
        This will run on your computer, in a prepared copy of the repository, only because you approved it.
      </p>
      <div className="field">Command</div>
      <pre className="approve-command" role="region" tabIndex={0} aria-label="Command to run">
        {pending.command}
      </pre>
      <dl className="stats small">
        <dt>Working folder</dt>
        <dd>{pending.cwd || '(repository root)'}</dd>
        <dt>Workspace</dt>
        <dd title={ws?.path ?? ''}>{ws?.path?.split('/').slice(-2).join('/')}</dd>
        <dt>Time limit</dt>
        <dd>5 minutes</dd>
      </dl>
      {pending.notes.length > 0 && (
        <ul className="approve-warnings" aria-label="Warnings">
          {pending.notes.map((n) => (
            <li key={n}>⚠ {n}</li>
          ))}
        </ul>
      )}
      <p className="small">
        {confined === false
          ? 'This machine cannot confine commands: it would run with all of your permissions.'
          : 'Confined by the OS: it can write only inside the workspace and a temporary folder. It does not inherit Nodecraft’s environment or secrets.'}
      </p>
      <label className="check">
        <input type="checkbox" checked={network} onChange={(e) => setNetwork(e.target.checked)} /> Allow
        network access
        <span className="muted small"> (off by default; needed to install packages)</span>
      </label>
      <label className="check">
        <input type="checkbox" checked={home} onChange={(e) => setHome(e.target.checked)} /> Allow reading my
        home folder
        <span className="muted small"> (off by default)</span>
      </label>
      {needsAck && (
        <label className="check">
          <input type="checkbox" checked={unconfined} onChange={(e) => setUnconfined(e.target.checked)} /> I
          understand it will run unconfined
        </label>
      )}
      <div className="dialog-actions">
        <button onClick={onClose}>Cancel</button>
        <button
          className="primary"
          disabled={busy || (needsAck && !unconfined)}
          onClick={async () => {
            setBusy(true)
            const ok = await run({
              command: pending.command,
              approved_command: pending.command,
              cwd: pending.cwd,
              allow_network: network,
              allow_home_read: home,
              acknowledge_unconfined: unconfined,
            })
            setBusy(false)
            if (ok) onClose()
          }}
        >
          Approve and run
        </button>
      </div>
    </Dialog>
  )
}

function DiffDialog({ patch, onClose }: { patch: RepoPatch; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null)
  useEffect(() => {
    void api
      .explorerPatchDiff(patch.revision_id, patch.id)
      .then(setText)
      .catch(() => setText('The diff could not be loaded.'))
  }, [patch])
  return (
    <Dialog title={patch.title} onClose={onClose} wide>
      <pre className="diff" role="region" tabIndex={0} aria-label={`Diff for ${patch.path}`}>
        {(text ?? 'Loading…').split('\n').map((l, i) => (
          <span
            key={i}
            className={
              l.startsWith('+') && !l.startsWith('+++')
                ? 'add'
                : l.startsWith('-') && !l.startsWith('---')
                  ? 'del'
                  : ''
            }
          >
            {l}
            {'\n'}
          </span>
        ))}
      </pre>
    </Dialog>
  )
}

function Output({ run }: { run: CommandRun }) {
  const cancel = useRunner((s) => s.cancel)
  return (
    <section className="run-output" aria-label="Command output">
      <div className="run-head">
        <code>{run.command}</code>
        <span className={`run-status run-${run.status}`}>
          {run.status}
          {run.exit_code !== null ? ` · exit ${run.exit_code}` : ''}
        </span>
        {run.status === 'running' && <button onClick={() => void cancel(run.id)}>Cancel</button>}
      </div>
      <pre role="region" tabIndex={0} aria-label="Output">
        {run.output || (run.status === 'running' ? 'Running…' : '(no output)')}
      </pre>
      {run.output_truncated && <p className="muted small">Output was cut at 256 KB.</p>}
    </section>
  )
}

export function RunView() {
  const rev = useExplorer((s) => s.revision)
  const r = useRunner()
  const [pending, setPending] = useState<Pending | null>(null)
  const [custom, setCustom] = useState('')
  const [diff, setDiff] = useState<RepoPatch | null>(null)
  useEffect(() => {
    if (rev) void useRunner.getState().load(rev.id)
  }, [rev?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!rev) return null
  const ready = r.workspace?.state === 'ready'
  const review = (s: Suggestion) => setPending({ command: shellQuote(s.argv), cwd: s.cwd, notes: s.notes })
  const latest = r.runs[r.runs.length - 1]

  return (
    <div className="run-view" role="region" tabIndex={0} aria-label="Run and proposed changes">
      {r.error && (
        <div className="explorer-error" role="alert">
          {r.error}
        </div>
      )}

      <section className="detail-section">
        <h2>Workspace</h2>
        {r.workspace?.state === 'ready' ? (
          <p className="small">
            Ready: a full copy of this commit ({r.workspace.file_count} files) on your computer.{' '}
            <button className="link-button" onClick={() => void r.resetWorkspace()}>
              Reset to the imported state
            </button>
          </p>
        ) : r.workspace?.state === 'preparing' ? (
          <p className="small" role="status">
            Downloading and unpacking…
          </p>
        ) : (
          <>
            <p className="small">
              To run tests, Nodecraft needs a full copy of this commit. This only downloads and unpacks files;
              it runs nothing.
            </p>
            {r.workspace?.error && (
              <div className="explorer-error" role="alert">
                {r.workspace.error}
              </div>
            )}
            <button onClick={() => void r.prepareWorkspace()}>Prepare workspace</button>
          </>
        )}
      </section>

      <section className="detail-section">
        <h2>Commands found in this repository</h2>
        {r.discovery && r.discovery.suggestions.length === 0 && (
          <p className="muted small">
            No test setup was found in the repository’s own files. You can still enter a command below.
          </p>
        )}
        <ul className="detail-list">
          {r.discovery?.suggestions.map((s) => (
            <li key={s.id} className="suggestion">
              <div>
                <code>{shellQuote(s.argv)}</code> <span className="muted">{s.framework}</span>
              </div>
              <div className="muted small">{s.evidence}</div>
              {s.notes.map((n) => (
                <div key={n} className="muted small">
                  {n}
                </div>
              ))}
              <button
                disabled={!ready}
                title={ready ? '' : 'Prepare the workspace first'}
                onClick={() => review(s)}
              >
                Review and run…
              </button>
            </li>
          ))}
        </ul>
        {r.discovery && r.discovery.test_files.length > 0 && (
          <p className="muted small">{r.discovery.test_files.length} test files found by name.</p>
        )}
        <form
          className="custom-command"
          onSubmit={(e) => {
            e.preventDefault()
            if (custom.trim()) setPending({ command: custom.trim(), cwd: '', notes: [] })
          }}
        >
          <input
            aria-label="Custom command"
            placeholder="Or type a command, e.g. python3 -m unittest"
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
          />
          <button disabled={!ready || !custom.trim()} type="submit">
            Review and run…
          </button>
        </form>
      </section>

      {latest && <Output run={latest} />}

      <section className="detail-section">
        <h2>
          Proposed changes <span className="muted">{r.patches.length}</span>
        </h2>
        {r.patches.length === 0 && (
          <p className="muted small">
            Open a file, choose “Propose a change”, edit a copy and save it here. Your changes never touch the
            imported files.
          </p>
        )}
        <ul className="detail-list">
          {r.patches.map((p) => (
            <li key={p.id} className="suggestion">
              <div>
                <strong>{p.title}</strong> <span className="muted">{p.path}</span>
              </div>
              <div className="muted small">
                +{p.additions} −{p.deletions} · {p.applied ? 'applied to the workspace' : 'not applied'}
              </div>
              <div className="row-actions">
                <button onClick={() => setDiff(p)}>View diff</button>
                {p.applied ? (
                  <button onClick={() => void r.revertPatch(p.id)}>Revert in workspace</button>
                ) : (
                  <button disabled={!ready} onClick={() => void r.applyPatch(p.id)}>
                    Apply to workspace
                  </button>
                )}
                <a
                  className="link-button"
                  href={`/api/v1/explorer/revisions/${p.revision_id}/patches/${p.id}/export`}
                  download={`${p.id}.patch`}
                >
                  Export .patch
                </a>
                <button disabled={p.applied} onClick={() => void r.deletePatch(p.id)}>
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {r.runs.length > 1 && (
        <section className="detail-section">
          <h2>Earlier runs</h2>
          <ul className="detail-list">
            {r.runs
              .slice(0, -1)
              .reverse()
              .map((x) => (
                <li key={x.id}>
                  <code>{x.command}</code> <span className={`run-status run-${x.status}`}>{x.status}</span>
                </li>
              ))}
          </ul>
        </section>
      )}

      {pending && <ApprovalDialog pending={pending} onClose={() => setPending(null)} />}
      {diff && <DiffDialog patch={diff} onClose={() => setDiff(null)} />}
    </div>
  )
}
