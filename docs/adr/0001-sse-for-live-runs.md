# 0001 — Live run updates over Server-Sent Events, read with `fetch`

**Status:** accepted

**Context.** The editor must show node status as a run progresses and recover after a dropped connection.

**Decision.** Events are persisted first (`run_events`, monotonic `seq` per run) and then streamed over SSE
(`GET /runs/{id}/events/stream`). A client resumes with `Last-Event-ID` / `?after=`, or catches up with
`GET /runs/{id}/events?after=N` (paged with `X-Has-More` / `X-Next-After`). The browser reads the stream with
`fetch` and its own frame parser instead of `EventSource`, because `EventSource` cannot send the
`Authorization` header the desktop app needs. A 4-second status poll is a safety net for silently stalled streams.

**Why not WebSockets.** Traffic is one-directional; cancel is a normal POST. SSE gives resumption for free and works
through plain HTTP infrastructure.

**Consequences.** Correctness never depends on the in-process wake-up hub: streams also poll the database. A future
interactive debugger (breakpoints) may need a bidirectional channel; revisit then.
