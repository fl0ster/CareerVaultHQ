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
import ApplicationDetail from './ApplicationDetail.tsx'
import StatusBadge from './StatusBadge.tsx'

const PAGE_SIZE = 200
const CV_POLL_MS = 3000

export default function ApplicationsPage() {
  const [applications, setApplications] = useState<Application[] | null>(null)
  const [total, setTotal] = useState(0)
  const [statuses, setStatuses] = useState<ApplicationStatus[]>([])
  const [filter, setFilter] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)
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
  const pending = applications?.some((a) => a.cv && isInProgress(a.cv)) ?? false
  useEffect(() => {
    if (!pending) return
    const timer = window.setTimeout(reload, CV_POLL_MS)
    return () => window.clearTimeout(timer)
  }, [pending, tick, reload])

  const replace = (updated: Application) => {
    setApplications((prev) => prev?.map((a) => (a.id === updated.id ? updated : a)) ?? prev)
    // The current status may have changed; the filtered list may no longer contain it.
    if (filter) reload()
  }

  const removed = (id: number) => {
    setApplications((prev) => prev?.filter((a) => a.id !== id) ?? prev)
    setTotal((t) => t - 1)
    setExpanded(null)
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
        {applications?.map((a) => {
          const open = expanded === a.id
          return (
            <li key={a.id} className={open ? 'app-item open' : 'app-item'}>
              <button
                type="button"
                className="app-row"
                aria-expanded={open}
                onClick={() => setExpanded(open ? null : a.id)}
              >
                <div className="job-main">
                  <span className="job-title">{a.job.title ?? a.job.link}</span>
                  <div className="job-meta">
                    {a.job.company && <span className="job-company">{a.job.company}</span>}
                    <span>{a.job.source}</span>
                    <span>
                      {a.status
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
              {open && (
                <ApplicationDetail
                  key={a.id}
                  application={a}
                  statuses={statuses}
                  onChange={replace}
                  onDelete={removed}
                />
              )}
            </li>
          )
        })}
      </ul>
    </>
  )
}
