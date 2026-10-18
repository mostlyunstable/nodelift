import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useStore } from '../state/store'
import { RunPanel } from '../panels/RunPanel'
import { ResultView } from '../panels/ResultView'

vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })

describe('store', () => {
  beforeEach(() => useStore.getState().reset())
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

describe('panels', () => {
  it('shows an error with its type', () => {
    render(
      <ResultView status="failed" duration_ms={3} output={null} logs={[]}
        error={{ type: 'syntax_error', message: 'invalid syntax', line: 1 }} />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('syntax_error')
  })
  it('prompts to run when there is no run', () => {
    render(<RunPanel />)
    expect(screen.getByText(/Run the workflow to see/)).toBeInTheDocument()
  })
})
