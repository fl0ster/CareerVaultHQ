import { ArrowLeft, Check, Pencil, ShieldAlert, ShieldCheck, Sparkles, Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import '../jobs/jobs.css'
import { pageHref } from '../shell/nav.ts'
import {
  type Journal,
  journalApi,
  type JournalMonth,
  type JournalNote,
  WORK_HISTORY_CHANGED,
  type WorkHistoryEntry,
} from './api.ts'
import JournalComposer from './JournalComposer.tsx'

/** How often the view checks on a refresh running on the worker, in ms. */
const POLL_INTERVAL = 2_000

const monthTitle = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })

const dayLabel = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })

const monthOf = (iso: string) => `${iso.slice(0, 7)}-01`

function Pills({ names, label }: { names: string[]; label: string }) {
  if (names.length === 0) return null
  return (
    <ul className="job-tech journal-tech" aria-label={label}>
      {names.map((name) => (
        <li key={name} className="badge job-tech-pill">
          {name}
        </li>
      ))}
    </ul>
  )
}

/** One raw note, editable in place. */
function Note({ roleId, note, onChanged }: { roleId: number; note: JournalNote; onChanged: () => void }) {
  const [editing, setEditing] = useState(false)
  const [body, setBody] = useState(note.body)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      setEditing(false)
      onChanged()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="journal-note">
      <div className="journal-note-head">
        <time dateTime={note.logged_on}>{dayLabel(note.logged_on)}</time>
        {!editing && (
          <span className="journal-note-actions">
            <button
              type="button"
              className="journal-icon-button"
              onClick={() => {
                setBody(note.body)
                setEditing(true)
              }}
              aria-label="Edit note"
              title="Edit"
            >
              <Pencil size={13} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="journal-icon-button danger"
              disabled={busy}
              onClick={() => {
                if (window.confirm('Delete this note? Its month will be summarised again without it.'))
                  void run(() => journalApi.remove(roleId, note.id))
              }}
              aria-label="Delete note"
              title="Delete"
            >
              <Trash2 size={13} aria-hidden="true" />
            </button>
          </span>
        )}
      </div>
      {editing ? (
        <div className="journal-note-edit">
          <textarea rows={3} value={body} onChange={(e) => setBody(e.target.value)} maxLength={10000} />
          <span className="journal-note-actions">
            <button
              type="button"
              className="small"
              disabled={busy || !body.trim() || body.trim() === note.body}
              onClick={() => void run(() => journalApi.update(roleId, note.id, { body: body.trim() }))}
            >
              <Check size={14} aria-hidden="true" /> Save
            </button>
            <button type="button" className="secondary small" disabled={busy} onClick={() => setEditing(false)}>
              <X size={14} aria-hidden="true" /> Cancel
            </button>
          </span>
        </div>
      ) : (
        <p className="journal-note-body">{note.body}</p>
      )}
      {error && <p className="error">{error}</p>}
    </li>
  )
}

