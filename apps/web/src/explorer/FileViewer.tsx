import Editor from '@monaco-editor/react'
import type { RepoFileContent } from '../api/client'
import { formatBytes } from './tree'

const REASONS: Record<string, string> = {
  binary: 'This is a binary file, so its content is not shown.',
  not_utf8: 'This file is not valid UTF-8 text, so its content is not shown.',
  too_large: 'This file is larger than the import limit, so its content was not downloaded.',
  cache_missing: 'The cached copy of this file is missing. Re-import the repository to restore it.',
}

export function FileViewer({
  file,
  error,
  theme,
}: {
  file: RepoFileContent | null
  error: string | null
  theme: 'dark' | 'light'
}) {
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
