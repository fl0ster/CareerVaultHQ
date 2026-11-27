import { BellRing, BookOpen, Clock } from 'lucide-react'
import { useEffect, useState } from 'react'
import '../interviews/interviews.css'
import '../companies/tags.css'
import CompanyDialog from '../companies/CompanyDialog.tsx'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import type { Crumb } from '../shell/nav.ts'
import { useDetailScroll } from '../shell/useDetailScroll.ts'
import './work-history.css'
import { daysAgo, WORK_HISTORY_CHANGED, type WorkHistoryEntry, workHistoryApi } from './api.ts'
import JournalComposer from './JournalComposer.tsx'
import JournalView from './JournalView.tsx'
import EmptyState from '../mascot/EmptyState.tsx'

/** A position held now: started, with no end date. */
const isCurrentPosition = (e: WorkHistoryEntry) => e.kind === 'job' && e.date_end === null && !e.pending

const since = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, {
    month: 'short',
    year: 'numeric',
  })

const label = (e: WorkHistoryEntry) => (e.employer ? `${e.role} at ${e.employer}` : e.role)

/** "Last entry 3 days ago" / "No journal entries yet", tinted when a week has passed. */
function JournalStatus({ entry }: { entry: WorkHistoryEntry }) {
  return (
    <p className={`employment-journal-status${entry.journal_overdue ? ' overdue' : ''}`}>
      <Clock size={13} aria-hidden="true" />
      {entry.last_journal_on ? (
        <span>
          Last journal entry{' '}
          <time
            dateTime={entry.last_journal_on}
            title={new Date(`${entry.last_journal_on}T00:00:00`).toLocaleDateString(undefined, { dateStyle: 'full' })}
          >
            {daysAgo(entry.last_journal_on)}
          </time>
        </span>
      ) : (
        <span>No journal entries yet</span>
      )}
    </p>
  )
}

type Props = {
  /** The position whose journal is open (`#/employment/<id>`). */
  detailId?: string | null
  onOpen: (id: number) => void
  onBack: () => void
  onCrumbsChange: (crumbs: Crumb[]) => void
}

/** The positions currently held, one card each (styled like the interview cards), each with
 * its work journal: a box to log a note, and the full journal one click away. */
export default function EmploymentPage({ detailId = null, onOpen, onBack, onCrumbsChange }: Props) {
  const [entries, setEntries] = useState<WorkHistoryEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Company popup: its tag and application stats.
  const [companyId, setCompanyId] = useState<number | null>(null)
  const openId = detailId != null ? Number(detailId) : null
  const open = openId != null ? entries?.find((e) => e.id === openId && e.kind === 'job') : undefined
  useDetailScroll(openId != null)

  useEffect(() => {
    const load = () =>
      workHistoryApi
        .list()
        .then(setEntries)
        .catch((e: Error) => setError(e.message))
    load()
    window.addEventListener(WORK_HISTORY_CHANGED, load)
    return () => window.removeEventListener(WORK_HISTORY_CHANGED, load)
  }, [])

  const crumb = open?.role
  useEffect(() => {
    onCrumbsChange(crumb ? [{ label: crumb, heading: `${crumb} · journal` }] : [])
  }, [crumb, onCrumbsChange])
  useEffect(() => () => onCrumbsChange([]), [onCrumbsChange])

  if (error) return <p className="muted">Could not load your employment: {error}</p>
  if (!entries) return <p className="muted">Loading…</p>

  if (openId != null) {
    if (open) return <JournalView key={open.id} role={open} onBack={onBack} />
    return (
      <p className="muted">
        This position no longer exists.{' '}
        <button type="button" className="secondary small" onClick={onBack}>
          Back to employment
        </button>
      </p>
    )
  }

  const current = entries.filter(isCurrentPosition)
  if (current.length === 0) return <EmptyState>No current positions.</EmptyState>
  const overdue = current.filter((e) => e.journal_overdue)

  return (
    <>
      {overdue.length > 0 && (
        <div className="employment-journal-alert" role="status">
          <BellRing size={16} aria-hidden="true" />
          <p>
            {overdue.length === 1 ? (
              <>
                No journal entry for a week or more at <strong>{label(overdue[0])}</strong>.
              </>
            ) : (
              <>
                No journal entry for a week or more at {overdue.length} positions:{' '}
                {overdue.map((e, i) => (
                  <span key={e.id}>
                    {i > 0 && ', '}
                    <strong>{label(e)}</strong>
                  </span>
                ))}
                .
              </>
            )}{' '}
            A few lines on what you did keep your career log and CVs accurate.
          </p>
        </div>
      )}
      <ul className="iv-grid">
        {current.map((e) => (
          <li key={e.id}>
            <article className={`iv-card employment-card${e.journal_overdue ? ' overdue' : ''}`}>
              <header className="iv-card-head">
                <div className="iv-card-title">
                  <h3 className="employment-role">{e.role}</h3>
                  <div className="iv-card-meta">
                    {e.company_id != null ? (
                      <CompanyTagBadge
                        companyId={e.company_id}
                        tag={e.company_tag}
                        name={e.employer}
                        onOpenCompany={setCompanyId}
                      />
                    ) : (
                      <span>{e.employer}</span>
                    )}
                    {e.location && <span className="muted">{e.location}</span>}
                  </div>
                </div>
                {e.journal_overdue && (
                  <span className="employment-journal-due" title="No journal note for a week or more">
                    <BellRing size={14} aria-hidden="true" /> Journal update due
                  </span>
                )}
              </header>
              <p className="muted employment-since">Since {since(e.date_start)}</p>
              <JournalStatus entry={e} />
              <JournalComposer role={e} compact />
              <button type="button" className="secondary small employment-journal-open" onClick={() => onOpen(e.id)}>
                <BookOpen size={14} aria-hidden="true" /> Open journal
                {e.journal_count > 0 && <span className="muted"> ({e.journal_count})</span>}
              </button>
            </article>
          </li>
        ))}
      </ul>
      {companyId != null && (
        <CompanyDialog key={companyId} companyId={companyId} onClose={() => setCompanyId(null)} />
      )}
    </>
  )
}
