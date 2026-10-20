import { Background, Controls, MiniMap, ReactFlow } from '@xyflow/react'
import { useEffect } from 'react'
import { CodeNode } from '../nodes/CodeNode'
import { Inspector } from '../panels/Inspector'
import { RunPanel } from '../panels/RunPanel'
import { checkConnection } from '../canvas/graph'
import { useStore } from '../state/store'
import { matchShortcut } from './shortcuts'

const nodeTypes = { node: CodeNode }

const SAVE_LABEL = {
  saved: 'Saved',
  saving: 'Saving…',
  unsaved: 'Unsaved changes',
  error: 'Save failed',
} as const

export function App() {
  const s = useStore()
  useEffect(() => {
    const st = useStore.getState()
    void st.refresh()
    void st.loadDefinitions()
    void st.restore() // reopen whatever the user was working on
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      const { dirty, saveState } = useStore.getState()
      if (dirty || saveState === 'saving') {
        e.preventDefault() // the browser shows its own "Leave site?" prompt
        e.returnValue = ''
      }
    }
    const onHide = () => {
      if (document.hidden) void useStore.getState().flush() // tab switch or close: save right now
    }
    const onKey = (e: KeyboardEvent) => {
      const action = matchShortcut(e)
      if (!action) return
      const store = useStore.getState()
      if (action === 'palette') return // wired up with the command palette
      e.preventDefault()
      if (action === 'undo') store.undo()
      else if (action === 'redo') store.redo()
      else if (action === 'save') void store.save()
      else if (action === 'run') {
        if (store.busy === null && store.nodes.length > 0) void store.runWorkflow()
      } else if (action === 'cancel') void store.cancel()
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    document.addEventListener('visibilitychange', onHide)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload)
      document.removeEventListener('visibilitychange', onHide)
      window.removeEventListener('keydown', onKey)
    }
  }, [])

  // Save pending edits before replacing the canvas; if that fails, ask before discarding them.
  const guarded = async (action: () => void | Promise<void>) => {
    const saved = await s.flush()
    if (!saved && !window.confirm('Your latest changes could not be saved. Discard them?')) return
    await action()
  }
  return (
    <div className="app">
      <header className="toolbar">
        <strong className="brand">Nodecraft</strong>
        <select
          aria-label="Add node"
          value=""
          onChange={(e) => e.target.value && s.addNode(e.target.value)}
        >
          <option value="">+ Add node…</option>
          {(s.nodeDefs.length > 0
            ? s.nodeDefs
            : [{ type: 'code.python', title: 'Python code' }]
          ).map((d) => (
            <option key={d.type} value={d.type}>
              {d.title}
            </option>
          ))}
        </select>
        <span className="sep" />
        <button onClick={s.validate}>Validate</button>
        <button className="primary" onClick={s.runWorkflow} disabled={s.busy !== null || s.nodes.length === 0}>
          {s.busy === 'run' ? 'Running…' : '▶ Run workflow'}
        </button>
        <button onClick={() => void s.cancel()} disabled={s.busy !== 'run' || s.run?.status !== 'running'}>
          Cancel
        </button>
        <span className="sep" />
        <input
          className="wf-name"
          aria-label="Workflow name"
          value={s.workflowName}
          onChange={(e) => s.setName(e.target.value)}
        />
        <span
          className={`save-state save-${s.saveState}`}
          role="status"
          aria-live="polite"
          title={s.saveState === 'error' ? (s.message ?? undefined) : undefined}
        >
          {SAVE_LABEL[s.saveState]}
        </span>
        <button onClick={() => s.save()}>Save</button>
        <button onClick={s.publish} title="Snapshot the current draft as an immutable version">
          Publish{s.versions.length > 0 ? ` (v${s.versions[0].version_no})` : ''}
        </button>
        <select
          aria-label="Open workflow"
          value=""
          onChange={(e) => {
            const id = e.target.value
            if (id) void guarded(() => s.open(id))
          }}
        >
          <option value="">Open…</option>
          {s.workflows.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
        <button onClick={() => void guarded(s.reset)}>New</button>
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
            isValidConnection={(c) => checkConnection(useStore.getState().edges, c.source, c.target).ok}
            onNodeDragStart={s.beginDrag}
            onNodeClick={(_, n) => s.select(n.id)}
            onPaneClick={() => s.select(null)}
            colorMode="dark"
            fitView
            minZoom={0.1} // the default 0.5 made graphs wider than the canvas impossible to see whole
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
