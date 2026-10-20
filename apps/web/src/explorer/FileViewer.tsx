import Editor from '@monaco-editor/react'
import type * as Monaco from 'monaco-editor'
import { useEffect, useRef, useState } from 'react'
import type { RepoDiagnostic, RepoFileContent } from '../api/client'
import { formatBytes } from './tree'

const REASONS: Record<string, string> = {
  binary: 'This is a binary file, so its content is not shown.',
  not_utf8: 'This file is not valid UTF-8 text, so its content is not shown.',
  too_large: 'This file is larger than the import limit, so its content was not downloaded.',
  cache_missing: 'The cached copy of this file is missing. Re-import the repository to restore it.',
}

type EditorHandle = { editor: Monaco.editor.IStandaloneCodeEditor; monaco: typeof Monaco }

export function FileViewer({
  file,
  error,
  theme,
  diagnostics = [],
  target = null,
}: {
  file: RepoFileContent | null
  error: string | null
  theme: 'dark' | 'light'
  diagnostics?: RepoDiagnostic[]
  target?: { path: string; line: number; n: number } | null
}) {
  const [handle, setHandle] = useState<EditorHandle | null>(null)
  const decorations = useRef<Monaco.editor.IEditorDecorationsCollection | null>(null)
  const path = file?.path
  const hasContent = file?.content != null

  // squiggles for analysis diagnostics, so a problem is visible where it is
  useEffect(() => {
    if (!handle || !path || !hasContent) return
    const model = handle.editor.getModel()
    if (!model) return
    const sev = handle.monaco.MarkerSeverity
    handle.monaco.editor.setModelMarkers(
      model,
      'nodecraft',
      diagnostics
        .filter((d) => d.path === path)
        .map((d) => ({
          severity: d.severity === 'error' ? sev.Error : d.severity === 'warning' ? sev.Warning : sev.Info,
          message: d.message,
          source: d.source,
          startLineNumber: d.line,
          startColumn: Math.max(1, d.column),
          endLineNumber: d.line,
          endColumn: Math.max(2, model.getLineMaxColumn(Math.min(d.line, model.getLineCount()))),
        })),
    )
  }, [handle, path, hasContent, diagnostics])

  // jump to a requested line and highlight it
  useEffect(() => {
    if (!handle || !target || target.path !== path || !hasContent) return
    const line = Math.min(Math.max(1, target.line), handle.editor.getModel()?.getLineCount() ?? 1)
    handle.editor.revealLineInCenter(line)
    handle.editor.setPosition({ lineNumber: line, column: 1 })
    decorations.current?.clear()
    decorations.current = handle.editor.createDecorationsCollection([
      {
        range: new handle.monaco.Range(line, 1, line, 1),
        options: { isWholeLine: true, className: 'nc-line-highlight' },
      },
    ])
  }, [handle, target, path, hasContent])

  if (error)
    return (
      <div className="viewer-empty" role="alert">
        {error}
      </div>
    )
  if (!file) return <div className="viewer-empty muted">Select a file to read its source.</div>
  return (
    <div className="viewer">
      <div className="viewer-head">
        <span className="viewer-path" title={file.path}>
          {file.path}
        </span>
        <span className="muted">
          {file.language} · {file.lines} lines · {formatBytes(file.size)} · read-only
        </span>
      </div>
      {file.content === null ? (
        <div className="viewer-empty muted">
          {REASONS[file.reason ?? ''] ?? 'The content is not available.'}
        </div>
      ) : (
        <Editor
          path={file.path}
          language={file.language}
          value={file.content}
          theme={theme === 'dark' ? 'vs-dark' : 'light'}
          onMount={(editor, monaco) => setHandle({ editor, monaco })}
          options={{
            readOnly: true,
            domReadOnly: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            fontSize: 12.5,
            automaticLayout: true,
            renderWhitespace: 'none',
          }}
        />
      )}
    </div>
  )
}
