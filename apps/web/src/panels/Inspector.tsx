import { ConfigEditor } from './ConfigEditors'
import { useStore } from '../state/store'
import { ResultView } from './ResultView'

export function Inspector() {
  const { nodes, selectedId, updateData, testNode, nodeTests, busy, requestFocusLine } = useStore()
  const node = nodes.find((n) => n.id === selectedId)
  if (!node) return <aside className="inspector muted pad">Select or add a node to edit it.</aside>
  const test = nodeTests[node.id]
  return (
    <aside className="inspector">
      <label className="field">
        Name
        <input value={node.data.name} onChange={(e) => updateData(node.id, { name: e.target.value })} />
      </label>
      <ConfigEditor node={node} />
      <div className="retry-row">
        <label title="Retries re-run your code, so only enable this if running it twice is safe">
          <input
            type="checkbox"
            checked={node.data.idempotent}
            onChange={(e) =>
              updateData(node.id, {
                idempotent: e.target.checked,
                maxAttempts: e.target.checked ? node.data.maxAttempts : 1,
              })
            }
          />{' '}
          Idempotent (safe to retry)
        </label>
        <label>
          Max attempts{' '}
          <input
            type="number"
            min={1}
            max={5}
            disabled={!node.data.idempotent}
            value={node.data.maxAttempts}
            onChange={(e) =>
              updateData(node.id, { maxAttempts: Math.min(5, Math.max(1, Number(e.target.value) || 1)) })
            }
          />
        </label>
      </div>
      <label className="field">
        Test input (JSON)
        <textarea
          rows={4}
          value={node.data.testInput}
          onChange={(e) => updateData(node.id, { testInput: e.target.value })}
        />
      </label>
      <button onClick={() => testNode(node.id)} disabled={busy !== null}>
        {busy === 'node' ? 'Running…' : '▶ Run node'}
      </button>
      {test && (
        <ResultView
          onShowLine={(line) => requestFocusLine(node.id, line)}
          status={test.status}
          duration_ms={test.duration_ms}
          output={test.output}
          logs={test.logs}
          error={test.error}
        />
      )}
    </aside>
  )
}
