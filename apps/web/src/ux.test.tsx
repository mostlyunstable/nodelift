import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type RepoFile, type RepoRevision } from './api/client'
import { buildCommands, type CommandContext } from './app/commands'
import { explainError } from './panels/errors'
import { ExplorerView } from './explorer/ExplorerView'
import { Inspector } from './panels/Inspector'
import { LonelyNodesNotice } from './ui/Overlays'
import { ProblemsView } from './explorer/ProblemsView'
import { buildGraph, fileId } from './explorer/graph'
import { useExplorer } from './state/explorer'
import { useStore } from './state/store'
import type { NodeDefinition } from './types/workflow'

vi.mock('@monaco-editor/react', () => ({
  default: () => <div data-testid="editor" />,
  DiffEditor: () => <div />,
}))

const def = (
  type: string,
  title: string,
  category: string,
  props: Record<string, unknown>,
  required: string[] = [],
): NodeDefinition => ({
  type,
  version: 1,
  title,
  category,
  description: `${title} node`,
  default_config: {},
  config_schema: { type: 'object', required, properties: props },
})
const DEFS = [
  def(
    'data.filter',
    'Filter list',
    'Data',
    {
      items_path: { type: 'string', default: '$' },
      match: { enum: ['all', 'any'], default: 'all' },
      where: { type: 'array' },
    },
    ['where'],
  ),
  def('data.csv', 'CSV', 'Data', {
    mode: { enum: ['parse', 'write'] },
    header: { type: 'boolean', default: true },
    delimiter: { type: 'string', default: ',' },
  }),
  def('db.sqlite', 'SQLite query', 'Files', {
    sql: { type: 'string' },
    limit: { type: 'integer', minimum: 1, maximum: 50 },
  }),
]
const node = (id: string, nodeType: string, config: Record<string, unknown> = {}, name = id) => ({
  id,
  type: 'node',
  position: { x: 0, y: 0 },
  data: { name, nodeType, config, idempotent: false, maxAttempts: 1, testInput: '{}' },
})

beforeEach(() => {
  vi.restoreAllMocks()
  useStore.setState({ nodes: [], edges: [], selectedId: null, nodeDefs: DEFS } as never)
  useExplorer.setState({
    mode: 'explorer',
    revision: null,
    revisions: [],
    files: [],
    error: null,
    notice: null,
    sidebarOpen: true,
    codeOnly: false,
  })
  vi.spyOn(api, 'explorerRevisions').mockResolvedValue([])
})

