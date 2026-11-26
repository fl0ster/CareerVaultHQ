import { Send } from 'lucide-react'
import { type FormEvent, type KeyboardEvent, useState } from 'react'
import { journalApi, type WorkHistoryEntry } from './api.ts'

const today = () => new Date().toLocaleDateString('en-CA') // YYYY-MM-DD in local time

/** A text box to log a new journal note on a position (Ctrl/⌘ + Enter saves). */
export default function JournalComposer({
  role,
  onSaved,
  compact = false,
}: {
  role: WorkHistoryEntry
  onSaved?: () => void
  /** On a card: the date picker stays hidden until asked for. */
  compact?: boolean
}) {
  const [body, setBody] = useState('')
  const [day, setDay] = useState('')
  const [pickDay, setPickDay] = useState(!compact)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const id = `journal-note-${role.id}`

  const submit = async (e?: FormEvent) => {
    e?.preventDefault()
    if (!body.trim() || saving) return
    setSaving(true)
    setError(null)
    try {
      await journalApi.add(role.id, body.trim(), day || undefined)
      setBody('')
      setDay('')
      setSaved(true)
      onSaved?.()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      void submit()
    }
  }

  return (
    <form className="journal-composer" onSubmit={submit}>
      <label htmlFor={id} className="sr-only">
        Journal note for {role.role}
      </label>
      <textarea
        id={id}
        rows={compact ? 2 : 3}
        value={body}
        placeholder="What did you work on? Tasks, results, tools, decisions…"
        onChange={(e) => {
          setBody(e.target.value)
          setSaved(false)
        }}
        onKeyDown={onKeyDown}
        maxLength={10000}
      />
      <div className="journal-composer-row">
        {pickDay ? (
          <label className="journal-composer-day">
            <span className="muted">Day</span>
            <input
              type="date"
              value={day || today()}
              min={role.date_start}
              max={role.date_end && role.date_end < today() ? role.date_end : today()}
              onChange={(e) => setDay(e.target.value)}
            />
          </label>
        ) : (
          <button type="button" className="link journal-composer-backdate" onClick={() => setPickDay(true)}>
            Another day?
          </button>
        )}
        <span className="journal-composer-status muted" role="status">
          {saved && !body ? 'Saved to your journal.' : ''}
        </span>
        <button type="submit" className="small" disabled={saving || !body.trim()} title="Ctrl/⌘ + Enter">
          <Send size={14} aria-hidden="true" /> {saving ? 'Saving…' : 'Log it'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  )
}
