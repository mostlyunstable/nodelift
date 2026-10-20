import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './client'
import { apiUrl, authHeaders, getApiConfig, setApiConfig } from './config'

afterEach(() => {
  setApiConfig({ baseUrl: '', token: null })
  vi.restoreAllMocks()
})

describe('api configuration', () => {
  it('defaults to same-origin with no token (browser dev through the Vite proxy)', () => {
    expect(apiUrl('/workflows')).toBe('/api/v1/workflows')
    expect(authHeaders()).toEqual({})
  })

  it('uses the desktop backend address and sends the token on every request', async () => {
    setApiConfig({ baseUrl: 'http://127.0.0.1:51234/', token: 'abc' })
    expect(getApiConfig().baseUrl).toBe('http://127.0.0.1:51234') // trailing slash trimmed
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('[]', { status: 200 }))
    await api.listWorkflows()
    await api.createWorkflow('x', { schema_version: 1, id: '', name: 'x', nodes: [], edges: [], ui: { positions: {} } })
    for (const [url, init] of spy.mock.calls) {
      expect(String(url)).toMatch(/^http:\/\/127\.0\.0\.1:51234\/api\/v1\//)
      expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer abc')
    }
    expect((spy.mock.calls[1][1]?.headers as Record<string, string>)['content-type']).toBe('application/json')
  })

  it('turns an error envelope into an ApiError with status, code and details', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ error: { code: 'validation_failed', message: 'bad', details: [{ code: 'cycle', message: 'c' }] } }), { status: 422 }),
    )
    const err = await api.listWorkflows().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 422, code: 'validation_failed', details: [{ code: 'cycle' }] })
  })
})
