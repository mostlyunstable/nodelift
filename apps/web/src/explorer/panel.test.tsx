import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type FileAnalysis, type RepoFileContent, type RepoRevision } from '../api/client'
import { useExplorer } from '../state/explorer'
import { ExplorerView } from './ExplorerView'
import { buildPreviewDoc, PREVIEW_CSP } from './preview'

const calls = vi.hoisted(() => ({
  markers: [] as { path: string; line: number; message: string; severity: number }[],
  revealed: [] as number[],
}))

vi.mock('@monaco-editor/react', () => ({
  default: function FakeEditor({
    value,
    path,
    onMount,
  }: {
    value: string
    path: string
    onMount?: (e: unknown, m: unknown) => void
  }) {
    useEffect(() => {
      const model = { getLineMaxColumn: () => 80, getLineCount: () => 100 }
      const editor = {
        getModel: () => model,
        revealLineInCenter: (n: number) => calls.revealed.push(n),
        setPosition: () => {},
        createDecorationsCollection: () => ({ clear: () => {} }),
      }
      const monaco = {
        MarkerSeverity: { Error: 8, Warning: 4, Info: 2 },
        Range: class {},
        editor: {
          setModelMarkers: (
            _m: unknown,
            _o: string,
            ms: { startLineNumber: number; message: string; severity: number }[],
          ) =>
            ms.forEach((x) =>
              calls.markers.push({ path, line: x.startLineNumber, message: x.message, severity: x.severity }),
            ),
        },
      }
      onMount?.(editor, monaco) // the real component calls this once per mounted editor
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [path])
    return <pre data-testid="editor">{value}</pre>
  },
}))

const rev: RepoRevision = {
  schema_version: 1,
  id: 'rev_1',
  owner: 'octo',
  repo: 'hello',
  full_name: 'octo/hello',
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
  analyzed_count: 3,
  analysis_status: 'done',
  analysis_error: null,
  edge_count: 2,
  diagnostic_count: 1,
  error_code: null,
  error_message: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}
const meta = (path: string, language: string) => ({
  path,
  language,
  size: 10,
  lines: 5,
  binary: false,
  stored: true,
  skip_reason: null,
  analysis_status: 'analyzed',
})
const content = (path: string, language: string, text: string): RepoFileContent => ({
  path,
  language,
  size: text.length,
  lines: 5,
  binary: false,
  content: text,
  reason: null,
})
const edge = (src: string, dst: string | null, over = {}) => ({
  src,
  dst,
  kind: 'import',
  confidence: 'resolved',
  line: 3,
  raw: dst ?? 'requests',
  provenance: 'python.ast',
  note: null,
  ...over,
})
const analysisFor = (path: string): FileAnalysis => ({
  path,
  status: 'analyzed',
  symbols: [
    { path, name: 'main', kind: 'function', line: 10, end_line: 20, parent: null, exported: true },
    { path, name: 'run', kind: 'method', line: 30, end_line: 35, parent: 'App', exported: true },
  ],
  imports: [
    edge(path, 'utils.py'),
    edge(path, null, { confidence: 'external', note: 'standard library', raw: 'os', line: 1 }),
    edge(path, null, {
      confidence: 'unresolved',
      note: 'relative import target not found',
      raw: '.nope',
      line: 5,
    }),
    edge(path, 'tests/test_main.py', {
      kind: 'tests',
      confidence: 'heuristic',
      note: 'matched by file name only',
    }),
  ],
  dependents: [edge('app.py', path, { line: 7 })],
  diagnostics: [
    {
      path,
      line: 12,
      column: 1,
      severity: 'error',
      code: 'syntax_error',
      message: 'SyntaxError: bad',
      source: 'python.ast',
    },
  ],
})

beforeEach(() => {
  vi.restoreAllMocks()
  calls.markers.length = 0
  calls.revealed.length = 0
  useExplorer.setState({
    mode: 'explorer',
    revision: rev,
    revisions: [],
    files: [meta('main.py', 'python'), meta('utils.py', 'python'), meta('index.html', 'html')],
    edges: [],
    diagnostics: [
      {
        path: 'main.py',
        line: 12,
        column: 1,
        severity: 'error',
        code: 'syntax_error',
        message: 'SyntaxError: bad',
        source: 'python.ast',
      },
    ],
    selectedPath: null,
    file: null,
    analysis: null,
    target: null,
    history: [],
    tab: 'code',
    expanded: new Set(['']),
    languages: new Set(),
    error: null,
  })
  vi.spyOn(api, 'explorerRevisions').mockResolvedValue([])
  vi.spyOn(api, 'explorerFile').mockImplementation(async (_id, path) =>
    content(
      path,
      path.endsWith('.html') ? 'html' : 'python',
      path.endsWith('.html') ? '<h1>hi</h1><script>alert(1)</script>' : 'x = 1',
    ),
  )
  vi.spyOn(api, 'explorerAnalysis').mockImplementation(async (_id, path) => analysisFor(path))
})

const open = async (path: string) => {
  await act(async () => {
    await useExplorer.getState().reveal(path)
  })
}

describe('file details', () => {
  it('lists imports, dependents, symbols, problems, and what could not be resolved', async () => {
    render(<ExplorerView theme="dark" />)
    await open('main.py')
    fireEvent.click(screen.getByRole('tab', { name: /Details/ }))
    expect(screen.getByRole('button', { name: 'utils.py' })).toBeInTheDocument() // import
    expect(screen.getByRole('button', { name: 'app.py' })).toBeInTheDocument() // imported by
    expect(screen.getByText('SyntaxError: bad')).toBeInTheDocument()
    expect(screen.getByText('standard library')).toBeInTheDocument()
    expect(screen.getByText('relative import target not found')).toBeInTheDocument()
    expect(screen.getByText(/matched by file name only/)).toBeInTheDocument()
    expect(screen.getByText(/App\.run/)).toBeInTheDocument()
  })

  it('opens a referenced file, and Back returns to the previous one', async () => {
    render(<ExplorerView theme="dark" />)
    await open('main.py')
    fireEvent.click(screen.getByRole('tab', { name: /Details/ }))
    fireEvent.click(screen.getByRole('button', { name: 'utils.py' }))
    await waitFor(() => expect(useExplorer.getState().selectedPath).toBe('utils.py'))
    expect(useExplorer.getState().history).toEqual(['main.py'])
    fireEvent.click(screen.getByRole('button', { name: 'Back to the previous file' }))
    await waitFor(() => expect(useExplorer.getState().selectedPath).toBe('main.py'))
    expect(useExplorer.getState().history).toEqual([])
  })

  it('a symbol and a dependent jump to the right line', async () => {
    render(<ExplorerView theme="dark" />)
    await open('main.py')
    fireEvent.click(screen.getByRole('tab', { name: /Details/ }))
    fireEvent.click(screen.getByRole('button', { name: 'main' }))
    await waitFor(() => expect(useExplorer.getState().target).toMatchObject({ path: 'main.py', line: 10 }))
    fireEvent.click(screen.getByRole('button', { name: 'app.py' }))
    await waitFor(() => expect(useExplorer.getState().target).toMatchObject({ path: 'app.py', line: 7 }))
  })

  it('says plainly when a file has no analyzer', async () => {
    vi.spyOn(api, 'explorerAnalysis').mockResolvedValue({
      path: 'x',
      status: 'unsupported',
      symbols: [],
      imports: [],
      dependents: [],
      diagnostics: [],
    })
    render(<ExplorerView theme="dark" />)
    await open('main.py')
    fireEvent.click(screen.getByRole('tab', { name: /Details/ }))
    expect(screen.getByText(/No analyzer for this language yet/)).toBeInTheDocument()
  })
})

describe('source viewer', () => {
  it('marks diagnostics in the editor and reveals the requested line', async () => {
    render(<ExplorerView theme="dark" />)
    await act(async () => {
      await useExplorer.getState().goTo('main.py', 12)
    })
    await waitFor(() =>
      expect(calls.markers).toEqual([
        { path: 'main.py', line: 12, message: 'SyntaxError: bad', severity: 8 },
      ]),
    )
    await waitFor(() => expect(calls.revealed).toContain(12))
  })

  it('imported source stays read-only', async () => {
    render(<ExplorerView theme="dark" />)
    await open('main.py')
    expect(screen.getByText(/read-only/)).toBeInTheDocument()
  })
})

describe('problems tab', () => {
  it('lists diagnostics and opens the file at the line', async () => {
    useExplorer.setState({ tab: 'problems' })
    render(<ExplorerView theme="dark" />)
    expect(screen.getByText('SyntaxError: bad')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /line 12/ }))
    await waitFor(() => expect(useExplorer.getState().target).toMatchObject({ path: 'main.py', line: 12 }))
    expect(useExplorer.getState().tab).toBe('code')
  })

  it('does not pretend to be a linter when nothing was found', () => {
    useExplorer.setState({ tab: 'problems', diagnostics: [] })
    render(<ExplorerView theme="dark" />)
    expect(screen.getByText(/not a linter or a test run/)).toBeInTheDocument()
  })
})

