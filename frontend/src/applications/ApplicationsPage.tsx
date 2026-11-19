import { useCallback, useEffect, useState } from 'react'
import './applications.css'
import '../cv/cv.css'
import '../jobs/jobs.css'
import { describeError, isInProgress } from '../cv/api.ts'
import {
  APPLICATIONS_CHANGED,
  type Application,
  type ApplicationStatus,
  applicationsApi,
  notifyApplicationsChanged,
  nextRoundLabel,
  serverDate,
} from './api.ts'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import '../companies/tags.css'
import CompanyDialog from '../companies/CompanyDialog.tsx'
import ApplicationDialog from './ApplicationDialog.tsx'
import InterviewProgress from './InterviewProgress.tsx'
import StatusBadge from './StatusBadge.tsx'
import RelevanceMeter from '../jobs/RelevanceMeter.tsx'

const PAGE_SIZE = 200
const CV_POLL_MS = 3000
const SEARCH_MIN_CHARS = 3
const SEARCH_DEBOUNCE_MS = 300

export default function ApplicationsPage() {
  const [applications, setApplications] = useState<Application[] | null>(null)
  const [statuses, setStatuses] = useState<ApplicationStatus[]>([])
  const [filter, setFilter] = useState('')
  const [searchInput, setSearchInput] = useState('')
  // The term actually sent to the API: debounced, and empty until it has enough characters.
  const [search, setSearch] = useState('')
  // Kept as an object (not just an id) so the dialog stays open even if a status change
  // drops the application out of the filtered list.
  const [selected, setSelected] = useState<Application | null>(null)
  // Company popup; stacks on top of the application popup when opened from it.
  const [companyId, setCompanyId] = useState<number | null>(null)
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
    const term = searchInput.trim()
    const next = term.length >= SEARCH_MIN_CHARS ? term : ''
    const timer = window.setTimeout(() => setSearch(next), next ? SEARCH_DEBOUNCE_MS : 0)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    const controller = new AbortController()
    applicationsApi
      .list({ limit: PAGE_SIZE, status: filter || undefined, q: search || undefined }, controller.signal)
      .then((page) => {
        setApplications(page.items)
        setSelected((prev) => (prev && page.items.find((a) => a.id === prev.id)) ?? prev)
        setError(null)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(`Could not load applications: ${describeError(e)}`)
      })
    return () => controller.abort()
  }, [filter, search, tick])

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
    if (filter || search) reload()
  }

  const removed = (id: number) => {
    setApplications((prev) => prev?.filter((a) => a.id !== id) ?? prev)
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

        <input
          type="search"
          className="app-search"
          placeholder="Search company or title…"
          aria-label="Search applications by company or title"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
      </div>

      {error && <p className="error">{error}</p>}

      {applications !== null && applications.length === 0 && (
        <p className="muted">
          {search
            ? 'No applications match your search.'
            : filter
            ? 'No applications with this status.'
            : 'No applications yet. Open a job on the Jobs tab and choose "Create application".'}
        </p>
      )}

      <ul className="app-list">
        {applications?.map((a) => (
          <li key={a.id} className={selected?.id === a.id ? 'app-item selected' : 'app-item'}>
            <button type="button" className="app-row" aria-haspopup="dialog" onClick={() => setSelected(a)}>
              <div className="job-main">
                {a.evaluation && <RelevanceMeter relevance={a.evaluation.relevance} />}
                <span className="job-title" style={{ marginLeft: '10px' }}>{a.job.title ?? a.job.link}</span>
                <div className="job-meta">
                  {a.job.company && (
                    <span className="job-company">
                      <CompanyTagBadge
                        companyId={a.job.company_id}
                        tag={a.job.company_tag}
                        name={a.job.company}
                        onOpenCompany={setCompanyId}
                      />{' '}
                    </span>
                  )}
                  <span>{a.job.source}</span>
                  <span>
                    {a.status && a.events.length > 0
                      ? `since ${serverDate(a.events[a.events.length - 1].occurred_at).toLocaleDateString()}`
                      : `created ${serverDate(a.created_at).toLocaleDateString()}`}
                  </span>
                  <InterviewProgress application={a} compact />
                </div>
              </div>
              <div className="app-badges">
                <StatusBadge
                  status={a.status}
                  nextRound={nextRoundLabel(a)}
                  statuses={statuses}
                  onSelect={(key) =>
                    applicationsApi
                      .addEvent(a.id, { status: key })
                      .then(replace)
                      .catch((e) => setError(`Could not change status: ${describeError(e)}`))
                  }
                />
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
          onOpenCompany={setCompanyId}
          onClose={() => setSelected(null)}
        />
      )}

      {/* Rendered after the application dialog so it opens on top of it; closing it
          returns to the application dialog. */}
      {companyId != null && (
        <CompanyDialog key={companyId} companyId={companyId} onClose={() => setCompanyId(null)} />
      )}
    </>
  )
}