/** A month: the polished log on top, the raw notes it was built from below. */
function Month({
  roleId,
  month,
  notes,
  refreshing,
  onChanged,
}: {
  roleId: number
  month: JournalMonth
  notes: JournalNote[]
  refreshing: boolean
  onChanged: () => void
}) {
  return (
    <section className="journal-month" aria-labelledby={`journal-month-${month.month}`}>
      <h3 id={`journal-month-${month.month}`}>{monthTitle(month.month)}</h3>
      <div className="journal-summary">
        {month.summary ? (
          <>
            <p>{month.summary}</p>
            {month.accomplishments.length > 0 && (
              <ul className="journal-accomplishments">
                {month.accomplishments.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
            <Pills names={month.tech} label={`Technologies in ${monthTitle(month.month)}`} />
            {month.stale && !refreshing && <p className="journal-hint muted">Notes changed since this summary.</p>}
          </>
        ) : (
          <p className="muted">{refreshing ? 'Summarising…' : 'Not summarised yet.'}</p>
        )}
      </div>
      <details className="journal-notes" open={!month.summary}>
        <summary>
          Your notes <span className="muted">({notes.length})</span>
        </summary>
        <ul>
          {notes.map((note) => (
            <Note key={note.id} roleId={roleId} note={note} onChanged={onChanged} />
          ))}
        </ul>
      </details>
    </section>
  )
}

/**
 * The work journal of a position: the notes logged on it (kept as written) and the truthful,
 * polished monthly log and description the LLM builds from them. Whatever is out of date is
 * regenerated on the worker when the journal is opened.
 */
export default function JournalView({ role, onBack }: { role: WorkHistoryEntry; onBack: () => void }) {
  const [journal, setJournal] = useState<Journal | null>(null)
  const [error, setError] = useState<string | null>(null)
  const roleId = role.id
  // The worker is regenerating the summaries: the view polls until it is done.
  const refreshing = journal?.refreshing ?? false

  // Reads the journal as stored and, when something is out of date, asks the worker to
  // regenerate it (lazily: on opening and after a change, never from the polling below, so a
  // refresh that leaves things stale is not retried in a loop).
  const load = useCallback(
    () =>
      journalApi
        .get(roleId)
        .then(async (current) => {
          setJournal(current)
          setError(null)
          if (current.stale && !current.refreshing) setJournal(await journalApi.refresh(roleId))
        })
        .catch((err: Error) => setError(err.message)),
    [roleId],
  )

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!refreshing) return
    const timer = window.setTimeout(() => {
      journalApi
        .get(roleId)
        .then((current) => {
          setJournal(current)
          // Done: the role's description and the menu counts may have changed.
          if (!current.refreshing) window.dispatchEvent(new Event(WORK_HISTORY_CHANGED))
        })
        .catch((err: Error) => setError(err.message))
    }, POLL_INTERVAL)
    return () => window.clearTimeout(timer)
  }, [refreshing, journal, roleId])

  const overrides = [journal?.context_overridden && 'description', journal?.tech_overridden && 'technologies'].filter(
    Boolean,
  )
  const notesOf = (month: string) => journal?.entries.filter((n) => monthOf(n.logged_on) === month) ?? []
  const period = `${new Date(`${role.date_start}T00:00:00`).toLocaleDateString(undefined, { month: 'short', year: 'numeric' })} – ${
    role.date_end
      ? new Date(`${role.date_end}T00:00:00`).toLocaleDateString(undefined, { month: 'short', year: 'numeric' })
      : 'present'
  }`

  return (
    <article className="detail-view journal-view" aria-labelledby={`journal-${roleId}`}>
      <button type="button" className="secondary small detail-back" onClick={onBack}>
        <ArrowLeft size={15} aria-hidden="true" /> Back to employment
      </button>

      <div className="detail-card journal-card">
        <header className="journal-head">
          <h2 id={`journal-${roleId}`}>{role.role}</h2>
          <p className="muted">
            {role.employer} · {period}
          </p>
        </header>

        <JournalComposer role={role} onSaved={() => void load()} />

        {error && <p className="error">{error}</p>}
        {refreshing && (
          <p className="journal-progress" role="status">
            <span className="spinner" aria-hidden="true" /> Summarising your notes…
          </p>
        )}
        {journal && journal.warnings.length > 0 && (
          <ul className="journal-warnings" role="status">
            {journal.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}

        {journal?.context_failed && !refreshing && journal.warnings.length === 0 && (
          <p className="journal-hint muted">
            <ShieldAlert size={13} aria-hidden="true" /> The role description built from these notes did not pass the
            truthfulness check{journal.journal_context ? ', so the previous one is kept' : ''}. It will be tried again
            once your notes change.
          </p>
        )}

        {journal && journal.entries.length === 0 && (
          <p className="muted journal-empty">
            No notes yet. Log what you work on as often as you like; each month is turned into a polished, truthful
            career log, and those into this role's description for your CVs.
          </p>
        )}

        {journal && (journal.journal_context || journal.journal_tech.length > 0) && (
          <section className="journal-context" aria-labelledby={`journal-context-${roleId}`}>
            <h3 id={`journal-context-${roleId}`}>
              <Sparkles size={14} aria-hidden="true" /> Role description from your journal
            </h3>
            {journal.journal_context && <p>{journal.journal_context}</p>}
            <Pills names={journal.journal_tech} label="Technologies from your journal" />
            <p className="journal-hint muted">
              <ShieldCheck size={13} aria-hidden="true" /> Built only from your notes and checked against them.{' '}
              {overrides.length > 0 ? (
                <>
                  Overridden by your own {overrides.join(' and ')} in{' '}
                  <a href={pageHref('work-history', roleId)}>My Career</a>; clear it there to use the journal's version.
                </>
              ) : (
                'Used for your CVs and work history while you have not written your own.'
              )}
            </p>
          </section>
        )}

        {journal?.months.map((month) => (
          <Month
            key={month.month}
            roleId={roleId}
            month={month}
            notes={notesOf(month.month)}
            refreshing={refreshing}
            onChanged={() => void load()}
          />
        ))}
      </div>
    </article>
  )
}
