import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { applyEvent, useStore } from '../state/store'
import type { RunEvent } from '../types/workflow'
import { RunPanel } from '../panels/RunPanel'
import { jsonResponse, sseStream } from '../test-utils/sse'
import { ResultView } from '../panels/ResultView'

vi.stubGlobal(
  'ResizeObserver',
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
)

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
  it('creates nodes from registry defaults and falls back for the code node', () => {
    useStore.getState().addNode()
    expect(useStore.getState().nodes[0].data).toMatchObject({ nodeType: 'code.python' })
    expect(String(useStore.getState().nodes[0].data.config.source)).toContain('def main')
    useStore.setState({
      nodeDefs: [
        {
          type: 'transform.json',
          version: 1,
          title: 'JSON transform',
          category: 'Data',
          description: '',
          config_schema: {},
          default_config: { mapping: { value: '$' } },
        },
      ],
    })
    useStore.getState().addNode('transform.json')
    const added = useStore.getState().nodes[1]
    expect(added.data.nodeType).toBe('transform.json')
    expect(added.data.config).toEqual({ mapping: { value: '$' } })
    expect(added.data.name).toBe('JSON transform 2')
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
    expect(calls.indexOf('POST /api/v1/workflows')).toBeLessThan(
      calls.indexOf('POST /api/v1/workflows/wf_1/runs'),
    )
  })
  it('explains a revision conflict', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ error: { code: 'revision_conflict', message: 'x' } }), { status: 409 }),
      ),
    )
    useStore.setState({ workflowId: 'wf_1', revision: 1 })
    expect(await useStore.getState().save()).toBeNull()
    expect(useStore.getState().message).toMatch(/Reopen/)
  })
})

describe('live run', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useStore.getState().reset()
  })

  it('shows node status as events arrive, ignores duplicates, and loads the final run', async () => {
    const stream = sseStream()
    const streamCalls: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) => {
      const u = String(url)
      if (u.includes('/events/stream')) {
        streamCalls.push(u)
        return Promise.resolve(stream.response())
      }
      if (u.endsWith('/workflows') && init?.method === 'POST')
        return jsonResponse({ id: 'wf_1', revision: 1 }, 201)
      if (u.endsWith('/workflows/wf_1/runs') && init?.method === 'POST')
        return jsonResponse({ id: 'run_1', status: 'running', nodes: [], duration_ms: 0, version_no: 1 }, 202)
      if (u.endsWith('/runs/run_1'))
        return jsonResponse({ id: 'run_1', status: 'succeeded', nodes: [], duration_ms: 5, version_no: 1 })
      return jsonResponse([])
    })
    useStore.getState().addNode()
    const nodeId = useStore.getState().nodes[0].id
    await useStore.getState().runWorkflow()
    await vi.waitFor(() => expect(streamCalls).toHaveLength(1))
    expect(streamCalls[0]).toContain('/runs/run_1/events/stream?after=0')
    expect(useStore.getState().busy).toBe('run')

    stream.send('node.started', { seq: 2, type: 'node.started', node_id: nodeId }, 2)
    await vi.waitFor(() => expect(useStore.getState().liveStatus[nodeId]).toBe('running'))
    stream.send('node.started', { seq: 2, type: 'node.started', node_id: nodeId }, 2) // replay after a reconnect
    stream.send('node.finished', { seq: 3, type: 'node.finished', node_id: nodeId, status: 'succeeded' }, 3)
    await vi.waitFor(() => expect(useStore.getState().liveStatus[nodeId]).toBe('succeeded'))
    expect(useStore.getState().events.map((e) => e.seq)).toEqual([2, 3]) // the duplicate was ignored

    stream.send('run.finished', { seq: 4, type: 'run.finished', status: 'succeeded' }, 4)
    await vi.waitFor(() => expect(useStore.getState().run?.status).toBe('succeeded'))
    expect(useStore.getState().busy).toBeNull()
    expect(streamCalls).toHaveLength(1) // finished runs are not re-followed
    stream.close()
  })
})

