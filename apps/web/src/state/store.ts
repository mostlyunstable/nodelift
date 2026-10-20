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
import { DEFAULT_SOURCE, fromWorkflow, toWorkflow, type FlowNode, type NodeData } from '../canvas/mapper'
import type {
  CodeRunResult,
  RunSummary,
  ExecutionRun,
  NodeDefinition,
  NodeLiveStatus,
  RunEvent,
  ValidationIssue,
  VersionSummary,
  WorkflowRecord,
  WorkflowSummary,
} from '../types/workflow'

function parseJson(text: string): { ok: true; value: unknown } | { ok: false; error: string } {
  try {
    return { ok: true, value: text.trim() === '' ? null : JSON.parse(text) }
  } catch (e) {
    return { ok: false, error: (e as Error).message }
  }
}

export const AUTOSAVE_MS = 1500
const RETRY_MS = 5000
const LAST_KEY = 'nodecraft.lastWorkflow'

// Storage can throw (private windows, blocked cookies); the app must work without it.
const remember = (id: string) => {
  try {
    localStorage.setItem(LAST_KEY, id)
  } catch {
    /* ignore */
  }
}
const recall = (): string | null => {
  try {
    return localStorage.getItem(LAST_KEY)
  } catch {
    return null
  }
}
const forget = () => {
  try {
    localStorage.removeItem(LAST_KEY)
  } catch {
    /* ignore */
  }
}

export type SaveState = 'saved' | 'saving' | 'unsaved' | 'error'

let autosaveTimer: ReturnType<typeof setTimeout> | undefined
let editSeq = 0 // bumped on every edit; a save only clears "dirty" if nothing changed meanwhile
let generation = 0 // bumped when a different workflow is opened/reset; stale saves must not apply
let inFlight: Promise<string | null> | null = null

interface State {
  dirty: boolean
  saveState: SaveState
  conflict: boolean // saved elsewhere; autosave stops until the workflow is reopened
  flush: () => Promise<boolean>
  restore: () => Promise<void>
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
  nodeDefs: NodeDefinition[]
  loadDefinitions: () => Promise<void>
  addNode: (type?: string) => void
  updateConfig: (id: string, patch: Record<string, unknown>) => void
  select: (id: string | null) => void
  updateData: (id: string, patch: Partial<NodeData>) => void
  setRunInput: (t: string) => void
  testNode: (id: string) => Promise<void>
  runWorkflow: () => Promise<void>
  validate: () => Promise<void>
  cancel: () => Promise<void>
  resume: () => Promise<void>
  setName: (n: string) => void
  save: () => Promise<string | null>
  open: (id: string, preloaded?: WorkflowRecord) => Promise<void>
  openRun: (runId: string) => Promise<void>
  publish: () => Promise<void>
  refresh: () => Promise<void>
  reset: () => void
}

let stopFollowing: (() => void) | null = null

let counter = 1
const newId = () => `n_${Date.now().toString(36)}${(counter++).toString(36)}`

