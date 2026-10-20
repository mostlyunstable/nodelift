import { ReactFlowProvider } from '@xyflow/react'
import { act, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { FlowNode } from '../canvas/mapper'
import { useStore } from '../state/store'
import { CodeNode } from './CodeNode'

vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })

const node = (nodeType: string, id = 'n1'): FlowNode => ({
  id, type: 'node', position: { x: 0, y: 0 },
  data: { name: 'Check size', nodeType, config: {}, testInput: '{}', idempotent: false, maxAttempts: 1 },
})

function show(nodeType: string) {
  const n = node(nodeType)
  const props = { id: n.id, data: n.data, selected: false, type: 'node', dragging: false, zIndex: 0, isConnectable: true, positionAbsoluteX: 0, positionAbsoluteY: 0 }
  return render(
    <ReactFlowProvider>
      <CodeNode {...(props as unknown as Parameters<typeof CodeNode>[0])} />
    </ReactFlowProvider>,
  )
}

describe('CodeNode ports', () => {
  beforeEach(() => {
    useStore.getState().reset()
    useStore.setState({ nodeDefs: [], run: null, liveStatus: {} })
  })

  it('an ordinary node has one input and one output', () => {
    const { container } = show('code.python')
    expect(container.querySelectorAll('.react-flow__handle')).toHaveLength(2)
    expect(container.querySelector('[data-handleid="out"]')).not.toBeNull()
    expect(screen.queryByText('true')).toBeNull()
  })

  it('a branch shows labelled true and false outputs', () => {
    const { container } = show('logic.branch')
    expect(container.querySelectorAll('.react-flow__handle.source')).toHaveLength(2)
    expect(container.querySelector('[data-handleid="true"]')).not.toBeNull()
    expect(container.querySelector('[data-handleid="false"]')).not.toBeNull()
    expect(screen.getByText('true')).toBeInTheDocument()
    expect(screen.getByText('false')).toBeInTheDocument()
  })

  it('takes its ports from the node definition, so plugin nodes with several outputs work', () => {
    useStore.setState({ nodeDefs: [{ type: 'demo.split', version: 1, title: 'Split', category: 'Demo', description: '', config_schema: {}, default_config: {}, outputs: [{ name: 'a' }, { name: 'b' }, { name: 'c' }] }] })
    const { container } = show('demo.split')
    expect(container.querySelectorAll('.react-flow__handle.source')).toHaveLength(3)
  })

  it('after a run it says which way a branch went and why a node was skipped', () => {
    const base = { input: null, output: null, logs: [], error: null, duration_ms: 3 }
    act(() =>
      useStore.setState({
        run: { id: 'r', status: 'succeeded', duration_ms: 1, nodes: [{ ...base, node_id: 'n1', status: 'succeeded', activated_ports: ['true'] }] },
      }),
    )
    const first = show('logic.branch')
    expect(first.container.querySelector('.code-node-meta')).toHaveTextContent('succeeded · 3ms · true')
    expect(screen.getByText('false').className).toContain('dim') // the side that did not fire is dimmed
    first.unmount()
    act(() =>
      useStore.setState({
        run: { id: 'r', status: 'succeeded', duration_ms: 1, nodes: [{ ...base, node_id: 'n1', status: 'skipped', skip_reason: 'branch_not_taken' }] },
      }),
    )
    const second = show('code.python')
    expect(second.container.querySelector('.code-node-meta')).toHaveTextContent('skipped · not taken')
  })

  it('names a skip caused by a failure differently from an untaken branch', () => {
    const base = { input: null, output: null, logs: [], error: null, duration_ms: 0 }
    act(() =>
      useStore.setState({
        run: { id: 'r', status: 'failed', duration_ms: 1, nodes: [{ ...base, node_id: 'n1', status: 'skipped', skip_reason: 'upstream_failed' }] },
      }),
    )
    const { container } = show('code.python')
    expect(container.querySelector('.code-node-meta')).toHaveTextContent('skipped · upstream failed')
  })
})
