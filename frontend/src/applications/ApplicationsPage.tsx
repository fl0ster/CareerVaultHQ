import { useCallback, useEffect, useState } from 'react'
import './applications.css'
import '../cv/cv.css'
import '../jobs/jobs.css'
import { describeError, isInProgress } from '../cv/api.ts'
import CvStatusBadge from '../cv/CvStatusBadge.tsx'
import {
  APPLICATIONS_CHANGED,
  type Application,
  type ApplicationStatus,
  applicationsApi,
  notifyApplicationsChanged,
  serverDate,
} from './api.ts'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import '../companies/tags.css'
import ApplicationDialog from './ApplicationDialog.tsx'
import StatusBadge from './StatusBadge.tsx'

const PAGE_SIZE = 200
const CV_POLL_MS = 3000

export default function ApplicationsPage() {
  const [applications, setApplications] = useState<Application[] | null>(null)
  const [total, setTotal] = useState(0)
  const [statuses, setStatuses] = useState<ApplicationStatus[]>([])
  const [filter, setFilter] = useState('')
  // Kept as an object (not just an id) so the dialog stays open even if a status change
  // drops the application out of the filtered list.
  const [selected, setSelected] = useState<Application | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  const reload = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    applicationsApi
      .statuses(controller.signal)
      .then(setStatuses)
      .catch((e) => {
        if (!controller.signal.aborted) setError(`Could not load statuses: ${describeError(e)}`)
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    applicationsApi
      .list({ limit: PAGE_SIZE, status: filter || undefined }, controller.signal)
      .then((page) => {
        setApplications(page.items)
        setTotal(page.total)
        setSelected((prev) => (prev && page.items.find((a) => a.id === prev.id)) ?? prev)
        setError(null)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(`Could not load applications: ${describeError(e)}`)
      })
    return () => controller.abort()
  }, [filter, tick])

  // Applications created or changed elsewhere (e.g. from the job dialog).
  useEffect(() => {
    window.addEventListener(APPLICATIONS_CHANGED, reload)
    return () => window.removeEventListener(APPLICATIONS_CHANGED, reload)
  }, [reload])

  // Keep polling while a CV is being generated.
  const pending =
    (applications?.some((a) => a.cv && isInProgress(a.cv)) ?? false) ||
    (selected?.cv != null && isInProgress(selected.cv))
  useEffect(() => {
    if (!pending) return
    const timer = window.setTimeout(reload, CV_POLL_MS)
    return () => window.clearTimeout(timer)
  }, [pending, tick, reload])

  const replace = (updated: Application) => {
    setSelected((prev) => (prev?.id === updated.id ? updated : prev))
    setApplications((prev) => prev?.map((a) => (a.id === updated.id ? updated : a)) ?? prev)
    // The current status may have changed; the filtered list may no longer contain it.
    if (filter) reload()
  }

  const removed = (id: number) => {
    setApplications((prev) => prev?.filter((a) => a.id !== id) ?? prev)
    setTotal((t) => t - 1)
    setSelected(null)
    notifyApplicationsChanged()
  }

  const counts = new Map<string, number>()
  for (const a of applications ?? []) {
    const key = a.status?.key ?? ''
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }

  return (
    <>
      <h1 className="title">Applications</h1>
      <p>
        {applications === null ? 'Loading…' : `${total} application${total === 1 ? '' : 's'}${filter ? ' with this status' : ''}.`}{' '}
        <button type="button" className="secondary small" onClick={reload}>
          Refresh
        </button>
      </p>

      <div className="jobs-controls">
        <label>
          Status{' '}
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All</option>
            {statuses.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
                {!filter && counts.has(s.key) ? ` (${counts.get(s.key)})` : ''}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="error">{error}</p>}

      {applications !== null && applications.length === 0 && (
        <p className="muted">
          {filter
            ? 'No applications with this status.'
            : 'No applications yet. Open a job on the Jobs tab and choose "Create application".'}
        </p>
      )}

      <ul className="app-list">
        {applications?.map((a) => (
          <li key={a.id} className={selected?.id === a.id ? 'app-item selected' : 'app-item'}>
            <button type="button" className="app-row" aria-haspopup="dialog" onClick={() => setSelected(a)}>
              <div className="job-main">
                <span className="job-title">{a.job.title ?? a.job.link}</span>
                <div className="job-meta">
                  {a.job.company && (
                    <span className="job-company">
                      {a.job.company} <CompanyTagBadge companyId={a.job.company_id} tag={a.job.company_tag} />
                    </span>
                  )}
                  <span>{a.job.source}</span>
                  <span>
                    {a.status && a.events.length > 0
                      ? `since ${serverDate(a.events[a.events.length - 1].occurred_at).toLocaleDateString()}`
                      : `created ${serverDate(a.created_at).toLocaleDateString()}`}
                  </span>
                </div>
              </div>
              <div className="app-badges">
                <StatusBadge status={a.status} />
                {a.cv && <CvStatusBadge status={a.cv.status} />}
              </div>
            </button>
          </li>
        ))}
      </ul>

      {selected && (
        <ApplicationDialog
          key={selected.id}
          application={selected}
          statuses={statuses}
          onChange={replace}
          onDelete={removed}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  )
}
