import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { diffWorkflows, isEmptyDiff } from '../canvas/diff'
import { toWorkflow } from '../canvas/mapper'
import { useStore } from '../state/store'
import type { SystemInfo } from '../types/workflow'
import { formatTime } from '../utils/format'
import { Dialog } from './Dialog'

export function VersionsDialog() {
  const { versions, viewedVersion, viewVersion, restoreVersion, closeDialog, nodes, edges, workflowName } =
    useStore()
  const current = useMemo(() => toWorkflow(nodes, edges, workflowName), [nodes, edges, workflowName])
  const diff = viewedVersion ? diffWorkflows(viewedVersion.definition, current) : null
  return (
    <Dialog title="Versions" onClose={closeDialog} wide>
      <p className="muted">
        A version is a frozen copy. Every run uses one, so you can always tell exactly what ran. Restoring
        puts a version back in the editor as an ordinary edit — nothing is lost, and undo works.
      </p>
      <div className="versions">
        <ul className="version-list" aria-label="Saved versions">
          {versions.length === 0 && (
            <li className="muted">No versions yet. Running the workflow creates one.</li>
          )}
          {versions.map((v) => (
            <li key={v.version_no}>
              <button
                className={viewedVersion?.version_no === v.version_no ? 'active' : undefined}
                onClick={() => void viewVersion(v.version_no)}
              >
                <strong>v{v.version_no}</strong>
                <span className="muted">{formatTime(v.created_at)}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="version-detail" aria-live="polite">
          {!viewedVersion && (
            <p className="muted">Pick a version to compare it with what is in the editor now.</p>
          )}
          {viewedVersion && diff && (
            <>
              <h3>Version {viewedVersion.version_no} compared with the editor</h3>
              {isEmptyDiff(diff) ? (
                <p>They are identical.</p>
              ) : (
                <ul className="diff">
                  {diff.added.map((n) => (
                    <li key={`a${n}`}>
                      <span className="pill pill-succeeded">in editor only</span> {n}
                    </li>
                  ))}
                  {diff.removed.map((n) => (
                    <li key={`r${n}`}>
                      <span className="pill pill-failed">in this version only</span> {n}
                    </li>
                  ))}
                  {diff.changed.map((c) => (
                    <li key={`c${c.name}`}>
                      <span className="pill pill-skipped">changed</span> {c.name}: {c.what.join(', ')}
                    </li>
                  ))}
                  {(diff.edgesAdded > 0 || diff.edgesRemoved > 0) && (
                    <li>
                      Connections: {diff.edgesAdded} added in the editor, {diff.edgesRemoved} only in this
                      version
                    </li>
                  )}
                </ul>
              )}
              <button className="primary" onClick={() => void restoreVersion(viewedVersion.version_no)}>
                Restore version {viewedVersion.version_no} into the editor
              </button>
            </>
          )}
        </div>
      </div>
    </Dialog>
  )
}

export function DiagnosticsDialog() {
  const closeDialog = useStore((s) => s.closeDialog)
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .systemInfo()
      .then(setInfo)
      .catch((e: Error) => setError(e.message))
    api
      .systemLogs(80)
      .then((r) => setLogs(r.lines))
      .catch(() => undefined)
  }, [])

  const report = [
    info ? `Nodecraft ${info.version} · Python ${info.python} · schema ${info.schema_revision}` : '',
    info ? `data: ${info.data_dir}` : '',
    info ? `logs: ${info.log_dir ?? 'not written to a file'}` : '',
    info ? `backups: ${info.backups.length} in ${info.backup_dir}` : '',
    info?.sandbox
      ? `code sandbox: ${info.sandbox.active ? `on (${info.sandbox.kind})` : 'off'} · memory limit: ${info.sandbox.memory_limit}`
      : '',
    error ? `error: ${error}` : '',
    '',
    ...logs,
  ].join('\n')

  return (
    <Dialog title="Diagnostics" onClose={closeDialog} wide>
      {error && <p role="alert">Could not reach the background service: {error}</p>}
      {info && (
        <dl className="facts">
          <dt>Version</dt>
          <dd>{info.version}</dd>
          <dt>Database schema</dt>
          <dd>
            {info.schema_revision}{' '}
            {info.schema_revision === info.schema_head ? '(current)' : `(latest is ${info.schema_head})`}
          </dd>
          <dt>Data folder</dt>
          <dd>{info.data_dir}</dd>
          <dt>Log folder</dt>
          <dd>{info.log_dir ?? '—'}</dd>
          <dt>Backups</dt>
          <dd>
            {info.backups.length === 0 ? 'none yet (made before each upgrade)' : info.backups.join(', ')}
          </dd>
          <dt>Running for</dt>
          <dd>{Math.round(info.uptime_s)} s</dd>
        </dl>
      )}
      <h3>Recent log</h3>
      <pre className="boot-log">{logs.length ? logs.join('\n') : 'No log lines to show.'}</pre>
      <button onClick={() => void navigator.clipboard?.writeText(report)}>Copy diagnostics</button>
      <p className="muted">Logs never contain your API token or workflow data.</p>
    </Dialog>
  )
}

export function ImportDialog() {
  const { importPreview, confirmImport, closeDialog } = useStore()
  if (!importPreview) return null
  const { preview } = importPreview
  const s = preview.summary
  return (
    <Dialog title="Import workflow" onClose={closeDialog}>
      <h3>{s.name}</h3>
      <p>
        {s.nodes} nodes, {s.edges} connections:{' '}
        {Object.entries(s.node_types)
          .map(([t, n]) => `${n}× ${t}`)
          .join(', ')}
      </p>
      {s.warnings.length > 0 && (
        <ul className="warnings" aria-label="Things to know">
          {s.warnings.map((w) => (
            <li key={w}>⚠ {w}</li>
          ))}
        </ul>
      )}
      {!preview.valid && (
        <div className="error-box" role="alert">
          <p className="explain">This file cannot be imported:</p>
          <ul>
            {preview.issues.map((i, k) => (
              <li key={k}>{i.message}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="muted">Importing creates a new workflow. It does not run anything.</p>
      <div className="boot-actions">
        <button className="primary" disabled={!preview.valid} onClick={() => void confirmImport()}>
          Import
        </button>
        <button onClick={closeDialog}>Cancel</button>
      </div>
    </Dialog>
  )
}

const SHORTCUTS: [string, string][] = [
  ['⌘K', 'Command palette'],
  ['⌘↵', 'Run the workflow'],
  ['⌘.', 'Stop the run'],
  ['⌘S', 'Save now (changes are also saved automatically)'],
  ['⌘Z / ⇧⌘Z', 'Undo / redo (when not typing in a field)'],
  ['Backspace / Delete', 'Remove the selected node or connection'],
  ['Scroll / pinch', 'Zoom the canvas'],
]

export function ShortcutsDialog() {
  const closeDialog = useStore((s) => s.closeDialog)
  return (
    <Dialog title="Keyboard shortcuts" onClose={closeDialog}>
      <dl className="facts">
        {SHORTCUTS.map(([k, d]) => (
          <div key={k} className="fact-row">
            <dt>
              <kbd>{k}</kbd>
            </dt>
            <dd>{d}</dd>
          </div>
        ))}
      </dl>
    </Dialog>
  )
}

const NAME_PATTERN = /^[A-Za-z0-9_.-]{1,64}$/

export function CredentialsDialog() {
  const { credentials, loadCredentials, saveCredential, removeCredential, closeDialog } = useStore()
  const [name, setName] = useState('')
  const [value, setValue] = useState('')
  const [replacing, setReplacing] = useState<string | null>(null)

  useEffect(() => {
    void loadCredentials()
  }, [loadCredentials])

  const target = replacing ?? name
  const problem =
    replacing === null && name !== '' && !NAME_PATTERN.test(name)
      ? 'Use letters, digits, dot, dash or underscore (up to 64).'
      : value !== '' && value.length < 8
        ? 'A secret must be at least 8 characters.'
        : null
  const canSave = target !== '' && value.length >= 8 && !problem

  const submit = async () => {
    const ok = await saveCredential(target, value, replacing === null)
    if (ok) {
      setValue('') // the secret is never kept in the interface after saving
      setName('')
      setReplacing(null)
    }
  }

  return (
    <Dialog title="Credentials" onClose={closeDialog} wide>
      <p className="muted">
        Secrets are kept in your system keychain, never in workflows, exports or run history. In an HTTP node,
        write <code>{'{{credential:NAME}}'}</code> inside a header value, for example{' '}
        <code>Bearer {'{{credential:github}}'}</code>. Values cannot be read back here, only replaced.
      </p>
      <ul className="credential-list" aria-label="Saved credentials">
        {credentials.length === 0 && <li className="muted">No credentials yet.</li>}
        {credentials.map((c) => (
          <li key={c.id}>
            <code>{`{{credential:${c.name}}}`}</code>
            <span className="muted">updated {formatTime(c.updated_at)}</span>
            <button onClick={() => setReplacing(c.name)} aria-label={`Replace the value of ${c.name}`}>
              Replace value
            </button>
            <button
              className="danger"
              aria-label={`Delete ${c.name}`}
              onClick={() => {
                if (
                  window.confirm(
                    `Delete “${c.name}”? Workflows that use it will fail until it is added again.`,
                  )
                ) {
                  void removeCredential(c.name)
                }
              }}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
      <h3>{replacing ? `New value for “${replacing}”` : 'Add a credential'}</h3>
      <form
        className="credential-form"
        onSubmit={(e) => {
          e.preventDefault()
          if (canSave) void submit()
        }}
      >
        {replacing === null && (
          <label className="field">
            Name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="github"
              autoComplete="off"
            />
          </label>
        )}
        <label className="field">
          Secret value
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            autoComplete="new-password"
            placeholder="paste the token or key"
          />
        </label>
        {problem && <span className="field-error">{problem}</span>}
        <div className="boot-actions">
          <button className="primary" type="submit" disabled={!canSave}>
            {replacing ? 'Replace value' : 'Save credential'}
          </button>
          {replacing && (
            <button
              type="button"
              onClick={() => {
                setReplacing(null)
                setValue('')
              }}
            >
              Cancel
            </button>
          )}
        </div>
      </form>
    </Dialog>
  )
}
