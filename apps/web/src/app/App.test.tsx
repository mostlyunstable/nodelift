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
