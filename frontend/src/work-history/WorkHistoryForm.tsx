import { type FormEvent, useState } from 'react'
import type { WorkHistoryEntry, WorkHistoryInput } from './api.ts'

type Props = {
  initial?: WorkHistoryEntry
  onSubmit: (input: WorkHistoryInput) => Promise<void>
  onCancel: () => void
}

type Draft = {
  date_start: string
  date_end: string
  current: boolean
  employer: string
  role: string
  location: string
  tech: string
  context: string
}

function toDraft(entry?: WorkHistoryEntry): Draft {
  return {
    date_start: entry?.date_start ?? '',
    date_end: entry?.date_end ?? '',
    current: entry ? entry.date_end === null : false,
    employer: entry?.employer ?? '',
    role: entry?.role ?? '',
    location: entry?.location ?? '',
    tech: entry?.tech.join(', ') ?? '',
    context: entry?.context ?? '',
  }
}

function toInput(d: Draft): WorkHistoryInput {
  return {
    date_start: d.date_start,
    date_end: d.current || !d.date_end ? null : d.date_end,
    employer: d.employer.trim(),
    role: d.role.trim(),
    location: d.location.trim() || null,
    tech: d.tech.split(/[,\n]/).map((t) => t.trim()).filter(Boolean),
    context: d.context.trim() || null,
  }
}

export default function WorkHistoryForm({ initial, onSubmit, onCancel }: Props) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(initial))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((prev) => ({ ...prev, [key]: value }))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!draft.current && draft.date_end && draft.date_end < draft.date_start) {
      setError('End date must not be earlier than start date.')
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
      <h2>{initial ? 'Edit position' : 'New position'}</h2>

      <div className="wh-grid">
        <label>
          Employer *
          <input required value={draft.employer} onChange={(e) => set('employer', e.target.value)} />
        </label>
        <label>
          Role *
          <input required value={draft.role} onChange={(e) => set('role', e.target.value)} />
        </label>
        <label>
          Location
          <input value={draft.location} onChange={(e) => set('location', e.target.value)} />
        </label>
        <label>
          Start date *
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
            value={draft.date_end}
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
          Current position
        </label>
      </div>

      <label>
        Technologies <span className="muted">(comma separated)</span>
        <input
          value={draft.tech}
          placeholder="Python, FastAPI, PostgreSQL"
          onChange={(e) => set('tech', e.target.value)}
        />
      </label>

      <label>
        Context <span className="muted">(what you did, achievements, team, scope)</span>
        <textarea
          rows={10}
          value={draft.context}
          onChange={(e) => set('context', e.target.value)}
        />
      </label>

      {error && <p className="error">{error}</p>}

      <div className="wh-actions">
        <button type="submit" disabled={saving}>
          {saving ? 'Saving…' : initial ? 'Save changes' : 'Add position'}
        </button>
        <button type="button" className="secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
      </div>
    </form>
  )
}
