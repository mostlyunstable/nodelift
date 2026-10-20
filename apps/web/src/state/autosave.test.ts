import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AUTOSAVE_MS, useStore } from './store'

interface Call {
  method: string
  url: string
  body?: any
}

/** Fake backend. `hold()` makes the next write wait until `release()` so races can be staged. */
function fakeBackend(opts: { failWrites?: boolean; conflict?: boolean } = {}) {
  const calls: Call[] = []
  let gate: Promise<void> | null = null
  let open: () => void = () => {}
  let revision = 0
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
    const method = init?.method ?? 'GET'
    const call: Call = {
      method,
      url: String(url),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    }
    calls.push(call)
    const reply = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
    if (method === 'POST' || method === 'PUT') {
      if (gate) await gate
      if (opts.failWrites) return reply({ error: { code: 'internal', message: 'boom' } }, 500)
      if (opts.conflict && method === 'PUT')
        return reply({ error: { code: 'revision_conflict', message: 'x' } }, 409)
      revision += 1
      return reply(
        { id: 'wf_1', name: 'Untitled', revision, draft: { nodes: [], edges: [] } },
        method === 'POST' ? 201 : 200,
      )
    }
    if (call.url.endsWith('/workflows/wf_1'))
      return reply({
        id: 'wf_1',
        name: 'Saved one',
        revision: 7,
        draft: {
          schema_version: 1,
          id: 'wf_1',
          name: 'Saved one',
          nodes: [{ id: 'n1', type: 'code.python', name: 'Hi', config: { source: 'x' } }],
          edges: [],
          ui: {},
        },
      })
    if (call.url.endsWith('/workflows/gone'))
      return reply({ error: { code: 'not_found', message: 'nope' } }, 404)
    return reply([])
  })
  return {
    calls,
    writes: () => calls.filter((c) => c.method === 'POST' || c.method === 'PUT'),
    hold() {
      gate = new Promise<void>((r) => (open = r))
    },
    release() {
      open()
      gate = null
    },
  }
}

const settle = () => vi.advanceTimersByTimeAsync(0)

