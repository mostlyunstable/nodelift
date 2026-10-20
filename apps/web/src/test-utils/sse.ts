/** A controllable Server-Sent-Events response for tests. */
export function sseStream() {
  const enc = new TextEncoder()
  let ctrl!: ReadableStreamDefaultController<Uint8Array>
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      ctrl = c
    },
  })
  return {
    response: () => new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } }),
    send(type: string, data: object, id: number) {
      ctrl.enqueue(enc.encode(`id: ${id}\nevent: ${type}\ndata: ${JSON.stringify(data)}\n\n`))
    },
    raw(text: string) {
      ctrl.enqueue(enc.encode(text))
    },
    close() {
      try {
        ctrl.close()
      } catch {
        /* already closed or cancelled */
      }
    },
  }
}

export const jsonResponse = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }))
