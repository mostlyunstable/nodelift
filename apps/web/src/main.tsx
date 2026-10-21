import '@xyflow/react/dist/style.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import { ErrorBoundary } from './app/ErrorBoundary'
import { watchErrors } from './utils/errorLog'
import { Boot } from './desktop/Boot'
import './editor/monaco-setup'
import './app/styles.css'

watchErrors()
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <Boot>
        <App />
      </Boot>
    </ErrorBoundary>
  </StrictMode>,
)