describe('html preview', () => {
  it('renders inside a fully sandboxed iframe with a deny-all CSP', async () => {
    render(<ExplorerView theme="dark" />)
    await open('index.html')
    fireEvent.click(screen.getByRole('tab', { name: 'Preview' }))
    const frame = screen.getByTitle('Preview of index.html') as HTMLIFrameElement
    expect(frame.getAttribute('sandbox')).toBe('') // no allow-scripts, no allow-same-origin, no forms, no navigation
    expect(frame.getAttribute('srcdoc')).toContain(PREVIEW_CSP)
    expect(frame.getAttribute('src')).toBeNull()
    expect(frame.getAttribute('referrerpolicy')).toBe('no-referrer')
  })

  it('is offered only for HTML', async () => {
    render(<ExplorerView theme="dark" />)
    await open('main.py')
    expect(screen.queryByRole('tab', { name: 'Preview' })).not.toBeInTheDocument()
  })

  it('the preview document starts with the CSP so repository markup cannot loosen it first', () => {
    const doc = buildPreviewDoc('<script src="http://evil/x.js"></script>')
    expect(doc.startsWith('<meta http-equiv="Content-Security-Policy"')).toBe(true)
    expect(PREVIEW_CSP).toContain("default-src 'none'")
    expect(PREVIEW_CSP).not.toMatch(/script-src|connect-src|http/)
  })
})
