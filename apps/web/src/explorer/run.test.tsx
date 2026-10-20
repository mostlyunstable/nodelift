import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  api,
  type CommandRun,
  type Discovery,
  type RepoPatch,
  type RepoRevision,
  type Workspace,
} from '../api/client'
import { useExplorer } from '../state/explorer'
import { useRunner } from '../state/runner'
import { ExplorerView } from './ExplorerView'

vi.mock('@monaco-editor/react', () => ({
  default: ({
    value,
    onChange,
    options,
  }: {
    value: string
    onChange?: (v: string) => void
    options?: { readOnly?: boolean }
  }) => (
    <textarea
      data-testid="editor"
      aria-label="Editor"
      readOnly={options?.readOnly}
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
  DiffEditor: ({ original, modified }: { original: string; modified: string }) => (
    <div data-testid="diff-editor">
      {original} → {modified}
    </div>
  ),
}))

const rev = {
  schema_version: 1,
  id: 'rev_1',
  owner: 'o',
  repo: 'r',
  full_name: 'o/r',
  branch: 'main',
  default_branch: 'main',
  commit_sha: 'a'.repeat(40),
  description: '',
  status: 'ready',
  phase: 'Ready',
  file_count: 2,
  text_count: 2,
  binary_count: 0,
  skipped_count: 0,
  total_bytes: 1,
  analyzed_count: 1,
  analysis_status: 'done',
  analysis_error: null,
  edge_count: 0,
  diagnostic_count: 0,
  error_code: null,
  error_message: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
} as RepoRevision

const discovery: Discovery = {
  suggestions: [
    {
      id: 'make:test',
      label: 'make test',
      argv: ['make', 'test'],
      framework: 'make',
      kind: 'test',
      cwd: '',
      evidence: 'Makefile:3 target test',
      notes: ['Runs whatever the Makefile says; read it before approving.'],
    },
  ],
  test_files: ['test_a.py'],
  frameworks: ['make'],
}
const wsReady: Workspace = { state: 'ready', path: '/data/repos/rev_1/workspace', file_count: 5, error: null }
const wsNone: Workspace = { state: 'none', path: null, file_count: 0, error: null }
const run = (over: Partial<CommandRun> = {}): CommandRun => ({
  id: 'cmd_1',
  revision_id: 'rev_1',
  command: 'make test',
  argv: ['make', 'test'],
  cwd: '',
  status: 'failed',
  exit_code: 2,
  started_at: '2026-01-01T00:00:00Z',
  ended_at: '2026-01-01T00:00:01Z',
  output: 'FAILED test_add\n',
  output_truncated: false,
  confinement: { confined: true },
  notes: [],
  ...over,
})
const patch = (over: Partial<RepoPatch> = {}): RepoPatch => ({
  id: 'patch_1',
  revision_id: 'rev_1',
  path: 'calc.py',
  title: 'Fix add()',
  additions: 1,
  deletions: 1,
  applied: false,
  created_at: '2026-01-01T00:00:00Z',
  applied_at: null,
  ...over,
})

async function firstReview() {
  await screen.findByText('Makefile:3 target test') // the suggestions are listed before their buttons
  const btn = screen.getAllByRole('button', { name: /Review and run/ })[0]!
  await waitFor(() => expect(btn).toBeEnabled())
  return btn
}

function setup(ws: Workspace, opts: { runs?: CommandRun[]; patches?: RepoPatch[]; sandbox?: boolean } = {}) {
  vi.spyOn(api, 'explorerRevisions').mockResolvedValue([])
  vi.spyOn(api, 'explorerDiscovery').mockResolvedValue(discovery)
  vi.spyOn(api, 'explorerWorkspace').mockResolvedValue(ws)
  vi.spyOn(api, 'explorerCommands').mockResolvedValue(opts.runs ?? [])
  vi.spyOn(api, 'explorerPatches').mockResolvedValue(opts.patches ?? [])
  vi.spyOn(api, 'systemInfo').mockResolvedValue({
    sandbox: { mode: 'auto', active: opts.sandbox ?? true, kind: 'macos-seatbelt', memory_limit: 'watchdog' },
  } as never)
  useExplorer.setState({ mode: 'explorer', revision: rev, tab: 'run', files: [], diagnostics: [], edges: [] })
  render(<ExplorerView theme="dark" />)
}

beforeEach(() => {
  vi.restoreAllMocks()
  useRunner.setState({
    revisionId: null,
    discovery: null,
    workspace: null,
    runs: [],
    patches: [],
    error: null,
  })
})

describe('Run tab', () => {
  it('cites why a command is suggested and warns before anything runs', async () => {
    setup(wsReady)
    expect(await screen.findByText('Makefile:3 target test')).toBeInTheDocument()
    expect(screen.getByText(/read it before approving/)).toBeInTheDocument()
  })

  it('cannot run until the workspace is prepared; preparing runs nothing', async () => {
    setup(wsNone)
    const button = await screen.findByRole('button', { name: /Review and run/ })
    expect(button).toBeDisabled()
    vi.spyOn(api, 'explorerPrepareWorkspace').mockResolvedValue({ ...wsNone, state: 'preparing' })
    const runSpy = vi.spyOn(api, 'explorerRunCommand')
    fireEvent.click(screen.getByRole('button', { name: 'Prepare workspace' }))
    await waitFor(() => expect(api.explorerPrepareWorkspace).toHaveBeenCalledWith('rev_1'))
    expect(runSpy).not.toHaveBeenCalled()
  })

  it('shows the exact command and runs it only after Approve, with network and home off', async () => {
    setup(wsReady)
    const runSpy = vi
      .spyOn(api, 'explorerRunCommand')
      .mockResolvedValue(run({ status: 'running', exit_code: null }))
    fireEvent.click(await firstReview())
    expect(screen.getByLabelText('Command to run')).toHaveTextContent('make test')
    expect(runSpy).not.toHaveBeenCalled() // reviewing is not running
    fireEvent.click(screen.getByRole('button', { name: 'Approve and run' }))
    await waitFor(() => expect(runSpy).toHaveBeenCalledTimes(1))
    expect(runSpy).toHaveBeenCalledWith('rev_1', {
      command: 'make test',
      approved_command: 'make test',
      cwd: '',
      allow_network: false,
      allow_home_read: false,
      acknowledge_unconfined: false,
    })
  })

  it('Cancel in the approval dialog runs nothing', async () => {
    setup(wsReady)
    const runSpy = vi.spyOn(api, 'explorerRunCommand')
    fireEvent.click(await firstReview())
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(runSpy).not.toHaveBeenCalled()
    expect(screen.queryByLabelText('Command to run')).not.toBeInTheDocument()
  })

  it('network and home access are opt-in checkboxes passed through only when ticked', async () => {
    setup(wsReady)
    const runSpy = vi.spyOn(api, 'explorerRunCommand').mockResolvedValue(run())
    fireEvent.change(await screen.findByLabelText('Custom command'), { target: { value: 'npm ci' } })
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: /Review and run/ }).at(-1)).toBeEnabled(),
    )
    fireEvent.click(screen.getAllByRole('button', { name: /Review and run/ }).at(-1)!)
    fireEvent.click(screen.getByLabelText(/Allow network access/))
    fireEvent.click(screen.getByRole('button', { name: 'Approve and run' }))
    await waitFor(() => expect(runSpy).toHaveBeenCalled())
    expect(runSpy.mock.calls[0]![1]).toMatchObject({
      command: 'npm ci',
      allow_network: true,
      allow_home_read: false,
    })
  })

  it('on a machine that cannot confine, approval needs an extra explicit acknowledgement', async () => {
    setup(wsReady, { sandbox: false })
    fireEvent.click(await firstReview())
    expect(screen.getByText(/cannot confine commands/)).toBeInTheDocument()
    const approve = screen.getByRole('button', { name: 'Approve and run' })
    expect(approve).toBeDisabled()
    fireEvent.click(screen.getByLabelText(/run unconfined/))
    expect(approve).toBeEnabled()
  })

  it('shows the real output and exit code of the latest run', async () => {
    setup(wsReady, { runs: [run()] })
    expect(await screen.findByText(/FAILED test_add/)).toBeInTheDocument()
    expect(screen.getByText(/failed · exit 2/)).toBeInTheDocument()
  })

  it('a running command can be cancelled', async () => {
    setup(wsReady, { runs: [run({ status: 'running', exit_code: null, output: '' })] })
    vi.spyOn(api, 'explorerCancelCommand').mockResolvedValue(run({ status: 'cancelled' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(api.explorerCancelCommand).toHaveBeenCalledWith('rev_1', 'cmd_1'))
  })
})

