import { useEffect, useState } from 'react'
import './work-history.css'
import { WORK_HISTORY_CHANGED, type WorkHistoryEntry, workHistoryApi } from './api.ts'

/** A position held now: started, with no end date. */
const isCurrentPosition = (e: WorkHistoryEntry) => e.kind === 'job' && e.date_end === null && !e.pending

const since = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: 'short', year: 'numeric' })

/** The positions currently held, each opening its entry in My Career. */
export default function EmploymentPage({ onOpen }: { onOpen: (id: number) => void }) {
  const [entries, setEntries] = useState<WorkHistoryEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = () =>
      workHistoryApi
        .list()
        .then((all) => setEntries(all.filter(isCurrentPosition)))
        .catch((e: Error) => setError(e.message))
    load()
    window.addEventListener(WORK_HISTORY_CHANGED, load)
    return () => window.removeEventListener(WORK_HISTORY_CHANGED, load)
  }, [])

  if (error) return <p className="muted">Could not load your employment: {error}</p>
  if (!entries) return <p className="muted">Loading…</p>
  if (entries.length === 0) return <p className="muted">No current positions.</p>

  return (
    <ul className="employment-list">
      {entries.map((e) => (
        <li key={e.id}>
          <button type="button" className="card employment-card" onClick={() => onOpen(e.id)}>
            <strong>{e.role}</strong>
            <span>{e.employer}</span>
            <span className="muted">
              Since {since(e.date_start)}
              {e.location ? ` · ${e.location}` : ''}
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
