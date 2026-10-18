import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { useStore } from '../state/store'

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal('ResizeObserver', RO)
vi.stubGlobal(
  'DOMMatrixReadOnly',
  class {
    m22 = 1
    constructor(public transform?: string) {}
  },
)

function backend(opts: { failWrites?: boolean } = {}) {
  const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status }))
  return vi.spyOn(globalThis, 'fetch').mockImplementation((_url, init) => {
    const method = init?.method ?? 'GET'
    if (method === 'POST' || method === 'PUT') {
      if (opts.failWrites) return json({ error: { code: 'x', message: 'down' } }, 500)
      return json({ id: 'wf_1', name: 'Untitled', revision: 1, draft: { nodes: [], edges: [] } }, 201)
    }
    return json([])
  })
}

describe('App unsaved-work protection', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    useStore.getState().reset()
  })

  it('shows the save state and asks the browser to confirm leaving while edits are unsaved', async () => {
    backend()
    render(<App />)
    expect(screen.getByRole('status')).toHaveTextContent('Saved')
    act(() => useStore.getState().addNode())
    expect(screen.getByRole('status')).toHaveTextContent('Unsaved changes')

    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true) // browser will show "Leave site?"

    await act(async () => {
      await useStore.getState().flush()
    })
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Saved'))
    const clean = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(clean)
    expect(clean.defaultPrevented).toBe(false) // nothing to lose, no prompt
  })

  it('"New" saves first and does not nag when the save works', async () => {
    backend()
    const confirm = vi.spyOn(window, 'confirm')
    render(<App />)
    act(() => useStore.getState().addNode())
    fireEvent.click(screen.getByRole('button', { name: 'New' }))
    await waitFor(() => expect(useStore.getState().nodes).toHaveLength(0))
    expect(confirm).not.toHaveBeenCalled()
  })

  it('"New" asks before discarding edits that could not be saved, and respects "Cancel"', async () => {
    backend({ failWrites: true })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<App />)
    act(() => useStore.getState().addNode())
    fireEvent.click(screen.getByRole('button', { name: 'New' }))
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
    expect(useStore.getState().nodes).toHaveLength(1) // kept: the user said no
    expect(screen.getByRole('status')).toHaveTextContent('Save failed')

    confirm.mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: 'New' }))
    await waitFor(() => expect(useStore.getState().nodes).toHaveLength(0)) // discarded on purpose
  })
})
