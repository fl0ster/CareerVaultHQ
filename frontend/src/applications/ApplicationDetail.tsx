import { type ReactNode, useState } from 'react'
import { Check, ExternalLink, Flag, Pencil, Trash2, Undo2 } from 'lucide-react'
import { describeError, isInProgress } from '../cv/api.ts'
import { CvPipelineReport } from '../cv/CvPipelineDialog.tsx'
import '../cv/cv.css'
import '../interviews/interviews.css'
import TechPills from '../jobs/TechPills.tsx'
import {
  type Application,
  type ApplicationEvent,
  type ApplicationStatus,
  type EventUpdate,
  type PlannedRound,
  isFinalStatus,
  ACCEPTED_STATUS,
  APPLIED_STATUS,
  DECLINED_STATUS,
  INITIAL_ONLY_STATUS,
  INTERVIEW_STATUS,
  MAX_INTERVIEW_ROUNDS,
  OFFER_STATUS,
  pickableStatuses,
  applicationsApi,
  formatDay,
  formatDuration,
  fromLocalInput,
  heldRounds,
  historyEvents,
  isAutoEvent,
  roundLabel,
  serverDate,
  toLocalInput,
} from './api.ts'
import ApplicationCv from './ApplicationCv.tsx'
import Salary from './Salary.tsx'
import WorkMode from './WorkMode.tsx'
import StatusBadge from './StatusBadge.tsx'
import { AcceptOfferButton, DeclineOfferButton } from './OfferActions.tsx'
import { pageHref } from '../shell/nav.ts'

type Props = {
  application: Application
  statuses: ApplicationStatus[]
  /** The job's technologies, shown quietly in the left column. */
  technologies: string[]
  /** The job's parsed description (`undefined` while loading, `null` when there is none). */
  description: string | null | undefined
  onChange: (application: Application) => void
  /** The offer was accepted (the application is now `ACCEPTED`). */
  onAccepted: (application: Application) => void
}

/** Runs an API call, tracking busy state and turning failures into an error message. */
function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true)
    setError(null)
    try {
      return await fn()
    } catch (e) {
      setError(describeError(e))
      return undefined
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, run }
}

/** Suggestions for the kind of an interview round. */
const ROUND_TYPES = [
  'HR screening',
  'Culture match',
  'Technical',
  'Live coding',
  'System design',
  'Home assignment',
  'Hiring manager',
  'Team meeting',
  'Final',
]
const ROUND_TYPES_ID = 'interview-round-types'

const DURATIONS = [15, 30, 45, 60, 90, 120, 180, 240]

function DurationSelect({
  value,
  onChange,
  disabled,
}: {
  value: number | null
  onChange: (minutes: number | null) => void
  disabled?: boolean
}) {
  return (
    <select
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      disabled={disabled}
      aria-label="Duration"
      title="Duration"
    >
      <option value="">Duration…</option>
      {DURATIONS.map((m) => (
        <option key={m} value={m}>
          {formatDuration(m)}
        </option>
      ))}
    </select>
  )
}

/** Small icon-only button for the actions of a step. */
function IconButton({
  label,
  onClick,
  disabled,
  danger,
  children,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
  danger?: boolean
  children: ReactNode
}) {
  return (
    <button
      type="button"
      className={`app-icon-btn${danger ? ' danger' : ''}`}
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
    >
      {children}
    </button>
  )
}

/** Colour class of a step: each state's dot (and the line below it) takes the state's colour. */
const stepTone = (key: string) => `tone-${key.toLowerCase()}`

/** Earliest `datetime-local` value a state of `key` may be dated at (`undefined`: no limit):
 * not before APPLIED once it is recorded, and an interview round or APPLIED itself not before
 * SHORTLISTED. `self` is the event being edited, left out of the reference points. */
