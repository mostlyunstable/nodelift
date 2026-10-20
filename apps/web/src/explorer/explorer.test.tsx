import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, type RepoRevision } from '../api/client'
import { useExplorer } from '../state/explorer'
import { ExplorerView } from './ExplorerView'

vi.mock('@monaco-editor/react', () => ({
  default: ({ value, language, path }: { value: string; language: string; path: string }) => (
    <pre data-testid="editor" data-language={language} data-path={path}>
      {value}
    </pre>
  ),
}))

const rev = (over: Partial<RepoRevision> = {}): RepoRevision => ({
  schema_version: 1,
  id: 'rev_1',
  owner: 'octo',
  repo: 'hello',
  full_name: 'octo/hello',
  branch: 'main',
  default_branch: 'main',
  commit_sha: 'a'.repeat(40),
  description: 'demo',
  status: 'ready',
  phase: 'Ready',
  file_count: 2,
  text_count: 2,
  binary_count: 0,
  skipped_count: 0,
  total_bytes: 100,
  analyzed_count: 0,
  error_code: null,
  error_message: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...over,
})

const file = (path: string) => ({
  path,
  language: path.endsWith('.py') ? 'python' : 'json',
  size: 10,
  lines: 1,
  binary: false,
  stored: true,
  skip_reason: null,
  analysis_status: 'not_analyzed',
})

beforeEach(() => {
  vi.restoreAllMocks()
  useExplorer.setState({
    mode: 'explorer',
    url: '',
    revision: null,
    revisions: [],
    files: [],
    selectedPath: null,
    file: null,
    fileError: null,
    error: null,
    starting: false,
  })
  vi.spyOn(api, 'explorerRevisions').mockResolvedValue([])
})

describe('Repository Explorer', () => {
  it('imports, lists real files, and opens source with the right language', async () => {
    vi.spyOn(api, 'explorerImport').mockResolvedValue(rev())
    vi.spyOn(api, 'explorerRevision').mockResolvedValue(rev())
    vi.spyOn(api, 'explorerFiles').mockResolvedValue([file('src/main.py'), file('config.json')])
    vi.spyOn(api, 'explorerFile').mockResolvedValue({
      path: 'config.json',
      language: 'json',
      size: 10,
      lines: 1,
      binary: false,
      content: '{"a": 1}',
      reason: null,
    })
    render(<ExplorerView theme="dark" />)

    const button = screen.getByRole('button', { name: 'Show Nodes' })
    expect(button).toBeDisabled()
    fireEvent.change(screen.getByLabelText('GitHub repository'), {
      target: { value: 'https://github.com/octo/hello' },
    })
    fireEvent.click(button)

    await screen.findByText('octo/hello')
    fireEvent.click(await screen.findByRole('treeitem', { name: /config\.json/ }))
    const editor = await screen.findByTestId('editor')
    expect(editor).toHaveTextContent('{"a": 1}')
    expect(editor).toHaveAttribute('data-language', 'json')
    expect(screen.getByText(/read-only/)).toBeInTheDocument()
    expect(api.explorerImport).toHaveBeenCalledWith('https://github.com/octo/hello')
  })

  it('shows the API error for an invalid or unavailable repository', async () => {
    vi.spyOn(api, 'explorerImport').mockRejectedValue(
      new ApiError('Only github.com repositories are supported', 422, 'invalid_repo_url'),
    )
    render(<ExplorerView theme="dark" />)
    fireEvent.change(screen.getByLabelText('GitHub repository'), {
      target: { value: 'https://gitlab.com/a/b' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Show Nodes' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Only github.com repositories are supported')
  })

  it('explains binary files instead of showing garbage', async () => {
    useExplorer.setState({ revision: rev(), files: [file('logo.png')], selectedPath: 'logo.png' })
    vi.spyOn(api, 'explorerFile').mockResolvedValue({
      path: 'logo.png',
      language: 'plaintext',
      size: 5,
      lines: 0,
      binary: true,
      content: null,
      reason: 'binary',
    })
    render(<ExplorerView theme="dark" />)
    fireEvent.click(screen.getByRole('treeitem', { name: /logo\.png/ }))
    expect(await screen.findByText(/binary file/)).toBeInTheDocument()
    expect(screen.queryByTestId('editor')).not.toBeInTheDocument()
  })

  it('filters the tree with search', async () => {
    useExplorer.setState({ revision: rev(), files: [file('src/main.py'), file('docs/readme.md')] })
    render(<ExplorerView theme="dark" />)
    fireEvent.change(screen.getByLabelText('Search files'), { target: { value: 'readme' } })
    expect(await screen.findByRole('option', { name: 'docs/readme.md' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'src/main.py' })).not.toBeInTheDocument()
  })

  it('reports a failed import with its reason', async () => {
    useExplorer.setState({
      revision: rev({ status: 'failed', error_message: 'The repository download is too large to import' }),
    })
    render(<ExplorerView theme="dark" />)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('too large'))
  })
})
