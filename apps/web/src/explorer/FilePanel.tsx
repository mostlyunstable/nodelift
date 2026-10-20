import { DiffEditor } from '@monaco-editor/react'
import { useState } from 'react'
import { useRunner } from '../state/runner'
import { Dialog } from '../ui/Dialog'
import { panelProps, Tabs } from '../ui/Tabs'
import { useExplorer } from '../state/explorer'
import { FileDetails } from './FileDetails'
import { FileViewer } from './FileViewer'
import { buildPreviewDoc } from './preview'

type PanelTab = 'source' | 'details' | 'preview'

/** Source, analysis details and (for HTML) a sandboxed preview for the selected file. */
export function FilePanel({ theme }: { theme: 'dark' | 'light' }) {
  const e = useExplorer()
  const [tab, setTab] = useState<PanelTab>('source')
  const [draft, setDraft] = useState<{ path: string; text: string } | null>(null)
  const [reviewing, setReviewing] = useState(false)
  const [title, setTitle] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const createPatch = useRunner((s) => s.createPatch)
  const path = e.selectedPath
  const isHtml = e.file?.language === 'html' && e.file.content != null
  const active: PanelTab = tab === 'preview' && !isHtml ? 'source' : tab
  const problems = e.analysis?.diagnostics.length ?? 0

  return (
    <div className="file-panel">
      <div className="panel-bar">
        <button
          className="icon-button"
          aria-label="Back to the previous file"
          disabled={e.history.length === 0}
          onClick={() => void e.back()}
        >
          ←
        </button>
        <Tabs
          className="subtabs"
          label="File views"
          prefix="fv"
          value={active}
          onChange={(id) => setTab(id as PanelTab)}
          tabs={[
            { id: 'source', label: 'Source' },
            {
              id: 'details',
              label: <>Details{problems > 0 && <span className="xn-problems"> ⚠ {problems}</span>}</>,
            },
            ...(isHtml ? [{ id: 'preview', label: 'Preview' }] : []),
          ]}
        />
      </div>
      <div className="tab-panel" {...panelProps('fv', active)}>
        {active === 'source' && e.file?.content != null && (
          <div className="edit-bar">
            {draft && draft.path === e.file.path ? (
              <>
                <span className="small">Editing a copy: the imported file is not modified.</span>
                <button
                  className="primary"
                  disabled={draft.text === e.file.content}
                  onClick={() => {
                    setTitle(`Change to ${e.file!.path}`)
                    setReviewing(true)
                  }}
                >
                  Review and save as patch…
                </button>
                <button onClick={() => setDraft(null)}>Discard</button>
              </>
            ) : (
              <button onClick={() => setDraft({ path: e.file!.path, text: e.file!.content! })}>
                Propose a change…
              </button>
            )}
            {notice && (
              <span className="small" role="status">
                {notice}
              </span>
            )}
          </div>
        )}
        {active === 'source' && (
          <FileViewer
            file={e.file}
            error={e.fileError}
            theme={theme}
            diagnostics={e.analysis?.diagnostics}
            target={e.target}
            references={e.analysis?.references}
            onGoTo={(path, line) => void e.goTo(path, line)}
            draft={draft && draft.path === e.file?.path ? draft.text : null}
            onDraftChange={(text) => setDraft((d) => (d ? { ...d, text } : d))}
          />
        )}
        {reviewing && draft && e.file?.content != null && (
          <Dialog title="Review your change" onClose={() => setReviewing(false)} wide>
            <div className="field">Path</div>
            <code>{draft.path}</code>
            <div className="diff-editor">
              <DiffEditor
                height="320px"
                language={e.file.language}
                original={e.file.content}
                modified={draft.text}
                theme={theme === 'dark' ? 'nodecraft-dark' : 'nodecraft-light'}
                options={{ readOnly: true, renderSideBySide: false, minimap: { enabled: false } }}
              />
            </div>
            <label className="field">
              Title
              <input aria-label="Patch title" value={title} onChange={(ev) => setTitle(ev.target.value)} />
            </label>
            <div className="dialog-actions">
              <button onClick={() => setReviewing(false)}>Back to editing</button>
              <button
                className="primary"
                onClick={async () => {
                  const p = await createPatch(draft.path, title, draft.text)
                  if (p) {
                    setReviewing(false)
                    setDraft(null)
                    setNotice('Saved. Apply it to the workspace from the Run tab.')
                  }
                }}
              >
                Save as patch
              </button>
            </div>
          </Dialog>
        )}
        {active === 'details' && path && <FileDetails analysis={e.analysis} path={path} />}
        {active === 'preview' && e.file?.content != null && (
          <div className="preview">
            <p className="muted small preview-note">
              Sandboxed preview of the markup only: scripts are disabled and nothing is loaded from the
              network or the repository.
            </p>
            <iframe
              title={`Preview of ${e.file.path}`}
              sandbox=""
              referrerPolicy="no-referrer"
              srcDoc={buildPreviewDoc(e.file.content)}
            />
          </div>
        )}
      </div>
    </div>
  )
}
