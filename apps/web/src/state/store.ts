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
import { DEFAULT_SOURCE, fromWorkflow, toWorkflow, type CodeNodeData, type FlowNode } from '../canvas/mapper'
import type { CodeRunResult, ExecutionRun, ValidationIssue } from '../types/workflow'

const STORAGE_KEY = 'nodecraft.workflow.v1'

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
  runInput: string
  nodeTests: Record<string, CodeRunResult>
  run: ExecutionRun | null
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
  save: () => void
  load: () => void
  reset: () => void
}

let counter = 1
const newId = () => `n_${Date.now().toString(36)}${(counter++).toString(36)}`

export const useStore = create<State>((set, get) => ({
  nodes: [],
  edges: [],
  selectedId: null,
  runInput: '{}',
  nodeTests: {},
  run: null,
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
    const { nodes, edges, runInput } = get()
    const parsed = parseJson(runInput)
    if (!parsed.ok) return set({ message: `Run input is not valid JSON: ${parsed.error}` })
    const abort = new AbortController()
    set({ busy: 'run', abort, message: null, issues: [], run: null })
    try {
      const run = await api.runWorkflow(toWorkflow(nodes, edges), parsed.value, abort.signal)
      set({ run })
    } catch (e) {
      if (e instanceof ApiError) set({ message: e.message, issues: e.details })
      else if ((e as Error).name !== 'AbortError') set({ message: (e as Error).message })
    } finally {
      set({ busy: null, abort: null })
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
    // Client-side cancel: stops waiting. Server-side cancellation lands with M6.
    get().abort?.abort()
    set({ busy: null, abort: null, message: 'Cancelled (the server may finish the current node).' })
  },

  save: () => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(toWorkflow(get().nodes, get().edges)))
      set({ message: 'Saved to this browser.' })
    } catch {
      set({ message: 'Could not save (storage unavailable).' })
    }
  },
  load: () => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw) return
      const { nodes, edges } = fromWorkflow(JSON.parse(raw))
      set({ nodes, edges })
    } catch {
      set({ message: 'Saved workflow could not be loaded.' })
    }
  },
  reset: () => set({ nodes: [], edges: [], selectedId: null, run: null, nodeTests: {}, issues: [] }),
}))
