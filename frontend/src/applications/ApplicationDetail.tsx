import { useState } from 'react'
import { describeError, isInProgress } from '../cv/api.ts'
import CvActions from '../cv/CvActions.tsx'
import CvStatusBadge from '../cv/CvStatusBadge.tsx'
import { updateCompanyNotes } from '../companies/api.ts'
import NotesEditor from '../notes/NotesEditor.tsx'
import {
  type Application,
  type ApplicationEvent,
  type ApplicationStatus,
  applicationsApi,
  fromLocalInput,
  notifyApplicationsChanged,
  serverDate,
  toLocalInput,
} from './api.ts'
import StatusBadge from './StatusBadge.tsx'

type Props = {
  application: Application
  statuses: ApplicationStatus[]
  onChange: (application: Application) => void
  onDelete: (id: number) => void
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
  const [when, setWhen] = useState(toLocalInput(event.occurred_at))
  const { busy, error, run } = useAction()

  const startEdit = () => {
    setStatus(event.status.key)
    setNote(event.note)
    setWhen(toLocalInput(event.occurred_at))
    setEditing(true)
  }

  const save = async () => {
    const updated = await run(() =>
      applicationsApi.updateEvent(application.id, event.id, { status, note, occurred_at: fromLocalInput(when) }),
    )
    if (updated) {
      onChange(updated)
      setEditing(false)
    }
  }

  const remove = async () => {
    if (!window.confirm(`Remove the "${event.status.label}" state?`)) return
    const updated = await run(() => applicationsApi.removeEvent(application.id, event.id))
    if (updated) onChange(updated)
  }

  if (editing) {
    return (
      <li className="app-event editing">
        <div className="app-form-row">
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {statuses.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
          <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
        </div>
        <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note for this state" rows={3} />
        <div className="app-buttons">
          <button type="button" className="small" onClick={save} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button type="button" className="secondary small" onClick={() => setEditing(false)} disabled={busy}>
            Cancel
          </button>
        </div>
        {error && <p className="error">{error}</p>}
      </li>
    )
  }

  return (
    <li className="app-event">
      <div className="app-event-head">
        <StatusBadge status={event.status} />
        <span className="muted">{serverDate(event.occurred_at).toLocaleString()}</span>
        <span className="app-buttons">
          <button type="button" className="secondary small" onClick={startEdit} disabled={busy}>
            Edit
          </button>
          <button type="button" className="secondary small danger" onClick={remove} disabled={busy}>
            Remove
          </button>
        </span>
      </div>
      {event.note && <p className="app-note">{event.note}</p>}
      {error && <p className="error">{error}</p>}
    </li>
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
  const selected = status || statuses[0]?.key || ''

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
          {statuses.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
        <input
          type="datetime-local"
          value={when}
          onChange={(e) => setWhen(e.target.value)}
          aria-label="When (defaults to now)"
          title="When (defaults to now)"
        />
        <button type="button" className="small" onClick={add} disabled={busy || !selected}>
          {busy ? 'Adding…' : 'Add status'}
        </button>
      </div>
      <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note for this state (optional)" rows={2} />
      {error && <p className="error">{error}</p>}
    </div>
  )
}

export default function ApplicationDetail({ application, statuses, onChange, onDelete }: Props) {
  const [notesTab, setNotesTab] = useState<'application' | 'company'>('application')
  const cvAction = useAction()
  const deleteAction = useAction()
  const cv = application.cv
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
        <dt>Created</dt>
        <dd>{serverDate(application.created_at).toLocaleString()}</dd>
      </dl>

      <section className="app-section">
        <h3>CV</h3>
        {cv ? (
          <div className="cv-head">
            <div className="cv-main">
              <div className="cv-meta">
                <CvStatusBadge status={cv.status} />
                <span>#{cv.id}</span>
                {cv.headline_role && <span>{cv.headline_role}</span>}
              </div>
              {cv.status === 'failed' && cv.error && <pre className="error cv-inline-error">{cv.error}</pre>}
            </div>
            <CvActions cv={cv} />
          </div>
        ) : (
          <p className="muted">No CV attached.</p>
        )}
        {(!cv || !isInProgress(cv)) && (
          <div className="app-buttons">
            <button type="button" className="secondary small" onClick={regenerate} disabled={cvAction.busy}>
              {cvAction.busy ? 'Requesting…' : cv ? 'Generate again' : 'Generate CV'}
            </button>
          </div>
        )}
        {cvAction.error && <p className="error">{cvAction.error}</p>}
      </section>

      <section className="app-section">
        <h3>Status history</h3>
        {application.events.length === 0 ? (
          <p className="muted">No status recorded yet.</p>
        ) : (
          <ol className="app-events">
            {application.events.map((event) => (
              <EventRow
                key={`${event.id}:${event.occurred_at}:${event.note}:${event.status.key}`}
                application={application}
                event={event}
                statuses={statuses}
                onChange={onChange}
              />
            ))}
          </ol>
        )}
        <AddEventForm application={application} statuses={statuses} onChange={onChange} />
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