function earliestFor(application: Application, key: string, self?: number): string | undefined {
  if (key === INITIAL_ONLY_STATUS) return undefined
  const at = (status: string) =>
    application.events.find((e) => e.id !== self && e.status.key === status && e.occurred_at)?.occurred_at
  const applied = key === APPLIED_STATUS ? undefined : at(APPLIED_STATUS)
  if (applied) return toLocalInput(applied)
  if (key !== INTERVIEW_STATUS && key !== APPLIED_STATUS) return undefined
  const shortlisted = at(INITIAL_ONLY_STATUS)
  return shortlisted ? toLocalInput(shortlisted) : undefined
}

/** Error message when `when` (a `datetime-local` value) is before `min`. */
function tooEarly(when: string, min: string | undefined): string | null {
  // Same fixed-width format, so the strings compare like the dates.
  return when && min && when < min ? `Pick a date on or after ${new Date(min).toLocaleString()}.` : null
}

/** A recorded state: a filled, checked dot in the state's colour, its name and date beside it
 * and the note under it. The latest one (the application's current state) is ringed. */
function EventRow({
  application,
  event,
  name,
  current,
  statuses,
  onChange,
}: {
  application: Application
  event: ApplicationEvent
  /** "Applied", "Round 2 · Technical"… */
  name: string
  /** The application's current state. */
  current: boolean
  statuses: ApplicationStatus[]
  onChange: (application: Application) => void
}) {
  const [editing, setEditing] = useState(false)
  const [status, setStatus] = useState(event.status.key)
  const [note, setNote] = useState(event.note)
  const [title, setTitle] = useState(event.title)
  const [duration, setDuration] = useState(event.duration_minutes)
  const [when, setWhen] = useState(toLocalInput(event.occurred_at))
  const { busy, error, run } = useAction()
  // SHORTLISTED is fixed for good; ACCEPTED / DECLINED can only be removed (undoing the answer).
  const locked = event.status.key === INITIAL_ONLY_STATUS
  const statusLocked = locked || event.status.key === ACCEPTED_STATUS || event.status.key === DECLINED_STATUS
  const isRound = status === INTERVIEW_STATUS
  const min = earliestFor(application, status, event.id)
  const dateError = when !== toLocalInput(event.occurred_at) ? tooEarly(when, min) : null

  const startEdit = () => {
    setStatus(event.status.key)
    setNote(event.note)
    setTitle(event.title)
    setDuration(event.duration_minutes)
    setWhen(toLocalInput(event.occurred_at))
    setEditing(true)
  }

  const save = async () => {
    // The input only has minute precision: re-sending an untouched value would truncate
    // the stored timestamp, so the date is sent only when the user actually changed it.
    const dateChanged = when !== toLocalInput(event.occurred_at)
    const updated = await run(() =>
      applicationsApi.updateEvent(application.id, event.id, {
        ...(statusLocked ? {} : { status }),
        note,
        title,
        duration_minutes: duration,
        ...(dateChanged ? { occurred_at: fromLocalInput(when) } : {}),
      }),
    )
    if (updated) {
      onChange(updated)
      setEditing(false)
    }
  }

  // Removing a held interview round turns it back into a planned one.
  const isHeldRound = event.status.key === INTERVIEW_STATUS && !event.stage_entry
  const remove = async () => {
    const question = isHeldRound
      ? `Mark ${event.title ? `the "${event.title}"` : 'this'} round as not held? It goes back to the planned rounds.`
      : event.status.key === ACCEPTED_STATUS
        ? `Undo accepting the offer? The application goes back to "Offer" and the position it added to My Career is deleted.`
        : event.status.key === DECLINED_STATUS
          ? `Undo declining the offer? The application goes back to "Offer".`
          : event.status.key === APPLIED_STATUS && application.events.some((e) => e.status.key !== APPLIED_STATUS && e.status.key !== INITIAL_ONLY_STATUS)
            ? `Remove the "Applied" state? Every later state (interviews, offer, rejection…) is undone: held rounds go back to planned and the job back to Jobs.`
            : `Remove the "${event.status.label}" state?`
    if (!window.confirm(question)) return
    const updated = await run(() => applicationsApi.removeEvent(application.id, event.id))
    if (updated) onChange(updated)
  }

  const stepClass = `iv-step is-held is-done ${stepTone(event.status.key)}${current ? ' is-current' : ''}`
  const dot = (
    <span className="iv-step-dot" aria-hidden="true">
      <Check size={12} strokeWidth={3} />
    </span>
  )

  if (editing) {
    return (
      <li className={`${stepClass} editing`}>
        {dot}
        <div className="app-step-body">
          <div className="app-form-row">
            {statusLocked ? (
              <StatusBadge status={event.status} auto={isAutoEvent(event)} />
            ) : (
              <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
                {pickableStatuses(statuses)
                  .filter(
                    (s) =>
                      s.key !== APPLIED_STATUS ||
                      !application.events.some((e) => e.id !== event.id && e.status.key === APPLIED_STATUS),
                  )
                  .map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.label}
                    </option>
                  ))}
              </select>
            )}
            <input type="datetime-local" value={when} min={min} onChange={(e) => setWhen(e.target.value)} />
          </div>
          {isRound && (
            <div className="app-form-row app-round-fields">
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                list={ROUND_TYPES_ID}
                placeholder="Kind of round (e.g. Technical)"
                aria-label="Kind of round"
                maxLength={128}
              />
              <DurationSelect value={duration} onChange={setDuration} />
            </div>
          )}
          <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note for this state" rows={2} />
          <div className="app-buttons">
            <button type="button" className="small" onClick={save} disabled={busy || !!dateError}>
              {busy ? 'Saving…' : 'Save'}
            </button>
            <button type="button" className="secondary small" onClick={() => setEditing(false)} disabled={busy}>
              Cancel
            </button>
          </div>
          {(dateError || error) && <p className="error">{dateError || error}</p>}
        </div>
      </li>
    )
  }

  const dateLine = [
    serverDate(event.occurred_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }),
    formatDuration(event.duration_minutes),
  ]
    .filter(Boolean)
    .join(' · ')
  return (
    <li className={stepClass}>
      {dot}
      <div className="app-step-body">
        <div className="app-step-head">
          <span className="iv-step-name">
            {isAutoEvent(event) && (
              <span className="app-status-auto" title="Recorded automatically from a Gmail rejection mail">
                ⚡
              </span>
            )}
            {name}
          </span>
          {current && <span className="sr-only">(current state)</span>}
          <span className="app-step-actions">
            <IconButton label="Edit" onClick={startEdit} disabled={busy}>
              <Pencil size={14} aria-hidden="true" />
            </IconButton>
            {!locked && (
              <IconButton label={isHeldRound ? 'Mark as not held' : 'Remove'} onClick={remove} disabled={busy} danger>
                {isHeldRound ? <Undo2 size={14} aria-hidden="true" /> : <Trash2 size={14} aria-hidden="true" />}
              </IconButton>
            )}
          </span>
        </div>
        <span className="iv-step-when">{dateLine}</span>
        {event.note && <p className="app-note">{event.note}</p>}
        {error && <p className="error">{error}</p>}
      </div>
    </li>
  )
}

