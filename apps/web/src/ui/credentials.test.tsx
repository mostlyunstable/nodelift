import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ConfigEditor } from '../panels/ConfigEditors'
import { useStore } from '../state/store'
import { jsonResponse } from '../test-utils/sse'
import type { Credential } from '../types/workflow'
import { CredentialsDialog } from './Dialogs'

vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })

const s = () => useStore.getState()
const cred = (name: string): Credential => ({ id: `c_${name}`, name, kind: 'other', description: '', created_at: '2026-10-20T10:00:00Z', updated_at: '2026-10-20T10:00:00Z' })
const SECRET = 'ghp_exampleSecretValue123'

/** A fake credentials backend that records what it was sent. */
function backend(initial: string[] = []) {
  const names = [...initial]
  const sent: { method: string; url: string; body: string | undefined }[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
    const method = init?.method ?? 'GET'
    const u = String(url).replace(/^.*\/api\/v1/, '')
    sent.push({ method, url: u, body: init?.body as string | undefined })
    if (u === '/credentials' && method === 'GET') return new Response(JSON.stringify(names.map(cred)))
    if (u === '/credentials' && method === 'POST') {
      const body = JSON.parse(String(init?.body))
      if (names.includes(body.name)) return jsonResponse({ error: { code: 'credential_exists', message: `A credential named '${body.name}' already exists` } }, 409)
      names.push(body.name)
      return jsonResponse(cred(body.name), 201)
    }
    if (u.startsWith('/credentials/') && method === 'PUT') return jsonResponse(cred(decodeURIComponent(u.split('/')[2])))
    if (u.startsWith('/credentials/') && method === 'DELETE') {
      names.splice(names.indexOf(decodeURIComponent(u.split('/')[2])), 1)
      return new Response(null, { status: 204 })
    }
    return new Response('[]')
  })
  return sent
}

beforeEach(() => {
  vi.restoreAllMocks()
  s().reset()
  useStore.setState({ credentials: [], dialog: null, message: null })
})

