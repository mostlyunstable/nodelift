import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, type FileAnalysis, type WorkflowDraft } from '../api/client'
import { useExplorer } from '../state/explorer'
import { useStore } from '../state/store'
import { NodeFromFunctionDialog } from './NodeFromFunctionDialog'
import { FileDetails } from './FileDetails'

const draft: WorkflowDraft = {
  name: 'total',
  node_type: 'code.python',
  kind: 'copied implementation',
  provenance: { repository: 'octo/hello', commit: 'a'.repeat(40), path: 'calc.py', line: 3, symbol: 'total' },
  config: {
    source:
      '# Copied from octo/hello\ndef total(a, b):\n    return a + b\n\ndef main(input_data):\n    return total(**input_data)\n',
    provenance: {
      repository: 'octo/hello',
      commit: 'a'.repeat(40),
      path: 'calc.py',
      symbol: 'total',
      kind: 'copied implementation',
    },
  },
  copied: [{ kind: 'function', name: 'total', line: 3 }],
  warnings: ['`requests` is not in the Python standard library.'],
  params: ['a', 'b'],
}

beforeEach(() => {
  vi.restoreAllMocks()
  useExplorer.setState({ mode: 'explorer' })
})

describe('Make a workflow node', () => {
  it('shows what it is, where it came from, what was not copied, and the source - and creates nothing yet', async () => {
    vi.spyOn(api, 'explorerWorkflowDraft').mockResolvedValue(draft)
    const create = vi.spyOn(api, 'createWorkflow')
    render(<NodeFromFunctionDialog revisionId="rev_1" path="calc.py" symbol="total" onClose={() => {}} />)
    expect(await screen.findByText(/Copied implementation\./)).toBeInTheDocument()
    expect(screen.getByText(/not linked to the repository/)).toBeInTheDocument()
    expect(screen.getAllByText(/octo\/hello/).length).toBeGreaterThan(0)
    expect(screen.getByText('calc.py:3')).toBeInTheDocument()
    expect(screen.getByLabelText('Warnings')).toHaveTextContent('requests')
    expect(screen.getByLabelText('Generated source')).toHaveTextContent('return total(**input_data)')
    expect(screen.getByText(/keyword arguments: a, b/)).toBeInTheDocument()
    expect(create).not.toHaveBeenCalled()
  })

  it('Create saves exactly the reviewed source with its provenance, then opens Build', async () => {
    vi.spyOn(api, 'explorerWorkflowDraft').mockResolvedValue(draft)
    const create = vi.spyOn(api, 'createWorkflow').mockImplementation(
      async (name, definition) =>
        ({
          id: 'wf_1',
          name,
          draft: definition,
          revision: 1,
          created_at: 'x',
          updated_at: 'x',
        }) as never,
    )
    const open = vi.spyOn(useStore.getState(), 'open').mockResolvedValue()
    useStore.setState({ open, refresh: vi.fn().mockResolvedValue(undefined) } as never)
    const onClose = vi.fn()
    render(<NodeFromFunctionDialog revisionId="rev_1" path="calc.py" symbol="total" onClose={onClose} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Create workflow in Build' }))
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    const [, def] = create.mock.calls[0]!
    expect(def.nodes).toHaveLength(1)
    expect(def.nodes[0]!.type).toBe('code.python')
    expect(def.nodes[0]!.config.source).toBe(draft.config.source)
    expect(def.nodes[0]!.config.provenance).toMatchObject({ kind: 'copied implementation', path: 'calc.py' })
    await waitFor(() => expect(useExplorer.getState().mode).toBe('build'))
    expect(onClose).toHaveBeenCalled()
  })

  it('shows the reason when a function cannot be converted', async () => {
    vi.spyOn(api, 'explorerWorkflowDraft').mockRejectedValue(
      new ApiError('"Box" is not a top-level function of this file', 422, 'not_convertible'),
    )
    render(<NodeFromFunctionDialog revisionId="rev_1" path="calc.py" symbol="Box" onClose={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('not a top-level function')
    expect(screen.queryByRole('button', { name: 'Create workflow in Build' })).not.toBeInTheDocument()
  })
})

describe('where the action is offered', () => {
  const analysis = (): FileAnalysis => ({
    path: 'calc.py',
    status: 'analyzed',
    references: [],
    called_by: [],
    imports: [],
    dependents: [],
    diagnostics: [],
    symbols: [
      {
        path: 'calc.py',
        name: 'total',
        kind: 'function',
        line: 3,
        end_line: 5,
        parent: null,
        exported: true,
      },
      { path: 'calc.py', name: 'Box', kind: 'class', line: 8, end_line: 9, parent: null, exported: true },
      { path: 'calc.py', name: 'run', kind: 'method', line: 10, end_line: 11, parent: 'Box', exported: true },
    ],
  })

  it('only top-level Python functions get a Make node button', async () => {
    useExplorer.setState({
      revision: { id: 'rev_1', commit_sha: 'a'.repeat(40) } as never,
      files: [
        { path: 'calc.py', language: 'python' } as never,
        { path: 'x.js', language: 'javascript' } as never,
      ],
    })
    const { rerender } = render(<FileDetails analysis={analysis()} path="calc.py" />)
    expect(screen.getAllByRole('button', { name: 'Make node…' })).toHaveLength(1) // not the class, not the method
    await act(async () => rerender(<FileDetails analysis={{ ...analysis(), path: 'x.js' }} path="x.js" />))
    expect(screen.queryByRole('button', { name: 'Make node…' })).not.toBeInTheDocument()
  })
})