/** A planned interview round: a dashed, numbered dot, edited inline (each field saves when it
 * is left; the parent remounts it when the stored values change). */
function PlannedEventRow({
  application,
  event,
  index,
  current,
  onChange,
}: {
  application: Application
  event: PlannedRound
  /** Position among all rounds (0-based). */
  index: number
  /** The next round to be held: ringed, as in the interview card's stepper. */
  current: boolean
  onChange: (application: Application) => void
}) {
  const [title, setTitle] = useState(event.title)
  const [renaming, setRenaming] = useState(false)
  const [note, setNote] = useState(event.note)
  const [when, setWhen] = useState(event.occurred_at ? toLocalInput(event.occurred_at) : '')
  const { busy, error, run } = useAction()
  const final = isFinalStatus(application.status)
  const min = earliestFor(application, INTERVIEW_STATUS)
  const dateError = tooEarly(when, min)

  const save = async (changes: EventUpdate) => {
    const updated = await run(() => applicationsApi.updateEvent(application.id, event.id, changes))
    if (updated) onChange(updated)
  }

  const saveTitle = () => {
    setRenaming(false)
    if (title.trim() !== event.title) void save({ title: title.trim() })
  }
  const cancelRename = () => {
    setTitle(event.title)
    setRenaming(false)
  }
  const defaultName = `Round ${index + 1}`
  const saveNote = () => {
    if (note !== event.note) void save({ note })
  }
  const saveWhen = () => {
    const stored = event.occurred_at ? toLocalInput(event.occurred_at) : ''
    if (when !== stored && !tooEarly(when, min)) void save({ occurred_at: when ? fromLocalInput(when) : null })
  }

  const remove = async () => {
    if (!window.confirm(`Remove ${roundLabel(event, index)} from the plan (one round fewer)?`)) return
    const updated = await run(() => applicationsApi.removeEvent(application.id, event.id))
    if (updated) onChange(updated)
  }

  return (
    <li className={`iv-step is-upcoming app-planned${final ? ' not-held' : ''}${current ? ' is-current' : ''}`}>
      {final ? (
        <span className="iv-step-dot" aria-hidden="true">
          {index + 1}
        </span>
      ) : (
        // The dot itself marks the round as held: its number turns into a check on hover.
        <button
          type="button"
          className="iv-step-dot app-dot-btn"
          onClick={() => void save({ planned: false })}
          disabled={busy}
          title="Mark as held"
          aria-label={`Mark round ${index + 1} as held`}
        >
          <span className="app-dot-num">{index + 1}</span>
          <Check className="app-dot-check" size={12} strokeWidth={3} aria-hidden="true" />
        </button>
      )}
      <div className="app-step-body">
        <div className="app-step-head">
          <span className="iv-step-name">
            {renaming ? (
              <input
                type="text"
                className="app-round-name-input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                onBlur={saveTitle}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') saveTitle()
                  else if (e.key === 'Escape') cancelRename()
                }}
                list={ROUND_TYPES_ID}
                placeholder={defaultName}
                aria-label={`${defaultName}: name`}
                maxLength={128}
                autoFocus
              />
            ) : (
              // The name (the custom one, or "Round N") is clicked to rename the round.
              <button
                type="button"
                className="app-round-name"
                onClick={() => setRenaming(true)}
                disabled={busy}
                title="Click to rename (e.g. Technical); leave empty for the default name"
              >
                {event.title || defaultName}
              </button>
            )}{' '}
            <span className="app-round-label">· {final ? 'not held' : 'planned'}</span>
          </span>
          <span className="app-step-actions">
            <IconButton label="Remove this round from the plan" onClick={remove} disabled={busy} danger>
              <Trash2 size={14} aria-hidden="true" />
            </IconButton>
          </span>
        </div>
        <div className="app-form-row app-round-fields">
          <DurationSelect
            value={event.duration_minutes}
            onChange={(minutes) => void save({ duration_minutes: minutes })}
            disabled={busy}
          />
          <input
            type="datetime-local"
            value={when}
            min={min}
            onChange={(e) => setWhen(e.target.value)}
            onBlur={saveWhen}
            aria-label={`Round ${index + 1}: scheduled for`}
            title="Scheduled for (optional)"
            disabled={busy}
          />
        </div>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onBlur={saveNote}
          placeholder="Note (optional)"
          aria-label={`Round ${index + 1}: note`}
          rows={1}
          disabled={busy}
        />
        {(dateError || error) && <p className="error">{dateError || error}</p>}
      </div>
    </li>
  )
}

