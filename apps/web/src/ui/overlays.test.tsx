import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { jsonResponse } from '../test-utils/sse'
import { useStore } from '../state/store'
import type { VersionRecord, WorkflowDefinition } from '../types/workflow'
import { DiagnosticsDialog, ImportDialog, ShortcutsDialog, VersionsDialog } from './Dialogs'
import { EmptyCanvas, RunAnnouncer, Toast, TourBanner } from './Overlays'

const s = () => useStore.getState()
const def = (source: string): WorkflowDefinition => ({
  schema_version: 1,
  id: '',
  name: 'W',
  edges: [],
  ui: { positions: {} },
  nodes: [{ id: 'n1', type: 'code.python', name: 'Step', config: { source } }],
})
const version = (n: number, source: string): VersionRecord => ({
  id: `v${n}`,
  workflow_id: 'wf_1',
  version_no: n,
  content_hash: 'h',
  created_at: '2026-10-20T10:00:00Z',
  definition: def(source),
})

beforeEach(() => {
  vi.restoreAllMocks()
  s().reset()
  useStore.setState({ dialog: null, tour: null, message: null, importPreview: null, viewedVersion: null })
})

describe('VersionsDialog', () => {
  it('explains versions, lists them, and compares a chosen one with the editor', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) =>
      String(url).endsWith('/versions/1') ? jsonResponse(version(1, 'old code')) : jsonResponse([]),
    )
    useStore.setState({
      workflowId: 'wf_1',
      versions: [
        { version_no: 2, content_hash: 'b', created_at: '2026-10-20T11:00:00Z' },
        { version_no: 1, content_hash: 'a', created_at: '2026-10-20T10:00:00Z' },
      ],
    })
    s().addNode()
    useStore.getState().updateConfig(s().nodes[0].id, { source: 'new code' })
    render(<VersionsDialog />)
    expect(screen.getByText(/frozen copy/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /v2/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /v1/ }))
    expect(await screen.findByText(/compared with the editor/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Restore version 1/ })).toBeInTheDocument()
  })

  it('invites you to run when there are no versions', () => {
    render(<VersionsDialog />)
    expect(screen.getByText(/No versions yet/)).toBeInTheDocument()
  })

  it('says so when a version matches the editor exactly', async () => {
    useStore.setState({
      workflowId: 'wf_1',
      versions: [{ version_no: 1, content_hash: 'a', created_at: '2026-10-20T10:00:00Z' }],
    })
    s().addNode()
    const node = s().nodes[0]
    vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
      jsonResponse({
        ...version(1, ''),
        definition: {
          schema_version: 1,
          id: '',
          name: s().workflowName,
          edges: [],
          ui: { positions: {} },
          nodes: [{ id: node.id, type: node.data.nodeType, name: node.data.name, config: node.data.config }],
        },
      }),
    )
    render(<VersionsDialog />)
    fireEvent.click(screen.getByRole('button', { name: /v1/ }))
    expect(await screen.findByText('They are identical.')).toBeInTheDocument()
  })
})

