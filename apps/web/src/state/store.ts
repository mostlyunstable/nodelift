import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from '@xyflow/react'
import { create } from 'zustand'
import { api, ApiError } from '../api/client'
import { followRun } from '../api/events'
import { DEFAULT_SOURCE, fromWorkflow, toWorkflow, type CodeNodeData, type FlowNode } from '../canvas/mapper'
import type {
  CodeRunResult,
  RunSummary,
  ExecutionRun,
  NodeLiveStatus,
  RunEvent,
  ValidationIssue,
  VersionSummary,
  WorkflowSummary,
} from '../types/workflow'

function parseJson(text: string): { ok: true; value: unknown } | { ok: false; error: string } {
  try {
    return { ok: true, value: text.trim() === '' ? null : JSON.parse(text) }
  } catch (e) {
    return { ok: false, error: (e as Error).message }
  }
}

interface State {
  nodes: FlowNode[]
  edges: Edge[]
  selectedId: string | null
  workflowId: string | null
  workflowName: string
  revision: number
  workflows: WorkflowSummary[]
  versions: VersionSummary[]
  runs: RunSummary[]
  runInput: string
  nodeTests: Record<string, CodeRunResult>
  run: ExecutionRun | null
  events: RunEvent[]
  liveStatus: Record<string, NodeLiveStatus>
  issues: ValidationIssue[]
  busy: 'node' | 'run' | null
  message: string | null
  abort: AbortController | null
  onNodesChange: (c: NodeChange<FlowNode>[]) => void
  onEdgesChange: (c: EdgeChange[]) => void
  onConnect: (c: Connection) => void
  addNode: () => void
  select: (id: string | null) => void
  updateData: (id: string, patch: Partial<CodeNodeData>) => void
  setRunInput: (t: string) => void
  testNode: (id: string) => Promise<void>
  runWorkflow: () => Promise<void>
  validate: () => Promise<void>
  cancel: () => void
  setName: (n: string) => void
  save: () => Promise<string | null>
  open: (id: string) => Promise<void>
  openRun: (runId: string) => Promise<void>
  publish: () => Promise<void>
  refresh: () => Promise<void>
  reset: () => void
}

let stopFollowing: (() => void) | null = null

let counter = 1
const newId = () => `n_${Date.now().toString(36)}${(counter++).toString(36)}`

function applyEvent(e: RunEvent) {
  const st = useStore.getState()
  if (st.events.some((x) => x.seq === e.seq)) return // duplicate after a reconnect
  const events = [...st.events, e].sort((a, b) => a.seq - b.seq)
  const liveStatus = { ...st.liveStatus }
  if (e.node_id && e.type === 'node.started') liveStatus[e.node_id] = 'running'
  if (e.node_id && e.type === 'node.finished') liveStatus[e.node_id] = e.status as NodeLiveStatus
  if (e.type === 'run.finished') {
    // a node still marked running never reported back (e.g. the server restarted mid-run)
    for (const [id, st] of Object.entries(liveStatus)) if (st === 'running') delete liveStatus[id]
  }
  useStore.setState({ events, liveStatus })
}

function follow(runId: string) {
  stopFollowing?.()
  const lastSeq = () => Math.max(0, ...useStore.getState().events.map((e) => e.seq))
  const finish = async () => {
    stopFollowing?.()
    stopFollowing = null
    try {
      useStore.setState({ run: await api.getRun(runId) })
    } finally {
      useStore.setState({ busy: null })
      await useStore.getState().refresh()
    }
  }
  const onEvent = (e: RunEvent) => {
    applyEvent(e)
    if (e.type === 'run.finished') void finish()
  }
  const onLost = async () => {
    // The browser gave up reconnecting: catch up over REST, then resume the stream.
    stopFollowing?.()
    try {
      for (const e of await api.listEvents(runId, lastSeq())) onEvent(e)
      setTimeout(() => {
        if (useStore.getState().busy === 'run') follow(runId)
      }, 1000)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        useStore.setState({ busy: null, message: 'This run no longer exists on the server.' })
        return
      }
      setTimeout(() => {
        if (useStore.getState().busy === 'run') follow(runId)
      }, 2000)
    }
  }
  const closeStream = followRun(runId, lastSeq(), onEvent, () => void onLost())
  // Safety net for a stream that stalls silently (dead proxy, server restart): poll the run's status.
  const watchdog = setInterval(async () => {
    try {
      const run = await api.getRun(runId)
      if (run.status === 'running') return
      for (const e of await api.listEvents(runId, lastSeq())) onEvent(e) // delivers run.finished
    } catch {
      /* server unreachable; try again on the next tick */
    }
  }, 4000)
  stopFollowing = () => {
    closeStream()
    clearInterval(watchdog)
  }
}

