import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as files from '../desktop/files'
import { jsonResponse, sseStream } from '../test-utils/sse'
import type { ExecutionRun } from '../types/workflow'
import { useStore } from './store'

const s = () => useStore.getState()
const DEF = (source: string) => ({
  schema_version: 1, id: 'wf_1', name: 'W', edges: [], ui: { positions: {} },
  nodes: [{ id: 'n1', type: 'code.python', name: 'Step', config: { source } }],
})

/** A tiny fake backend keyed by "METHOD path". */
function backend(routes: Record<string, (init?: RequestInit) => Response | Promise<Response>>) {
  const calls: string[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
    const key = `${init?.method ?? 'GET'} ${String(url).replace(/^.*\/api\/v1/, '')}`
    calls.push(key)
    const handler = routes[key]
    if (handler) return handler(init)
    if (key.startsWith('GET /workflows') || key.startsWith('GET /examples')) return new Response('[]')
    return new Response(JSON.stringify({ error: { message: `no route ${key}` } }), { status: 404 })
  })
  return calls
}

describe('versions', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    s().reset()
  })

  it('restoring a version puts it in the editor as an undoable, unsaved edit', async () => {
    backend({
      'GET /workflows/wf_1/versions/2': () =>
        new Response(JSON.stringify({ id: 'v', workflow_id: 'wf_1', version_no: 2, content_hash: 'h', created_at: '', definition: DEF('old code') })),
    })
    useStore.setState({ workflowId: 'wf_1' })
    s().addNode()
    const before = s().nodes
    await s().restoreVersion(2)
    expect(s().nodes).toHaveLength(1)
    expect(s().nodes[0].data.config.source).toBe('old code')
    expect(s().dirty).toBe(true) // autosave will persist it as a new draft revision
    expect(s().message).toMatch(/Restored version 2/)
    s().undo()
    expect(s().nodes).toEqual(before) // nothing was lost
  })

  it('viewing a version loads it for the comparison; failures are reported, not thrown', async () => {
    backend({ 'GET /workflows/wf_1/versions/1': () => new Response('nope', { status: 404 }) })
    useStore.setState({ workflowId: 'wf_1' })
    await s().viewVersion(1)
    expect(s().viewedVersion).toBeNull()
    expect(s().message).toBeTruthy()
  })

  it('does nothing without a saved workflow', async () => {
    const calls = backend({})
    await s().restoreVersion(1)
    await s().viewVersion(1)
    expect(calls).toHaveLength(0)
  })
})

describe('deleting workflows', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    s().reset()
  })

  it('deleting the open workflow clears the editor and forgets it', async () => {
    const calls = backend({ 'DELETE /workflows/wf_1': () => new Response(null, { status: 204 }) })
    useStore.setState({ workflowId: 'wf_1', nodes: [{ id: 'a' } as never] })
    await s().deleteWorkflow('wf_1')
    expect(calls).toContain('DELETE /workflows/wf_1')
    expect(s().workflowId).toBeNull()
    expect(s().nodes).toHaveLength(0)
    expect(s().message).toBe('Workflow deleted.')
  })

  it('deleting a different workflow leaves the editor alone', async () => {
    backend({ 'DELETE /workflows/other': () => new Response(null, { status: 204 }) })
    useStore.setState({ workflowId: 'wf_1', nodes: [{ id: 'a' } as never] })
    await s().deleteWorkflow('other')
    expect(s().workflowId).toBe('wf_1')
    expect(s().nodes).toHaveLength(1)
  })
})

