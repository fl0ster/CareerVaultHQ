import { type FormEvent, useEffect, useRef, useState } from 'react'
import { Plus, X } from 'lucide-react'
import '../jobs/jobs.css'
import type { WorkHistoryEntry, WorkHistoryInput } from './api.ts'
import { type Draft, draftError, draftReady, toDraft, toInput, withKind } from './draft.ts'
import { KINDS } from './kinds.ts'
import KindSwitch from './KindSwitch.tsx'
import { predecessorCandidate } from './tenure.ts'
import TransitionSwitch from './TransitionSwitch.tsx'

const EMPTY: Draft = toDraft()

type TextField = 'role' | 'employer' | 'location' | 'date_start' | 'date_end' | 'tech' | 'context'

/**
 * Floating "add" button in the bottom-right corner that morphs into a Gmail-style compose
 * window, like the one for adding jobs. It adds a position, an education entry or a
 * certificate (the switch at the top). Clicking outside minimises it back into the button;
 * the draft is kept. A position at an employer the career already has offers to continue the
 * earlier role there (a promotion or a role change).
 */
export default function AddPositionComposer({
  entries,
  onSubmit,
}: {
  entries: WorkHistoryEntry[]
  onSubmit: (input: WorkHistoryInput) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const roleRef = useRef<HTMLInputElement>(null)
  const info = KINDS[draft.kind]

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

  const ready = draftReady(draft)
  const previous = predecessorCandidate(entries, draft)

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
      await onSubmit(toInput(previous ? draft : { ...draft, transition: '' }))
      // Keep the kind: several certificates or degrees are often added in a row.
      setDraft(withKind(EMPTY, draft.kind))
      setOpen(false)
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err))
    } finally {
      setSaving(false)
    }
  }

  const hasDraft = Object.entries(draft).some(
    ([key, v]) => typeof v === 'string' && key !== 'kind' && v.trim() !== '',
  )
  const point = draft.kind === 'certificate' && draft.current

  return (
    <div ref={rootRef} className={open ? 'add-job add-position open' : 'add-job add-position'}>
      <button
        type="button"
        className="add-job-fab"
        onClick={() => setOpen(true)}
        aria-label="Add a position, education or certificate"
        title={hasDraft ? `Continue adding ${info.noun} (draft)` : 'Add a position, education or certificate'}
        tabIndex={open ? -1 : 0}
      >
        <Plus size={24} aria-hidden="true" />
        {hasDraft && <span className="add-job-dot" aria-hidden="true" />}
      </button>

      <form className="add-job-panel" onSubmit={submit} aria-hidden={!open} inert={!open}>
        <header className="add-job-head">
          <span>New {info.noun}</span>
          <button type="button" className="add-job-close" onClick={() => setOpen(false)} aria-label="Minimise">
            <X size={16} aria-hidden="true" />
          </button>
        </header>
        <KindSwitch
          className="compact"
          value={draft.kind}
          onChange={(kind) => setDraft((d) => withKind(d, kind))}
        />
        <input
          ref={roleRef}
          placeholder={info.titlePlaceholder}
          aria-label={info.title}
          value={draft.role}
          onChange={set('role')}
          required
        />
        <input
          placeholder={info.organisationPlaceholder}
          aria-label={info.organisation}
          value={draft.employer}
          onChange={set('employer')}
          required={info.organisationRequired}
        />
        {previous && (
          <TransitionSwitch
            className="compact"
            value={draft.transition}
            onChange={(transition) => setDraft((d) => ({ ...d, transition }))}
            previous={previous}
            dateStart={draft.date_start}
          />
        )}
        {info.showLocation && (
          <input placeholder="Location (optional)" value={draft.location} onChange={set('location')} />
        )}
        <div className="add-position-dates">
          <label>
            <span>{point ? 'Date' : 'Start'}</span>
            <input type="date" value={draft.date_start} onChange={set('date_start')} required />
          </label>
          {!point && (
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
          )}
          <label className="add-position-current">
            <input
              type="checkbox"
              checked={draft.current}
              onChange={(e) => setDraft((d) => ({ ...d, current: e.target.checked }))}
            />
            {info.openEndedShort}
          </label>
        </div>
        {info.showTech && (
          <input placeholder="Technologies, comma separated" value={draft.tech} onChange={set('tech')} />
        )}
        <textarea placeholder={info.contextPlaceholder} value={draft.context} onChange={set('context')} />
        {error && <p className="error">{error}</p>}
        <footer className="add-job-foot">
          <button type="submit" disabled={saving || !ready}>
            {saving ? 'Adding…' : `Add ${info.noun}`}
          </button>
          {hasDraft && (
            <button
              type="button"
              className="secondary small"
              onClick={() => {
                setDraft(withKind(EMPTY, draft.kind))
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
