import { create } from 'zustand'
import { api, ApiError, type RepoFile, type RepoFileContent, type RepoRevision } from '../api/client'

export type Mode = 'build' | 'explorer'

interface ExplorerState {
  mode: Mode
  setMode: (m: Mode) => void
  url: string
  setUrl: (u: string) => void
  revision: RepoRevision | null
  revisions: RepoRevision[]
  files: RepoFile[]
  selectedPath: string | null
  file: RepoFileContent | null
  fileError: string | null
  error: string | null
  starting: boolean
  loadRevisions: () => Promise<void>
  showNodes: () => Promise<void>
  openRevision: (id: string) => Promise<void>
  cancelImport: () => Promise<void>
  removeRevision: (id: string) => Promise<void>
  closeRevision: () => void
  selectFile: (path: string) => Promise<void>
}

let pollTimer: ReturnType<typeof setTimeout> | undefined
let generation = 0 // a newer import/open invalidates older polls
let fileGen = 0 // a newer file selection invalidates older file loads

const message = (e: unknown) => (e instanceof ApiError ? e.message : 'Could not reach the Nodecraft backend.')

export const useExplorer = create<ExplorerState>((set, get) => {
  const stopPolling = () => {
    clearTimeout(pollTimer)
    generation++
  }

  const track = (id: string) => {
    const mine = ++generation
    const tick = async () => {
      try {
        const rev = await api.explorerRevision(id)
        if (mine !== generation) return
        set({ revision: rev })
        if (rev.status === 'importing') {
          pollTimer = setTimeout(() => void tick(), 400)
        } else if (rev.status === 'ready') {
          const files = await api.explorerFiles(id)
          if (mine === generation) set({ files })
          void get().loadRevisions()
        } else {
          void get().loadRevisions()
        }
      } catch (e) {
        if (mine === generation) set({ error: message(e) })
      }
    }
    void tick()
  }

  return {
    mode: 'build',
    setMode: (mode) => set({ mode }),
    url: '',
    setUrl: (url) => set({ url }),
    revision: null,
    revisions: [],
    files: [],
    selectedPath: null,
    file: null,
    fileError: null,
    error: null,
    starting: false,

    loadRevisions: async () => {
      try {
        set({ revisions: await api.explorerRevisions() })
      } catch {
        /* the list is only a convenience */
      }
    },

    showNodes: async () => {
      const url = get().url.trim()
      if (!url || get().starting) return
      stopPolling()
      set({ starting: true, error: null, revision: null, files: [], selectedPath: null, file: null })
      try {
        const rev = await api.explorerImport(url)
        set({ revision: rev, starting: false })
        track(rev.id)
      } catch (e) {
        set({ starting: false, error: message(e) })
      }
    },

    openRevision: async (id) => {
      stopPolling()
      set({ error: null, files: [], selectedPath: null, file: null, fileError: null })
      try {
        set({ revision: await api.explorerRevision(id) })
        track(id)
      } catch (e) {
        set({ error: message(e) })
      }
    },

    cancelImport: async () => {
      const rev = get().revision
      if (!rev) return
      try {
        await api.explorerCancel(rev.id)
      } catch (e) {
        set({ error: message(e) })
      }
    },

    removeRevision: async (id) => {
      try {
        await api.explorerDelete(id)
      } catch (e) {
        set({ error: message(e) })
        return
      }
      if (get().revision?.id === id) get().closeRevision()
      await get().loadRevisions()
    },

    closeRevision: () => {
      stopPolling()
      set({ revision: null, files: [], selectedPath: null, file: null, fileError: null, error: null })
    },

    selectFile: async (path) => {
      const rev = get().revision
      if (!rev || rev.status !== 'ready') return
      const mine = ++fileGen
      set({ selectedPath: path, fileError: null })
      try {
        const file = await api.explorerFile(rev.id, path)
        if (mine === fileGen) set({ file })
      } catch (e) {
        if (mine === fileGen) set({ file: null, fileError: message(e) })
      }
    },
  }
})
