import { type FormEvent, useEffect, useState } from 'react'
import './candidate-profile.css'
import { type CandidateProfile, candidateProfileApi } from './api.ts'

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString()
}

export default function CandidateProfilePage() {
  const [profile, setProfile] = useState<CandidateProfile | null | undefined>(undefined)
  const [content, setContent] = useState('')
  const [workHistoryId, setWorkHistoryId] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState<string | null>(null)

  const apply = (p: CandidateProfile | null) => {
    setProfile(p)
    setContent(p?.content ?? '')
    setWorkHistoryId(p?.work_history_id ?? '')
  }

  const load = () =>
    candidateProfileApi.latest().then(
      (p) => {
        apply(p)
        setLoadError(null)
      },
      (e) => setLoadError(`Could not load candidate profile: ${String(e instanceof Error ? e.message : e)}`),
    )

  useEffect(() => {
    load()
  }, [])

  const dirty =
    profile === undefined
      ? false
      : content !== (profile?.content ?? '') || workHistoryId !== (profile?.work_history_id ?? '')

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (profile == null)
      return;

    setSaving(true)
    setSaveError(null)
    try {
      const input = { content, work_history_id: workHistoryId.trim() || null }
      const saved = await candidateProfileApi.update(profile.id, input)
      apply(saved)
      setSavedAt(saved.updated_at)
    } catch (err) {
      setSaveError(String(err instanceof Error ? err.message : err))
    } finally {
      setSaving(false)
    }
  }

  const reset = () => {
    if (profile !== undefined) apply(profile)
    setSaveError(null)
  }

  return (
    <>
      <h1 className="title">Candidate profile</h1>

      {profile === undefined && !loadError && <p>Loading…</p>}

      {loadError && (
        <p className="error">
          {loadError}{' '}
          <button type="button" className="secondary small" onClick={load}>Retry</button>
        </p>
      )}

      {profile !== undefined && (
        <form className="cp-form" onSubmit={submit}>
          <p className="cp-status">
            {profile
              ? `Profile #${profile.id}, last updated ${formatDate(profile.updated_at)}.`
              : 'No profile yet.'}
          </p>

          <label>
            Profile
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder=""
              rows={20}
            />
          </label>

          {saveError && <p className="error">{saveError}</p>}

          {profile ?
            <div className="cp-actions">
              <button type="submit" disabled={saving || !dirty}>
                {saving ? 'Saving…' : 'Save changes'}
              </button>
              <button type="button" className="secondary" onClick={reset} disabled={saving || !dirty}>
                Discard changes
              </button>
              {savedAt && !dirty && <span className="cp-saved">Saved {formatDate(savedAt)}</span>}
            </div>
            : null}
        </form>
      )}
    </>
  )
}
