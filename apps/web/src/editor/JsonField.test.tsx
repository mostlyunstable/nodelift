import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { JsonField } from './JsonField'

describe('JsonField', () => {
  it('commits valid JSON and keeps invalid text without losing it', () => {
    const onChange = vi.fn()
    render(<JsonField label="Headers" value={{}} onChange={onChange} />)
    const box = screen.getByLabelText(/Headers/)
    fireEvent.change(box, { target: { value: '{"a": 1}' } })
    expect(onChange).toHaveBeenLastCalledWith({ a: 1 })
    fireEvent.change(box, { target: { value: '{"a": ' } })
    expect(screen.getByText(/Invalid JSON/)).toBeInTheDocument()
    expect(onChange).toHaveBeenCalledTimes(1) // the broken text was not committed
    expect(box).toHaveValue('{"a": ')
  })
  it('treats empty text as undefined', () => {
    const onChange = vi.fn()
    render(<JsonField label="Body" value={{ x: 1 }} onChange={onChange} />)
    fireEvent.change(screen.getByLabelText(/Body/), { target: { value: '  ' } })
    expect(onChange).toHaveBeenLastCalledWith(undefined)
  })
})
