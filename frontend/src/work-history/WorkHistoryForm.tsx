import { type FormEvent, useState } from 'react'
import { formatDay } from '../applications/api.ts'
import type { Transition, WorkHistoryEntry, WorkHistoryInput } from './api.ts'
import { type Draft, draftError, toDraft, toInput, withKind } from './draft.ts'
import { KINDS } from './kinds.ts'
import KindSwitch from './KindSwitch.tsx'
import { dayBefore, predecessorCandidate, TRANSITIONS } from './tenure.ts'

function formatMonth(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { year: 'numeric', month: 'short' })
}

/** "Role change at Acme: continues Software Engineer (Jan 2019 – present), which ends on 29/02/2024." */
function ContinuesNote({
  transition,
  previous,
  dateStart,
  adding,
}: {
  transition: Transition
  previous: WorkHistoryEntry
  dateStart: string
  /** A new role: an ongoing previous role is ended the day before it starts. */
  adding: boolean
}) {
  const { icon: Icon, label } = TRANSITIONS[transition]
  const end = previous.date_end ? formatMonth(previous.date_end) : 'present'
  const closes = adding && previous.date_end === null && dateStart
  return (
    <p className="wh-transition-note">
      <Icon size={14} aria-hidden="true" />
      <span>
        {label} at {previous.employer}: continues <strong>{previous.role}</strong> ({formatMonth(previous.date_start)} –{' '}
        {end}){closes ? `, which ends on ${formatDay(dayBefore(dateStart))}` : ''}.
      </span>
    </p>
  )
}

type Props = {
  /** The entry being edited; without it the form adds a new one. */
  initial?: WorkHistoryEntry
  /** Starting values of a new entry (e.g. a role change at an employer). */
  seed?: Draft
  /** Heading of a new entry's form (default "New position"). */
  heading?: string
  /** The whole career, to find the role a role change continues. */
  entries: WorkHistoryEntry[]
  onSubmit: (input: WorkHistoryInput) => Promise<void>
  onCancel: () => void
}

export default function WorkHistoryForm({ initial, seed, heading, entries, onSubmit, onCancel }: Props) {
  const [draft, setDraft] = useState<Draft>(() => seed ?? toDraft(initial))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const info = KINDS[draft.kind]
  const point = draft.kind === 'certificate' && draft.current
  const previous = predecessorCandidate(entries, draft, initial?.id)
  // What the work journal built for the position; used while the user's own fields are empty.
  const journalContext = initial?.journal_context ?? ''
  const journalTech = initial?.journal_tech.join(', ') ?? ''
  // A position stays a position: it can't be turned into education or a certificate, and a
  // role change is a position too.
  const kindLocked = initial?.kind === 'job' || !!seed
  // A role change (or promotion) is at the employer of the role it continues. Whether a role
  // continues an earlier one is set when it is added and is not changed here.
  const continues = draft.kind === 'job' && draft.transition ? previous : null

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
      // Without an earlier position at the employer there is nothing to continue.
      await onSubmit(toInput(previous ? draft : { ...draft, transition: '' }))
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="wh-form" onSubmit={submit}>
      <h2>{initial ? `Edit ${info.noun}` : (heading ?? `New ${info.noun}`)}</h2>

      {!kindLocked && <KindSwitch value={draft.kind} onChange={(kind) => setDraft((d) => withKind(d, kind))} />}

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
            readOnly={!!continues}
            title={continues ? 'The employer of the role this one continues' : undefined}
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

      {continues && draft.transition && (
        <ContinuesNote
          transition={draft.transition}
          previous={continues}
          dateStart={draft.date_start}
          adding={!initial}
        />
      )}

      {info.showTech && (
        <label>
          Technologies <span className="muted">(comma separated)</span>
          <input
            value={draft.tech}
            placeholder={journalTech ? `From your journal: ${journalTech}` : 'Python, FastAPI, PostgreSQL'}
            onChange={(e) => set('tech', e.target.value)}
          />
        </label>
      )}

      <label>
        {info.contextLabel} <span className="muted">({info.contextPlaceholder.replace('…', '')})</span>
        <textarea
          rows={info.showTech ? 10 : 4}
          value={draft.context}
          placeholder={journalContext ? `From your journal: ${journalContext}` : undefined}
          onChange={(e) => set('context', e.target.value)}
        />
      </label>
      {(journalContext || journalTech) && (
        <p className="muted wh-journal-hint">
          Leave {journalContext && journalTech ? 'these' : 'this'} empty to use what your work journal built; anything you
          write here takes precedence and is never overwritten.
        </p>
      )}

      {error && <p className="error">{error}</p>}

      <div className="wh-actions">
        <button type="submit" disabled={saving}>
          {saving
            ? 'Saving…'
            : initial
              ? 'Save changes'
              : draft.transition
                ? `Add ${TRANSITIONS[draft.transition].label.toLowerCase()}`
                : `Add ${info.noun}`}
        </button>
        <button type="button" className="secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
      </div>
    </form>
  )
}