describe('export and import', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    s().reset()
  })
  const file = (text: string) => new File([text], 'w.json', { type: 'application/json' })
  const PREVIEW = { valid: true, issues: [], summary: { name: 'X', nodes: 1, edges: 0, node_types: { 'code.python': 1 }, code_nodes: 1, http_hosts: [], warnings: ['w'] } }

  it('exports the saved workflow through the file dialog', async () => {
    const save = vi.spyOn(files, 'saveTextFile').mockResolvedValue(true)
    backend({
      'POST /workflows': () => jsonResponse({ id: 'wf_1', revision: 1, name: 'My flow', draft: DEF('x') }, 201),
      'GET /workflows/wf_1/export': () => jsonResponse({ format: 'nodecraft-workflow', format_version: 1, workflow: { name: 'My flow', definition: DEF('x') } }),
    })
    s().addNode()
    s().setName('My flow')
    await s().exportCurrent()
    expect(save).toHaveBeenCalledTimes(1)
    const [name, text] = save.mock.calls[0]
    expect(name).toBe('my-flow.nodecraft.json')
    expect(JSON.parse(text).format).toBe('nodecraft-workflow')
    expect(s().message).toBe('Workflow exported.')
  })

  it('says nothing when the user cancels the save dialog', async () => {
    vi.spyOn(files, 'saveTextFile').mockResolvedValue(false)
    backend({ 'GET /system/export': () => jsonResponse({ format: 'nodecraft-backup', workflows: [] }) })
    await s().exportAll()
    expect(s().message).toBeNull()
  })

  it('a file that is not JSON is rejected before it reaches the server', async () => {
    const calls = backend({})
    await s().importFile(file('this is not json {'))
    expect(s().message).toMatch(/not valid JSON/)
    expect(calls).toHaveLength(0)
    expect(s().dialog).toBeNull()
  })

  it('shows a preview first and creates nothing until the user confirms', async () => {
    const calls = backend({
      'POST /workflows/import/preview': () => jsonResponse(PREVIEW),
      'POST /workflows/import': () => jsonResponse({ id: 'wf_9', name: 'X', revision: 1, draft: DEF('x') }, 201),
    })
    await s().importFile(file(JSON.stringify({ format: 'nodecraft-workflow', format_version: 1, workflow: {} })))
    expect(s().dialog).toBe('import')
    expect(calls.filter((c) => c === 'POST /workflows/import')).toHaveLength(0) // preview only
    await s().confirmImport()
    expect(calls).toContain('POST /workflows/import')
    expect(s().workflowId).toBe('wf_9')
    expect(s().dialog).toBeNull()
    expect(s().message).toMatch(/has not been run/)
  })

  it('never imports a file the server called invalid, and surfaces the server reason', async () => {
    const calls = backend({
      'POST /workflows/import/preview': () =>
        jsonResponse({ error: { code: 'unsupported_format_version', message: 'made by a newer Nodecraft' } }, 422),
    })
    await s().importFile(file('{"format":"nodecraft-workflow","format_version":99,"workflow":{}}'))
    expect(s().message).toMatch(/newer Nodecraft/)
    await s().confirmImport()
    expect(calls.filter((c) => c === 'POST /workflows/import')).toHaveLength(0)

    backend({ 'POST /workflows/import/preview': () => jsonResponse({ ...PREVIEW, valid: false, issues: [{ code: 'x', message: 'bad node' }] }) })
    await s().importFile(file('{"a":1}'))
    const calls2 = backend({})
    await s().confirmImport() // invalid preview: refused locally
    expect(calls2.filter((c) => c === 'POST /workflows/import')).toHaveLength(0)
  })

  it('closing the dialog discards the pending import', async () => {
    backend({ 'POST /workflows/import/preview': () => jsonResponse(PREVIEW) })
    await s().importFile(file('{"a":1}'))
    s().closeDialog()
    expect(s().importPreview).toBeNull()
    expect(s().dialog).toBeNull()
  })
})

describe('the first-run example and tour', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    s().reset()
    useStore.setState({ tour: null })
  })

  const run = (status: ExecutionRun['status']): ExecutionRun => ({ id: 'run_1', status, nodes: [], duration_ms: 1 })

  async function runToEnd(final: ExecutionRun) {
    const stream = sseStream()
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) => {
      const u = String(url)
      if (u.includes('/events/stream')) return Promise.resolve(stream.response())
      if (u.endsWith('/workflows/wf_ex/runs') && init?.method === 'POST')
        return jsonResponse({ id: 'run_1', status: 'running', nodes: [], duration_ms: 0, version_no: 1 }, 202)
      if (u.endsWith('/workflows/wf_ex') && init?.method === 'PUT') return jsonResponse({ id: 'wf_ex', revision: 2 })
      if (u.endsWith('/runs/run_1')) return jsonResponse(final)
      return jsonResponse([])
    })
    await s().runWorkflow()
    stream.send('run.finished', { seq: 9, type: 'run.finished', status: final.status }, 9)
    await vi.waitFor(() => expect(s().run?.status).toBe(final.status))
    stream.close()
  }

  async function loadExample() {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      if (String(url).endsWith('/examples/debug-me/create') && init?.method === 'POST')
        return new Response(JSON.stringify({ id: 'wf_ex', name: 'Debug me (example)', revision: 1, draft: { ...DEF('x'), name: 'Debug me (example)' } }), { status: 201 })
      return new Response('[]')
    })
    await s().createExample()
  }

  it('creating the example opens it and starts the tour', async () => {
    await loadExample()
    expect(s().workflowId).toBe('wf_ex')
    expect(s().workflowName).toBe('Debug me (example)')
    expect(s().tour).toBe('run')
    expect(s().dirty).toBe(false) // an untouched example is not an unsaved edit
  })

  it('a failed run moves the tour to "fix it", and a later success to "done"', async () => {
    await loadExample()
    await runToEnd(run('failed'))
    expect(s().tour).toBe('fix')
    await runToEnd(run('succeeded'))
    expect(s().tour).toBe('done')
    s().dismissTour()
    expect(s().tour).toBeNull()
  })

  it('does not start a tour for ordinary runs', async () => {
    useStore.setState({ workflowId: 'wf_ex' })
    s().addNode()
    await runToEnd(run('failed'))
    expect(s().tour).toBeNull()
  })

  it('reports a failure to create the example instead of throwing', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: { message: 'boom' } }), { status: 500 }))
    await s().createExample()
    expect(s().message).toMatch(/Could not create the example: boom/)
    expect(s().tour).toBeNull()
  })
})

describe('theme', () => {
  it('remembers the choice and survives storage that throws', () => {
    s().setTheme('light')
    expect(s().theme).toBe('light')
    expect(localStorage.getItem('nodecraft.theme')).toBe('light')
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(() => s().setTheme('dark')).not.toThrow()
    expect(s().theme).toBe('dark')
    vi.restoreAllMocks()
    s().setTheme('system')
  })
})

describe('file helpers', () => {
  it('makes safe, readable file names', () => {
    expect(files.fileSlug('My Flow: v2 (final)!')).toBe('my-flow-v2-final')
    expect(files.fileSlug('   ')).toBe('workflow')
    expect(files.fileSlug('../../etc/passwd')).toBe('etc-passwd')
    expect(files.fileSlug('x'.repeat(200)).length).toBe(60)
  })
})
