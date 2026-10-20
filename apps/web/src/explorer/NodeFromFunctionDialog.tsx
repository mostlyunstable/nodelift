import { useEffect, useState } from 'react'
import { api, ApiError, type WorkflowDraft } from '../api/client'
import { useExplorer } from '../state/explorer'
import { useStore } from '../state/store'
import { Dialog } from '../ui/Dialog'

/** Review a node generated from repository code before any workflow exists. */
export function NodeFromFunctionDialog({
  revisionId,
  path,
  symbol,
  onClose,
}: {
  revisionId: string
  path: string
  symbol: string
  onClose: () => void
}) {
  const [draft, setDraft] = useState<WorkflowDraft | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const setMode = useExplorer((s) => s.setMode)

  useEffect(() => {
    api
      .explorerWorkflowDraft(revisionId, { path, symbol })
      .then(setDraft)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Could not build the draft.'))
  }, [revisionId, path, symbol])

  const create = async () => {
    if (!draft) return
    setBusy(true)
    try {
      const id = `n_${Math.random().toString(36).slice(2, 10)}`
      const def = {
        schema_version: 1 as const,
        id: '',
        name: `From ${draft.provenance.repository as string}: ${draft.name}`,
        nodes: [{ id, type: draft.node_type, name: draft.name, config: draft.config }],
        edges: [],
        ui: { positions: { [id]: { x: 120, y: 120 } } },
      }
      const rec = await api.createWorkflow(def.name, def)
      await useStore.getState().open(rec.id, rec)
      void useStore.getState().refresh()
      setMode('build')
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not create the workflow.')
      setBusy(false)
    }
  }

  return (
    <Dialog title={`Make a workflow node from ${symbol}`} onClose={onClose} wide>
      {error && (
        <div className="explorer-error" role="alert">
          {error}
        </div>
      )}
      {!draft && !error && <p className="muted">Building a draft…</p>}
      {draft && (
        <>
          <p className="small">
            <strong>Copied implementation.</strong> The function
            {draft.copied.length > 1 ? ' and what it uses' : ''} are copied into a new Python code node. It is
            not linked to the repository: later changes upstream are not reflected. Nothing has been created
            or run yet.
          </p>
          <dl className="stats small">
            <dt>From</dt>
            <dd>
              {draft.provenance.repository as string} @{' '}
              <code>{String(draft.provenance.commit).slice(0, 7)}</code>
            </dd>
            <dt>File</dt>
            <dd>
              {draft.provenance.path as string}:{String(draft.provenance.line)}
            </dd>
            <dt>Input becomes</dt>
            <dd>
              {draft.params.length === 1
                ? 'the single argument'
                : `keyword arguments: ${draft.params.join(', ')}`}
            </dd>
            <dt>Copied</dt>
            <dd>{draft.copied.map((c) => `${c.kind} ${String(c.name)}`).join(', ')}</dd>
          </dl>
          {draft.warnings.length > 0 && (
            <ul className="approve-warnings" aria-label="Warnings">
              {draft.warnings.map((w) => (
                <li key={w}>⚠ {w}</li>
              ))}
            </ul>
          )}
          <div className="field">Generated source (review it)</div>
          <pre className="approve-command" role="region" tabIndex={0} aria-label="Generated source">
            {String(draft.config.source)}
          </pre>
          <p className="muted small">
            You can edit the node afterwards. Code nodes run confined on macOS (no network unless you tick
            it).
          </p>
          <div className="dialog-actions">
            <button onClick={onClose}>Cancel</button>
            <button className="primary" disabled={busy} onClick={() => void create()}>
              Create workflow in Build
            </button>
          </div>
        </>
      )}
    </Dialog>
  )
}