describe('proposed changes', () => {
  it('apply and revert go through the API; an applied patch cannot be deleted', async () => {
    setup(wsReady, { patches: [patch()] })
    vi.spyOn(api, 'explorerApplyPatch').mockResolvedValue(patch({ applied: true }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply to workspace' }))
    await waitFor(() => expect(api.explorerApplyPatch).toHaveBeenCalledWith('rev_1', 'patch_1'))
    await act(async () => {
      useRunner.setState({ patches: [patch({ applied: true })] })
    })
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled()
    vi.spyOn(api, 'explorerRevertPatch').mockResolvedValue(patch())
    fireEvent.click(screen.getByRole('button', { name: 'Revert in workspace' }))
    await waitFor(() => expect(api.explorerRevertPatch).toHaveBeenCalled())
  })

  it('view diff shows the real unified diff', async () => {
    setup(wsReady, { patches: [patch()] })
    vi.spyOn(api, 'explorerPatchDiff').mockResolvedValue(
      'diff --git a/calc.py b/calc.py\n-    return a - b\n+    return a + b\n',
    )
    fireEvent.click(await screen.findByRole('button', { name: 'View diff' }))
    expect(await screen.findByText(/return a \+ b/)).toBeInTheDocument()
  })

  it('proposing a change edits a copy and saves it as a patch, never the imported file', async () => {
    vi.spyOn(api, 'explorerRevisions').mockResolvedValue([])
    vi.spyOn(api, 'explorerAnalysis').mockRejectedValue(new Error('none'))
    vi.spyOn(api, 'explorerFile').mockResolvedValue({
      path: 'calc.py',
      language: 'python',
      size: 10,
      lines: 2,
      binary: false,
      content: 'x = 1\n',
      reason: null,
    })
    vi.spyOn(api, 'explorerPatches').mockResolvedValue([])
    const create = vi.spyOn(api, 'explorerCreatePatch').mockResolvedValue(patch())
    useExplorer.setState({
      mode: 'explorer',
      revision: rev,
      tab: 'code',
      selectedPath: 'calc.py',
      files: [],
      diagnostics: [],
      edges: [],
    })
    render(<ExplorerView theme="dark" />)
    await act(async () => {
      await useExplorer.getState().selectFile('calc.py')
    })
    expect(screen.getByLabelText('Editor')).toHaveAttribute('readonly')
    fireEvent.click(screen.getByRole('button', { name: /Propose a change/ }))
    const editor = screen.getByLabelText('Editor')
    expect(editor).not.toHaveAttribute('readonly')
    fireEvent.change(editor, { target: { value: 'x = 2\n' } })
    fireEvent.click(screen.getByRole('button', { name: /Review and save as patch/ }))
    expect(screen.getByTestId('diff-editor')).toHaveTextContent('x = 1 → x = 2')
    fireEvent.click(screen.getByRole('button', { name: 'Save as patch' }))
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith('rev_1', {
        path: 'calc.py',
        title: 'Change to calc.py',
        new_content: 'x = 2\n',
      }),
    )
  })
})
