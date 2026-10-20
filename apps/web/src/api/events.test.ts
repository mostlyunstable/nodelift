import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { sseStream } from '../test-utils/sse'
import type { RunEvent } from '../types/workflow'
import { setApiConfig } from './config'
import { createFrameParser, followRun } from './events'

describe('createFrameParser', () => {
  const collect = () => {
    const frames: { id?: string; event?: string; data: string }[] = []
    return { frames, feed: createFrameParser((f) => frames.push(f)) }
  }

  it('assembles a frame that arrives in several chunks', () => {
    const { frames, feed } = collect()
    feed('id: 7\nev')
    feed('ent: node.started\nda')
    expect(frames).toHaveLength(0)
    feed('ta: {"a":1}\n\n')
    expect(frames).toEqual([{ id: '7', event: 'node.started', data: '{"a":1}' }])
  })

  it('handles several frames in one chunk, CRLF, comments and multi-line data', () => {
    const { frames, feed } = collect()
    feed(': keepalive\n\nid: 1\r\nevent: a\r\ndata: x\r\ndata: y\r\n\r\nid: 2\nevent: b\ndata: z\n\n')
    expect(frames).toEqual([
      { id: '1', event: 'a', data: 'x\ny' },
      { id: '2', event: 'b', data: 'z' },
    ])
  })
})

describe('followRun', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    setApiConfig({ baseUrl: 'http://127.0.0.1:9999', token: 'secret-token' })
  })
  afterEach(() => {
    setApiConfig({ baseUrl: '', token: null })
    vi.useRealTimers()
  })

  const ev = (seq: number, type: RunEvent['type']) => ({ seq, type, created_at: '' })

  it('authenticates, resumes from the given sequence and delivers events in order', async () => {
    const stream = sseStream()
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(stream.response())
    const got: number[] = []
    const stop = followRun('run_9', 4, (e) => got.push(e.seq), vi.fn())
    await vi.waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    const [url, init] = spy.mock.calls[0]
    expect(String(url)).toBe('http://127.0.0.1:9999/api/v1/runs/run_9/events/stream?after=4')
    expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer secret-token')
    expect((init?.headers as Record<string, string>)['Last-Event-ID']).toBe('4')
    stream.send('node.started', ev(5, 'node.started'), 5)
    stream.send('node.finished', ev(6, 'node.finished'), 6)
    await vi.waitFor(() => expect(got).toEqual([5, 6]))
    stop()
    stream.close()
  })

  it('stops after run.finished instead of reconnecting', async () => {
    const stream = sseStream()
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(stream.response())
    const got: string[] = []
    followRun('r', 0, (e) => got.push(e.type), vi.fn())
    await vi.waitFor(() => expect(spy).toHaveBeenCalled())
    stream.send('run.finished', ev(3, 'run.finished'), 3)
    stream.close()
    await vi.waitFor(() => expect(got).toEqual(['run.finished']))
    await new Promise((r) => setTimeout(r, 700)) // longer than the first reconnect delay
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('reconnects after a dropped connection and asks for what it missed', async () => {
    const first = sseStream()
    const second = sseStream()
    const spy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(first.response())
      .mockResolvedValueOnce(second.response())
    const got: number[] = []
    const stop = followRun('r', 0, (e) => got.push(e.seq), vi.fn())
    await vi.waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    first.send('node.started', ev(1, 'node.started'), 1)
    first.send('node.finished', ev(2, 'node.finished'), 2)
    await vi.waitFor(() => expect(got).toEqual([1, 2]))
    first.close() // the connection drops before run.finished
    await vi.waitFor(() => expect(spy).toHaveBeenCalledTimes(2), { timeout: 3000 })
    const [url, init] = spy.mock.calls[1]
    expect(String(url)).toContain('after=2')
    expect((init?.headers as Record<string, string>)['Last-Event-ID']).toBe('2')
    second.send('run.finished', ev(3, 'run.finished'), 3)
    await vi.waitFor(() => expect(got).toEqual([1, 2, 3]))
    stop()
    second.close()
  })

  it.each([404, 401, 403])('gives up on HTTP %i and reports it as lost', async (status) => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('no', { status }))
    const onLost = vi.fn()
    followRun('r', 0, vi.fn(), onLost)
    await vi.waitFor(() => expect(onLost).toHaveBeenCalledTimes(1))
    await new Promise((r) => setTimeout(r, 700))
    expect(spy).toHaveBeenCalledTimes(1) // no retry storm against a request that cannot succeed
  })

  it('retries a server error instead of giving up', async () => {
    const stream = sseStream()
    const spy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('oops', { status: 503 }))
      .mockResolvedValueOnce(stream.response())
    const onLost = vi.fn()
    const stop = followRun('r', 0, vi.fn(), onLost)
    await vi.waitFor(() => expect(spy).toHaveBeenCalledTimes(2), { timeout: 3000 })
    expect(onLost).not.toHaveBeenCalled()
    stop()
    stream.close()
  })

  it('ignores unknown event types and malformed data, and stop() aborts the request', async () => {
    const stream = sseStream()
    let signal: AbortSignal | undefined
    vi.spyOn(globalThis, 'fetch').mockImplementation((_u, init) => {
      signal = init?.signal as AbortSignal
      return Promise.resolve(stream.response())
    })
    const got: number[] = []
    const stop = followRun('r', 0, (e) => got.push(e.seq), vi.fn())
    await vi.waitFor(() => expect(signal).toBeDefined())
    stream.send('mystery', { seq: 1 }, 1)
    stream.raw('id: 2\nevent: node.started\ndata: {not json\n\n')
    stream.send('node.started', ev(3, 'node.started'), 3)
    await vi.waitFor(() => expect(got).toEqual([3]))
    stop()
    expect(signal?.aborted).toBe(true)
    stream.close()
  })
})
