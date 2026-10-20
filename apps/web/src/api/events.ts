import type { RunEvent } from '../types/workflow'
import { apiUrl, authHeaders } from './config'

const TYPES = new Set<RunEvent['type']>([
  'run.started',
  'node.started',
  'node.finished',
  'run.finished',
  'run.cancel_requested',
])

/** Splits an SSE byte stream into frames; handles frames that arrive in pieces. */
export function createFrameParser(onFrame: (f: { id?: string; event?: string; data: string }) => void) {
  let buffer = ''
  return (chunk: string) => {
    buffer += chunk.replace(/\r\n/g, '\n')
    let end: number
    while ((end = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      const frame: { id?: string; event?: string; data: string } = { data: '' }
      for (const line of raw.split('\n')) {
        if (line.startsWith(':')) continue // keep-alive comment
        const i = line.indexOf(':')
        const field = i === -1 ? line : line.slice(0, i)
        const value = i === -1 ? '' : line.slice(i + 1).replace(/^ /, '')
        if (field === 'id') frame.id = value
        else if (field === 'event') frame.event = value
        else if (field === 'data') frame.data += (frame.data ? '\n' : '') + value
      }
      if (frame.data || frame.event) onFrame(frame)
    }
  }
}

const RECONNECT_MS = [500, 1000, 2000, 4000]

/**
 * Follow a run over Server-Sent Events using fetch, because EventSource cannot send the
 * Authorization header. Reconnects with `Last-Event-ID` after a dropped connection, so the server
 * replays whatever was missed; callers still dedupe by `seq`. `onLost` fires when the server
 * answers with an error that retrying will not fix (unknown run, bad token).
 */
export function followRun(
  runId: string,
  afterSeq: number,
  onEvent: (e: RunEvent) => void,
  onLost: () => void,
): () => void {
  const controller = new AbortController()
  let lastId = afterSeq
  let finished = false

  const connect = async (attempt: number): Promise<void> => {
    if (controller.signal.aborted || finished) return
    let gotData = false
    try {
      const res = await fetch(apiUrl(`/runs/${runId}/events/stream?after=${lastId}`), {
        headers: authHeaders({ Accept: 'text/event-stream', 'Last-Event-ID': String(lastId) }),
        signal: controller.signal,
      })
      if (!res.ok || !res.body) {
        if (res.status >= 400 && res.status < 500) return onLost()
        throw new Error(`stream failed (${res.status})`)
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      const parse = createFrameParser((frame) => {
        gotData = true
        if (frame.id && /^\d+$/.test(frame.id)) lastId = Math.max(lastId, Number(frame.id))
        if (!frame.event || !TYPES.has(frame.event as RunEvent['type'])) return
        try {
          const event = JSON.parse(frame.data) as RunEvent
          if (event.type === 'run.finished') finished = true
          onEvent(event)
        } catch {
          /* ignore a malformed frame rather than dropping the stream */
        }
      })
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        parse(decoder.decode(value, { stream: true }))
      }
    } catch (e) {
      if (controller.signal.aborted) return
      void e // network error: fall through to reconnect
    }
    if (controller.signal.aborted || finished) return
    const delay = RECONNECT_MS[Math.min(gotData ? 0 : attempt, RECONNECT_MS.length - 1)]
    setTimeout(() => void connect(gotData ? 0 : attempt + 1), delay)
  }

  void connect(0)
  return () => controller.abort()
}
