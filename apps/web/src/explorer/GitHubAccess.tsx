import { useEffect, useId, useState } from 'react'
import { api } from '../api/client'

/**
 * A GitHub token lets the Explorer read private repositories and raises GitHub's hourly limit from 60 to 5,000
 * requests. It is stored in the system keychain like any other credential, never in the database or an export.
 */
export function GitHubAccess() {
  const [saved, setSaved] = useState<boolean | null>(null)
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const id = useId()

  const refresh = () =>
    api
      .listCredentials()
      .then((list) => setSaved(list.some((c) => c.name === 'github')))
      .catch(() => setSaved(null))
  useEffect(() => {
    void refresh()
  }, [])

  const save = async () => {
    setBusy(true)
    setProblem(null)
    try {
      if (saved) await api.rotateCredential('github', value.trim())
      else await api.createCredential({ name: 'github', value: value.trim(), kind: 'github' })
      setValue('')
      setOpen(false)
      await refresh()
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'The token could not be saved')
    } finally {
      setBusy(false)
    }
  }
  const remove = async () => {
    setBusy(true)
    try {
      await api.deleteCredential('github')
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="github-access" aria-label="GitHub access">
      <div className="muted small">
        {saved
          ? 'GitHub token saved: private repositories and 5,000 requests an hour.'
          : 'No GitHub token: public repositories only, 60 requests an hour.'}{' '}
        <button className="link-button" aria-expanded={open} onClick={() => setOpen(!open)}>
          {saved ? 'Change token' : 'Add a token'}
        </button>
        {saved && (
          <>
            {' · '}
            <button className="link-button" disabled={busy} onClick={() => void remove()}>
              Remove
            </button>
          </>
        )}
      </div>
      {open && (
        <form
          className="github-token-form"
          onSubmit={(ev) => {
            ev.preventDefault()
            void save()
          }}
        >
          <label htmlFor={id}>GitHub personal access token</label>
          <input
            id={id}
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={value}
            onChange={(ev) => setValue(ev.target.value)}
            placeholder="ghp_… or github_pat_…"
          />
          <p className="muted small">
            Create one at github.com/settings/tokens. For private repositories give it read access to the
            repository contents. It is kept in your system keychain and only ever sent to github.com.
          </p>
          {problem && <div role="alert">{problem}</div>}
          <button className="primary" type="submit" disabled={busy || value.trim().length < 8}>
            Save token
          </button>
        </form>
      )}
    </section>
  )
}
