import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getApiConfig, setApiConfig } from '../api/config'
import { Boot } from './Boot'
import type { BackendInfo, DesktopBridge } from './bridge'

const INFO: BackendInfo = { baseUrl: 'http://127.0.0.1:50000', token: 'tok' }

function fakeBridge(overrides: Partial<DesktopBridge> = {}) {
  let exitCb: ((reason: string) => void) | undefined
  const bridge: DesktopBridge = {
    waitForBackend: vi.fn().mockResolvedValue(INFO),
    restartBackend: vi.fn().mockResolvedValue(undefined),
    revealLogs: vi.fn().mockResolvedValue(undefined),
    onBackendExit: vi.fn().mockImplementation(async (cb: (reason: string) => void) => {
      exitCb = cb
      return () => undefined
    }),
    ...overrides,
  }
  return { bridge, exit: (reason: string) => act(() => exitCb?.(reason)) }
}

describe('Boot', () => {
  beforeEach(() => setApiConfig({ baseUrl: '', token: null }))
  afterEach(() => vi.restoreAllMocks())

  it('renders the app straight away outside the desktop shell', () => {
    render(
      <Boot>
        <div>the editor</div>
      </Boot>,
    )
    expect(screen.getByText('the editor')).toBeInTheDocument()
  })

  it('waits for the backend, applies its address and token, then shows the app', async () => {
    let resolve!: (i: BackendInfo) => void
    const { bridge } = fakeBridge({ waitForBackend: () => new Promise((r) => (resolve = r)) })
    render(
      <Boot bridge={bridge}>
        <div>the editor</div>
      </Boot>,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Starting')
    expect(screen.queryByText('the editor')).not.toBeInTheDocument() // no API calls before it is ready
    await act(async () => resolve(INFO))
    expect(await screen.findByText('the editor')).toBeInTheDocument()
    expect(getApiConfig()).toEqual({ baseUrl: 'http://127.0.0.1:50000', token: 'tok' })
  })

  it('shows why startup failed, with the log tail, and lets the user retry', async () => {
    const failure = {
      message: 'port already in use',
      logTail: ['line one', 'line two'],
      logPath: '/tmp/logs/backend.log',
    }
    const waitForBackend = vi.fn().mockRejectedValueOnce(failure).mockResolvedValueOnce(INFO)
    const { bridge } = fakeBridge({ waitForBackend })
    render(
      <Boot bridge={bridge}>
        <div>the editor</div>
      </Boot>,
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('could not start')
    expect(screen.getByText('port already in use')).toBeInTheDocument()
    expect(screen.getByText(/line one/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('the editor')).toBeInTheDocument()
    expect(bridge.restartBackend).toHaveBeenCalledTimes(1)
    expect(waitForBackend).toHaveBeenCalledTimes(2)
  })

  it('offers the log folder and copies diagnostics', async () => {
    const failure = { message: 'boom', logTail: ['tail'], logPath: '/tmp/x.log' }
    const { bridge } = fakeBridge({ waitForBackend: vi.fn().mockRejectedValue(failure) })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    render(
      <Boot bridge={bridge}>
        <div />
      </Boot>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Show log folder' }))
    expect(bridge.revealLogs).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Copy diagnostics' }))
    expect(writeText).toHaveBeenCalledWith('boom\n\ntail')
  })

  it('hides the log button when there is no log path and tolerates plain-string errors', async () => {
    const { bridge } = fakeBridge({ waitForBackend: vi.fn().mockRejectedValue('plain failure') })
    render(
      <Boot bridge={bridge}>
        <div />
      </Boot>,
    )
    expect(await screen.findByText('plain failure')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show log folder' })).not.toBeInTheDocument()
  })

  it('shows a restarting message when the backend exits, and recovers', async () => {
    const waitForBackend = vi.fn().mockResolvedValueOnce(INFO)
    const { bridge, exit } = fakeBridge({ waitForBackend })
    render(
      <Boot bridge={bridge}>
        <div>the editor</div>
      </Boot>,
    )
    expect(await screen.findByText('the editor')).toBeInTheDocument()
    let resolveAgain!: (i: BackendInfo) => void
    waitForBackend.mockImplementationOnce(() => new Promise((r) => (resolveAgain = r)))
    exit('exit code 1')
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Restarting'))
    await act(async () => resolveAgain({ ...INFO, token: 'new-token' }))
    expect(await screen.findByText('the editor')).toBeInTheDocument()
    expect(getApiConfig().token).toBe('new-token') // picks up the restarted backend's credentials
  })
})

describe('Boot stability', () => {
  it('waits for the backend exactly once however often it re-renders', async () => {
    const { bridge } = fakeBridge()
    const { rerender } = render(
      <Boot bridge={bridge}>
        <div>app</div>
      </Boot>,
    )
    expect(await screen.findByText('app')).toBeInTheDocument()
    for (let i = 0; i < 5; i++) {
      rerender(
        <Boot bridge={{ ...bridge }}>
          <div>app</div>
        </Boot>,
      ) // a brand-new bridge object each time must not restart startup
    }
    expect(bridge.waitForBackend).toHaveBeenCalledTimes(1)
    expect(bridge.onBackendExit).toHaveBeenCalledTimes(1)
  })
})
