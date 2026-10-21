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
  mode?: 'build' | 'explorer' // in the Explorer, commands for editing and running workflows are not offered
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
    credentials: () => void
    triggers: () => void
    templates: () => void
    files: () => void
    shortcuts: () => void
    theme: (t: 'dark' | 'light' | 'system') => void
    tidy?: () => void // arrange the workflow's nodes in tidy columns
    explore?: () => void // switch to the repository Explorer
    build?: () => void // switch to the workflow editor
    closeRepo?: () => void // go back to the list of imported repositories
  }
}

/** Only commands that make sense right now are returned. */
export function buildCommands(c: CommandContext): Command[] {
  const a = c.actions
  const out: Command[] = []
  const add = (id: string, title: string, group: string, run: () => void, hint?: string) =>
    out.push({ id, title, group, run, hint })

  if (c.hasNodes && c.busy === null) add('run', 'Run workflow', 'Run', a.run, '⌘↵')
  if (c.runStatus === 'running') add('stop', 'Stop the running workflow', 'Run', a.stop, '⌘.')
  if (c.runStatus === 'failed' || c.runStatus === 'cancelled')
    add('resume', 'Resume from failure', 'Run', a.resume)
  if (c.hasNodes && a.tidy) add('tidy', 'Tidy up the layout', 'Edit', a.tidy)
  if (c.hasNodes) add('validate', 'Check workflow for problems', 'Run', a.validate)

  if (a.explore) add('explore', 'Explore a GitHub repository…', 'Explorer', a.explore)
  if (a.build) add('build', 'Go to the workflow editor (Build)', 'Explorer', a.build)
  if (a.closeRepo)
    add('repos', 'Show imported repositories', 'Explorer', () => {
      a.explore?.()
      a.closeRepo?.()
    })

  if (c.canUndo) add('undo', 'Undo', 'Edit', a.undo, '⌘Z')
  if (c.canRedo) add('redo', 'Redo', 'Edit', a.redo, '⇧⌘Z')
  for (const def of c.nodeDefs)
    add(`add:${def.type}`, `Add node: ${def.title}`, 'Nodes', () => a.addNode(def.type))

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
  for (const ex of c.examples)
    add(`example:${ex.id}`, `Try the example: ${ex.title}`, 'Learn', () => a.example(ex.id))
  for (const w of c.workflows) {
    if (w.id !== c.workflowId) add(`open:${w.id}`, `Open: ${w.name}`, 'Open', () => a.open(w.id))
  }

  add('templates', 'Templates: ready-made workflows…', 'Learn', a.templates)
  add('files', 'Files: notes, data and results…', 'App', a.files)
  add('triggers', 'Triggers: schedules and webhooks…', 'Workflow', a.triggers)
  add('credentials', 'Manage credentials…', 'App', a.credentials)
  add('diagnostics', 'Diagnostics…', 'App', a.diagnostics)
  add('shortcuts', 'Keyboard shortcuts…', 'App', a.shortcuts)
  add('theme-dark', 'Theme: dark', 'App', () => a.theme('dark'))
  add('theme-light', 'Theme: light', 'App', () => a.theme('light'))
  add('theme-system', 'Theme: follow the system', 'App', () => a.theme('system'))
  return c.mode === 'explorer' ? out.filter((x) => x.group === 'Explorer' || x.group === 'App') : out
}

export function filterCommands(commands: Command[], query: string): Command[] {
  return rank(commands, query, (cmd) => `${cmd.title} ${cmd.group}`)
}
