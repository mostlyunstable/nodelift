import { useEffect } from 'react'
import { useStore } from '../state/store'

/** Short-lived messages. Cleared after a while; always readable by screen readers. */
export function Toast() {
  const message = useStore((s) => s.message)
  useEffect(() => {
    if (!message) return
    const t = setTimeout(() => useStore.setState((s) => (s.message === message ? { message: null } : s)), 8000)
    return () => clearTimeout(t)
  }, [message])
  if (!message) return null
  return (
    <div className="toast" role="status" aria-live="polite">
      <span>{message}</span>
      <button className="icon-button" aria-label="Dismiss message" onClick={() => useStore.setState({ message: null })}>
        ✕
      </button>
    </div>
  )
}

/** Announces run progress to screen readers without cluttering the screen. */
export function RunAnnouncer() {
  const text = useStore((s) => {
    if (s.busy === 'run') return 'Run in progress'
    const run = s.run
    if (!run) return ''
    if (run.status === 'succeeded') return 'Run succeeded'
    if (run.status === 'cancelled') return 'Run cancelled'
    if (run.status === 'failed') {
      const bad = [...run.nodes].reverse().find((n) => n.status === 'failed')
      const name = s.nodes.find((n) => n.id === bad?.node_id)?.data.name
      return name ? `Run failed at ${name}` : 'Run failed'
    }
    return ''
  })
  return (
    <div className="visually-hidden" role="status" aria-live="assertive">
      {text}
    </div>
  )
}

export function EmptyCanvas() {
  const { nodes, createExample, addNode, openDialog } = useStore()
  if (nodes.length > 0) return null
  return (
    <div className="empty-canvas">
      <h2>Build something that runs</h2>
      <p>
        Connect nodes to pass data from one step to the next. Every run keeps what each node received and
        returned, so you can see exactly what happened.
      </p>
      <div className="boot-actions">
        <button className="primary" onClick={() => void createExample()}>
          Try the “Debug me” example
        </button>
        <button onClick={() => addNode('code.python')}>Add a Python node</button>
      </div>
      <p className="muted">
        Press <kbd>⌘K</kbd> for every command, or{' '}
        <button className="link-button" onClick={() => openDialog('shortcuts')}>
          see the shortcuts
        </button>
        .
      </p>
    </div>
  )
}

const TOUR: Record<'run' | 'fix' | 'done', string> = {
  run: 'This example has a bug on purpose. Press Run (⌘↵) and watch what happens.',
  fix: 'It stopped at the node that failed, and the failing line is underlined. Fix it (the comment shows how), then press “Resume from failure”: steps whose code and input did not change are reused, not run again.',
  done: 'Fixed. Look at the Run history: the first nodes were reused, not re-run. Everything here works the same on your own workflows.',
}

export function TourBanner() {
  const { tour, dismissTour } = useStore()
  if (!tour) return null
  return (
    <div className="tour" role="note">
      <strong>{tour === 'done' ? 'Nice work' : tour === 'fix' ? 'Now fix it' : 'Start here'}</strong>
      <span>{TOUR[tour]}</span>
      <button className="icon-button" aria-label="Dismiss tip" onClick={dismissTour}>
        ✕
      </button>
    </div>
  )
}
