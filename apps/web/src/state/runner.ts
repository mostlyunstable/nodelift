import { create } from 'zustand'
import {
  api,
  ApiError,
  type CommandRequest,
  type CommandRun,
  type Discovery,
  type RepoPatch,
  type Workspace,
} from '../api/client'
import { useExplorer } from './explorer'

const message = (e: unknown) => (e instanceof ApiError ? e.message : 'Could not reach the Nodecraft backend.')

interface RunnerState {
  revisionId: string | null
  discovery: Discovery | null
  workspace: Workspace | null
  runs: CommandRun[]
  patches: RepoPatch[]
  error: string | null
  sandboxActive: boolean | null
  load: (revisionId: string) => Promise<void>
  prepareWorkspace: () => Promise<void>
  resetWorkspace: () => Promise<void>
  run: (req: CommandRequest) => Promise<boolean>
  cancel: (runId: string) => Promise<void>
  createPatch: (path: string, title: string, newContent: string) => Promise<RepoPatch | null>
  applyPatch: (id: string) => Promise<void>
  revertPatch: (id: string) => Promise<void>
  deletePatch: (id: string) => Promise<void>
}

let timer: ReturnType<typeof setTimeout> | undefined

export const useRunner = create<RunnerState>((set, get) => {
  const rid = () => get().revisionId ?? useExplorer.getState().revision?.id ?? null
  const refreshPatches = async () => {
    const id = rid()
    if (id) set({ patches: await api.explorerPatches(id) })
  }
  const poll = () => {
    clearTimeout(timer)
    const id = rid()
    if (!id) return
    timer = setTimeout(async () => {
      try {
        const [ws, runs] = await Promise.all([api.explorerWorkspace(id), api.explorerCommands(id)])
        set({ workspace: ws, runs })
        if (ws.state === 'preparing' || runs.some((r) => r.status === 'running')) poll()
      } catch {
        /* the next user action will show the error */
      }
    }, 600)
  }

  return {
    revisionId: null,
    discovery: null,
    workspace: null,
    runs: [],
    patches: [],
    error: null,
    sandboxActive: null,

    load: async (revisionId) => {
      set({ revisionId, error: null })
      try {
        const [discovery, workspace, runs, patches, info] = await Promise.all([
          api.explorerDiscovery(revisionId),
          api.explorerWorkspace(revisionId),
          api.explorerCommands(revisionId),
          api.explorerPatches(revisionId),
          api.systemInfo().catch(() => null),
        ])
        set({ discovery, workspace, runs, patches, sandboxActive: info?.sandbox?.active ?? null })
        if (workspace.state === 'preparing' || runs.some((r) => r.status === 'running')) poll()
      } catch (e) {
        set({ error: message(e) })
      }
    },

    prepareWorkspace: async () => {
      const id = rid()
      if (!id) return
      try {
        set({ workspace: await api.explorerPrepareWorkspace(id), error: null })
        poll()
      } catch (e) {
        set({ error: message(e) })
      }
    },

    resetWorkspace: async () => {
      const id = rid()
      if (!id) return
      try {
        set({ workspace: await api.explorerResetWorkspace(id), error: null })
        await refreshPatches()
      } catch (e) {
        set({ error: message(e) })
      }
    },

    run: async (req) => {
      const id = rid()
      if (!id) return false
      try {
        const r = await api.explorerRunCommand(id, req)
        set((s) => ({ runs: [...s.runs, r], error: null }))
        poll()
        return true
      } catch (e) {
        set({ error: message(e) })
        return false
      }
    },

    cancel: async (runId) => {
      const id = rid()
      if (!id) return
      try {
        await api.explorerCancelCommand(id, runId)
        poll()
      } catch (e) {
        set({ error: message(e) })
      }
    },

    createPatch: async (path, title, newContent) => {
      const id = rid()
      if (!id) return null
      try {
        const p = await api.explorerCreatePatch(id, { path, title, new_content: newContent })
        await refreshPatches()
        set({ error: null })
        return p
      } catch (e) {
        set({ error: message(e) })
        return null
      }
    },

    applyPatch: async (patchId) => {
      const id = rid()
      if (!id) return
      try {
        await api.explorerApplyPatch(id, patchId)
        await refreshPatches()
        set({ error: null })
      } catch (e) {
        set({ error: message(e) })
      }
    },

    revertPatch: async (patchId) => {
      const id = rid()
      if (!id) return
      try {
        await api.explorerRevertPatch(id, patchId)
        await refreshPatches()
        set({ error: null })
      } catch (e) {
        set({ error: message(e) })
      }
    },

    deletePatch: async (patchId) => {
      const id = rid()
      if (!id) return
      try {
        await api.explorerDeletePatch(id, patchId)
        await refreshPatches()
        set({ error: null })
      } catch (e) {
        set({ error: message(e) })
      }
    },
  }
})
