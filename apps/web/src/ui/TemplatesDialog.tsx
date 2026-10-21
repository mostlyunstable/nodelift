import { useStore } from '../state/store'
import { Dialog } from './Dialog'

/** Ready-made workflows for real jobs. Each one is a normal workflow you can change after creating it. */
export function TemplatesDialog() {
  const { examples, createExample, closeDialog, openDialog } = useStore()
  return (
    <Dialog title="Templates" onClose={closeDialog} wide>
      <p className="muted">
        Each template is a normal workflow: create it, read what each step does, and change anything. Some
        need a credential (⋯ → Credentials) or sample files, which are added for you (⋯ →{' '}
        <button className="link-button" onClick={() => openDialog('files')}>
          Files
        </button>
        ). Nothing runs until you press Run.
      </p>
      <ul className="template-list" aria-label="Templates">
        {examples.map((ex) => (
          <li key={ex.id}>
            <div>
              <strong>{ex.title}</strong> <span className="muted">· {ex.nodes} steps</span>
              <p className="muted small">{ex.description}</p>
            </div>
            <button
              className="primary"
              aria-label={`Use this template: ${ex.title}`}
              onClick={() => {
                closeDialog()
                void createExample(ex.id)
              }}
            >
              Use this
            </button>
          </li>
        ))}
      </ul>
    </Dialog>
  )
}
