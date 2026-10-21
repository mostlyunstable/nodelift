import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type Trigger } from '../api/client'
import { ErrorBoundary } from '../app/ErrorBoundary'
import { GitHubAccess } from '../explorer/GitHubAccess'
import { useStore } from '../state/store'
import { recordedErrors } from '../utils/errorLog'
import { TriggersDialog } from './TriggersDialog'

const trigger = (over: Partial<Trigger> = {}): Trigger => ({
  id: 'trg_1',
  workflow_id: 'w1',
  kind: 'schedule',
  every_minutes: 15,
  daily_at: null,
  enabled: true,
  last_run_at: null,
  last_run_id: null,
  next_run_at: '2026-10-21T09:00:00Z',
  created_at: '2026-10-21T08:00:00Z',
  ...over,
})

describe('TriggersDialog', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useStore.setState({ workflowId: 'w1', dialog: 'triggers' })
  })

  it('lists schedules, adds one, and turns one off', async () => {
    const list = vi.spyOn(api, 'listTriggers').mockResolvedValue([trigger()])
    const add = vi
      .spyOn(api, 'addTrigger')
      .mockResolvedValue({ trigger: trigger({ id: 'trg_2' }), webhook_path: null })
    const toggle = vi.spyOn(api, 'setTriggerEnabled').mockResolvedValue(trigger({ enabled: false }))
    render(<TriggersDialog />)
    expect(await screen.findByText('Every 15 minutes')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add schedule' }))
    await waitFor(() => expect(add).toHaveBeenCalledWith('w1', { kind: 'schedule', every_minutes: 15 }))
    fireEvent.click(screen.getByRole('button', { name: /Turn off: Every 15 minutes/ }))
    await waitFor(() => expect(toggle).toHaveBeenCalledWith('trg_1', false))
    expect(list.mock.calls.length).toBeGreaterThan(1) // the list is reloaded after each change
  })

  it('shows a new webhook address once, with a ready-made command', async () => {
    vi.spyOn(api, 'listTriggers').mockResolvedValue([])
    vi.spyOn(api, 'addTrigger').mockResolvedValue({
      trigger: trigger({ id: 'trg_9', kind: 'webhook', every_minutes: null }),
      webhook_path: '/api/v1/hooks/trg_9/SECRETTOKEN',
    })
    render(<TriggersDialog />)
    fireEvent.click(await screen.findByRole('button', { name: 'Create a webhook address' }))
    expect(await screen.findByText(/shown only once/)).toBeInTheDocument()
    expect(screen.getAllByText(/hooks\/trg_9\/SECRETTOKEN/).length).toBeGreaterThan(0)
  })

  it('says what went wrong instead of failing silently', async () => {
    vi.spyOn(api, 'listTriggers').mockResolvedValue([])
    vi.spyOn(api, 'addTrigger').mockRejectedValue(new Error('Run every 1 to 10080 minutes'))
    render(<TriggersDialog />)
    fireEvent.click(await screen.findByRole('button', { name: 'Add schedule' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Run every 1 to 10080 minutes')
  })
})

describe('GitHubAccess', () => {
  const cred = { id: 'c', name: 'github', kind: 'github', description: '', created_at: '', updated_at: '' }
  beforeEach(() => vi.restoreAllMocks())

  it('without a token says what that costs, and saves one without ever showing it back', async () => {
    vi.spyOn(api, 'listCredentials').mockResolvedValueOnce([]).mockResolvedValue([cred])
    const create = vi.spyOn(api, 'createCredential').mockResolvedValue(cred)
    render(<GitHubAccess />)
    expect(await screen.findByText(/public repositories only, 60 requests an hour/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add a token' }))
    const box = screen.getByLabelText('GitHub personal access token')
    expect(box).toHaveAttribute('type', 'password')
    fireEvent.change(box, { target: { value: 'ghp_abcdefghijkl' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save token' }))
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({ name: 'github', value: 'ghp_abcdefghijkl', kind: 'github' }),
    )
    expect(await screen.findByText(/private repositories and 5,000 requests/)).toBeInTheDocument()
    expect(screen.queryByDisplayValue('ghp_abcdefghijkl')).toBeNull()
  })

  it('replaces an existing token rather than creating a second one', async () => {
    vi.spyOn(api, 'listCredentials').mockResolvedValue([cred])
    const rotate = vi.spyOn(api, 'rotateCredential').mockResolvedValue(cred)
    render(<GitHubAccess />)
    fireEvent.click(await screen.findByRole('button', { name: 'Change token' }))
    fireEvent.change(screen.getByLabelText('GitHub personal access token'), {
      target: { value: 'github_pat_newvalue1' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save token' }))
    await waitFor(() => expect(rotate).toHaveBeenCalledWith('github', 'github_pat_newvalue1'))
  })
})

describe('ErrorBoundary', () => {
  it('replaces a crashed screen with a message, a reload button and the details to send', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const Boom = () => {
      throw new Error('kaboom')
    }
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong')
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy details' })).toBeInTheDocument()
    act(() => undefined)
    expect(recordedErrors().some((e) => e.includes('kaboom'))).toBe(true)
  })
})