/** The states that can end the interview stage, in the order offered. */
const OUTCOME_STATUSES = [OFFER_STATUS, 'REJECTED', 'CLOSED']

/** After the last round is held: a closing step with a dashed dot whose buttons record how the
 * interviews ended (Offer / Rejected / Closed). */
function OutcomeRow({
  application,
  statuses,
  onChange,
}: {
  application: Application
  statuses: ApplicationStatus[]
  onChange: (application: Application) => void
}) {
  const { busy, error, run } = useAction()
  const options = OUTCOME_STATUSES.flatMap((key) => statuses.filter((s) => s.key === key))
  if (options.length === 0) return null

  const pick = async (key: string) => {
    const updated = await run(() => applicationsApi.addEvent(application.id, { status: key }))
    if (updated) onChange(updated)
  }

  return (
    <li className="iv-step is-upcoming app-outcome">
      <span className="iv-step-dot" aria-hidden="true">
        <Flag size={12} strokeWidth={2.5} />
      </span>
      <div className="app-step-body">
        <div className="app-step-head">
          <span className="iv-step-name">
            Outcome <span className="app-outcome-hint">· all rounds done</span>
          </span>
        </div>
        <div className="app-outcome-choices" role="group" aria-label="Record the outcome">
          {options.map((s) => (
            <button
              key={s.key}
              type="button"
              className={`app-outcome-btn ${stepTone(s.key)}`}
              onClick={() => void pick(s.key)}
              disabled={busy}
            >
              {s.label}
            </button>
          ))}
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    </li>
  )
}