describe('ImportDialog', () => {
  const preview = (over = {}) => ({
    file: {},
    preview: {
      valid: true,
      issues: [],
      summary: {
        name: 'Orders',
        nodes: 3,
        edges: 2,
        node_types: { 'code.python': 2, 'http.request': 1 },
        code_nodes: 2,
        http_hosts: ['api.example.com'],
        warnings: ['2 code node(s) run Python as you on this computer. Read them before running.'],
      },
      ...over,
    },
  })

  it('shows what is in the file and the warnings, and lets you import or cancel', () => {
    useStore.setState({ importPreview: preview(), dialog: 'import' })
    render(<ImportDialog />)
    expect(screen.getByRole('heading', { name: 'Orders' })).toBeInTheDocument()
    expect(screen.getByText(/2× code.python, 1× http.request/)).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Things to know' })).toHaveTextContent('Read them before running')
    expect(screen.getByText(/does not run anything/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(s().dialog).toBeNull()
  })

  it('refuses an invalid file and lists why', () => {
    useStore.setState({
      importPreview: preview({
        valid: false,
        issues: [{ code: 'unknown_node_type', message: 'Unknown type magic.node' }],
      }),
      dialog: 'import',
    })
    render(<ImportDialog />)
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('Unknown type magic.node')
  })

  it('renders nothing without a pending import', () => {
    const { container } = render(<ImportDialog />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('DiagnosticsDialog', () => {
  const INFO = {
    version: '0.1.0',
    schema_revision: '0003',
    schema_head: '0003',
    data_dir: '/data',
    log_dir: '/logs',
    backup_dir: '/data/backups',
    backups: [],
    python: '3.12.15',
    uptime_s: 12.4,
  }

  it('shows the facts a support request needs and copies a report', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) =>
      String(url).includes('/system/info')
        ? jsonResponse(INFO)
        : jsonResponse({ path: '/logs/backend.log', lines: ['line one', 'line two'] }),
    )
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    render(<DiagnosticsDialog />)
    expect(await screen.findByText('/data')).toBeInTheDocument()
    expect(screen.getByText(/\(current\)/)).toBeInTheDocument()
    expect(await screen.findByText(/line one/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Copy diagnostics' }))
    const report = writeText.mock.calls[0][0] as string
    expect(report).toContain('Nodecraft 0.1.0')
    expect(report).toContain('line two')
    expect(screen.getByText(/never contain your API token/)).toBeInTheDocument()
  })

  it('reports an unreachable service instead of hanging', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('offline'))
    render(<DiagnosticsDialog />)
    expect(await screen.findByRole('alert')).toHaveTextContent('offline')
  })
})

describe('ShortcutsDialog', () => {
  it('documents the shortcuts that really exist', () => {
    render(<ShortcutsDialog />)
    for (const key of ['⌘K', '⌘↵', '⌘.', '⌘S', '⌘Z / ⇧⌘Z']) expect(screen.getByText(key)).toBeInTheDocument()
  })
})

describe('Toast', () => {
  afterEach(() => vi.useRealTimers())

  it('shows a message, can be dismissed, and goes away by itself', () => {
    vi.useFakeTimers()
    render(<Toast />)
    expect(screen.queryByRole('status')).toBeNull()
    act(() => useStore.setState({ message: 'Saved a version' }))
    expect(screen.getByRole('status')).toHaveTextContent('Saved a version')
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss message' }))
    expect(screen.queryByRole('status')).toBeNull()
    act(() => useStore.setState({ message: 'Will fade' }))
    act(() => void vi.advanceTimersByTime(8100))
    expect(useStore.getState().message).toBeNull()
  })

  it('does not erase a newer message when an older timer fires', () => {
    vi.useFakeTimers()
    render(<Toast />)
    act(() => useStore.setState({ message: 'first' }))
    act(() => void vi.advanceTimersByTime(5000))
    act(() => useStore.setState({ message: 'second' }))
    act(() => void vi.advanceTimersByTime(4000)) // the first timer's deadline passes
    expect(useStore.getState().message).toBe('second')
  })
})

describe('RunAnnouncer', () => {
  const live = () => screen.getByRole('status')
  it('announces progress and outcomes for screen readers', () => {
    render(<RunAnnouncer />)
    expect(live()).toHaveTextContent('')
    act(() => useStore.setState({ busy: 'run' }))
    expect(live()).toHaveTextContent('Run in progress')
    act(() =>
      useStore.setState({ busy: null, run: { id: 'r', status: 'succeeded', nodes: [], duration_ms: 1 } }),
    )
    expect(live()).toHaveTextContent('Run succeeded')
    act(() => useStore.setState({ run: { id: 'r', status: 'cancelled', nodes: [], duration_ms: 1 } }))
    expect(live()).toHaveTextContent('Run cancelled')
  })

  it('names the node a run failed at', () => {
    s().addNode()
    const node = s().nodes[0]
    act(() =>
      useStore.setState({
        run: {
          id: 'r',
          status: 'failed',
          duration_ms: 1,
          nodes: [
            {
              node_id: node.id,
              status: 'failed',
              input: null,
              output: null,
              logs: [],
              error: null,
              duration_ms: 1,
            },
          ],
        },
      }),
    )
    render(<RunAnnouncer />)
    expect(live()).toHaveTextContent(`Run failed at ${node.data.name}`)
  })
})

describe('EmptyCanvas and TourBanner', () => {
  it('offers a way in only while the canvas is empty', () => {
    const { rerender } = render(<EmptyCanvas />)
    expect(screen.getByRole('button', { name: /Debug me/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add a Python node' }))
    expect(s().nodes).toHaveLength(1)
    rerender(<EmptyCanvas />)
    expect(screen.queryByRole('button', { name: /Debug me/ })).toBeNull()
  })

  it('the shortcuts link opens the shortcuts dialog', () => {
    render(<EmptyCanvas />)
    fireEvent.click(screen.getByRole('button', { name: 'see the shortcuts' }))
    expect(s().dialog).toBe('shortcuts')
  })

  it('shows the right tip for each stage and can be dismissed', () => {
    render(<TourBanner />)
    expect(screen.queryByRole('note')).toBeNull()
    act(() => useStore.setState({ tour: 'run' }))
    expect(screen.getByRole('note')).toHaveTextContent('Press Run')
    act(() => useStore.setState({ tour: 'fix' }))
    expect(screen.getByRole('note')).toHaveTextContent('Resume from failure')
    act(() => useStore.setState({ tour: 'done' }))
    expect(screen.getByRole('note')).toHaveTextContent('reused, not re-run')
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss tip' }))
    expect(screen.queryByRole('note')).toBeNull()
  })
})
