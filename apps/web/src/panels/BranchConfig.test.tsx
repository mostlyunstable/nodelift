import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useStore } from '../state/store'
import { ConfigEditor } from './ConfigEditors'

vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })

describe('branch settings', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('[]'))
    useStore.getState().reset()
    useStore.setState({ nodeDefs: [{ type: 'logic.branch', version: 1, title: 'Branch (if / else)', category: 'Logic', description: '', config_schema: {}, default_config: { path: '$', operator: 'truthy' }, outputs: [{ name: 'true' }, { name: 'false' }] }] })
    useStore.getState().addNode('logic.branch')
  })

  const editor = () => render(<ConfigEditor node={useStore.getState().nodes[0]} />)

  it('starts with sensible defaults and no value box for a "has a value" test', () => {
    editor()
    expect(useStore.getState().nodes[0].data.config).toEqual({ path: '$', operator: 'truthy' })
    expect(screen.getByLabelText(/Look at/)).toHaveValue('$')
    expect(screen.queryByLabelText(/this value/)).toBeNull()
  })

  it('shows the comparison value only for operators that need one, and stores what you type', () => {
    const { rerender } = editor()
    fireEvent.change(screen.getByLabelText(/Send it down/), { target: { value: 'gt' } })
    rerender(<ConfigEditor node={useStore.getState().nodes[0]} />)
    const value = screen.getByLabelText(/this value/)
    fireEvent.change(value, { target: { value: '100' } })
    fireEvent.change(screen.getByLabelText(/Look at/), { target: { value: '$.order.total' } })
    expect(useStore.getState().nodes[0].data.config).toMatchObject({ path: '$.order.total', operator: 'gt', value: 100 })
    fireEvent.change(screen.getByLabelText(/Send it down/), { target: { value: 'exists' } })
    rerender(<ConfigEditor node={useStore.getState().nodes[0]} />)
    expect(screen.queryByLabelText(/this value/)).toBeNull()
  })

  it('explains what happens to the other side', () => {
    editor()
    expect(screen.getByText(/the other side is skipped/)).toBeInTheDocument()
  })

  it('creates the node with the palette defaults and a readable name', () => {
    expect(useStore.getState().nodes[0].data.name).toBe('Branch (if / else) 1')
    expect(useStore.getState().nodes[0].data.nodeType).toBe('logic.branch')
  })
})

describe('connecting a branch', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('[]'))
    useStore.getState().reset()
  })

  it('keeps the true and false connections separate and labels them', () => {
    const s = () => useStore.getState()
    s().addNode()
    s().addNode()
    const [a, b] = s().nodes.map((n) => n.id)
    s().onConnect({ source: a, target: b, sourceHandle: 'true', targetHandle: 'in' })
    s().onConnect({ source: a, target: b, sourceHandle: 'false', targetHandle: 'in' })
    s().onConnect({ source: a, target: b, sourceHandle: 'true', targetHandle: 'in' }) // exact duplicate
    expect(s().edges.map((e) => e.label)).toEqual(['true', 'false'])
    expect(new Set(s().edges.map((e) => e.id)).size).toBe(2)
    s().onConnect({ source: a, target: b, sourceHandle: 'out', targetHandle: 'in' })
    expect(s().edges[2].label).toBeUndefined() // a plain output stays unlabelled
  })
})
