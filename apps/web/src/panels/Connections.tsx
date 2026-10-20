import { useState } from 'react'
import { checkConnection } from '../canvas/graph'
import type { FlowNode } from '../canvas/mapper'
import { useStore } from '../state/store'

/**
 * Connect and disconnect nodes without dragging: a list-and-button alternative to the canvas, for keyboard and
 * screen-reader users (and anyone who finds a tiny drag handle fiddly).
 */
export function Connections({ node }: { node: FlowNode }) {
  const { nodes, edges, nodeDefs, onConnect, onEdgesChange } = useStore()
  const [target, setTarget] = useState('')
  const [port, setPort] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const nameOf = (id: string) => nodes.find((n) => n.id === id)?.data.name ?? id
  const ports =
    nodeDefs.find((d) => d.type === node.data.nodeType)?.outputs?.map((p) => p.name) ??
    (node.data.nodeType === 'logic.branch' ? ['true', 'false'] : ['out'])
  const outputs = edges.filter((e) => e.source === node.id)
  const inputs = edges.filter((e) => e.target === node.id)
  const others = nodes.filter((n) => n.id !== node.id)
  const chosenPort = port || ports[0] || 'out'

  const connect = () => {
    const check = checkConnection(edges, node.id, target, chosenPort, 'in')
    if (!check.ok) {
      setProblem(check.reason ?? 'That connection is not possible')
      return
    }
    setProblem(null)
    onConnect({ source: node.id, target, sourceHandle: chosenPort, targetHandle: 'in' })
    setTarget('')
  }

  return (
    <section className="connections" aria-label="Connections">
      <h2>Connections</h2>
      {inputs.length === 0 && outputs.length === 0 && (
        <p className="muted small">Not connected to anything yet.</p>
      )}
      <ul className="detail-list">
        {inputs.map((e) => (
          <li key={e.id}>
            Receives from <strong>{nameOf(e.source)}</strong>
            {e.sourceHandle && e.sourceHandle !== 'out' ? ` (when ${e.sourceHandle})` : ''}{' '}
            <button
              className="link-button"
              aria-label={`Remove the connection from ${nameOf(e.source)}`}
              onClick={() => onEdgesChange([{ type: 'remove', id: e.id }])}
            >
              Remove
            </button>
          </li>
        ))}
        {outputs.map((e) => (
          <li key={e.id}>
            Sends{e.sourceHandle && e.sourceHandle !== 'out' ? ` (when ${e.sourceHandle})` : ''} to{' '}
            <strong>{nameOf(e.target)}</strong>{' '}
            <button
              className="link-button"
              aria-label={`Remove the connection to ${nameOf(e.target)}`}
              onClick={() => onEdgesChange([{ type: 'remove', id: e.id }])}
            >
              Remove
            </button>
          </li>
        ))}
      </ul>
      {others.length > 0 && (
        <div className="connect-row">
          <label>
            Send the output of this node to
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">Choose a node…</option>
              {others.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.data.name}
                </option>
              ))}
            </select>
          </label>
          {ports.length > 1 && (
            <label>
              When
              <select value={chosenPort} onChange={(e) => setPort(e.target.value)}>
                {ports.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button disabled={!target} onClick={connect}>
            Connect
          </button>
        </div>
      )}
      {problem && (
        <div className="field-error" role="alert">
          {problem}
        </div>
      )}
    </section>
  )
}