/** Number of interview rounds (held + planned): −/+ stepper around an editable count. */
function InterviewPlan({
  application,
  onChange,
}: {
  application: Application
  onChange: (application: Application) => void
}) {
  const { busy, error, run } = useAction()
  const held = heldRounds(application).length
  const rounds = held + application.planned_events.length
  // The parent keys this by `rounds`, so the draft restarts from every stored change.
  const [draft, setDraft] = useState(rounds ? String(rounds) : '')

  const set = async (n: number) => {
    const next = Math.min(Math.max(n, held), MAX_INTERVIEW_ROUNDS)
    if (next === rounds) return setDraft(rounds ? String(rounds) : '')
    const updated = await run(() => applicationsApi.setInterviewRounds(application.id, next))
    if (updated) onChange(updated)
  }
  const commitDraft = () => void set(Math.round(Number(draft)) || 0)

  return (
    <div className="app-plan">
      <span className="app-stepper">
        <button
          type="button"
          className="secondary small"
          aria-label="One round fewer"
          onClick={() => set(rounds - 1)}
          disabled={busy || rounds <= held}
        >
          −
        </button>
        <input
          type="number"
          min={held}
          max={MAX_INTERVIEW_ROUNDS}
          value={draft}
          placeholder="—"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitDraft}
          onKeyDown={(e) => e.key === 'Enter' && commitDraft()}
          aria-label="Number of interview rounds"
          disabled={busy}
        />
        <button
          type="button"
          className="secondary small"
          aria-label="One more round"
          onClick={() => set(rounds + 1)}
          disabled={busy || rounds >= MAX_INTERVIEW_ROUNDS}
        >
          +
        </button>
      </span>
      {application.planned_events.length > 0 && (
        <IconButton
          label="Clear the plan (remove every planned round)"
          onClick={() => {
            if (window.confirm('Remove every planned round?')) void set(0)
          }}
          disabled={busy}
          danger
        >
          <Trash2 size={14} aria-hidden="true" />
        </IconButton>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  )
}

/** The offer stage: the agreed start date (saved when changed) and accepting or declining
 * the offer. */
function OfferBox({
  application,
  onChange,
  onAccepted,
}: {
  application: Application
  onChange: (application: Application) => void
  onAccepted: (application: Application) => void
}) {
  const [startDate, setStartDate] = useState(application.start_date ?? '')
  const { busy, error, run } = useAction()
  const [acceptError, setAcceptError] = useState<string | null>(null)

  const saveStartDate = async () => {
    if (startDate === (application.start_date ?? '')) return
    const updated = await run(() => applicationsApi.setStartDate(application.id, startDate || null))
    if (updated) onChange(updated)
  }

  return (
    <div className="app-offer-box">
      <label className="app-offer-start">
        <span>Start date</span>
        <input
          type="date"
          value={startDate}
          disabled={busy}
          onChange={(e) => setStartDate(e.target.value)}
          onBlur={() => void saveStartDate()}
        />
      </label>
      <AcceptOfferButton
        // The date on screen, even while it is still being saved.
        application={{ ...application, start_date: startDate || null }}
        label="Accept offer"
        onAccepted={onAccepted}
        onError={setAcceptError}
      />
      <DeclineOfferButton application={application} label="Decline offer" onDeclined={onChange} />
      <p className="muted app-offer-hint">
        Accepting moves the position to My Career{startDate ? '' : ' (you will be asked for the start date)'};
        declining closes the application. Remove the offer state instead to record more steps.
      </p>
      {(error || acceptError) && <p className="error">{error ?? acceptError}</p>}
    </div>
  )
}

/** Free-text notes about the position: a draft saved with the Save button (or Ctrl/⌘+Enter). */
function NotesPane({
  application,
  onChange,
}: {
  application: Application
  onChange: (application: Application) => void
}) {
  const [draft, setDraft] = useState(application.notes)
  const [saved, setSaved] = useState(false)
  const { busy, error, run } = useAction()
  const dirty = draft !== application.notes

  const save = async () => {
    if (!dirty) return
    const updated = await run(() => applicationsApi.updateNotes(application.id, draft))
    if (updated) {
      onChange(updated)
      setSaved(true)
    }
  }

  return (
    <div className="app-notes">
      <textarea
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value)
          setSaved(false)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) void save()
        }}
        placeholder="Your notes about this position…"
        aria-label="Notes about this position"
        rows={10}
        disabled={busy}
      />
      <div className="app-buttons">
        <button type="button" className="small" onClick={() => void save()} disabled={busy || !dirty}>
          {busy ? 'Saving…' : 'Save'}
        </button>
        {dirty && (
          <button type="button" className="secondary small" onClick={() => setDraft(application.notes)} disabled={busy}>
            Discard changes
          </button>
        )}
        {saved && !dirty && <span className="muted">Saved.</span>}
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  )
}

