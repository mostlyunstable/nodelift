import Editor from '@monaco-editor/react'
import type * as Monaco from 'monaco-editor'
import { useEffect, useRef, useState } from 'react'
import type { RepoDiagnostic, RepoFileContent, RepoReference } from '../api/client'
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
  draft = null,
  onDraftChange,
  references = [],
  onGoTo,
}: {
  file: RepoFileContent | null
  error: string | null
  theme: 'dark' | 'light'
  diagnostics?: RepoDiagnostic[]
  target?: { path: string; line: number; n: number } | null
  draft?: string | null // when set, the editor shows this editable copy instead of the imported file
  onDraftChange?: (text: string) => void
  references?: RepoReference[] // names in this file tied to a definition (for Go to Definition)
  onGoTo?: (path: string, line: number) => void
}) {
  const [handle, setHandle] = useState<EditorHandle | null>(null)
  const decorations = useRef<Monaco.editor.IEditorDecorationsCollection | null>(null)
  const refDecorations = useRef<Monaco.editor.IEditorDecorationsCollection | null>(null)
  const refsRef = useRef<RepoReference[]>(references)
  const goRef = useRef(onGoTo)
  useEffect(() => {
    refsRef.current = references
    goRef.current = onGoTo
  })
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

  // underline names we can tie to a definition; Cmd/Ctrl+click or F12 follows them
  useEffect(() => {
    if (!handle || !path || !hasContent) return
    refDecorations.current?.clear()
    refDecorations.current = handle.editor.createDecorationsCollection(
      references
        .filter((r) => r.path === path)
        .map((r) => ({
          range: new handle.monaco.Range(r.line, r.column, r.line, r.end_column),
          options: {
            inlineClassName: 'nc-ref',
            hoverMessage: {
              value: `**${r.dst_symbol}** — \`${r.dst_path}:${r.dst_line}\`\n\n${r.confidence}${r.note ? ` · ${r.note}` : ''}\n\n_Cmd/Ctrl+click or F12 to open_`,
            },
          },
        })),
    )
  }, [handle, path, hasContent, references])

  useEffect(() => {
    if (!handle) return
    const at = (line: number, col: number) =>
      refsRef.current.find((r) => r.line === line && col >= r.column && col <= r.end_column)
    const go = (r: RepoReference | undefined) => r && goRef.current?.(r.dst_path, r.dst_line)
    const click = handle.editor.onMouseDown((e) => {
      const p = e.target.position
      if ((e.event.ctrlKey || e.event.metaKey) && p) go(at(p.lineNumber, p.column))
    })
    const action = handle.editor.addAction({
      id: 'nodecraft.goToDefinition',
      label: 'Go to Definition',
      keybindings: [handle.monaco.KeyCode.F12],
      run: (ed) => {
        const p = ed.getPosition()
        if (p) go(at(p.lineNumber, p.column))
      },
    })
    return () => {
      click.dispose()
      action.dispose()
    }
  }, [handle])

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
          {file.language} · {file.lines} lines · {formatBytes(file.size)} ·{' '}
          {draft === null ? 'read-only' : 'editing a copy'}
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
          value={draft ?? file.content}
          theme={theme === 'dark' ? 'nodecraft-dark' : 'nodecraft-light'}
          onMount={(editor, monaco) => setHandle({ editor, monaco })}
          onChange={(v) => onDraftChange?.(v ?? '')}
          options={{
            readOnly: draft === null,
            domReadOnly: draft === null,
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
