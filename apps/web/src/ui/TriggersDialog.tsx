import { useCallback, useEffect, useState } from 'react'
import { api, type Trigger } from '../api/client'
import { apiUrl } from '../api/config'
import { useStore } from '../state/store'
import { formatTime } from '../utils/format'
import { Dialog } from './Dialog'

const describe = (t: Trigger): string =>
  t.kind === 'webhook'
    ? 'Webhook'
    : t.every_minutes
      ? `Every ${t.every_minutes} minute${t.every_minutes === 1 ? '' : 's'}`
      : `Every day at ${t.daily_at}`

/** Schedules and webhooks that start the open workflow by themselves. */
export function TriggersDialog() {
  const closeDialog = useStore((s) => s.closeDialog)
  const workflowId = useStore((s) => s.workflowId)
  const [items, setItems] = useState<Trigger[]>([])
  const [mode, setMode] = useState<'every' | 'daily'>('every')
  const [minutes, setMinutes] = useState('15')
  const [time, setTime] = useState('08:00')
  const [hook, setHook] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!workflowId) return
    api
      .listTriggers(workflowId)
      .then(setItems)
      .catch((e: Error) => setProblem(e.message))
  }, [workflowId])
  useEffect(load, [load])

  const guard = async (fn: () => Promise<void>) => {
    setProblem(null)
    try {
      await fn()
      load()
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'That did not work')
    }
  }

  if (!workflowId) {
    return (
      <Dialog title="Triggers" onClose={closeDialog}>
        <p>Open or save a workflow first.</p>
      </Dialog>
    )
  }
  return (
    <Dialog title="Triggers" onClose={closeDialog} wide>
      <p className="muted">
        A trigger runs this workflow without you pressing Run. Schedules run only while Nodecraft is open, and
        a run missed while it was closed is not made up. A webhook is a private address on this computer: a
        script or another app can call it to start a run.
      </p>
      <ul className="credential-list" aria-label="Triggers">
        {items.length === 0 && <li className="muted">No triggers yet.</li>}
        {items.map((t) => (
          <li key={t.id}>
            <strong>{describe(t)}</strong>
            <span className="muted">
              {t.kind === 'schedule' && t.enabled && t.next_run_at
                ? `next ${formatTime(t.next_run_at)}`
                : t.enabled
                  ? 'on'
                  : 'off'}
              {t.last_run_at ? ` · last ${formatTime(t.last_run_at)}` : ''}
            </span>
            <button
              onClick={() => void guard(() => api.setTriggerEnabled(t.id, !t.enabled).then(() => undefined))}
              aria-label={`${t.enabled ? 'Turn off' : 'Turn on'}: ${describe(t)}`}
            >
              {t.enabled ? 'Turn off' : 'Turn on'}
            </button>
            <button
              className="danger"
              aria-label={`Delete: ${describe(t)}`}
              onClick={() => void guard(() => api.deleteTrigger(t.id).then(() => undefined))}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>

      <h3>Add a schedule</h3>
      <form
        className="credential-form"
        onSubmit={(e) => {
          e.preventDefault()
          void guard(async () => {
            await api.addTrigger(
              workflowId,
              mode === 'every'
                ? { kind: 'schedule', every_minutes: Number(minutes) }
                : { kind: 'schedule', daily_at: time },
            )
          })
        }}
      >
        <label className="field">
          Repeat
          <select value={mode} onChange={(e) => setMode(e.target.value as 'every' | 'daily')}>
            <option value="every">every N minutes</option>
            <option value="daily">once a day</option>
          </select>
        </label>
        {mode === 'every' ? (
          <label className="field">
            Minutes
            <input
              type="number"
              min={1}
              max={10080}
              value={minutes}
              onChange={(e) => setMinutes(e.target.value)}
            />
          </label>
        ) : (
          <label className="field">
            Time (this computer’s clock)
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
          </label>
        )}
        <button className="primary" type="submit">
          Add schedule
        </button>
      </form>

      <h3>Add a webhook</h3>
      <button
        onClick={() =>
          void guard(async () => {
            const made = await api.addTrigger(workflowId, { kind: 'webhook' })
            setHook(made.webhook_path ? apiUrl(made.webhook_path.replace(/^\/api\/v1/, '')) : null)
          })
        }
      >
        Create a webhook address
      </button>
      {hook && (
        <div role="status">
          <p className="muted">
            Copy this now: it is shown only once. Anything that can reach this computer and knows it can start
            the workflow. Send JSON in the body to pass it as the run’s input.
          </p>
          <pre className="boot-log">{hook}</pre>
          <pre className="boot-log">{`curl -X POST '${hook}' -H 'content-type: application/json' -d '{"hello": 1}'`}</pre>
          <button onClick={() => void navigator.clipboard?.writeText(hook)}>Copy address</button>
        </div>
      )}
      {problem && <p role="alert">{problem}</p>}
    </Dialog>
  )
}