describe('node settings are a form, not a JSON box', () => {
  const open = (n: ReturnType<typeof node>) => {
    useStore.setState({ nodes: [n], selectedId: n.id } as never)
    render(<Inspector />)
  }

  it('builds filter conditions with an operator menu and edits the real config', () => {
    open(
      node('f', 'data.filter', {
        items_path: '$',
        match: 'all',
        where: [{ path: '$.age', op: 'gte', value: 18 }],
      }),
    )
    expect(screen.getByLabelText('Condition 1 path')).toHaveValue('$.age')
    expect(screen.getByLabelText('Condition 1 operator')).toHaveValue('gte')
    expect(screen.getByLabelText('Condition 1 value')).toHaveValue('18')
    fireEvent.change(screen.getByLabelText('Condition 1 value'), { target: { value: '21' } })
    expect((useStore.getState().nodes[0]!.data.config.where as { value: unknown }[])[0]!.value).toBe(21) // numbers stay numbers
    fireEvent.click(screen.getByRole('button', { name: 'Add condition' }))
    expect((useStore.getState().nodes[0]!.data.config.where as unknown[]).length).toBe(2)
    fireEvent.click(screen.getByRole('button', { name: 'Remove condition 2' }))
    expect((useStore.getState().nodes[0]!.data.config.where as unknown[]).length).toBe(1)
    expect(screen.getByText(/Each path starts at the item itself/)).toBeInTheDocument() // says what the field is for
  })

  it('renders booleans, choices and numbers with the right controls and limits', () => {
    open(node('c', 'data.csv', { mode: 'parse', header: true }))
    fireEvent.change(screen.getByLabelText(/^Mode/), { target: { value: 'write' } })
    expect(useStore.getState().nodes[0]!.data.config.mode).toBe('write')
    fireEvent.click(screen.getByLabelText(/^Header/))
    expect(useStore.getState().nodes[0]!.data.config.header).toBe(false)
  })

  it('numbers respect the schema limits and long text gets a text area', () => {
    open(node('q', 'db.sqlite', { sql: 'select 1' }))
    expect(screen.getByLabelText(/^Limit/)).toHaveAttribute('max', '50')
    expect(screen.getByLabelText(/^Sql/).tagName).toBe('TEXTAREA')
  })

  it('still lets you edit the raw JSON, and come back', () => {
    open(node('c', 'data.csv', { mode: 'parse' }))
    fireEvent.click(screen.getByRole('button', { name: 'Edit as JSON' }))
    expect(screen.getByLabelText('Settings (JSON)')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Back to the form' }))
    expect(screen.getByLabelText(/^Mode/)).toBeInTheDocument()
  })

  it('shows retry settings only where retrying means something, and explains them', () => {
    useStore.setState({ nodes: [node('c', 'data.csv', {})], selectedId: 'c' } as never)
    const first = render(<Inspector />)
    expect(screen.queryByText(/Idempotent/)).not.toBeInTheDocument()
    first.unmount()
    useStore.setState({ nodes: [node('p', 'code.python', { source: 'x' })], selectedId: 'p' } as never)
    render(<Inspector />)
    expect(screen.getByText(/Idempotent/)).toBeInTheDocument()
    expect(screen.getByText(/only if running it twice is harmless/)).toBeInTheDocument()
  })
})

describe('unconnected nodes', () => {
  it('says which nodes stand alone and how to connect them', () => {
    useStore.setState({
      nodes: [
        node('a', 'code.python', {}, 'First'),
        node('b', 'code.python', {}, 'Second'),
        node('c', 'code.python', {}, 'Third'),
      ],
      edges: [{ id: 'e', source: 'a', target: 'b' }],
    } as never)
    render(<LonelyNodesNotice />)
    expect(screen.getByRole('note')).toHaveTextContent('“Third” isn’t connected to anything')
    expect(screen.getByRole('note')).toHaveTextContent(/Drag from the dot on the right/)
  })

  it('says nothing for a single node or a fully connected graph', () => {
    useStore.setState({ nodes: [node('a', 'code.python')], edges: [] } as never)
    const { container, rerender } = render(<LonelyNodesNotice />)
    expect(container).toBeEmptyDOMElement()
    useStore.setState({
      nodes: [node('a', 'code.python'), node('b', 'code.python')],
      edges: [{ id: 'e', source: 'a', target: 'b' }],
    } as never)
    rerender(<LonelyNodesNotice />)
    expect(container).toBeEmptyDOMElement()
  })
})

it('a data error tells you what to check instead of blaming "the transform"', () => {
  const t = explainError({ type: 'transform_error', message: 'The input at items_path is not a list' })
  expect(t).toContain('The input at items_path is not a list')
  expect(t).toMatch(/connected to a node that produces what it expects/)
  expect(t).not.toMatch(/The transform could not/)
})

describe('the Explorer is easy to find and to leave', () => {
  const revision = (over: Partial<RepoRevision> = {}): RepoRevision =>
    ({
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
      file_count: 3,
      text_count: 3,
      binary_count: 0,
      skipped_count: 0,
      total_bytes: 1,
      analyzed_count: 0,
      analysis_status: 'done',
      analysis_error: null,
      edge_count: 0,
      diagnostic_count: 0,
      error_code: null,
      error_message: null,
      created_at: '',
      updated_at: '',
      ...over,
    }) as RepoRevision
  const file = (path: string, language: string): RepoFile => ({
    path,
    language,
    size: 1,
    lines: 1,
    binary: false,
    stored: true,
    skip_reason: null,
    analysis_status: 'analyzed',
  })

  it('the welcome screen offers examples that start an import', async () => {
    vi.spyOn(api, 'explorerImport').mockResolvedValue(revision({ status: 'importing' }))
    vi.spyOn(api, 'explorerRevision').mockResolvedValue(revision({ status: 'importing' }))
    render(<ExplorerView theme="dark" />)
    expect(screen.getByText('See a codebase as nodes')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /octocat\/Spoon-Knife/ }))
    await waitFor(() =>
      expect(api.explorerImport).toHaveBeenCalledWith('https://github.com/octocat/Spoon-Knife'),
    )
  })

  it('you can leave a repository, check for a newer commit, and hide the file list', async () => {
    useExplorer.setState({ revision: revision(), files: [file('a.py', 'python')], revisions: [revision()] })
    vi.spyOn(api, 'explorerImport').mockResolvedValue(revision())
    vi.spyOn(api, 'explorerRevision').mockResolvedValue(revision())
    vi.spyOn(api, 'explorerFiles').mockResolvedValue([file('a.py', 'python')])
    render(<ExplorerView theme="dark" />)
    fireEvent.click(screen.getByRole('button', { name: 'Check for newer commit' }))
    expect(await screen.findByText(/already have the latest commit \(aaaaaaa\)/)).toBeInTheDocument()
    expect(api.explorerImport).toHaveBeenCalledWith('https://github.com/o/r/tree/main')
    fireEvent.click(screen.getByRole('button', { name: 'Hide the file list' }))
    expect(document.querySelector('.explorer-side')).toHaveAttribute('hidden')
    fireEvent.click(screen.getByRole('button', { name: 'Show the file list' }))
    expect(document.querySelector('.explorer-side')).not.toHaveAttribute('hidden')
    fireEvent.click(screen.getByRole('button', { name: /All repositories/ }))
    expect(useExplorer.getState().revision).toBeNull()
  })

  it('going back lists your imports at once, even if you leave while the import is still working', async () => {
    const list = [revision({ id: 'rev_9', full_name: 'a/b' })]
    vi.spyOn(api, 'explorerRevisions').mockResolvedValue(list)
    useExplorer.setState({ revision: revision(), files: [file('a.py', 'python')], revisions: [] })
    render(<ExplorerView theme="dark" />)
    fireEvent.click(screen.getByRole('button', { name: /All repositories/ }))
    expect(await screen.findByRole('region', { name: 'Recent imports' })).toHaveTextContent('a/b')
    expect(document.activeElement).toBe(document.getElementById('repo-url')) // ready for a different link
  })

  it('big repositories open code-only, and say so; the toggle shows everything', async () => {
    const files = [
      ...Array.from({ length: 70 }, (_, i) => file(`docs/d${i}.md`, 'markdown')),
      ...Array.from({ length: 6 }, (_, i) => file(`src/s${i}.py`, 'python')),
    ]
    vi.spyOn(api, 'explorerRevision').mockResolvedValue(revision({ file_count: 76 }))
    vi.spyOn(api, 'explorerFiles').mockResolvedValue(files)
    useExplorer.setState({ tab: 'graph' })
    render(<ExplorerView theme="dark" />)
    await act(async () => {
      await useExplorer.getState().openRevision('rev_1')
    })
    await waitFor(() => expect(useExplorer.getState().codeOnly).toBe(true))
    expect(await screen.findByText(/Showing source code only/)).toBeInTheDocument()
    expect(document.querySelectorAll('.xt-file')).toHaveLength(6)
    fireEvent.click(screen.getByRole('button', { name: 'Code only' }))
    expect(screen.queryByText(/Showing source code only/)).not.toBeInTheDocument()
  })
})