describe('autosave and unsaved-change tracking', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.restoreAllMocks()
    localStorage.clear()
    useStore.getState().reset()
  })
  afterEach(() => vi.useRealTimers())

  it('marks an edit dirty, then saves it automatically and remembers the workflow', async () => {
    const be = fakeBackend()
    useStore.getState().addNode()
    expect(useStore.getState()).toMatchObject({ dirty: true, saveState: 'unsaved' })
    expect(be.writes()).toHaveLength(0) // debounced, not instant
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS)
    expect(be.writes().map((c) => c.method)).toEqual(['POST']) // first save creates the workflow
    expect(useStore.getState()).toMatchObject({ dirty: false, saveState: 'saved', workflowId: 'wf_1' })
    expect(localStorage.getItem('nodecraft.lastWorkflow')).toBe('wf_1')
    expect(be.writes()[0].body.definition.nodes).toHaveLength(1)
  })

  it('debounces bursts of edits into one save and then updates with the revision', async () => {
    const be = fakeBackend()
    useStore.getState().addNode()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS)
    for (let i = 0; i < 5; i++) {
      useStore.getState().setName(`name ${i}`)
      await vi.advanceTimersByTimeAsync(300)
    }
    expect(be.writes()).toHaveLength(1) // still only the create: the burst is still being debounced
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS)
    const writes = be.writes()
    expect(writes.map((c) => c.method)).toEqual(['POST', 'PUT'])
    expect(writes[1].body).toMatchObject({ name: 'name 4', revision: 1 })
  })

  it('selecting and measuring are not edits, moving and removing are', () => {
    fakeBackend()
    useStore.getState().addNode()
    const id = useStore.getState().nodes[0].id
    useStore.setState({ dirty: false, saveState: 'saved' })
    useStore.getState().onNodesChange([{ type: 'select', id, selected: true }])
    useStore.getState().onNodesChange([{ type: 'dimensions', id, dimensions: { width: 10, height: 10 } }])
    useStore.getState().select(id)
    expect(useStore.getState().dirty).toBe(false)
    useStore.getState().onNodesChange([{ type: 'position', id, position: { x: 9, y: 9 } }])
    expect(useStore.getState().dirty).toBe(true)
    useStore.setState({ dirty: false })
    useStore.getState().onNodesChange([{ type: 'remove', id }])
    expect(useStore.getState().dirty).toBe(true)
  })

  it('an edit made while a save is in flight stays dirty and is saved afterwards', async () => {
    const be = fakeBackend()
    useStore.getState().addNode()
    be.hold()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS) // POST is now in flight
    expect(useStore.getState().saveState).toBe('saving')
    useStore.getState().setName('typed during save')
    be.release()
    await settle()
    expect(useStore.getState()).toMatchObject({ dirty: true, saveState: 'unsaved' }) // not falsely "saved"
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS)
    expect(be.writes().map((c) => c.method)).toEqual(['POST', 'PUT'])
    expect(be.writes()[1].body.name).toBe('typed during save')
    expect(useStore.getState().dirty).toBe(false)
  })

  it('does not create an empty workflow just because the user added then deleted a node', async () => {
    const be = fakeBackend()
    useStore.getState().addNode()
    const id = useStore.getState().nodes[0].id
    useStore.getState().onNodesChange([{ type: 'remove', id }])
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS)
    expect(be.writes()).toHaveLength(0)
    expect(useStore.getState()).toMatchObject({ dirty: false, saveState: 'saved' })
  })

  it('reports a failed save, keeps the edits, and retries', async () => {
    const be = fakeBackend({ failWrites: true })
    useStore.getState().addNode()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS)
    expect(useStore.getState()).toMatchObject({ dirty: true, saveState: 'error' })
    expect(useStore.getState().message).toMatch(/Could not save/)
    expect(useStore.getState().nodes).toHaveLength(1) // nothing lost
    await vi.advanceTimersByTimeAsync(5000)
    expect(be.writes().length).toBeGreaterThanOrEqual(2) // retried
  })

  it('stops autosaving after a revision conflict instead of looping', async () => {
    const be = fakeBackend({ conflict: true })
    useStore.setState({ workflowId: 'wf_1', revision: 1, nodes: [], edges: [] })
    useStore.getState().setName('mine')
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS)
    expect(useStore.getState()).toMatchObject({ saveState: 'error', conflict: true, dirty: true })
    expect(useStore.getState().message).toMatch(/Saved elsewhere/)
    const before = be.writes().length
    useStore.getState().setName('mine again')
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS * 4)
    expect(be.writes().length).toBe(before) // no more attempts until the workflow is reopened
  })

  it('flush saves pending edits immediately and reports whether it worked', async () => {
    const be = fakeBackend()
    useStore.getState().addNode()
    expect(await useStore.getState().flush()).toBe(true)
    expect(be.writes()).toHaveLength(1)
    expect(useStore.getState().dirty).toBe(false)
    const failing = fakeBackend({ failWrites: true })
    useStore.getState().setName('x')
    expect(await useStore.getState().flush()).toBe(false) // caller must ask before discarding
    expect(failing.writes().length).toBeGreaterThan(0)
  })

  it('flush on an empty untouched canvas is a no-op that succeeds', async () => {
    const be = fakeBackend()
    expect(await useStore.getState().flush()).toBe(true)
    expect(be.calls.filter((c) => c.method !== 'GET')).toHaveLength(0)
  })

  it('a save finishing after the user opened another workflow does not overwrite it', async () => {
    const be = fakeBackend()
    useStore.getState().addNode()
    be.hold()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS)
    useStore.getState().reset() // "New" while the save is in flight
    be.release()
    await settle()
    expect(useStore.getState()).toMatchObject({ workflowId: null, dirty: false, nodes: [] })
    expect(localStorage.getItem('nodecraft.lastWorkflow')).toBeNull()
  })

  it('restore reopens the last workflow, and forgets one that no longer exists', async () => {
    fakeBackend()
    localStorage.setItem('nodecraft.lastWorkflow', 'wf_1')
    await useStore.getState().restore()
    expect(useStore.getState()).toMatchObject({
      workflowId: 'wf_1',
      workflowName: 'Saved one',
      revision: 7,
      dirty: false,
    })
    expect(useStore.getState().nodes[0].data.name).toBe('Hi')

    useStore.getState().reset()
    localStorage.setItem('nodecraft.lastWorkflow', 'gone')
    await useStore.getState().restore()
    expect(useStore.getState().workflowId).toBeNull()
    expect(localStorage.getItem('nodecraft.lastWorkflow')).toBeNull()
    expect(useStore.getState().message).toBeNull() // a deleted workflow is not an error to show
  })

  it('works when localStorage throws', async () => {
    fakeBackend()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    useStore.getState().addNode()
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS)
    expect(useStore.getState().saveState).toBe('saved')
    await expect(useStore.getState().restore()).resolves.toBeUndefined()
  })
})
