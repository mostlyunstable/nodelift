import Editor from '@monaco-editor/react'
import { useStore } from '../state/store'
import { ResultView } from './ResultView'

export function Inspector() {
  const { nodes, selectedId, updateData, testNode, nodeTests, busy } = useStore()
  const node = nodes.find((n) => n.id === selectedId)
  if (!node) return <aside className="inspector muted pad">Select or add a node to edit it.</aside>
  const test = nodeTests[node.id]
  return (
    <aside className="inspector">
      <label className="field">
        Name
        <input value={node.data.name} onChange={(e) => updateData(node.id, { name: e.target.value })} />
      </label>
      <div className="field">Python — define <code>main(input_data)</code></div>
      <div className="editor">
        <Editor
          height="240px"
          language="python"
          theme="vs-dark"
          value={node.data.source}
          onChange={(v) => updateData(node.id, { source: v ?? '' })}
          options={{ minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false }}
        />
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
