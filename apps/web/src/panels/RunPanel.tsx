import { useStore } from '../state/store'
import { ResultView } from './ResultView'

export function RunPanel() {
  const { run, runInput, setRunInput, selectedId, nodes, issues, message } = useStore()
  const exec = run?.nodes.find((n) => n.node_id === selectedId)
  const nameOf = (id: string) => nodes.find((n) => n.id === id)?.data.name ?? id
  return (
    <section className="runpanel">
      <div className="run-col">
        <label className="field">
          Workflow input (JSON, passed to entry nodes)
          <textarea rows={3} value={runInput} onChange={(e) => setRunInput(e.target.value)} />
        </label>
        {message && <div className="notice">{message}</div>}
        {issues.length > 0 && (
          <ul className="issues">
            {issues.map((i, k) => (
              <li key={k}>
                <strong>{i.code}</strong> {i.message}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="run-col">
        <h4>
          Run history{' '}
          {run && (
            <span className={`pill pill-${run.status}`}>
              {run.status} · {run.duration_ms}ms
            </span>
          )}
        </h4>
        {!run && <div className="muted">Run the workflow to see per-node results.</div>}
        <ul className="steps">
          {run?.nodes.map((n) => (
            <li
              key={n.node_id}
              className={n.node_id === selectedId ? 'active' : ''}
              onClick={() => useStore.getState().select(n.node_id)}
            >
              <span className={`dot dot-${n.status}`} /> {nameOf(n.node_id)}
              <span className="muted"> {n.status} · {n.duration_ms}ms</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="run-col wide">
        <h4>Node execution{exec ? `: ${nameOf(exec.node_id)}` : ''}</h4>
        {exec ? (
          <ResultView
            status={exec.status}
            duration_ms={exec.duration_ms}
            input={exec.input}
            output={exec.output}
            logs={exec.logs}
            error={exec.error}
          />
        ) : (
          <div className="muted">Select a node after a run to inspect its input, output, logs and errors.</div>
        )}
      </div>
    </section>
  )
}
