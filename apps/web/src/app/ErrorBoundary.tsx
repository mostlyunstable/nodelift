import { Component, type ErrorInfo, type ReactNode } from 'react'
import { recordedErrors, recordError, saveTextFile } from '../utils/errorLog'

/** Without this a bug in one panel blanks the whole window. Work is saved as you go, so reloading is safe. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    recordError(`render (${info.componentStack?.split('\n')[1]?.trim() ?? 'unknown component'})`, error)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    const report = [`Nodecraft interface error`, `build: ${__BUILD_ID__}`, '', ...recordedErrors()].join('\n')
    return (
      <div className="fatal" role="alert">
        <h1>Something went wrong</h1>
        <p>
          Nodecraft hit an unexpected error and stopped drawing this screen. Your workflows are saved
          automatically, so reloading is safe.
        </p>
        <pre className="boot-log">{error.message}</pre>
        <div className="row">
          <button className="primary" onClick={() => window.location.reload()}>
            Reload
          </button>
          <button onClick={() => void navigator.clipboard?.writeText(report)}>Copy details</button>
          <button onClick={() => saveTextFile('nodecraft-error.txt', report)}>Save details as a file</button>
        </div>
      </div>
    )
  }
}