describe('failed runs', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useStore.getState().reset()
  })

  it('selects the failing node and asks the editor to show the failing line', async () => {
    const stream = sseStream()
    const failedRun = {
      id: 'run_1',
      status: 'failed',
      duration_ms: 9,
      version_no: 1,
      nodes: [
        {
          node_id: 'good',
          status: 'succeeded',
          attempt: 1,
          input: null,
          output: 1,
          logs: [],
          error: null,
          duration_ms: 1,
        },
        {
          node_id: 'bad',
          status: 'failed',
          attempt: 1,
          input: 1,
          output: null,
          logs: [],
          duration_ms: 2,
          error: {
            type: 'runtime_error',
            message: 'ZeroDivisionError: x',
            traceback:
              'Traceback (most recent call last):\n  File "<node>", line 4, in main\nZeroDivisionError: x',
          },
        },
        {
          node_id: 'later',
          status: 'skipped',
          attempt: 1,
          input: null,
          output: null,
          logs: [],
          error: null,
          duration_ms: 0,
        },
      ],
    }
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) => {
      const u = String(url)
      if (u.includes('/events/stream')) return Promise.resolve(stream.response())
      if (u.endsWith('/workflows') && init?.method === 'POST')
        return jsonResponse({ id: 'wf_1', revision: 1 }, 201)
      if (u.endsWith('/workflows/wf_1/runs') && init?.method === 'POST')
        return jsonResponse({ id: 'run_1', status: 'running', nodes: [], duration_ms: 0, version_no: 1 }, 202)
      if (u.endsWith('/runs/run_1')) return jsonResponse(failedRun)
      return jsonResponse([])
    })
    useStore.getState().addNode()
    await useStore.getState().runWorkflow()
    stream.send('run.finished', { seq: 9, type: 'run.finished', status: 'failed' }, 9)
    await vi.waitFor(() => expect(useStore.getState().selectedId).toBe('bad'))
    expect(useStore.getState().focusLine).toMatchObject({ nodeId: 'bad', line: 4 })
    stream.close()
  })

  it('does not steal the selection when a run succeeds', async () => {
    useStore.setState({ selectedId: 'mine' })
    const stream = sseStream()
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) => {
      const u = String(url)
      if (u.includes('/events/stream')) return Promise.resolve(stream.response())
      if (u.endsWith('/workflows') && init?.method === 'POST')
        return jsonResponse({ id: 'wf_1', revision: 1 }, 201)
      if (u.endsWith('/workflows/wf_1/runs') && init?.method === 'POST')
        return jsonResponse({ id: 'run_2', status: 'running', nodes: [], duration_ms: 0, version_no: 1 }, 202)
      if (u.endsWith('/runs/run_2'))
        return jsonResponse({ id: 'run_2', status: 'succeeded', nodes: [], duration_ms: 1, version_no: 1 })
      return jsonResponse([])
    })
    useStore.getState().addNode()
    useStore.setState({ selectedId: 'mine' })
    await useStore.getState().runWorkflow()
    stream.send('run.finished', { seq: 3, type: 'run.finished', status: 'succeeded' }, 3)
    await vi.waitFor(() => expect(useStore.getState().run?.status).toBe('succeeded'))
    expect(useStore.getState().selectedId).toBe('mine')
    stream.close()
  })
})

