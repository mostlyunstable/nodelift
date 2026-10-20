import { Background, Controls, MiniMap, ReactFlow } from '@xyflow/react'
import { useEffect, useMemo, useRef } from 'react'
import { checkConnection } from '../canvas/graph'
import { CodeNode } from '../nodes/CodeNode'
import { Inspector } from '../panels/Inspector'
import { RunPanel } from '../panels/RunPanel'
import { loadTheme, useStore } from '../state/store'
import { resolveTheme } from '../state/theme'
import { CommandPalette } from '../ui/CommandPalette'
import { CredentialsDialog, DiagnosticsDialog, ImportDialog, ShortcutsDialog, VersionsDialog } from '../ui/Dialogs'
import { Menu, type MenuItem } from '../ui/Menu'
import { EmptyCanvas, RunAnnouncer, Toast, TourBanner } from '../ui/Overlays'
import { buildCommands, type CommandContext } from './commands'
import { matchShortcut } from './shortcuts'

const nodeTypes = { node: CodeNode }

const SAVE_LABEL = {
  saved: 'Saved',
  saving: 'Saving…',
  unsaved: 'Unsaved changes',
  error: 'Save failed',
} as const

function useResolvedTheme(): 'dark' | 'light' {
  const choice = useStore((st) => st.theme)
  useEffect(() => {
    const apply = () => {
      document.documentElement.dataset.theme = resolveTheme(choice)
    }
    apply()
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    mq?.addEventListener?.('change', apply)
    return () => mq?.removeEventListener?.('change', apply)
  }, [choice])
  return resolveTheme(choice)
}

