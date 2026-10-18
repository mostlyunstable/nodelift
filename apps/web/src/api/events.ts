import type { RunEvent } from '../types/workflow'

const TYPES: RunEvent['type'][] = ['run.started', 'node.started', 'node.finished', 'run.finished']

/**
 * Follow a run over SSE starting after `afterSeq`. EventSource reconnects by itself and resends
 * Last-Event-ID, so the server replays what was missed; callers still dedupe by `seq`.
 * `onLost` fires only if the browser gives up (stream CLOSED) so the caller can catch up via REST.
 */
export function followRun(
  runId: string,
  afterSeq: number,
  onEvent: (e: RunEvent) => void,
  onLost: () => void,
): () => void {
  const es = new EventSource(`/api/v1/runs/${runId}/events/stream?after=${afterSeq}`)
  for (const t of TYPES) {
    es.addEventListener(t, (m) => onEvent(JSON.parse((m as MessageEvent<string>).data) as RunEvent))
  }
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) onLost()
  }
  return () => es.close()
}