export function applyEvent(e: RunEvent) {
  const st = useStore.getState()
  if (st.events.some((x) => x.seq === e.seq)) return // duplicate after a reconnect
  const events = [...st.events, e].sort((a, b) => a.seq - b.seq)
  const liveStatus = { ...st.liveStatus }
  if (e.node_id && e.type === 'node.started') liveStatus[e.node_id] = 'running'
  if (e.node_id && e.type === 'node.finished')
    liveStatus[e.node_id] = e.will_retry ? 'running' : (e.status as NodeLiveStatus)
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
      useStore.setState({ busy: null, message: null })
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

function scheduleAutosave() {
  clearTimeout(autosaveTimer)
  if (useStore.getState().conflict) return // someone else changed it; saving would just fail again
  autosaveTimer = setTimeout(() => void useStore.getState().save(), AUTOSAVE_MS)
}

function markDirty() {
  editSeq++
  const { conflict, saveState } = useStore.getState()
  useStore.setState({
    dirty: true,
    saveState: conflict ? 'error' : saveState === 'saving' ? 'saving' : 'unsaved',
  })
  scheduleAutosave()
}

export const useStore = create<State>((set, get) => ({
  nodes: [],
  edges: [],
  dirty: false,
  saveState: 'saved',
  conflict: false,
  selectedId: null,
  nodeDefs: [],
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

  onNodesChange: (c) => {
    set({ nodes: applyNodeChanges(c, get().nodes) })
    // selection and measurement are not edits; moves, adds and removals are
    if (c.some((ch) => ch.type !== 'select' && ch.type !== 'dimensions')) markDirty()
  },
  onEdgesChange: (c) => {
    set({ edges: applyEdgeChanges(c, get().edges) })
    if (c.some((ch) => ch.type !== 'select')) markDirty()
  },
  onConnect: (c) => {
    set({ edges: addEdge({ ...c, id: `e_${c.source}_${c.target}` }, get().edges) })
    markDirty()
  },

  loadDefinitions: async () => {
    try {
      set({ nodeDefs: await api.nodeDefinitions() })
    } catch {
      /* palette falls back to the built-in code node while the backend is unreachable */
    }
  },
  addNode: (type = 'code.python') => {
    const n = get().nodes.length
    const id = newId()
    const def = get().nodeDefs.find((d) => d.type === type)
    const config = def?.default_config ?? (type === 'code.python' ? { source: DEFAULT_SOURCE } : {})
    const node: FlowNode = {
      id,
      type: 'node',
      position: { x: 80 + n * 40, y: 80 + n * 60 },
      data: {
        name: `${def?.title ?? 'Node'} ${n + 1}`,
        nodeType: type,
        config: structuredClone(config),
        testInput: '{}',
        idempotent: false,
        maxAttempts: 1,
      },
    }
    set({ nodes: [...get().nodes, node], selectedId: id })
    markDirty()
  },
  updateConfig: (id, patch) => {
    set({
      nodes: get().nodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, config: { ...n.data.config, ...patch } } } : n,
      ),
    })
    markDirty()
  },
  select: (id) => set({ selectedId: id }),
  updateData: (id, patch) => {
    set({ nodes: get().nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)) })
    markDirty()
  },
  setRunInput: (t) => set({ runInput: t }),

  testNode: async (id) => {
    const node = get().nodes.find((n) => n.id === id)
    if (!node) return
    const parsed = parseJson(node.data.testInput)
    if (!parsed.ok) return set({ message: `Test input is not valid JSON: ${parsed.error}` })
    const abort = new AbortController()
    set({ busy: 'node', abort, message: null })
    try {
      const res = await api.testNode(node.data.nodeType, node.data.config, parsed.value, abort.signal)
      set({ nodeTests: { ...get().nodeTests, [id]: res } })
    } catch (e) {
      if (e instanceof ApiError && e.details.length > 0)
        set({ message: `${e.message}: ${e.details.map((d) => d.message).join('; ')}` })
      else if ((e as Error).name !== 'AbortError') set({ message: (e as Error).message })
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

  cancel: async () => {
    const run = get().run
    if (!run || run.status !== 'running') return
    try {
      // The server kills the running node and ends the run as `cancelled`; we keep following until then.
      await api.cancelRun(run.id)
      set({ message: 'Cancelling…' })
    } catch (e) {
      set({ message: (e as Error).message })
    }
  },

  resume: async () => {
    const run = get().run
    if (!run || run.status === 'running' || run.status === 'succeeded') return
    stopFollowing?.()
    set({ busy: 'run', message: null, events: [], liveStatus: {} })
    try {
      const next = await api.resumeRun(run.id)
      set({ run: next })
      follow(next.id)
      await get().refresh()
    } catch (e) {
      set({ busy: null, message: (e as Error).message })
    }
  },

  setName: (n) => {
    set({ workflowName: n })
    markDirty()
  },

  save: async () => {
    if (inFlight) {
      // wait for the running save, then save again if more edits arrived meanwhile
      return inFlight.then((id) => (get().dirty ? get().save() : id))
    }
    clearTimeout(autosaveTimer)
    const { nodes, edges, workflowId, workflowName, revision } = get()
    if (!workflowId && nodes.length === 0) {
      set({ dirty: false, saveState: 'saved' }) // nothing worth creating yet
      return null
    }
    const seqAtStart = editSeq
    const gen = generation
    const definition = toWorkflow(nodes, edges, workflowName)
    set({ saveState: 'saving' })
    inFlight = (async () => {
      try {
        const rec = workflowId
          ? await api.updateWorkflow(workflowId, workflowName, definition, revision)
          : await api.createWorkflow(workflowName, definition)
        if (gen !== generation) return rec.id // the user moved to another workflow meanwhile
        const edited = editSeq !== seqAtStart
        set({
          workflowId: rec.id,
          revision: rec.revision,
          dirty: edited,
          saveState: edited ? 'unsaved' : 'saved',
          conflict: false,
        })
        remember(rec.id)
        if (edited) scheduleAutosave()
        await get().refresh()
        return rec.id
      } catch (e) {
        if (gen !== generation) return null
        const conflict = e instanceof ApiError && e.code === 'revision_conflict'
        set({
          saveState: 'error',
          conflict,
          message: conflict
            ? 'Saved elsewhere since you opened it. Reopen to get the latest.'
            : `Could not save: ${(e as Error).message}`,
        })
        if (!conflict) autosaveTimer = setTimeout(() => void get().save(), RETRY_MS)
        return null
      } finally {
        inFlight = null
      }
    })()
    return inFlight
  },

  flush: async () => {
    clearTimeout(autosaveTimer)
    const { dirty, workflowId, nodes } = get()
    if (!workflowId && nodes.length === 0) {
      set({ dirty: false, saveState: 'saved' })
      return true
    }
    if (!dirty && !inFlight) return true
    await get().save()
    return !get().dirty
  },

  restore: async () => {
    const id = recall()
    if (!id) return
    try {
      const rec = await api.getWorkflow(id)
      await get().open(rec.id, rec)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) forget()
      else set({ message: `Could not reopen your last workflow: ${(e as Error).message}` })
    }
  },

  open: async (id, preloaded) => {
    try {
      const rec = preloaded ?? (await api.getWorkflow(id))
      const { nodes, edges } = fromWorkflow(rec.draft)
      stopFollowing?.()
      clearTimeout(autosaveTimer)
      generation++
      set({
        events: [], liveStatus: {}, busy: null,
        nodes, edges, workflowId: rec.id, workflowName: rec.name, revision: rec.revision,
        selectedId: null, run: null, nodeTests: {}, issues: [], message: null,
        dirty: false, saveState: 'saved', conflict: false,
      })
      remember(rec.id)
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

  reset: () => {
    stopFollowing?.()
    stopFollowing = null
    clearTimeout(autosaveTimer)
    generation++
    forget()
    set({
      events: [], liveStatus: {}, nodes: [], edges: [], selectedId: null, run: null, nodeTests: {}, issues: [],
      runInput: '{}', workflowId: null, workflowName: 'Untitled', revision: 0, versions: [], runs: [], message: null,
      dirty: false, saveState: 'saved', conflict: false,
    })
  },
}))
