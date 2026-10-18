import { Background, Controls, MiniMap, ReactFlow } from '@xyflow/react'
import { useEffect } from 'react'
import { CodeNode } from '../nodes/CodeNode'
import { Inspector } from '../panels/Inspector'
import { RunPanel } from '../panels/RunPanel'
import { useStore } from '../state/store'

const nodeTypes = { code: CodeNode }

export function App() {
  const s = useStore()
  useEffect(() => {
    useStore.getState().refresh()
  }, [])
  return (
    <div className="app">
      <header className="toolbar">
        <strong className="brand">Nodecraft</strong>
        <button onClick={s.addNode}>+ Code node</button>
        <span className="sep" />
        <button onClick={s.validate}>Validate</button>
        <button className="primary" onClick={s.runWorkflow} disabled={s.busy !== null || s.nodes.length === 0}>
          {s.busy === 'run' ? 'Running…' : '▶ Run workflow'}
        </button>
        <button onClick={s.cancel} disabled={s.busy === null}>
          Cancel
        </button>
        <span className="sep" />
        <input
          className="wf-name"
          aria-label="Workflow name"
          value={s.workflowName}
          onChange={(e) => s.setName(e.target.value)}
        />
        <button onClick={() => s.save()}>Save</button>
        <button onClick={s.publish} title="Snapshot the current draft as an immutable version">
          Publish{s.versions.length > 0 ? ` (v${s.versions[0].version_no})` : ''}
        </button>
        <select
          aria-label="Open workflow"
          value=""
          onChange={(e) => e.target.value && s.open(e.target.value)}
        >
          <option value="">Open…</option>
          {s.workflows.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
        <button onClick={s.reset}>New</button>
        <span className="warn">⚠ Code runs unsandboxed on your machine</span>
      </header>
      <main className="workspace">
        <div className="canvas">
          <ReactFlow
            nodes={s.nodes}
            edges={s.edges}
            nodeTypes={nodeTypes}
            onNodesChange={s.onNodesChange}
            onEdgesChange={s.onEdgesChange}
            onConnect={s.onConnect}
            onNodeClick={(_, n) => s.select(n.id)}
            onPaneClick={() => s.select(null)}
            colorMode="dark"
            fitView
            deleteKeyCode={['Backspace', 'Delete']}
          >
            <Background />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>
        <Inspector />
      </main>
      <RunPanel />
    </div>
  )
}
