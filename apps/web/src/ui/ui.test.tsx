import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { Command } from '../app/commands'
import { CommandPalette } from './CommandPalette'
import { Dialog } from './Dialog'
import { Menu } from './Menu'

describe('Dialog', () => {
  function Host() {
    const [open, setOpen] = useState(false)
    return (
      <>
        <button onClick={() => setOpen(true)}>open it</button>
        {open && (
          <Dialog title="Demo" onClose={() => setOpen(false)}>
            <input aria-label="first" />
            <button>second</button>
          </Dialog>
        )}
      </>
    )
  }

  it('is an accessible modal, focuses its content, and Escape closes it and restores focus', () => {
    render(<Host />)
    const opener = screen.getByRole('button', { name: 'open it' })
    opener.focus()
    fireEvent.click(opener)
    const dialog = screen.getByRole('dialog', { name: 'Demo' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog.contains(document.activeElement)).toBe(true)
    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(opener)
  })

  it('keeps Tab inside the dialog in both directions', () => {
    render(<Host />)
    fireEvent.click(screen.getByRole('button', { name: 'open it' }))
    const dialog = screen.getByRole('dialog')
    const close = screen.getByRole('button', { name: 'Close' })
    const last = screen.getByRole('button', { name: 'second' })
    last.focus()
    fireEvent.keyDown(dialog, { key: 'Tab' })
    expect(document.activeElement).toBe(close) // wrapped to the first control
    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(last) // and back to the last
  })

  it('closes when the backdrop is clicked but not when the dialog itself is', () => {
    render(<Host />)
    fireEvent.click(screen.getByRole('button', { name: 'open it' }))
    fireEvent.mouseDown(screen.getByRole('dialog'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    fireEvent.mouseDown(screen.getByRole('dialog').parentElement as HTMLElement)
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('Menu', () => {
  const items = (spy = vi.fn()) => [
    { label: 'First', onSelect: () => spy('first') },
    { label: 'Disabled', onSelect: () => spy('disabled'), disabled: true },
    { label: 'Third', onSelect: () => spy('third'), hint: '⌘T' },
  ]

  it('opens, runs the chosen action, and closes', () => {
    const spy = vi.fn()
    render(<Menu label="Actions" ariaLabel="Actions" items={items(spy)} />)
    expect(screen.queryByRole('menu')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Actions' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('menuitem', { name: /Third/ }))
    expect(spy).toHaveBeenCalledWith('third')
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('does not run disabled items', () => {
    const spy = vi.fn()
    render(<Menu label="Actions" ariaLabel="Actions" items={items(spy)} />)
    fireEvent.click(screen.getByRole('button', { name: 'Actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Disabled' }))
    expect(spy).not.toHaveBeenCalled()
  })

  it('supports arrow keys (skipping disabled items), Escape and outside clicks', () => {
    render(<Menu label="Actions" ariaLabel="Actions" items={items()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Actions' }))
    const menu = screen.getByRole('menu')
    expect(document.activeElement).toBe(screen.getByRole('menuitem', { name: 'First' })) // focus moves in
    fireEvent.keyDown(menu, { key: 'ArrowDown' })
    expect(document.activeElement).toBe(screen.getByRole('menuitem', { name: /Third/ })) // skipped the disabled one
    fireEvent.keyDown(menu, { key: 'ArrowDown' })
    expect(document.activeElement).toBe(screen.getByRole('menuitem', { name: 'First' })) // wraps
    fireEvent.keyDown(menu, { key: 'Escape' })
    expect(screen.queryByRole('menu')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Actions' }))
    fireEvent.mouseDown(document.body)
    expect(screen.queryByRole('menu')).toBeNull()
  })
})

describe('CommandPalette', () => {
  const commands = (spy = vi.fn()): Command[] => [
    { id: 'run', title: 'Run workflow', group: 'Run', hint: '⌘↵', run: () => spy('run') },
    { id: 'undo', title: 'Undo', group: 'Edit', run: () => spy('undo') },
    { id: 'theme-dark', title: 'Theme: dark', group: 'App', run: () => spy('dark') },
  ]

  it('filters as you type, Enter runs the top match and closes', async () => {
    const spy = vi.fn()
    const onClose = vi.fn()
    render(<CommandPalette commands={commands(spy)} onClose={onClose} />)
    const input = screen.getByRole('combobox', { name: 'Search commands' })
    expect(screen.getAllByRole('option')).toHaveLength(3)
    fireEvent.change(input, { target: { value: 'und' } })
    expect(screen.getAllByRole('option')).toHaveLength(1)
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(spy).toHaveBeenCalledWith('undo')
    expect(onClose).toHaveBeenCalled()
  })

  it('arrow keys change the selection and Enter picks it', () => {
    const spy = vi.fn()
    render(<CommandPalette commands={commands(spy)} onClose={vi.fn()} />)
    const input = screen.getByRole('combobox')
    expect(screen.getAllByRole('option')[0]).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(screen.getAllByRole('option')[2]).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(input, { key: 'ArrowDown' }) // stays on the last item
    expect(screen.getAllByRole('option')[2]).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(spy).toHaveBeenCalledWith('undo')
  })

  it('clicking a result runs it; an empty result list says so and Enter does nothing', () => {
    const spy = vi.fn()
    const { unmount } = render(<CommandPalette commands={commands(spy)} onClose={vi.fn()} />)
    fireEvent.click(screen.getByRole('option', { name: /Run workflow/ }))
    expect(spy).toHaveBeenCalledWith('run')
    unmount()
    spy.mockClear()
    render(<CommandPalette commands={commands(spy)} onClose={vi.fn()} />)
    const input = screen.getByRole('combobox')
    fireEvent.change(input, { target: { value: 'zzzzqq' } })
    expect(screen.getByText(/Nothing matches/)).toBeInTheDocument()
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(spy).not.toHaveBeenCalled()
  })

  it('focuses the search box on open', async () => {
    render(<CommandPalette commands={commands()} onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole('combobox')).toHaveFocus())
    await act(async () => undefined)
  })
})
