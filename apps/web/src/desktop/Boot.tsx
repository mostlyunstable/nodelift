import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { applyBackendInfo, isDesktop, tauriBridge, type DesktopBridge, type StartupFailure } from './bridge'

type Phase = { name: 'starting' } | { name: 'ready' } | { name: 'failed'; failure: StartupFailure }

function toFailure(e: unknown): StartupFailure {
  if (e && typeof e === 'object' && 'message' in e) {
    const f = e as Partial<StartupFailure>
    return { message: String(f.message), logTail: f.logTail ?? [], logPath: f.logPath ?? null }
  }
  return { message: String(e), logTail: [], logPath: null }
}

/**
 * In the desktop app, waits for the bundled backend before showing the editor and shows a real
 * error (with the log tail) if it cannot start. In a browser it renders the app immediately.
 */
export function Boot({ children, bridge }: { children: ReactNode; bridge?: DesktopBridge }) {
  const active = bridge ?? (isDesktop() ? tauriBridge() : null)
  const [phase, setPhase] = useState<Phase>(active ? { name: 'starting' } : { name: 'ready' })
  const [crashed, setCrashed] = useState<string | null>(null)

  const start = useCallback(async () => {
    if (!active) return
    setPhase({ name: 'starting' })
    try {
      applyBackendInfo(await active.waitForBackend())
      setCrashed(null)
      setPhase({ name: 'ready' })
    } catch (e) {
      setPhase({ name: 'failed', failure: toFailure(e) })
    }
  }, [active])

  useEffect(() => {
    void start()
    let off: (() => void) | undefined
    void active?.onBackendExit((reason) => {
      setCrashed(reason) // the shell restarts it; wait for it to come back
      void start()
    }).then((fn) => (off = fn))
    return () => off?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (phase.name === 'starting') {
    return (
      <div className="boot" role="status" aria-live="polite">
        <div className="boot-card">
          <strong className="brand">Nodecraft</strong>
          <p>{crashed ? 'The background service stopped. Restarting…' : 'Starting…'}</p>
        </div>
      </div>
    )
  }
  if (phase.name === 'failed') {
    const { failure } = phase
    const diagnostics = [failure.message, '', ...failure.logTail].join('\n')
    return (
      <div className="boot" role="alert">
        <div className="boot-card boot-error">
          <strong className="brand">Nodecraft could not start</strong>
          <p>{failure.message}</p>
          {failure.logTail.length > 0 && <pre className="boot-log">{failure.logTail.join('\n')}</pre>}
          <div className="boot-actions">
            <button
              className="primary"
              onClick={() => void active?.restartBackend().then(start, start)}
            >
              Try again
            </button>
            <button onClick={() => void navigator.clipboard?.writeText(diagnostics)}>Copy diagnostics</button>
            {failure.logPath && <button onClick={() => void active?.revealLogs()}>Show log folder</button>}
          </div>
        </div>
      </div>
    )
  }
  return <>{children}</>
}