export function App() {
  const s = useStore()
  const theme = useResolvedTheme()
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const st = useStore.getState()
    st.setTheme(loadTheme())
    void st.refresh()
    void st.loadDefinitions()
    void st.loadExamples()
    void st.loadCredentials()
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
      e.preventDefault()
      if (action === 'palette') store.openDialog('palette')
      else if (action === 'undo') store.undo()
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

  const context: CommandContext = {
    hasNodes: s.nodes.length > 0,
    busy: s.busy,
    runStatus: s.run?.status ?? null,
    canUndo: s.canUndo,
    canRedo: s.canRedo,
    workflowId: s.workflowId,
    workflows: s.workflows,
    nodeDefs: s.nodeDefs,
    examples: s.examples,
    hasVersions: s.versions.length > 0,
    actions: {
      run: () => void s.runWorkflow(),
      stop: () => void s.cancel(),
      resume: () => void s.resume(),
      undo: s.undo,
      redo: s.redo,
      save: () => void s.save(),
      saveVersion: () => void s.publish(),
      showVersions: () => s.openDialog('versions'),
      validate: () => void s.validate(),
      newWorkflow: () => void guarded(s.reset),
      open: (id) => void guarded(() => s.open(id)),
      deleteCurrent: () => {
        if (s.workflowId && window.confirm(`Delete “${s.workflowName}” and its run history? This cannot be undone.`)) {
          void s.deleteWorkflow(s.workflowId)
        }
      },
      addNode: s.addNode,
      example: (id) => void guarded(() => s.createExample(id)),
      exportCurrent: () => void s.exportCurrent(),
      exportAll: () => void s.exportAll(),
      importFile: () => fileInput.current?.click(),
      credentials: () => s.openDialog('credentials'),
      diagnostics: () => s.openDialog('diagnostics'),
      shortcuts: () => s.openDialog('shortcuts'),
      theme: s.setTheme,
    },
  }
  const commands = useMemo(() => buildCommands(context), [context.hasNodes, context.busy, context.runStatus, context.canUndo, context.canRedo, context.workflowId, context.workflows, context.nodeDefs, context.examples, context.hasVersions, s.workflowName]) // eslint-disable-line react-hooks/exhaustive-deps

  const addItems: MenuItem[] = (s.nodeDefs.length > 0 ? s.nodeDefs : [{ type: 'code.python', title: 'Python code' }]).map((d) => ({
    label: d.title,
    onSelect: () => s.addNode(d.type),
  }))
  const workflowItems: MenuItem[] = [
    { label: 'New workflow', onSelect: () => void guarded(s.reset) },
    ...s.examples.map((ex) => ({
      label: `Example: ${ex.title}`,
      onSelect: () => void guarded(() => s.createExample(ex.id)),
    })),
    ...s.workflows.map((w, i) => ({
      label: w.name,
      onSelect: () => void guarded(() => s.open(w.id)),
      separatorBefore: i === 0,
      disabled: w.id === s.workflowId,
    })),
  ]
  const moreItems: MenuItem[] = [
    { label: 'Check for problems', onSelect: () => void s.validate(), disabled: s.nodes.length === 0 },
    { label: 'Versions…', onSelect: () => s.openDialog('versions'), disabled: !s.workflowId },
    { label: 'Save a version', onSelect: () => void s.publish(), disabled: s.nodes.length === 0 },
    { label: 'Export this workflow…', onSelect: () => void s.exportCurrent(), disabled: s.nodes.length === 0, separatorBefore: true },
    { label: 'Import a workflow…', onSelect: () => fileInput.current?.click() },
    { label: 'Export everything…', onSelect: () => void s.exportAll() },
    { label: 'Credentials…', onSelect: () => s.openDialog('credentials'), separatorBefore: true },
    { label: 'Diagnostics…', onSelect: () => s.openDialog('diagnostics') },
    { label: 'Keyboard shortcuts…', onSelect: () => s.openDialog('shortcuts') },
  ]

  return (
    <div className="app">
      <header className="toolbar">
        <strong className="brand">Nodecraft</strong>
        <input
          className="wf-name"
          aria-label="Workflow name"
          value={s.workflowName}
          onChange={(e) => s.setName(e.target.value)}
        />
        <span
          className={`save-state save-${s.saveState}`}
          role="status"
          aria-label="Save status"
          aria-live="polite"
          title={s.saveState === 'error' ? (s.message ?? undefined) : undefined}
        >
          {SAVE_LABEL[s.saveState]}
        </span>
        <span className="sep" />
        <button className="primary" onClick={() => void s.runWorkflow()} disabled={s.busy !== null || s.nodes.length === 0} title="Run (⌘↵)">
          {s.busy === 'run' ? 'Running…' : '▶ Run'}
        </button>
        <button onClick={() => void s.cancel()} disabled={s.busy !== 'run' || s.run?.status !== 'running'} title="Stop (⌘.)">
          Stop
        </button>
        <span className="spacer" />
        <Menu label="+ Node" ariaLabel="Add node" items={addItems} />
        <Menu label="Workflows" ariaLabel="Workflows" items={workflowItems} align="right" />
        <button onClick={() => s.openDialog('palette')} title="Command palette (⌘K)" aria-label="Command palette">
          ⌘K
        </button>
        <Menu label="⋯" ariaLabel="More actions" items={moreItems} align="right" />
      </header>
      <main className="workspace">
        <div className="canvas">
          <TourBanner />
          <EmptyCanvas />
          <ReactFlow
            nodes={s.nodes}
            edges={s.edges}
            nodeTypes={nodeTypes}
            onNodesChange={s.onNodesChange}
            onEdgesChange={s.onEdgesChange}
            onConnect={s.onConnect}
            isValidConnection={(c) =>
              checkConnection(useStore.getState().edges, c.source, c.target, c.sourceHandle, c.targetHandle).ok
            }
            onNodeDragStart={s.beginDrag}
            onNodeClick={(_, n) => s.select(n.id)}
            onPaneClick={() => s.select(null)}
            colorMode={theme}
            fitView
            minZoom={0.1} // the default 0.5 made graphs wider than the canvas impossible to see whole
            deleteKeyCode={['Backspace', 'Delete']}
          >
            <Background />
            <Controls />
            {s.nodes.length > 12 && <MiniMap pannable zoomable />}
          </ReactFlow>
        </div>
        <Inspector />
      </main>
      <RunPanel />
      <Toast />
      <RunAnnouncer />
      <input
        ref={fileInput}
        type="file"
        accept="application/json,.json"
        hidden
        aria-label="Choose a workflow file to import"
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = ''
          if (file) void s.importFile(file)
        }}
      />
      {s.dialog === 'palette' && <CommandPalette commands={commands} onClose={s.closeDialog} />}
      {s.dialog === 'versions' && <VersionsDialog />}
      {s.dialog === 'diagnostics' && <DiagnosticsDialog />}
      {s.dialog === 'credentials' && <CredentialsDialog />}
      {s.dialog === 'import' && <ImportDialog />}
      {s.dialog === 'shortcuts' && <ShortcutsDialog />}
    </div>
  )
}