describe('cancel and resume', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useStore.getState().reset()
  })

  it('cancels on the server and keeps following until run.finished', async () => {
    const calls: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) => {
      calls.push(`${init?.method ?? 'GET'} ${String(url)}`)
      return jsonResponse({ id: 'run_1', status: 'running', nodes: [], duration_ms: 0, version_no: 1 }, 202)
    })
    useStore.setState({ run: { id: 'run_1', status: 'running', nodes: [], duration_ms: 0 }, busy: 'run' })
    await useStore.getState().cancel()
    expect(calls).toContain('POST /api/v1/runs/run_1/cancel')
    expect(useStore.getState().busy).toBe('run') // still waiting for the server to confirm
  })

  it('does nothing when no run is in progress', async () => {
    const spy = vi.spyOn(globalThis, 'fetch')
    await useStore.getState().cancel()
    expect(spy).not.toHaveBeenCalled()
  })

  it('saves the latest edits first, then resumes as a new run and follows it', async () => {
    const stream = sseStream()
    const order: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) => {
      const u = String(url)
      order.push(`${init?.method ?? 'GET'} ${u.replace(/^.*\/api\/v1/, '')}`)
      if (u.includes('/events/stream')) return Promise.resolve(stream.response())
      if (u.endsWith('/workflows/wf_1') && init?.method === 'PUT')
        return jsonResponse({ id: 'wf_1', revision: 5 })
      return jsonResponse({ id: 'run_2', status: 'running', nodes: [], duration_ms: 0, version_no: 2 }, 202)
    })
    useStore.setState({
      workflowId: 'wf_1',
      revision: 4,
      run: { id: 'run_1', status: 'failed', nodes: [], duration_ms: 3 },
    })
    await useStore.getState().resume()
    expect(useStore.getState().run?.id).toBe('run_2')
    expect(order.indexOf('PUT /workflows/wf_1')).toBeGreaterThanOrEqual(0)
    expect(order.indexOf('PUT /workflows/wf_1')).toBeLessThan(order.indexOf('POST /runs/run_1/resume')) // fix is saved BEFORE resuming
    await vi.waitFor(() => expect(order.some((o) => o.includes('/runs/run_2/events/stream'))).toBe(true))
    stream.close()
  })

  it('does not resume if the edits could not be saved', async () => {
    const calls: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) => {
      calls.push(`${init?.method ?? 'GET'} ${String(url)}`)
      return jsonResponse({ error: { message: 'disk full' } }, 500)
    })
    useStore.setState({
      workflowId: 'wf_1',
      revision: 1,
      run: { id: 'run_1', status: 'failed', nodes: [], duration_ms: 3 },
    })
    await useStore.getState().resume()
    expect(calls.some((c) => c.includes('/resume'))).toBe(false)
    expect(useStore.getState().busy).toBeNull()
    expect(useStore.getState().message).toMatch(/Could not save/)
  })

  it('refuses to resume a succeeded run', async () => {
    const spy = vi.spyOn(globalThis, 'fetch')
    useStore.setState({ run: { id: 'run_1', status: 'succeeded', nodes: [], duration_ms: 3 } })
    await useStore.getState().resume()
    expect(spy).not.toHaveBeenCalled()
  })

  it('keeps a node shown as running while it will be retried', () => {
    const ev = (seq: number, type: RunEvent['type'], extra: Partial<RunEvent> = {}): RunEvent => ({
      seq,
      type,
      created_at: '',
      node_id: 'n1',
      ...extra,
    })
    applyEvent(ev(1, 'node.started', { attempt: 1 }))
    applyEvent(ev(2, 'node.finished', { status: 'failed', attempt: 1, will_retry: true }))
    expect(useStore.getState().liveStatus.n1).toBe('running')
    applyEvent(ev(3, 'node.started', { attempt: 2 }))
    applyEvent(ev(4, 'node.finished', { status: 'succeeded', attempt: 2, will_retry: false }))
    expect(useStore.getState().liveStatus.n1).toBe('succeeded')
  })
})

describe('panels', () => {
  it('shows an error with its type', () => {
    render(
      <ResultView
        status="failed"
        duration_ms={3}
        output={null}
        logs={[]}
        error={{ type: 'syntax_error', message: 'invalid syntax', line: 1 }}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('syntax_error')
  })
  it('shows empty history', () => {
    render(<RunPanel />)
    expect(screen.getByText(/No saved runs yet/)).toBeInTheDocument()
  })
})
