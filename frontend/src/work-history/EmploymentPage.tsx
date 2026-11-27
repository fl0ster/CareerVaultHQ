import { BellRing, ChevronRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import '../interviews/interviews.css'
import '../companies/tags.css'
import CompanyDialog from '../companies/CompanyDialog.tsx'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import type { Crumb } from '../shell/nav.ts'
import { useDetailScroll } from '../shell/useDetailScroll.ts'
import './work-history.css'
import {
  daysAgo,
  journalApi,
  type JournalNote,
  WORK_HISTORY_CHANGED,
  type WorkHistoryEntry,
  workHistoryApi,
} from './api.ts'
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

  return (
    <>
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
                    <span className="muted">Since {since(e.date_start)}</span>
                  </div>
                </div>
                <div className="iv-card-head-actions">
                  <button type="button" className="secondary iv-card-details" onClick={() => onOpen(e.id)}>
                    Open journal
                    {e.journal_count > 0 && <span className="muted">({e.journal_count})</span>}
                    <ChevronRight size={16} aria-hidden="true" />
                  </button>
                </div>
              </header>
              <div className="iv-card-body">
                <div className="iv-card-side">
                  {e.journal_overdue && (
                    <span className="employment-journal-due" title="No journal note for a week or more">
                      <BellRing size={14} aria-hidden="true" />
                      {e.last_journal_on ? (
                        <span>
                          Last entry{' '}
                          <time
                            dateTime={e.last_journal_on}
                            title={new Date(`${e.last_journal_on}T00:00:00`).toLocaleDateString(undefined, {
                              dateStyle: 'full',
                            })}
                          >
                            {daysAgo(e.last_journal_on)}
                          </time>
                        </span>
                      ) : (
                        <span>No journal entries yet</span>
                      )}
                    </span>
                  )}
                  <JournalTimeline role={e} />
                </div>
                <JournalComposer role={e} compact />
              </div>
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

/** The latest notes of a position, newest first, as a timeline down the card's left column;
 * it follows the composer's height and fades out where it is cut off. */
function JournalTimeline({ role }: { role: WorkHistoryEntry }) {
  const [notes, setNotes] = useState<JournalNote[] | null>(null)

  useEffect(() => {
    let live = true
    const load = () =>
      journalApi
        .get(role.id)
        .then((j) => live && setNotes(j.entries.slice(0, 8)))
        .catch(() => live && setNotes([]))
    load()
    window.addEventListener(WORK_HISTORY_CHANGED, load)
    return () => {
      live = false
      window.removeEventListener(WORK_HISTORY_CHANGED, load)
    }
  }, [role.id])

  if (!notes) return null
  if (notes.length === 0) return <p className="muted employment-log-empty">Nothing logged yet.</p>
  return (
    <div className="employment-log-wrap">
      <ol className="employment-log" aria-label={`Latest journal notes for ${role.role}`}>
        {notes.map((n) => (
          <li key={n.id} className="employment-log-item">
            <time
              className="employment-log-when"
              dateTime={n.logged_on}
              title={new Date(`${n.logged_on}T00:00:00`).toLocaleDateString(undefined, { dateStyle: 'full' })}
            >
              {daysAgo(n.logged_on)}
            </time>
            <span className="employment-log-body">{n.body}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}
