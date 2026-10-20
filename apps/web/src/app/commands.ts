import type { ExampleInfo, NodeDefinition, WorkflowSummary } from '../types/workflow'
import { rank } from '../utils/fuzzy'

export interface Command {
  id: string
  title: string
  group: string
  hint?: string
  run: () => void
}

/** What the command list needs to know and be able to do. The store satisfies this; tests fake it. */
export interface CommandContext {
  hasNodes: boolean
  busy: 'node' | 'run' | null
  runStatus: 'running' | 'succeeded' | 'failed' | 'cancelled' | null
  canUndo: boolean
  canRedo: boolean
  workflowId: string | null
  workflows: WorkflowSummary[]
  nodeDefs: NodeDefinition[]
  examples: ExampleInfo[]
  hasVersions: boolean
  actions: {
    run: () => void
    stop: () => void
    resume: () => void
    undo: () => void
    redo: () => void
    save: () => void
    saveVersion: () => void
    showVersions: () => void
    validate: () => void
    newWorkflow: () => void
    open: (id: string) => void
    deleteCurrent: () => void
    addNode: (type: string) => void
    example: (id: string) => void
    exportCurrent: () => void
    exportAll: () => void
    importFile: () => void
    diagnostics: () => void
    shortcuts: () => void
    theme: (t: 'dark' | 'light' | 'system') => void
  }
}

/** Only commands that make sense right now are returned. */
export function buildCommands(c: CommandContext): Command[] {
  const a = c.actions
  const out: Command[] = []
  const add = (id: string, title: string, group: string, run: () => void, hint?: string) => out.push({ id, title, group, run, hint })

  if (c.hasNodes && c.busy === null) add('run', 'Run workflow', 'Run', a.run, '⌘↵')
  if (c.runStatus === 'running') add('stop', 'Stop the running workflow', 'Run', a.stop, '⌘.')
  if (c.runStatus === 'failed' || c.runStatus === 'cancelled') add('resume', 'Resume from failure', 'Run', a.resume)
  if (c.hasNodes) add('validate', 'Check workflow for problems', 'Run', a.validate)

  if (c.canUndo) add('undo', 'Undo', 'Edit', a.undo, '⌘Z')
  if (c.canRedo) add('redo', 'Redo', 'Edit', a.redo, '⇧⌘Z')
  for (const def of c.nodeDefs) add(`add:${def.type}`, `Add node: ${def.title}`, 'Nodes', () => a.addNode(def.type))

  add('save', 'Save now', 'Workflow', a.save, '⌘S')
  if (c.workflowId) {
    add('save-version', 'Save a version', 'Workflow', a.saveVersion)
    if (c.hasVersions) add('versions', 'Show versions…', 'Workflow', a.showVersions)
    add('export', 'Export this workflow…', 'Workflow', a.exportCurrent)
    add('delete', 'Delete this workflow…', 'Workflow', a.deleteCurrent)
  }
  add('new', 'New workflow', 'Workflow', a.newWorkflow)
  add('import', 'Import a workflow file…', 'Workflow', a.importFile)
  add('export-all', 'Export everything (backup)…', 'Workflow', a.exportAll)
  for (const ex of c.examples) add(`example:${ex.id}`, `Try the example: ${ex.title}`, 'Learn', () => a.example(ex.id))
  for (const w of c.workflows) {
    if (w.id !== c.workflowId) add(`open:${w.id}`, `Open: ${w.name}`, 'Open', () => a.open(w.id))
  }

  add('diagnostics', 'Diagnostics…', 'App', a.diagnostics)
  add('shortcuts', 'Keyboard shortcuts…', 'App', a.shortcuts)
  add('theme-dark', 'Theme: dark', 'App', () => a.theme('dark'))
  add('theme-light', 'Theme: light', 'App', () => a.theme('light'))
  add('theme-system', 'Theme: follow the system', 'App', () => a.theme('system'))
  return out
}

export function filterCommands(commands: Command[], query: string): Command[] {
  return rank(commands, query, (cmd) => `${cmd.title} ${cmd.group}`)
}
