import { describe, expect, it, vi } from 'vitest'
import { buildCommands, filterCommands, type CommandContext } from './commands'

const noop = () => undefined
function context(over: Partial<CommandContext> = {}): CommandContext {
  return {
    hasNodes: true, busy: null, runStatus: null, canUndo: false, canRedo: false, workflowId: 'wf_1',
    workflows: [{ id: 'wf_1', name: 'Current', revision: 1, updated_at: '' }, { id: 'wf_2', name: 'Orders', revision: 1, updated_at: '' }],
    nodeDefs: [{ type: 'code.python', version: 1, title: 'Python code', category: 'Code', description: '', config_schema: {}, default_config: {} }],
    hasVersions: true,
    actions: new Proxy({}, { get: () => noop }) as CommandContext['actions'],
    ...over,
  }
}
const ids = (c: CommandContext) => buildCommands(c).map((x) => x.id)

describe('buildCommands', () => {
  it('only offers what makes sense right now', () => {
    expect(ids(context())).toContain('run')
    expect(ids(context({ busy: 'run' }))).not.toContain('run') // cannot start while one is running
    expect(ids(context({ hasNodes: false }))).not.toContain('run')
    expect(ids(context({ runStatus: 'running' }))).toContain('stop')
    expect(ids(context())).not.toContain('stop')
    expect(ids(context({ runStatus: 'failed' }))).toContain('resume')
    expect(ids(context({ runStatus: 'cancelled' }))).toContain('resume')
    expect(ids(context({ runStatus: 'succeeded' }))).not.toContain('resume')
    expect(ids(context())).not.toContain('undo')
    expect(ids(context({ canUndo: true, canRedo: true }))).toEqual(expect.arrayContaining(['undo', 'redo']))
  })
  it('workflow-specific actions need a saved workflow, and Open skips the current one', () => {
    const none = ids(context({ workflowId: null }))
    expect(none).not.toContain('delete')
    expect(none).not.toContain('export')
    const some = ids(context())
    expect(some).toEqual(expect.arrayContaining(['delete', 'export', 'save-version']))
    expect(some).toContain('open:wf_2')
    expect(some).not.toContain('open:wf_1')
    expect(ids(context({ hasVersions: false }))).not.toContain('versions')
  })
  it('lists a command per node type, and always offers help and the example', () => {
    expect(ids(context())).toContain('add:code.python')
    expect(ids(context({ hasNodes: false, workflowId: null }))).toEqual(expect.arrayContaining(['example', 'shortcuts', 'diagnostics', 'new', 'import']))
  })
  it('commands call the matching action', () => {
    const run = vi.fn()
    const c = context({ actions: { ...context().actions, run } })
    buildCommands(c).find((x) => x.id === 'run')?.run()
    expect(run).toHaveBeenCalledTimes(1)
  })
})

describe('filterCommands', () => {
  const all = buildCommands(context())
  it('finds commands by title or group with typos in spacing', () => {
    expect(filterCommands(all, 'run')[0].id).toBe('run')
    expect(filterCommands(all, 'orders')[0].id).toBe('open:wf_2')
    expect(filterCommands(all, 'dark').map((c) => c.id)).toContain('theme-dark')
  })
  it('returns everything for an empty query and nothing for gibberish', () => {
    expect(filterCommands(all, '')).toHaveLength(all.length)
    expect(filterCommands(all, 'qqqqzz')).toEqual([])
  })
})
