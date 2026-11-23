import { type FormEvent, useEffect, useRef, useState } from 'react'
import { Plus, X } from 'lucide-react'
import '../jobs/jobs.css'
import type { WorkHistoryInput } from './api.ts'
import { type Draft, draftError, toDraft, toInput } from './draft.ts'

const EMPTY: Draft = toDraft()

type TextField = 'role' | 'employer' | 'location' | 'date_start' | 'date_end' | 'tech' | 'context'

/**
 * Floating "add position" button in the bottom-right corner that morphs into a Gmail-style
 * compose window, like the one for adding jobs. Clicking outside minimises it back into the
 * button; the draft is kept.
 */
export default function AddPositionComposer({ onSubmit }: { onSubmit: (input: WorkHistoryInput) => Promise<void> }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const roleRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    const focus = window.setTimeout(() => roleRef.current?.focus(), 180)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
      window.clearTimeout(focus)
    }
  }, [open])

  const set = (key: TextField) => (e: { target: { value: string } }) =>
    setDraft((d) => ({ ...d, [key]: e.target.value }))

  const ready = !!draft.role.trim() && !!draft.employer.trim() && !!draft.date_start

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!ready || saving) return
    const invalid = draftError(draft)
    if (invalid) {
      setError(invalid)
      return
    }
    setSaving(true)
    setError(null)
    try {
      await onSubmit(toInput(draft))
      setDraft(EMPTY)
      setOpen(false)
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err))
    } finally {
      setSaving(false)
    }
  }

  const hasDraft =
    draft.current || Object.values(draft).some((v) => typeof v === 'string' && v.trim() !== '')

  return (
    <div ref={rootRef} className={open ? 'add-job add-position open' : 'add-job add-position'}>
      <button
        type="button"
        className="add-job-fab"
        onClick={() => setOpen(true)}
        aria-label="Add a position"
        title={hasDraft ? 'Continue adding position (draft)' : 'Add a position'}
        tabIndex={open ? -1 : 0}
      >
        <Plus size={24} aria-hidden="true" />
        {hasDraft && <span className="add-job-dot" aria-hidden="true" />}
      </button>

      <form className="add-job-panel" onSubmit={submit} aria-hidden={!open} inert={!open}>
        <header className="add-job-head">
          <span>New position</span>
          <button type="button" className="add-job-close" onClick={() => setOpen(false)} aria-label="Minimise">
            <X size={16} aria-hidden="true" />
          </button>
        </header>
        <input ref={roleRef} placeholder="Role" value={draft.role} onChange={set('role')} required />
        <input placeholder="Employer" value={draft.employer} onChange={set('employer')} required />
        <input placeholder="Location (optional)" value={draft.location} onChange={set('location')} />
        <div className="add-position-dates">
          <label>
            <span>Start</span>
            <input type="date" value={draft.date_start} onChange={set('date_start')} required />
          </label>
          <label>
            <span>End</span>
            <input
              type="date"
              value={draft.current ? '' : draft.date_end}
              min={draft.date_start || undefined}
              disabled={draft.current}
              onChange={set('date_end')}
            />
          </label>
          <label className="add-position-current">
            <input
              type="checkbox"
              checked={draft.current}
              onChange={(e) => setDraft((d) => ({ ...d, current: e.target.checked }))}
            />
            Current
          </label>
        </div>
        <input placeholder="Technologies, comma separated" value={draft.tech} onChange={set('tech')} />
        <textarea
          placeholder="What you did: achievements, team, scope…"
          value={draft.context}
          onChange={set('context')}
        />
        {error && <p className="error">{error}</p>}
        <footer className="add-job-foot">
          <button type="submit" disabled={saving || !ready}>
            {saving ? 'Adding…' : 'Add position'}
          </button>
          {hasDraft && (
            <button
              type="button"
              className="secondary small"
              onClick={() => {
                setDraft(EMPTY)
                setError(null)
              }}
            >
              Discard
            </button>
          )}
        </footer>
      </form>
    </div>
  )
}
