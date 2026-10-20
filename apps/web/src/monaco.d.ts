// Monaco ships no types for its deep ESM entry points; they re-export the public API.
declare module 'monaco-editor/esm/vs/editor/edcore.main' {
  export * from 'monaco-editor'
}
declare module 'monaco-editor/esm/vs/basic-languages/python/python.contribution'
