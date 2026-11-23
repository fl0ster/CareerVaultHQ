import { type FormEvent, useState } from 'react'
import type { WorkHistoryEntry, WorkHistoryInput } from './api.ts'
import { type Draft, draftError, toDraft, toInput, withKind } from './draft.ts'
import { KINDS } from './kinds.ts'
import KindSwitch from './KindSwitch.tsx'

type Props = {
  initial?: WorkHistoryEntry
  onSubmit: (input: WorkHistoryInput) => Promise<void>
  onCancel: () => void
}

export default function WorkHistoryForm({ initial, onSubmit, onCancel }: Props) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(initial))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const info = KINDS[draft.kind]
  const point = draft.kind === 'certificate' && draft.current

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((prev) => ({ ...prev, [key]: value }))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const invalid = draftError(draft)
    if (invalid) {
      setError(invalid)
      return
    }
    setSaving(true)
    setError(null)
    try {
      await onSubmit(toInput(draft))
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="wh-form" onSubmit={submit}>
      <h2>{initial ? `Edit ${info.noun}` : `New ${info.noun}`}</h2>

      <KindSwitch value={draft.kind} onChange={(kind) => setDraft((d) => withKind(d, kind))} />

      <div className="wh-grid">
        <label>
          {info.title} *
          <input required value={draft.role} onChange={(e) => set('role', e.target.value)} />
        </label>
        <label>
          {info.organisation}
          {info.organisationRequired ? ' *' : ''}
          <input
            required={info.organisationRequired}
            value={draft.employer}
            onChange={(e) => set('employer', e.target.value)}
          />
        </label>
        {info.showLocation ? (
          <label>
            Location
            <input value={draft.location} onChange={(e) => set('location', e.target.value)} />
          </label>
        ) : (
          <span aria-hidden="true" />
        )}
        <label>
          {point ? 'Date *' : 'Start date *'}
          <input
            type="date"
            required
            value={draft.date_start}
            onChange={(e) => set('date_start', e.target.value)}
          />
        </label>
        <label>
          End date
          <input
            type="date"
            value={draft.current ? '' : draft.date_end}
            disabled={draft.current}
            min={draft.date_start || undefined}
            onChange={(e) => set('date_end', e.target.value)}
          />
        </label>
        <label className="wh-check">
          <input
            type="checkbox"
            checked={draft.current}
            onChange={(e) => set('current', e.target.checked)}
          />
          {info.openEnded}
        </label>
      </div>

      {info.showTech && (
        <label>
          Technologies <span className="muted">(comma separated)</span>
          <input
            value={draft.tech}
            placeholder="Python, FastAPI, PostgreSQL"
            onChange={(e) => set('tech', e.target.value)}
          />
        </label>
      )}

      <label>
        {info.contextLabel} <span className="muted">({info.contextPlaceholder.replace('…', '')})</span>
        <textarea
          rows={info.showTech ? 10 : 4}
          value={draft.context}
          onChange={(e) => set('context', e.target.value)}
        />
      </label>

      {error && <p className="error">{error}</p>}

      <div className="wh-actions">
        <button type="submit" disabled={saving}>
          {saving ? 'Saving…' : initial ? 'Save changes' : `Add ${info.noun}`}
        </button>
        <button type="button" className="secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
      </div>
    </form>
  )
}
