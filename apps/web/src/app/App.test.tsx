import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useStore } from '../state/store'
import { RunPanel } from '../panels/RunPanel'
import { ResultView } from '../panels/ResultView'

vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })

describe('store', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useStore.getState().reset()
  })
  it('adds and selects a node', () => {
    useStore.getState().addNode()
    const s = useStore.getState()
    expect(s.nodes).toHaveLength(1)
    expect(s.selectedId).toBe(s.nodes[0].id)
  })
  it('rejects invalid run input without calling the API', async () => {
    const spy = vi.spyOn(globalThis, 'fetch')
    useStore.getState().setRunInput('{nope')
    await useStore.getState().runWorkflow()
    expect(useStore.getState().message).toMatch(/not valid JSON/)
    expect(spy).not.toHaveBeenCalled()
  })
})

describe('persistence', () => {
  beforeEach(() => useStore.getState().reset())
  it('saves first, then runs the saved workflow and keeps the revision', async () => {
    const json = (body: unknown, status = 200) =>
      Promise.resolve(new Response(JSON.stringify(body), { status }))
    const calls: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) => {
      const u = String(url)
      calls.push(`${init?.method ?? 'GET'} ${u}`)
      if (u.endsWith('/workflows') && init?.method === 'POST') return json({ id: 'wf_1', revision: 1 }, 201)
      if (u.endsWith('/workflows/wf_1/runs') && init?.method === 'POST')
        return json({ id: 'run_1', status: 'succeeded', nodes: [], duration_ms: 1, version_no: 1 }, 201)
      return json([])
    })
    useStore.getState().addNode()
    await useStore.getState().runWorkflow()
    const s = useStore.getState()
    expect(s.workflowId).toBe('wf_1')
    expect(s.run?.id).toBe('run_1')
    expect(calls.indexOf('POST /api/v1/workflows')).toBeLessThan(calls.indexOf('POST /api/v1/workflows/wf_1/runs'))
  })
  it('explains a revision conflict', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ error: { code: 'revision_conflict', message: 'x' } }), { status: 409 })),
    )
    useStore.setState({ workflowId: 'wf_1', revision: 1 })
    expect(await useStore.getState().save()).toBeNull()
    expect(useStore.getState().message).toMatch(/Reopen/)
  })
})

class FakeEventSource {
  static instances: FakeEventSource[] = []
  static CLOSED = 2
  readyState = 1
  onerror: (() => void) | null = null
  listeners: Record<string, (m: MessageEvent<string>) => void> = {}
  constructor(public url: string) {
    FakeEventSource.instances.push(this)
  }
  addEventListener(type: string, fn: (m: MessageEvent<string>) => void) {
    this.listeners[type] = fn
  }
  emit(type: string, data: object) {
    this.listeners[type]?.({ data: JSON.stringify(data) } as MessageEvent<string>)
  }
  close() {
    this.readyState = FakeEventSource.CLOSED
  }
}

describe('live run', () => {
  beforeEach(() => {
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.restoreAllMocks()
    useStore.getState().reset()
  })

  it('shows node status as events arrive, ignores duplicates, and loads the final run', async () => {
    const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }))
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) => {
      const u = String(url)
      if (u.endsWith('/workflows') && init?.method === 'POST') return json({ id: 'wf_1', revision: 1 }, 201)
      if (u.endsWith('/workflows/wf_1/runs') && init?.method === 'POST')
        return json({ id: 'run_1', status: 'running', nodes: [], duration_ms: 0, version_no: 1 }, 202)
      if (u.endsWith('/runs/run_1'))
        return json({ id: 'run_1', status: 'succeeded', nodes: [], duration_ms: 5, version_no: 1 })
      return json([])
    })
    useStore.getState().addNode()
    const nodeId = useStore.getState().nodes[0].id
    await useStore.getState().runWorkflow()
    const es = FakeEventSource.instances[0]
    expect(es.url).toContain('/runs/run_1/events/stream?after=0')
    expect(useStore.getState().busy).toBe('run')

    es.emit('node.started', { seq: 2, type: 'node.started', node_id: nodeId })
    expect(useStore.getState().liveStatus[nodeId]).toBe('running')
    es.emit('node.started', { seq: 2, type: 'node.started', node_id: nodeId }) // replay after reconnect
    expect(useStore.getState().events).toHaveLength(1)

    es.emit('node.finished', { seq: 3, type: 'node.finished', node_id: nodeId, status: 'succeeded' })
    expect(useStore.getState().liveStatus[nodeId]).toBe('succeeded')
    es.emit('run.finished', { seq: 4, type: 'run.finished', status: 'succeeded' })
    await vi.waitFor(() => expect(useStore.getState().run?.status).toBe('succeeded'))
    expect(useStore.getState().busy).toBeNull()
    expect(es.readyState).toBe(FakeEventSource.CLOSED)
  })
})

describe('panels', () => {
  it('shows an error with its type', () => {
    render(
      <ResultView status="failed" duration_ms={3} output={null} logs={[]}
        error={{ type: 'syntax_error', message: 'invalid syntax', line: 1 }} />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('syntax_error')
  })
  it('shows empty history', () => {
    render(<RunPanel />)
    expect(screen.getByText(/No saved runs yet/)).toBeInTheDocument()
  })
})