export const useStore = create<State>((set, get) => ({
  nodes: [],
  edges: [],
  selectedId: null,
  workflowId: null,
  workflowName: 'Untitled',
  revision: 0,
  workflows: [],
  versions: [],
  runs: [],
  runInput: '{}',
  nodeTests: {},
  run: null,
  events: [],
  liveStatus: {},
  issues: [],
  busy: null,
  message: null,
  abort: null,

  onNodesChange: (c) => set({ nodes: applyNodeChanges(c, get().nodes) }),
  onEdgesChange: (c) => set({ edges: applyEdgeChanges(c, get().edges) }),
  onConnect: (c) => set({ edges: addEdge({ ...c, id: `e_${c.source}_${c.target}` }, get().edges) }),

  addNode: () => {
    const n = get().nodes.length
    const id = newId()
    const node: FlowNode = {
      id,
      type: 'code',
      position: { x: 80 + n * 40, y: 80 + n * 60 },
      data: { name: `Code ${n + 1}`, source: DEFAULT_SOURCE, testInput: '{}' },
    }
    set({ nodes: [...get().nodes, node], selectedId: id })
  },
  select: (id) => set({ selectedId: id }),
  updateData: (id, patch) =>
    set({ nodes: get().nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)) }),
  setRunInput: (t) => set({ runInput: t }),

  testNode: async (id) => {
    const node = get().nodes.find((n) => n.id === id)
    if (!node) return
    const parsed = parseJson(node.data.testInput)
    if (!parsed.ok) return set({ message: `Test input is not valid JSON: ${parsed.error}` })
    const abort = new AbortController()
    set({ busy: 'node', abort, message: null })
    try {
      const res = await api.testCode(node.data.source, parsed.value, abort.signal)
      set({ nodeTests: { ...get().nodeTests, [id]: res } })
    } catch (e) {
      if ((e as Error).name !== 'AbortError') set({ message: (e as Error).message })
    } finally {
      set({ busy: null, abort: null })
    }
  },

  runWorkflow: async () => {
    const parsed = parseJson(get().runInput)
    if (!parsed.ok) return set({ message: `Run input is not valid JSON: ${parsed.error}` })
    stopFollowing?.()
    set({ busy: 'run', message: null, issues: [], run: null, events: [], liveStatus: {} })
    try {
      const id = await get().save() // runs are pinned to a saved version
      if (!id) return set({ busy: null })
      const run = await api.startRun(id, parsed.value)
      set({ run })
      follow(run.id)
      await get().refresh()
    } catch (e) {
      if (e instanceof ApiError) set({ message: e.message, issues: e.details })
      else set({ message: (e as Error).message })
      set({ busy: null })
    }
  },

  validate: async () => {
    try {
      const r = await api.validate(toWorkflow(get().nodes, get().edges))
      set({ issues: r.issues, message: r.valid ? 'Workflow is valid.' : 'Workflow has issues.' })
    } catch (e) {
      set({ message: (e as Error).message })
    }
  },

  cancel: () => {
    // Client-side only: stops following. The server finishes the run (server-side cancel is M6).
    get().abort?.abort()
    stopFollowing?.()
    stopFollowing = null
    set({ busy: null, abort: null, message: 'Stopped watching. The run continues on the server.' })
  },

  setName: (n) => set({ workflowName: n }),

  save: async () => {
    const { nodes, edges, workflowId, workflowName, revision } = get()
    const definition = toWorkflow(nodes, edges, workflowName)
    try {
      const rec = workflowId
        ? await api.updateWorkflow(workflowId, workflowName, definition, revision)
        : await api.createWorkflow(workflowName, definition)
      set({ workflowId: rec.id, revision: rec.revision, message: 'Saved.' })
      await get().refresh()
      return rec.id
    } catch (e) {
      const conflict = e instanceof ApiError && e.code === 'revision_conflict'
      set({ message: conflict ? 'Saved elsewhere since you opened it. Reopen to get the latest.' : (e as Error).message })
      return null
    }
  },

  open: async (id) => {
    try {
      const rec = await api.getWorkflow(id)
      const { nodes, edges } = fromWorkflow(rec.draft)
      stopFollowing?.()
      set({
        events: [], liveStatus: {}, busy: null,
        nodes, edges, workflowId: rec.id, workflowName: rec.name, revision: rec.revision,
        selectedId: null, run: null, nodeTests: {}, issues: [], message: null,
      })
      await get().refresh()
    } catch (e) {
      set({ message: (e as Error).message })
    }
  },

  openRun: async (runId) => {
    stopFollowing?.()
    try {
      const [run, events] = await Promise.all([api.getRun(runId), api.listEvents(runId)])
      const liveStatus: Record<string, NodeLiveStatus> = {}
      for (const e of events) {
        if (e.node_id && e.type === 'node.started') liveStatus[e.node_id] = 'running'
        if (e.node_id && e.type === 'node.finished') liveStatus[e.node_id] = e.status as NodeLiveStatus
      }
      set({ run, events, liveStatus })
      if (run.status === 'running') {
        set({ busy: 'run' })
        follow(run.id)
      }
    } catch (e) {
      set({ message: (e as Error).message })
    }
  },

  publish: async () => {
    const id = await get().save()
    if (!id) return
    try {
      const v = await api.createVersion(id)
      set({ message: `Version ${v.version_no} is current.` })
      await get().refresh()
    } catch (e) {
      set({ message: (e as Error).message })
    }
  },

  refresh: async () => {
    try {
      const id = get().workflowId
      const [workflows, versions, runs] = await Promise.all([
        api.listWorkflows(),
        id ? api.listVersions(id) : Promise.resolve([]),
        id ? api.listRuns(id) : Promise.resolve([]),
      ])
      set({ workflows, versions, runs })
    } catch {
      /* listing is best-effort; the backend may be down */
    }
  },

  reset: () =>
    set({
      events: [], liveStatus: {}, nodes: [], edges: [], selectedId: null, run: null, nodeTests: {}, issues: [],
      runInput: '{}', workflowId: null, workflowName: 'Untitled', revision: 0, versions: [], runs: [], message: null,
    }),
}))
