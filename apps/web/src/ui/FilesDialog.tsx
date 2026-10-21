import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type FileInfo } from '../api/client'
import { useStore } from '../state/store'
import { formatTime } from '../utils/format'
import { Dialog } from './Dialog'

const size = (n: number) =>
  n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`

/**
 * The folder that file nodes read and write. Put your notes, CSVs and backups here, and take results out:
 * workflows can reach nothing else on this computer.
 */
export function FilesDialog() {
  const closeDialog = useStore((s) => s.closeDialog)
  const [files, setFiles] = useState<FileInfo[]>([])
  const [folder, setFolder] = useState('')
  const [open, setOpen] = useState<{ path: string; text: string; isNew: boolean } | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const picker = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    api
      .listFiles()
      .then((l) => {
        setFiles(l.files)
        setFolder(l.folder)
      })
      .catch((e: Error) => setProblem(e.message))
  }, [])
  useEffect(load, [load])

  const guard = async (fn: () => Promise<void>) => {
    setProblem(null)
    try {
      await fn()
      load()
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'That did not work')
    }
  }

  const view = (path: string) =>
    void guard(async () => {
      const f = await api.readFile(path)
      setOpen({ path: f.path, text: f.text, isNew: false })
    })

  return (
    <Dialog title="Files" onClose={closeDialog} wide>
      <p className="muted">
        This is the one folder workflows can read and write (the Read, Write and List file nodes). Add your
        notes or data here and read the results. It lives at <code>{folder || '…'}</code>.
      </p>
      <div className="row">
        <button onClick={() => setOpen({ path: '', text: '', isNew: true })}>New file</button>
        <button onClick={() => picker.current?.click()}>Add a text file from this computer…</button>
        <input
          ref={picker}
          type="file"
          hidden
          aria-label="Choose a text file to add"
          onChange={(ev) => {
            const f = ev.target.files?.[0]
            ev.target.value = ''
            if (!f) return
            void f.text().then((text) => setOpen({ path: f.name, text, isNew: true }))
          }}
        />
      </div>
      <ul className="credential-list" aria-label="Files">
        {files.length === 0 && <li className="muted">The folder is empty.</li>}
        {files.map((f) => (
          <li key={f.path}>
            <code>{f.path}</code>
            <span className="muted">
              {size(f.bytes)} · {formatTime(f.modified)}
            </span>
            <button onClick={() => view(f.path)} aria-label={`Open ${f.path}`}>
              Open
            </button>
            <button
              className="danger"
              aria-label={`Delete ${f.path}`}
              onClick={() => {
                if (window.confirm(`Delete “${f.path}”? This cannot be undone.`)) {
                  void guard(async () => {
                    await api.deleteFile(f.path)
                    if (open?.path === f.path) setOpen(null)
                  })
                }
              }}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
      {open && (
        <form
          className="credential-form"
          onSubmit={(ev) => {
            ev.preventDefault()
            void guard(async () => {
              await api.writeFile(open.path.trim(), open.text)
              setOpen(null)
            })
          }}
        >
          <label className="field">
            Name (folders are made from slashes, for example study/notes.txt)
            <input
              value={open.path}
              readOnly={!open.isNew}
              onChange={(e) => setOpen({ ...open, path: e.target.value })}
            />
          </label>
          <label className="field">
            Contents
            <textarea
              rows={10}
              value={open.text}
              onChange={(e) => setOpen({ ...open, text: e.target.value })}
              spellCheck={false}
            />
          </label>
          <div className="row">
            <button className="primary" type="submit" disabled={!open.path.trim()}>
              Save
            </button>
            <button type="button" onClick={() => void navigator.clipboard?.writeText(open.text)}>
              Copy contents
            </button>
            <button type="button" onClick={() => setOpen(null)}>
              Close
            </button>
          </div>
        </form>
      )}
      {problem && <p role="alert">{problem}</p>}
    </Dialog>
  )
}
