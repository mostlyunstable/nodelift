import { Json } from '../editor/Json'
import type { LogLine, NodeError } from '../types/workflow'
import { errorLine, explainError } from './errors'

interface Props {
  status: string
  duration_ms: number
  input?: unknown
  output: unknown
  logs: LogLine[]
  error: NodeError | null
  onShowLine?: (line: number) => void
}

export function ResultView({ status, duration_ms, input, output, logs, error, onShowLine }: Props) {
  const line = errorLine(error)
  return (
    <div className="result">
      <div className="result-head">
        <span className={`pill pill-${status}`}>{status}</span>
        <span className="muted">{duration_ms} ms</span>
      </div>
      {error && (
        <div className="error-box" role="alert">
          <p className="explain">{explainError(error)}</p>
          {line != null && onShowLine && (
            <button className="link-button" onClick={() => onShowLine(line)}>
              Show line {line} in the code
            </button>
          )}
          <details>
            <summary>
              {error.type}: {error.message}
            </summary>
            {error.traceback && <pre>{error.traceback}</pre>}
          </details>
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
