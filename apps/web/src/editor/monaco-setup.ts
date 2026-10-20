// Bundles Monaco with the app so the editor works offline (the default loader fetches from a CDN).
// Only tokenisers are loaded for most languages; JSON also gets its validating worker.
import { loader } from '@monaco-editor/react'
import 'monaco-editor/esm/vs/basic-languages/python/python.contribution'
import 'monaco-editor/esm/vs/basic-languages/javascript/javascript.contribution'
import 'monaco-editor/esm/vs/basic-languages/typescript/typescript.contribution'
import 'monaco-editor/esm/vs/basic-languages/html/html.contribution'
import 'monaco-editor/esm/vs/basic-languages/css/css.contribution'
import 'monaco-editor/esm/vs/basic-languages/scss/scss.contribution'
import 'monaco-editor/esm/vs/basic-languages/less/less.contribution'
import 'monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution'
import 'monaco-editor/esm/vs/basic-languages/sql/sql.contribution'
import 'monaco-editor/esm/vs/basic-languages/shell/shell.contribution'
import 'monaco-editor/esm/vs/basic-languages/markdown/markdown.contribution'
import 'monaco-editor/esm/vs/basic-languages/xml/xml.contribution'
import 'monaco-editor/esm/vs/basic-languages/ini/ini.contribution'
import 'monaco-editor/esm/vs/basic-languages/dockerfile/dockerfile.contribution'
import 'monaco-editor/esm/vs/basic-languages/go/go.contribution'
import 'monaco-editor/esm/vs/basic-languages/rust/rust.contribution'
import 'monaco-editor/esm/vs/basic-languages/java/java.contribution'
import 'monaco-editor/esm/vs/basic-languages/ruby/ruby.contribution'
import 'monaco-editor/esm/vs/basic-languages/php/php.contribution'
import 'monaco-editor/esm/vs/basic-languages/cpp/cpp.contribution'
import 'monaco-editor/esm/vs/basic-languages/csharp/csharp.contribution'
import 'monaco-editor/esm/vs/basic-languages/swift/swift.contribution'
import 'monaco-editor/esm/vs/basic-languages/kotlin/kotlin.contribution'
import 'monaco-editor/esm/vs/language/json/monaco.contribution'
import * as monaco from 'monaco-editor/esm/vs/editor/edcore.main'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import JsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'

// Editor colours follow the app's warm palette.
monaco.editor.defineTheme('nodecraft-light', {
  base: 'vs',
  inherit: true,
  rules: [],
  colors: {
    'editor.background': '#ffffff',
    'editor.foreground': '#1f1e1d',
    'editorLineNumber.foreground': '#a8a493',
    'editorLineNumber.activeForeground': '#6b6a63',
    'editor.lineHighlightBackground': '#f5f4ee',
    'editorCursor.foreground': '#b8532f',
    'editor.selectionBackground': '#f0d9cd',
    'editorGutter.background': '#ffffff',
    'editorWidget.background': '#ffffff',
  },
})
monaco.editor.defineTheme('nodecraft-dark', {
  base: 'vs-dark',
  inherit: true,
  rules: [],
  colors: {
    'editor.background': '#2b2a27',
    'editor.foreground': '#f2f0e8',
    'editorLineNumber.foreground': '#7d7a6e',
    'editorLineNumber.activeForeground': '#b5b2a6',
    'editor.lineHighlightBackground': '#33322e',
    'editorCursor.foreground': '#e08a66',
    'editor.selectionBackground': '#5a3d31',
    'editorGutter.background': '#2b2a27',
    'editorWidget.background': '#353430',
  },
})

self.MonacoEnvironment = {
  getWorker: (_id: string, label: string) => (label === 'json' ? new JsonWorker() : new EditorWorker()),
}
loader.config({ monaco })
