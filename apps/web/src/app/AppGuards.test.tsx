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

/** "New workflow" now lives in the Workflows menu. */
function chooseNew() {
  fireEvent.click(screen.getByRole('button', { name: 'Workflows' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'New workflow' }))
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
    expect(screen.getByRole('status', { name: 'Save status' })).toHaveTextContent('Saved')
    act(() => useStore.getState().addNode())
    expect(screen.getByRole('status', { name: 'Save status' })).toHaveTextContent('Unsaved changes')

    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true) // browser will show "Leave site?"

    await act(async () => {
      await useStore.getState().flush()
    })
    await waitFor(() =>
      expect(screen.getByRole('status', { name: 'Save status' })).toHaveTextContent('Saved'),
    )
    const clean = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(clean)
    expect(clean.defaultPrevented).toBe(false) // nothing to lose, no prompt
  })

  it('"New" saves first and does not nag when the save works', async () => {
    backend()
    const confirm = vi.spyOn(window, 'confirm')
    render(<App />)
    act(() => useStore.getState().addNode())
    chooseNew()
    await waitFor(() => expect(useStore.getState().nodes).toHaveLength(0))
    expect(confirm).not.toHaveBeenCalled()
  })

  it('"New" asks before discarding edits that could not be saved, and respects "Cancel"', async () => {
    backend({ failWrites: true })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<App />)
    act(() => useStore.getState().addNode())
    chooseNew()
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
    expect(useStore.getState().nodes).toHaveLength(1) // kept: the user said no
    expect(screen.getByRole('status', { name: 'Save status' })).toHaveTextContent('Save failed')

    confirm.mockReturnValue(true)
    chooseNew()
    await waitFor(() => expect(useStore.getState().nodes).toHaveLength(0)) // discarded on purpose
  })
})

describe('App shell', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    useStore.getState().reset()
    useStore.setState({ dialog: null, theme: 'dark', nodeDefs: [], workflows: [] })
  })

  const key = (k: string, mods: KeyboardEventInit = {}) =>
    act(
      () =>
        void window.dispatchEvent(
          new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...mods }),
        ),
    )

  it('⌘K opens the command palette from anywhere, Escape closes it', async () => {
    backend()
    render(<App />)
    key('k', { metaKey: true })
    expect(await screen.findByRole('dialog', { name: 'Command palette' })).toBeInTheDocument()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('running a palette command works end to end (add a node)', async () => {
    const defs = [
      {
        type: 'code.python',
        version: 1,
        title: 'Python code',
        category: 'Code',
        description: '',
        config_schema: {},
        default_config: { source: 'x' },
      },
    ]
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) =>
      Promise.resolve(new Response(JSON.stringify(String(url).endsWith('/nodes/definitions') ? defs : []))),
    )
    render(<App />)
    await waitFor(() => expect(useStore.getState().nodeDefs).toHaveLength(1))
    key('k', { metaKey: true })
    const input = await screen.findByRole('combobox', { name: 'Search commands' })
    fireEvent.change(input, { target: { value: 'add node python' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(useStore.getState().nodes).toHaveLength(1))
    expect(screen.queryByRole('dialog')).toBeNull() // the palette closed itself
  })

  it('⌘Z undoes and ⇧⌘Z redoes, but not while typing in a field', () => {
    backend()
    render(<App />)
    act(() => useStore.getState().addNode())
    expect(useStore.getState().nodes).toHaveLength(1)
    const name = screen.getByRole('textbox', { name: 'Workflow name' })
    name.focus()
    fireEvent.keyDown(name, { key: 'z', metaKey: true })
    expect(useStore.getState().nodes).toHaveLength(1) // the text field keeps its own undo
    ;(document.activeElement as HTMLElement).blur()
    key('z', { metaKey: true })
    expect(useStore.getState().nodes).toHaveLength(0)
    key('z', { metaKey: true, shiftKey: true })
    expect(useStore.getState().nodes).toHaveLength(1)
  })

  it('⌘↵ runs only when there is something to run', () => {
    const run = vi.spyOn(useStore.getState(), 'runWorkflow').mockResolvedValue()
    useStore.setState({ runWorkflow: run })
    backend()
    render(<App />)
    key('Enter', { metaKey: true })
    expect(run).not.toHaveBeenCalled() // empty canvas
    act(() => useStore.getState().addNode())
    key('Enter', { metaKey: true })
    expect(run).toHaveBeenCalledTimes(1)
  })

  it('the Workflows menu lists saved workflows and disables the open one', () => {
    backend()
    useStore.setState({
      workflows: [
        { id: 'a', name: 'Alpha', revision: 1, updated_at: '' },
        { id: 'b', name: 'Beta', revision: 1, updated_at: '' },
      ],
      workflowId: 'a',
    })
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Workflows' }))
    expect(screen.getByRole('menuitem', { name: 'Alpha' })).toBeDisabled()
    expect(screen.getByRole('menuitem', { name: 'Beta' })).toBeEnabled()
    expect(screen.getByRole('menuitem', { name: /Example: Debug me/ })).toBeInTheDocument()
  })

  it('applies the chosen theme to the page', () => {
    backend()
    render(<App />)
    act(() => useStore.getState().setTheme('light'))
    expect(document.documentElement.dataset.theme).toBe('light')
    act(() => useStore.getState().setTheme('dark'))
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('shows the empty-canvas welcome on a fresh start', () => {
    backend()
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Build something that runs' })).toBeInTheDocument()
    act(() => useStore.getState().addNode())
    expect(screen.queryByRole('heading', { name: 'Build something that runs' })).toBeNull()
  })

  it('the run button is disabled with nothing to run and while a run is in progress', () => {
    backend()
    render(<App />)
    expect(screen.getByRole('button', { name: /Run/ })).toBeDisabled()
    act(() => useStore.getState().addNode())
    expect(screen.getByRole('button', { name: /^▶ Run$/ })).toBeEnabled()
    act(() => useStore.setState({ busy: 'run' }))
    expect(screen.getByRole('button', { name: /Running/ })).toBeDisabled()
  })
})
