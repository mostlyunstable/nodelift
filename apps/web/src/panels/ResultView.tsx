import { Json } from '../editor/Json'
import type { LogLine, NodeError } from '../types/workflow'

interface Props {
  status: string
  duration_ms: number
  input?: unknown
  output: unknown
  logs: LogLine[]
  error: NodeError | null
}

export function ResultView({ status, duration_ms, input, output, logs, error }: Props) {
  return (
    <div className="result">
      <div className="result-head">
        <span className={`pill pill-${status}`}>{status}</span>
        <span className="muted">{duration_ms} ms</span>
      </div>
      {error && (
        <div className="error-box" role="alert">
          <strong>{error.type}</strong>: {error.message}
          {error.line != null && <span> (line {error.line})</span>}
          {error.traceback && <pre>{error.traceback}</pre>}
        </div>
      )}
      {input !== undefined && (
        <>
          <h4>Input</h4>
          <Json value={input} />
        </>
      )}
      {status === 'succeeded' && (
        <>
          <h4>Output</h4>
          <Json value={output} />
        </>
      )}
      <h4>Logs</h4>
      {logs.length === 0 ? (
        <div className="muted">No logs</div>
      ) : (
        <pre className="logs">
          {logs.map((l, i) => (
            <div key={i} className={l.stream}>
              {l.text}
            </div>
          ))}
        </pre>
      )}
    </div>
  )
}
