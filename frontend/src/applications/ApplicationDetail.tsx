import { useState } from 'react'
import { describeError, type GeneratedCv, isInProgress } from '../cv/api.ts'
import CvActions from '../cv/CvActions.tsx'
import CvStatusBadge from '../cv/CvStatusBadge.tsx'
import { updateCompanyNotes } from '../companies/api.ts'
import NotesEditor from '../notes/NotesEditor.tsx'
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
  nextRoundLabel,
  notifyApplicationsChanged,
  roundLabel,
  serverDate,
  toLocalInput,
} from './api.ts'
import InterviewProgress from './InterviewProgress.tsx'
import StatusBadge from './StatusBadge.tsx'
import { AcceptOfferButton, DeclineOfferButton } from './OfferActions.tsx'
import { pageHref } from '../shell/nav.ts'

type Props = {
  application: Application
  statuses: ApplicationStatus[]
  onChange: (application: Application) => void
  /** The offer was accepted (the application is now `ACCEPTED`). */
  onAccepted: (application: Application) => void
  onDelete: (id: number) => void
  /** Opens the generation breakdown of the attached CV. */
  onShowPipeline?: (cv: GeneratedCv) => void
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

function EventRow({
  application,
  event,
  statuses,
  onChange,
}: {
  application: Application
  event: ApplicationEvent
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

  if (editing) {
    return (
      <li className="app-event editing">
        <div className="app-form-row">
          {statusLocked ? (
            <StatusBadge status={event.status} auto={isAutoEvent(event)} />
          ) : (
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
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
        <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note for this state" rows={3} />
        <div className="app-buttons">
          <button type="button" className="small" onClick={save} disabled={busy || !!dateError}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button type="button" className="secondary small" onClick={() => setEditing(false)} disabled={busy}>
            Cancel
          </button>
        </div>
        {(dateError || error) && <p className="error">{dateError || error}</p>}
      </li>
    )
  }

  return (
    <li className="app-event">
      <div className="app-event-head">
        <StatusBadge status={event.status} auto={isAutoEvent(event)} />
        {event.title && <strong className="app-round-title">{event.title}</strong>}
        {event.duration_minutes && <span className="muted">{formatDuration(event.duration_minutes)}</span>}
        <span className="muted">{serverDate(event.occurred_at).toLocaleString()}</span>
        <span className="app-buttons">
          <button type="button" className="secondary small" onClick={startEdit} disabled={busy}>
            Edit
          </button>
          {!locked && (
            <button type="button" className="secondary small danger" onClick={remove} disabled={busy}>
              {isHeldRound ? 'Not held' : 'Remove'}
            </button>
          )}
        </span>
      </div>
      {event.note && <p className="app-note">{event.note}</p>}
      {error && <p className="error">{error}</p>}
    </li>
  )
}

/** A planned interview round: dashed, edited inline (each field saves when it is left;
 * the parent remounts it when the stored values change). */
function PlannedEventRow({
  application,
  event,
  index,
  onChange,
}: {
  application: Application
  event: PlannedRound
  /** Position among all rounds (0-based). */
  index: number
  onChange: (application: Application) => void
}) {
  const [title, setTitle] = useState(event.title)
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
    if (title.trim() !== event.title) void save({ title: title.trim() })
  }
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
    <li className={`app-event planned${final ? ' not-held' : ''}`}>
      <div className="app-event-head">
        <span className="app-round-label">
          Round {index + 1} · {final ? 'not held' : 'planned'}
        </span>
        <span className="app-buttons">
          {!final && (
            <button type="button" className="secondary small" onClick={() => save({ planned: false })} disabled={busy}>
              Mark held
            </button>
          )}
          <button type="button" className="secondary small danger" onClick={remove} disabled={busy}>
            Remove round
          </button>
        </span>
      </div>
      <div className="app-form-row app-round-fields">
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={saveTitle}
          onKeyDown={(e) => e.key === 'Enter' && saveTitle()}
          list={ROUND_TYPES_ID}
          placeholder="Kind of round (e.g. Technical)"
          aria-label={`Round ${index + 1}: kind`}
          maxLength={128}
          disabled={busy}
        />
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
        rows={1}
        disabled={busy}
      />
      {(dateError || error) && <p className="error">{dateError || error}</p>}
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
      <div className="app-form-row">
        <span>Interview rounds</span>
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
        <InterviewProgress application={application} />
        {application.planned_events.length > 0 && (
          <button
            type="button"
            className="secondary small"
            onClick={() => window.confirm('Remove every planned round?') && set(0)}
            disabled={busy}
          >
            Clear plan
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  )
}

function AddEventForm({
  application,
  statuses,
  onChange,
}: {
  application: Application
  statuses: ApplicationStatus[]
  onChange: (application: Application) => void
}) {
  const [status, setStatus] = useState('')
  const [note, setNote] = useState('')
  const [when, setWhen] = useState('')
  const { busy, error, run } = useAction()
  const options = pickableStatuses(statuses, application.status?.key ?? null)
  const selected = status || options[0]?.key || ''
  const nextRound = selected === INTERVIEW_STATUS ? nextRoundLabel(application) : undefined
  const min = earliestFor(application, selected)
  const dateError = tooEarly(when, min)

  const add = async () => {
    const updated = await run(() =>
      applicationsApi.addEvent(application.id, { status: selected, note, occurred_at: fromLocalInput(when) }),
    )
    if (updated) {
      onChange(updated)
      setNote('')
      setWhen('')
    }
  }

  return (
    <div className="app-add-event">
      <div className="app-form-row">
        <select value={selected} onChange={(e) => setStatus(e.target.value)} aria-label="New status">
          {options.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
        <input
          type="datetime-local"
          value={when}
          min={min}
          onChange={(e) => setWhen(e.target.value)}
          aria-label="When (defaults to now)"
          title="When (defaults to now)"
        />
        <button type="button" className="small" onClick={add} disabled={busy || !selected || !!dateError}>
          {busy
            ? 'Adding…'
            : nextRound
              ? `Record ${nextRound}`
              : 'Add status'}
        </button>
      </div>
      <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note for this state (optional)" rows={2} />
      {(dateError || error) && <p className="error">{dateError || error}</p>}
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

export default function ApplicationDetail({
  application,
  statuses,
  onChange,
  onAccepted,
  onDelete,
  onShowPipeline,
}: Props) {
  const [notesTab, setNotesTab] = useState<'application' | 'company'>('application')
  const cvAction = useAction()
  const deleteAction = useAction()
  const cv = application.cv
  const heldCount = heldRounds(application).length
  const { company, company_id: companyId, company_notes: companyNotes } = application.job

  const saveNotes = async (notes: string) => {
    onChange(await applicationsApi.updateNotes(application.id, notes))
  }

  const saveCompanyNotes = async (notes: string) => {
    if (companyId == null) return
    const updated = await updateCompanyNotes(companyId, notes)
    onChange({ ...application, job: { ...application.job, company_notes: updated.notes } })
    // Other applications to the same company show these notes too.
    notifyApplicationsChanged()
  }

  const tab = (key: 'application' | 'company', label: string, hasNotes: boolean, disabled = false) => (
    <button
      type="button"
      role="tab"
      aria-selected={notesTab === key}
      disabled={disabled}
      title={disabled ? 'The job has no resolved company' : undefined}
      onClick={() => setNotesTab(key)}
    >
      {label}
      {hasNotes && <span className="notes-dot" aria-label="(has notes)" />}
    </button>
  )

  const regenerate = async () => {
    const updated = await cvAction.run(() => applicationsApi.regenerateCv(application.id))
    if (updated) onChange(updated)
  }

  const remove = async () => {
    if (!window.confirm('Delete this application and its status history? The generated CV is kept.')) return
    const ok = await deleteAction.run(() => applicationsApi.remove(application.id).then(() => true))
    if (ok) onDelete(application.id)
  }

  return (
    <div className="app-detail">
      <dl className="job-facts">
        <dt>Link</dt>
        <dd>
          <a href={application.job.link} target="_blank" rel="noreferrer">
            {application.job.link}
          </a>
        </dd>
      </dl>

      <section className="app-section">
        <h3>CV</h3>
        {cv ? (
          <div className="cv-head">
            <div className="cv-main">
              <div className="cv-meta">
                <span>#{cv.id}</span>
                {cv.headline_role && <span>{cv.headline_role}</span>}
              </div>
              {cv.status === 'failed' && cv.error && <pre className="error cv-inline-error">{cv.error}</pre>}
            </div>
            {cv.status === 'finished'
              ? <CvActions cv={cv} />
              : <CvStatusBadge status={cv.status} />}
          </div>
        ) : (
          <p className="muted">No CV attached.</p>
        )}
        {(!cv || !isInProgress(cv)) && (
          <div className="app-buttons">
            {cv?.status === 'finished' && onShowPipeline && (
              <button type="button" className="secondary small" onClick={() => onShowPipeline(cv)}>
                How it was generated
              </button>
            )}
            <button type="button" className="secondary small" onClick={regenerate} disabled={cvAction.busy}>
              {cvAction.busy ? 'Requesting…' : cv ? 'Generate again' : 'Generate CV'}
            </button>
          </div>
        )}
        {cvAction.error && <p className="error">{cvAction.error}</p>}
      </section>

      <section className="app-section">
        <h3>Status history</h3>
        <InterviewPlan
          key={heldCount + application.planned_events.length}
          application={application}
          onChange={onChange}
        />
        <datalist id={ROUND_TYPES_ID}>
          {ROUND_TYPES.map((t) => (
            <option key={t} value={t} />
          ))}
        </datalist>
        {historyEvents(application).length === 0 && application.planned_events.length === 0 ? (
          <p className="muted">No status recorded yet.</p>
        ) : (
          <ol className="app-events">
            {historyEvents(application).map((event) => (
              <EventRow
                key={`${event.id}:${event.occurred_at}:${event.note}:${event.status.key}:${event.title}:${event.duration_minutes}`}
                application={application}
                event={event}
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
                index={heldCount + i}
                onChange={onChange}
              />
            ))}
          </ol>
        )}
        {application.status?.key === OFFER_STATUS ? (
          <OfferBox
            key={application.start_date ?? ''}
            application={application}
            onChange={onChange}
            onAccepted={onAccepted}
          />
        ) : application.status?.key === ACCEPTED_STATUS ? (
          <p className="app-accepted">
            <span>
              Offer accepted{application.start_date ? `, starting ${formatDay(application.start_date)}` : ''}.
            </span>
            {application.work_history_id != null ? (
              <a href={pageHref('work-history', application.work_history_id)}>View in My Career</a>
            ) : (
              <span className="muted">Its My Career entry was deleted.</span>
            )}
          </p>
        ) : application.status?.key === DECLINED_STATUS ? (
          <p className="app-declined">
            <strong>Offer declined.</strong> Remove the “Declined” state to reopen the offer.
          </p>
        ) : isFinalStatus(application.status) ? (
          <p className="muted">{application.status?.label} is final — remove that state to record new ones.</p>
        ) : (
          <AddEventForm application={application} statuses={statuses} onChange={onChange} />
        )}
      </section>

      <section className="app-section">
        <h3>Notes</h3>
        <div className="notes-switch" role="tablist" aria-label="Notes">
          {tab('application', 'Application', !!application.notes)}
          {tab('company', company ? `Company: ${company}` : 'Company', !!companyNotes, companyId == null)}
        </div>
        {/* Both stay mounted so switching tabs keeps unsaved drafts. */}
        <div hidden={notesTab !== 'application'}>
          <NotesEditor
            label="Application notes"
            value={application.notes}
            placeholder="Notes about this application"
            onSave={saveNotes}
          />
        </div>
        {companyId != null && (
          <div hidden={notesTab !== 'company'}>
            <NotesEditor
              label="Company notes"
              value={companyNotes ?? ''}
              placeholder="Notes about this company (shared by all its applications)"
              onSave={saveCompanyNotes}
            />
          </div>
        )}
      </section>

      <div className="app-buttons app-danger-zone">
        <button type="button" className="secondary small danger" onClick={remove} disabled={deleteAction.busy}>
          {deleteAction.busy ? 'Deleting…' : 'Delete application'}
        </button>
        {deleteAction.error && <span className="error">{deleteAction.error}</span>}
      </div>
    </div>
  )
}