describe('commands', () => {
  it('in the Explorer the palette hides workflow-editing commands', () => {
    const ctx = {
      mode: 'explorer',
      hasNodes: true,
      busy: null,
      runStatus: null,
      canUndo: true,
      canRedo: false,
      workflowId: 'w',
      workflows: [],
      nodeDefs: [{ type: 'a', title: 'A' }],
      examples: [],
      hasVersions: false,
      actions: new Proxy({}, { get: () => vi.fn() }),
    } as unknown as CommandContext
    const groups = new Set(buildCommands(ctx).map((c) => c.group))
    expect([...groups].sort()).toEqual(['App', 'Explorer'])
  })

  it('the palette can take you to the Explorer from anywhere', () => {
    const ctx = {
      hasNodes: false,
      busy: null,
      runStatus: null,
      canUndo: false,
      canRedo: false,
      workflowId: null,
      workflows: [],
      nodeDefs: [],
      examples: [],
      hasVersions: false,
      actions: new Proxy({}, { get: () => vi.fn() }),
    } as unknown as CommandContext
    const titles = buildCommands(ctx).map((c) => c.title)
    expect(titles).toContain('Explore a GitHub repository…')
    expect(titles).toContain('Go to the workflow editor (Build)')
  })
})

describe('notes are not problems', () => {
  const diag = (path: string, severity: string, message: string) => ({
    path,
    line: 1,
    column: 1,
    severity,
    code: 'x',
    message,
    source: 's',
  })

  it('the graph badge counts only problems', () => {
    const files = [
      {
        path: 'a.js',
        language: 'javascript',
        size: 1,
        lines: 1,
        binary: false,
        stored: true,
        skip_reason: null,
        analysis_status: 'analyzed',
      },
    ]
    const g = buildGraph(files, 'r', {
      expanded: new Set(['']),
      languages: new Set(),
      diagnostics: [
        diag('a.js', 'info', 'parser note'),
        diag('a.js', 'info', 'another note'),
        diag('a.js', 'warning', 'real'),
      ],
    })
    expect(g.nodes.find((n) => n.id === fileId('a.js'))!.data.problems).toBe(1)
  })

  it('the Problems tab lists real problems and keeps notes folded away', () => {
    useExplorer.setState({
      revision: { analysis_status: 'done' } as never,
      diagnostics: [
        diag('a.py', 'error', 'SyntaxError: bad'),
        diag('b.js', 'info', 'The parser could not fully read this file'),
      ],
    })
    render(<ProblemsView />)
    expect(screen.getByText('SyntaxError: bad')).toBeInTheDocument()
    const notes = screen.getByText(/1 note \(not problems\)/)
    expect(notes.closest('details')).not.toHaveAttribute('open') // collapsed by default
    expect(screen.getByText(/could not fully read this file/)).toBeInTheDocument() // still available inside
  })

  it('with only notes it says there are no problems, and still offers the notes', () => {
    useExplorer.setState({
      revision: { analysis_status: 'done' } as never,
      diagnostics: [diag('b.js', 'info', 'a note')],
    })
    render(<ProblemsView />)
    expect(screen.getByText(/No problems found/)).toBeInTheDocument()
    expect(screen.getByText(/1 note \(not problems\)/)).toBeInTheDocument()
  })
})
