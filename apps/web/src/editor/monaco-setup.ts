// Bundles Monaco with the app so the editor works offline (the default loader fetches from a CDN).
import { loader } from '@monaco-editor/react'
import 'monaco-editor/esm/vs/basic-languages/python/python.contribution'
import * as monaco from 'monaco-editor/esm/vs/editor/edcore.main'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'

self.MonacoEnvironment = { getWorker: () => new EditorWorker() }
loader.config({ monaco })
