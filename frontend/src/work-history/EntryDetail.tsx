import { ArrowLeft, ChevronLeft, ChevronRight, Pencil, Trash2, TrendingUp } from 'lucide-react'
import { useEffect, useState } from 'react'
import '../jobs/jobs.css'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import { formatDay } from '../applications/api.ts'
import type { WorkHistoryEntry, WorkHistoryInput } from './api.ts'
import ApplicationSteps from './ApplicationSteps.tsx'
import { nextRoleDraft } from './draft.ts'
import { isPoint, KINDS } from './kinds.ts'
import { linkedTransition, TRANSITIONS } from './tenure.ts'
import { type Bar, formatDuration, monthIndex, todayIndex } from './timeline-model.ts'
import WorkHistoryForm from './WorkHistoryForm.tsx'

function formatMonth(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { year: 'numeric', month: 'short' })
}

/** The organisation of an entry: a position's employer as the company pill (tag picker, stats,
 * and the name opens the company popup); an institution or issuer as text. */
export function Organisation({
  entry,
  onOpenCompany,
}: {
  entry: WorkHistoryEntry
  onOpenCompany: (companyId: number) => void
}) {
  if (!entry.employer) return null
  if (entry.kind !== 'job') return <span className="wh-org">{entry.employer}</span>
  if (entry.company_id != null) {
    return (
      <span className="wh-org">
        <CompanyTagBadge
          companyId={entry.company_id}
          tag={entry.company_tag}
          name={entry.employer}
          onOpenCompany={onOpenCompany}
        />
      </span>
    )
  }
  return (
    <span className="wh-org">
      <span className="badge company-tag none wh-org-plain" title="Not among the known companies">
        {entry.employer}
      </span>
    </span>
  )
}

/** "Mar 2021 – present · 3 yrs 2 mos", "Issued Jun 2020", "Starts 1 Jan 2027". */
export function EntryPeriod({ entry, bar }: { entry: WorkHistoryEntry; bar: Bar | undefined }) {
  if (entry.pending) {
    return (
      <span>
        Starts {formatDay(entry.date_start)}
        {entry.date_end ? ` – ${formatMonth(entry.date_end)}` : ''}
      </span>
    )
  }
  if (isPoint(entry)) return <span>Issued {formatMonth(entry.date_start)}</span>
  return (
    <>
      <span>
        {formatMonth(entry.date_start)} – {entry.date_end ? formatMonth(entry.date_end) : 'present'}
      </span>
      {bar && <span>{formatDuration(bar.end - bar.start)}</span>}
    </>
  )
}

/** "Promoted from Software Engineer" on a role that continues `previous` at its employer. */
export function TransitionChip({ entry, previous }: { entry: WorkHistoryEntry; previous: WorkHistoryEntry }) {
  const transition = linkedTransition(entry)
  if (!transition) return null
  const { icon: Icon, from } = TRANSITIONS[transition]
  return (
    <span className={`wh-transition-chip ${transition}`}>
      <Icon size={13} aria-hidden="true" />
      {from} <strong>{previous.role}</strong>
    </span>
  )
}

/** "Jan 2019 – Feb 2022" */
function period(entry: WorkHistoryEntry): string {
  return `${formatMonth(entry.date_start)} – ${entry.date_end ? formatMonth(entry.date_end) : 'present'}`
}

