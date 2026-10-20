import { useState } from 'react'
import { useExplorer } from '../state/explorer'
import { FileDetails } from './FileDetails'
import { FileViewer } from './FileViewer'
import { buildPreviewDoc } from './preview'

type PanelTab = 'source' | 'details' | 'preview'

/** Source, analysis details and (for HTML) a sandboxed preview for the selected file. */
export function FilePanel({ theme }: { theme: 'dark' | 'light' }) {
  const e = useExplorer()
  const [tab, setTab] = useState<PanelTab>('source')
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
        <div className="subtabs" role="tablist" aria-label="File views">
          <button role="tab" aria-selected={active === 'source'} onClick={() => setTab('source')}>
            Source
          </button>
          <button role="tab" aria-selected={active === 'details'} onClick={() => setTab('details')}>
            Details{problems > 0 && <span className="xn-problems"> ⚠ {problems}</span>}
          </button>
          {isHtml && (
            <button role="tab" aria-selected={active === 'preview'} onClick={() => setTab('preview')}>
              Preview
            </button>
          )}
        </div>
      </div>
      {active === 'source' && (
        <FileViewer
          file={e.file}
          error={e.fileError}
          theme={theme}
          diagnostics={e.analysis?.diagnostics}
          target={e.target}
        />
      )}
      {active === 'details' && path && <FileDetails analysis={e.analysis} path={path} />}
      {active === 'preview' && e.file?.content != null && (
        <div className="preview">
          <p className="muted small preview-note">
            Sandboxed preview of the markup only: scripts are disabled and nothing is loaded from the network
            or the repository.
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
  )
}