describe('CredentialsDialog', () => {
  it('explains how credentials work and lists the saved ones without values', async () => {
    backend(['github', 'stripe'])
    render(<CredentialsDialog />)
    expect(screen.getByText(/system keychain/)).toBeInTheDocument()
    const list = await screen.findByRole('list', { name: 'Saved credentials' })
    await waitFor(() => expect(within(list).getAllByRole('listitem')).toHaveLength(2))
    expect(within(list).getByText('{{credential:github}}')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain(SECRET)
  })

  it('validates before saving: name format and minimum secret length', async () => {
    backend()
    render(<CredentialsDialog />)
    const save = screen.getByRole('button', { name: 'Save credential' })
    expect(save).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'has space' } })
    fireEvent.change(screen.getByLabelText('Secret value'), { target: { value: SECRET } })
    expect(screen.getByText(/Use letters, digits/)).toBeInTheDocument()
    expect(save).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'github' } })
    fireEvent.change(screen.getByLabelText('Secret value'), { target: { value: 'short' } })
    expect(screen.getByText(/at least 8 characters/)).toBeInTheDocument()
    expect(save).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Secret value'), { target: { value: SECRET } })
    expect(save).toBeEnabled()
  })

  it('uses a masked field, sends the value once, and clears it from the screen afterwards', async () => {
    const sent = backend()
    render(<CredentialsDialog />)
    const field = screen.getByLabelText('Secret value')
    expect(field).toHaveAttribute('type', 'password')
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'github' } })
    fireEvent.change(field, { target: { value: SECRET } })
    fireEvent.click(screen.getByRole('button', { name: 'Save credential' }))
    await waitFor(() => expect(sent.some((c) => c.method === 'POST')).toBe(true))
    expect(JSON.parse(sent.find((c) => c.method === 'POST')?.body ?? '{}')).toMatchObject({ name: 'github', value: SECRET })
    await waitFor(() => expect(screen.getByLabelText('Secret value')).toHaveValue('')) // not kept in the UI
    expect(screen.getByLabelText('Name')).toHaveValue('')
    expect(s().message).toBe('Saved credential “github”.')
    expect(JSON.stringify(useStore.getState().credentials)).not.toContain(SECRET) // state never holds a value
    expect(JSON.stringify(s().message)).not.toContain(SECRET)
  })

  it('keeps what you typed when saving fails, and shows the reason', async () => {
    backend(['github'])
    render(<CredentialsDialog />)
    await waitFor(() => expect(s().credentials).toHaveLength(1))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'github' } })
    fireEvent.change(screen.getByLabelText('Secret value'), { target: { value: SECRET } })
    fireEvent.click(screen.getByRole('button', { name: 'Save credential' }))
    await waitFor(() => expect(s().message).toMatch(/already exists/))
    expect(screen.getByLabelText('Secret value')).toHaveValue(SECRET) // not lost on a failure
  })

  it('replaces a value without ever showing the old one', async () => {
    const sent = backend(['github'])
    render(<CredentialsDialog />)
    fireEvent.click(await screen.findByRole('button', { name: 'Replace the value of github' }))
    expect(screen.getByRole('heading', { name: /New value for “github”/ })).toBeInTheDocument()
    expect(screen.queryByLabelText('Name')).toBeNull() // the name cannot change while replacing
    fireEvent.change(screen.getByLabelText('Secret value'), { target: { value: SECRET } })
    fireEvent.click(screen.getByRole('button', { name: 'Replace value' }))
    await waitFor(() => expect(sent.some((c) => c.method === 'PUT' && c.url === '/credentials/github')).toBe(true))
    await waitFor(() => expect(s().message).toMatch(/Replaced the value of “github”/))
    expect(screen.getByRole('heading', { name: 'Add a credential' })).toBeInTheDocument()
  })

  it('deletes only after confirmation', async () => {
    const sent = backend(['github'])
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    render(<CredentialsDialog />)
    const del = await screen.findByRole('button', { name: 'Delete github' })
    fireEvent.click(del)
    expect(sent.some((c) => c.method === 'DELETE')).toBe(false) // declined
    fireEvent.click(del)
    await waitFor(() => expect(sent.some((c) => c.method === 'DELETE')).toBe(true))
    expect(confirm).toHaveBeenCalledTimes(2)
    await waitFor(() => expect(s().message).toMatch(/Deleted credential “github”/))
  })

  it('encodes unusual names safely in the URL', async () => {
    const sent = backend(['a.b-c'])
    await s().removeCredential('a b/c')
    expect(sent.find((c) => c.method === 'DELETE')?.url).toBe('/credentials/a%20b%2Fc')
  })
})

describe('HTTP node credential hint', () => {
  it('tells you not to paste secrets, lists saved credentials, and opens the manager', () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('[]'))
    useStore.setState({ credentials: [cred('github'), cred('stripe')], nodeDefs: [{ type: 'http.request', version: 1, title: 'HTTP request', category: 'Integrations', description: '', config_schema: {}, default_config: { url: 'https://', method: 'GET' } }] })
    s().addNode('http.request')
    render(<ConfigEditor node={s().nodes[0]} />)
    const hint = screen.getByTestId('credential-hint')
    expect(hint).toHaveTextContent('Never paste a secret into a header')
    expect(hint).toHaveTextContent('Saved: github, stripe')
    fireEvent.click(screen.getByRole('button', { name: 'Manage credentials' }))
    expect(s().dialog).toBe('credentials')
  })

  it('says so when nothing is saved yet', () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('[]'))
    useStore.setState({ credentials: [] })
    s().addNode('http.request')
    render(<ConfigEditor node={s().nodes[0]} />)
    expect(screen.getByTestId('credential-hint')).toHaveTextContent('None saved yet')
  })
})
