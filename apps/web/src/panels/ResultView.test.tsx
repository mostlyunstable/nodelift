import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ResultView } from './ResultView'

const failure = {
  type: 'runtime_error',
  message: 'ZeroDivisionError: float division by zero',
  traceback: 'Traceback (most recent call last):\n  File "<node>", line 3, in main\nZeroDivisionError: x',
}

describe('ResultView errors', () => {
  it('leads with a plain-language explanation and keeps the technical detail one click away', () => {
    render(<ResultView status="failed" duration_ms={5} output={null} logs={[]} error={failure} />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('Something was divided by zero (line 3).')
    expect(alert.querySelector('details')).not.toBeNull()
    expect(alert).toHaveTextContent('ZeroDivisionError: float division by zero') // still there for experts
  })

  it('offers "Show line N" only when there is a line and a handler, and calls it', () => {
    const onShowLine = vi.fn()
    const { rerender } = render(
      <ResultView status="failed" duration_ms={5} output={null} logs={[]} error={failure} onShowLine={onShowLine} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Show line 3 in the code' }))
    expect(onShowLine).toHaveBeenCalledWith(3)
    rerender(<ResultView status="failed" duration_ms={5} output={null} logs={[]} error={failure} />)
    expect(screen.queryByRole('button', { name: /Show line/ })).toBeNull() // no handler, no button
    rerender(
      <ResultView status="failed" duration_ms={5} output={null} logs={[]} onShowLine={onShowLine}
        error={{ type: 'timeout', message: 'Exceeded 5s limit' }} />,
    )
    expect(screen.queryByRole('button', { name: /Show line/ })).toBeNull() // no line to show
  })

  it('shows no error box for a successful node', () => {
    render(<ResultView status="succeeded" duration_ms={5} output={{ a: 1 }} logs={[]} error={null} />)
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