/** Body of the application view: the CV, salary & work mode, the interview round count and the
 * job's technologies in a narrow column on the left; beside it the status history (a vertical stepper),
 * how the latest CV was generated (CV Settings), notes about the position or the job description, switched by tabs, plus a
 * Link that opens the offer. */
export default function ApplicationDetail({
  application,
  statuses,
  technologies,
  description,
  onChange,
  onAccepted,
}: Props) {
  const [pane, setPane] = useState<'history' | 'cv' | 'notes' | 'description'>('history')
  const held = heldRounds(application)
  const history = historyEvents(application)
  const status = application.status
  const final = isFinalStatus(status)
  // As in the interview card: while rounds are planned the next one is the current step (ringed);
  // otherwise the latest recorded state is.
  const upcoming = !final && application.planned_events.length > 0
  // Every round held (none left planned) and the latest state is one of them: time to record how
  // the interviews ended.
  const roundsDone =
    status?.key === INTERVIEW_STATUS &&
    held.length > 0 &&
    application.planned_events.length === 0 &&
    history[history.length - 1] === held[held.length - 1]

  /** "Round 2 · Technical" for a held round, the state's label otherwise. */
  const eventName = (event: ApplicationEvent) => {
    const round = held.indexOf(event)
    if (round < 0) return event.status.label
    return `Round ${round + 1}${event.title ? ` · ${event.title}` : ''}`
  }

  return (
    <div className="app-detail">
      <aside className="app-aside">
        <ApplicationCv application={application} onChange={onChange} />
        <Salary application={application} onChange={onChange} />
        <WorkMode application={application} onChange={onChange} />
        <section className="app-section app-rounds" aria-labelledby={`app-rounds-${application.id}`}>
          <h3 id={`app-rounds-${application.id}`}>Interview rounds</h3>
          <InterviewPlan
            key={held.length + application.planned_events.length}
            application={application}
            onChange={onChange}
          />
        </section>
        {technologies.length > 0 && (
          <section className="app-section app-tech" aria-label="Technologies">
            <h3>Technologies</h3>
            <TechPills technologies={technologies} />
          </section>
        )}
      </aside>

      <section className="app-section app-history" aria-labelledby={`app-history-${application.id}`}>
        <div className="app-tabs" role="tablist" aria-label="Application">
          <button
            type="button"
            role="tab"
            id={`app-history-${application.id}`}
            aria-selected={pane === 'history'}
            onClick={() => setPane('history')}
          >
            Status history
          </button>
          <button type="button" role="tab" aria-selected={pane === 'cv'} onClick={() => setPane('cv')}>
            CV Settings
          </button>
          <button type="button" role="tab" aria-selected={pane === 'notes'} onClick={() => setPane('notes')}>
            Notes
            {application.notes.trim() && (
              <span className="app-tab-dot" title="This position has notes" aria-label="(has notes)" />
            )}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={pane === 'description'}
            onClick={() => setPane('description')}
          >
            Description
          </button>
          <a href={application.job.link} target="_blank" rel="noreferrer" title={`Open the job offer: ${application.job.link}`}>
            Link <ExternalLink size={13} aria-hidden="true" />
          </a>
        </div>
        {pane === 'cv' && (
          <div className="app-cv-report" role="tabpanel">
            {!application.cv ? (
              <p className="muted">No CV generated for this application yet.</p>
            ) : isInProgress(application.cv) ? (
              <p className="muted">The CV is being generated; how it was made shows here once it is done.</p>
            ) : (
              <CvPipelineReport key={application.cv.id} cv={application.cv} />
            )}
          </div>
        )}
        {/* Kept mounted while other tabs show, so an unsaved draft survives. */}
        <div hidden={pane !== 'notes'} role="tabpanel">
          <NotesPane application={application} onChange={onChange} />
        </div>
        {pane === 'description' && (
          <div className="job-desc app-description" role="tabpanel">
            {description === undefined ? (
              <span className="spinner" aria-hidden="true" />
            ) : description ? (
              <pre className="description">{description}</pre>
            ) : (
              <p className="muted">No parsed description.</p>
            )}
          </div>
        )}
        {/* Kept mounted while the description shows, so drafts of planned rounds survive. */}
        <div hidden={pane !== 'history'} role="tabpanel" aria-labelledby={`app-history-${application.id}`}>
        <datalist id={ROUND_TYPES_ID}>
          {ROUND_TYPES.map((t) => (
            <option key={t} value={t} />
          ))}
        </datalist>
        <ol className={`iv-stepper app-timeline${final && status ? ` ${status.key.toLowerCase()}` : ''}`}>
          {history.map((event, i) => (
            <EventRow
              key={`${event.id}:${event.occurred_at}:${event.note}:${event.status.key}:${event.title}:${event.duration_minutes}`}
              application={application}
              event={event}
              name={eventName(event)}
              current={!upcoming && i === history.length - 1}
              statuses={statuses}
              onChange={onChange}
            />
          ))}
          {application.planned_events.map((event, i) => (
            <PlannedEventRow
              // Remounted (fresh field drafts) whenever the stored round changes.
              key={`${event.id}:${event.title}:${event.note}:${event.occurred_at}`}
              application={application}
              event={event}
              index={held.length + i}
              current={upcoming && i === 0}
              onChange={onChange}
            />
          ))}
          {roundsDone && <OutcomeRow application={application} statuses={statuses} onChange={onChange} />}
        </ol>
        {status?.key === OFFER_STATUS ? (
          <OfferBox
            key={application.start_date ?? ''}
            application={application}
            onChange={onChange}
            onAccepted={onAccepted}
          />
        ) : status?.key === ACCEPTED_STATUS ? (
          <p className="app-accepted">
            <span>Offer accepted{application.start_date ? `, starting ${formatDay(application.start_date)}` : ''}.</span>
            {application.work_history_id != null ? (
              <a href={pageHref('work-history', application.work_history_id)}>View in My Career</a>
            ) : (
              <span className="muted">Its My Career entry was deleted.</span>
            )}
          </p>
        ) : status?.key === DECLINED_STATUS ? (
          <p className="app-declined">
            <strong>Offer declined.</strong> Remove the “Declined” state to reopen the offer.
          </p>
        ) : final ? (
          <p className="muted app-final-hint">{status?.label} is final — remove that state to record new ones.</p>
        ) : null}
        </div>
      </section>
    </div>
  )
}