/** Every role held at the employer of the open one (oldest first), each opening its details. */
function Progression({ roles, current, onOpen }: { roles: WorkHistoryEntry[]; current: number; onOpen: (id: number) => void }) {
  const last = roles[roles.length - 1]
  const months =
    (last.date_end ? monthIndex(last.date_end) + 1 : Math.max(todayIndex(), monthIndex(last.date_start) + 1)) -
    monthIndex(roles[0].date_start)
  return (
    <section className="wh-progression" aria-label={`Roles at ${last.employer}`}>
      <h3>
        At {last.employer} <span>· {formatDuration(months)} in {roles.length} roles</span>
      </h3>
      <ol>
        {roles.map((role) => {
          const transition = linkedTransition(role)
          const Step = transition ? TRANSITIONS[transition].icon : null
          return (
            <li key={role.id} className={role.id === current ? 'current' : undefined}>
              {Step && (
                <span className="wh-progression-step" title={TRANSITIONS[transition!].label}>
                  <Step size={12} aria-hidden="true" />
                </span>
              )}
              <button
                type="button"
                onClick={() => onOpen(role.id)}
                aria-current={role.id === current || undefined}
                disabled={role.id === current}
              >
                <strong>{role.role}</strong>
                <small>{period(role)}</small>
              </button>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

export function PrefillStatus({ entry }: { entry: WorkHistoryEntry }) {
  if (entry.prefill_state === 'queued') {
    return (
      <p className="wh-prefill" role="status">
        <span className="spinner" aria-hidden="true" /> Filling in the details from the application…
      </p>
    )
  }
  if (entry.prefill_state === 'failed') {
    return <p className="wh-prefill failed">Could not fill in the details from the application. Edit them by hand.</p>
  }
  return null
}

const editable = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || !!target.closest('.wh-tl'))

type Props = {
  entry: WorkHistoryEntry
  bar: Bar | undefined
  /** The roles held at the entry's employer, oldest first (just the entry when it stands alone). */
  tenure: WorkHistoryEntry[]
  /** The whole career, for the forms. */
  entries: WorkHistoryEntry[]
  /** The neighbouring entries in the list: newer (above) and older (below). */
  newer: WorkHistoryEntry | null
  older: WorkHistoryEntry | null
  onOpen: (id: number) => void
  onOpenCompany: (companyId: number) => void
  onBack: () => void
  onUpdate: (input: WorkHistoryInput) => Promise<void>
  /** Adds the next role at the entry's employer (and opens it). */
  onAddNext: (input: WorkHistoryInput) => Promise<void>
  onDelete: () => void
}

/** The details of one career entry, shown under the timeline in place of the list. */
export default function EntryDetail({
  entry,
  bar,
  tenure,
  entries,
  newer,
  older,
  onOpen,
  onOpenCompany,
  onBack,
  onUpdate,
  onAddNext,
  onDelete,
}: Props) {
  /** Showing the details, editing them, or adding the next role at the employer. */
  const [mode, setMode] = useState<'view' | 'edit' | 'next'>('view')
  const editing = mode !== 'view'
  const setEditing = (on: boolean) => setMode(on ? 'edit' : 'view')
  const { icon: Icon, label: kindLabel } = KINDS[entry.kind]
  const filling = entry.prefill_state === 'queued'
  const previous = tenure.find((role) => role.id === entry.previous_role_id)
  // The next role is added from the latest role at the employer.
  const canAddNext = entry.kind === 'job' && tenure[tenure.length - 1].id === entry.id

  // ← / → step to the older / newer entry (not while typing or on the timeline, which steps itself).
  useEffect(() => {
    if (editing) return
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || editable(e.target)) return
      if (document.querySelector('dialog[open]')) return // e.g. the company popup
      const to = e.key === 'ArrowLeft' ? older : e.key === 'ArrowRight' ? newer : null
      if (!to) return
      e.preventDefault()
      onOpen(to.id)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [editing, newer, older, onOpen])

  return (
    <article className={`detail-view wh-detail kind-${entry.kind}${bar ? ` tone-${bar.tone}` : ''}`} aria-labelledby={`wh-entry-${entry.id}`}>
      <nav className="wh-detail-nav" aria-label="Career entries">
        <button type="button" className="secondary small detail-back" onClick={onBack}>
          <ArrowLeft size={15} aria-hidden="true" /> Back to career
        </button>
        <span className="wh-detail-step">
          <button
            type="button"
            className="secondary small"
            disabled={!older}
            onClick={() => older && onOpen(older.id)}
            title={older ? `Older: ${older.role}` : undefined}
          >
            <ChevronLeft size={15} aria-hidden="true" /> Older
          </button>
          <button
            type="button"
            className="secondary small"
            disabled={!newer}
            onClick={() => newer && onOpen(newer.id)}
            title={newer ? `Newer: ${newer.role}` : undefined}
          >
            Newer <ChevronRight size={15} aria-hidden="true" />
          </button>
        </span>
      </nav>

      <div className="detail-card wh-detail-card">
        {mode === 'edit' ? (
          <WorkHistoryForm
            key={entry.id}
            initial={entry}
            entries={entries}
            onSubmit={async (input) => {
              await onUpdate(input)
              setEditing(false)
            }}
            onCancel={() => setEditing(false)}
          />
        ) : mode === 'next' ? (
          <WorkHistoryForm
            key={`next-${entry.id}`}
            seed={nextRoleDraft(entry)}
            heading={`Next role at ${entry.employer}`}
            entries={entries}
            onSubmit={onAddNext}
            onCancel={() => setMode('view')}
          />
        ) : (
          <>
            <header className="wh-detail-head">
              <div className="wh-detail-title">
                <span className="wh-kind-badge" title={kindLabel}>
                  <Icon size={13} aria-hidden="true" />
                  {kindLabel}
                </span>
                {entry.pending && (
                  <span
                    className="badge wh-pending"
                    title="Not started yet: left out of your CVs and candidate profile until the start date."
                  >
                    Pending
                  </span>
                )}
                <h2 id={`wh-entry-${entry.id}`}>{entry.role}</h2>
                <Organisation entry={entry} onOpenCompany={onOpenCompany} />
              </div>
              <div className="wh-detail-actions">
                {canAddNext && (
                  <button
                    type="button"
                    className="secondary small"
                    onClick={() => setMode('next')}
                    disabled={filling}
                    title={`Promoted or moved to another role at ${entry.employer}? Add it here.`}
                  >
                    <TrendingUp size={14} aria-hidden="true" /> Add next role
                  </button>
                )}
                <button
                  type="button"
                  className="secondary small"
                  onClick={() => setEditing(true)}
                  disabled={filling}
                  title={filling ? 'Available once the details are filled in' : undefined}
                >
                  <Pencil size={14} aria-hidden="true" /> Edit
                </button>
                <button type="button" className="secondary small danger" onClick={onDelete}>
                  <Trash2 size={14} aria-hidden="true" /> Delete
                </button>
              </div>
            </header>

            <div className="wh-meta">
              <EntryPeriod entry={entry} bar={bar} />
              {entry.location && <span>{entry.location}</span>}
              {entry.application_id != null && <span className="wh-origin">From an accepted offer</span>}
              {previous && <TransitionChip entry={entry} previous={previous} />}
            </div>

            <PrefillStatus entry={entry} />

            {tenure.length > 1 && <Progression roles={tenure} current={entry.id} onOpen={onOpen} />}

            {entry.tech.length > 0 && (
              <ul className="job-tech wh-detail-tech" aria-label="Technologies">
                {entry.tech.map((t) => (
                  <li key={t} className="badge job-tech-pill">
                    {t}
                  </li>
                ))}
              </ul>
            )}

            {entry.context ? (
              <section className="wh-detail-section">
                <h3>{KINDS[entry.kind].contextLabel}</h3>
                <p className="wh-detail-context">{entry.context}</p>
              </section>
            ) : (
              !filling && (
                <p className="muted wh-detail-empty">
                  No {KINDS[entry.kind].contextLabel.toLowerCase()} yet.{' '}
                  <button type="button" className="link" onClick={() => setEditing(true)}>
                    Add some
                  </button>
                </p>
              )
            )}

            {entry.application_id != null && <ApplicationSteps applicationId={entry.application_id} />}
          </>
        )}
      </div>
    </article>
  )
}
