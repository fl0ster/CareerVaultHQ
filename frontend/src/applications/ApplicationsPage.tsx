import { useCallback, useEffect, useRef, useState } from 'react'
import './applications.css'
import '../cv/cv.css'
import '../jobs/jobs.css'
import { describeError, isInProgress } from '../cv/api.ts'
import {
  APPLICATIONS_CHANGED,
  type Application,
  type ApplicationStatus,
  INTERVIEW_STATUS,
  applicationsApi,
  currentEvent,
  isAutoEvent,
  notifyApplicationsChanged,
  nextRoundLabel,
} from './api.ts'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import '../companies/tags.css'
import CompanyDialog from '../companies/CompanyDialog.tsx'
import ApplicationView from './ApplicationView.tsx'
import InterviewProgress from './InterviewProgress.tsx'
import StatusBadge from './StatusBadge.tsx'
import Confetti from './Confetti.tsx'
import { OFFER_STATUS } from './useStageCounts.ts'
import RelevanceMeter from '../jobs/RelevanceMeter.tsx'
import type { EvaluatedJobDetail } from '../jobs/api.ts'
import type { Crumb } from '../shell/nav.ts'
import { useDetailScroll } from '../shell/useDetailScroll.ts'
import { useStuck } from '../shell/useStuck.ts'

const PAGE_SIZE = 200
const CV_POLL_MS = 3000
const SEARCH_MIN_CHARS = 3
const SEARCH_DEBOUNCE_MS = 300

/** Which applications the page lists: all of them, or only those in the interview / offer stage. */
export type Stage = 'all' | 'interviews' | 'offers'

type Props = {
  stage: Stage
  /** Id of the application shown in place of the list (from the URL), or null for the list. */
  detailId: string | null
  /** This page is the one on screen. */
  active: boolean
  onOpen: (id: number) => void
  onBack: () => void
  /** Breadcrumb entries after the page name while a detail is open. */
  onCrumbsChange: (crumbs: Crumb[]) => void
}

export default function ApplicationsPage({ stage, detailId, active, onOpen, onBack, onCrumbsChange }: Props) {
  const [applications, setApplications] = useState<Application[] | null>(null)
  const [statuses, setStatuses] = useState<ApplicationStatus[]>([])
  const [filter, setFilter] = useState('')
  const [searchInput, setSearchInput] = useState('')
  // The term actually sent to the API: debounced, and empty until it has enough characters.
  const [search, setSearch] = useState('')
  // The open application. Kept as its own object (fetched by id) so the view stays put even
  // when the application is not in the current list (filter, search, a deep link).
  const openId = detailId != null && /^\d+$/.test(detailId) ? Number(detailId) : null
  const [selected, setSelected] = useState<Application | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [shownId, setShownId] = useState<number | null>(null)
  if (openId !== shownId) {
    // Show the list's copy right away; the fetch below brings the full, fresh one.
    setShownId(openId)
    setSelected(openId == null ? null : (applications?.find((a) => a.id === openId) ?? null))
    setDetailError(null)
  }
  // Company popup; also opens over the application view.
  const [companyId, setCompanyId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  // The toolbar sticks under the top bar; once stuck it gets the top bar's translucent look.
  const toolbarRef = useRef<HTMLDivElement>(null)
  const stuck = useStuck(toolbarRef, active && detailId == null)

  const reload = useCallback(() => setTick((t) => t + 1), [])
  const detailOpen = detailId != null
  useDetailScroll(detailOpen, active)

  // Pages stay mounted; coming back to this one refetches it so changes made elsewhere
  // (e.g. a work history edit that makes scores outdated) show without a page reload.
  const wasActive = useRef(active)
  useEffect(() => {
    if (active && !wasActive.current) reload()
    wasActive.current = active
  }, [active, reload])

  /** The application's job was re-scored from its relevance meter. */
  const rescored = (fresh: EvaluatedJobDetail) => {
    const score = fresh.evaluation
    if (!score) return
    const update = (a: Application): Application =>
      a.job.id === fresh.id
        ? {
            ...a,
            evaluation: {
              id: score.id,
              candidate_profile_id: score.candidate_profile_id,
              relevance: score.relevance,
              outdated: score.outdated,
            },
          }
        : a
    setApplications((prev) => prev?.map(update) ?? prev)
    setSelected((prev) => (prev ? update(prev) : prev))
  }

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
      .list(
        stage === 'offers'
          ? { limit: PAGE_SIZE, status: OFFER_STATUS, q: search || undefined }
          : stage === 'interviews'
          ? { limit: PAGE_SIZE, status: INTERVIEW_STATUS, q: search || undefined }
          : {
              limit: PAGE_SIZE,
              status: filter || undefined,
              q: search || undefined,
            },
        controller.signal,
      )
      .then((page) => {
        setApplications(page.items)
        setError(null)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(`Could not load applications: ${describeError(e)}`)
      })
    return () => controller.abort()
  }, [stage, filter, search, tick])

  // The open application, refetched on every reload so it stays current wherever it was changed.
  useEffect(() => {
    if (openId == null) return
    const controller = new AbortController()
    applicationsApi
      .get(openId, controller.signal)
      .then((a) => {
        setSelected(a)
        setDetailError(null)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setDetailError(describeError(e))
      })
    return () => controller.abort()
  }, [openId, tick])

  const title = selected ? (selected.job.title ?? 'Untitled job') : null
  const placeholder = detailOpen && !selected ? (detailError || openId == null ? 'Not found' : 'Loading…') : null
  useEffect(() => {
    const crumbs: Crumb[] = []
    if (title !== null) crumbs.push({ label: title })
    else if (placeholder) crumbs.push({ label: placeholder })
    onCrumbsChange(crumbs)
  }, [title, placeholder, onCrumbsChange])

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

  // Bumped when an application reaches the offer stage from this page; replays the confetti.
  const [celebrations, setCelebrations] = useState(0)

  const replace = (updated: Application) => {
    const before = selected?.id === updated.id ? selected : applications?.find((a) => a.id === updated.id)
    if (updated.status?.key === OFFER_STATUS && before?.status?.key !== OFFER_STATUS) {
      setCelebrations((n) => n + 1)
    }
    setSelected((prev) => (prev?.id === updated.id ? updated : prev))
    setApplications((prev) => prev?.map((a) => (a.id === updated.id ? updated : a)) ?? prev)
    // The current status may have changed, which moves the application between the
    // Interviews / Offers pages and their menu counts.
    notifyApplicationsChanged()
  }

  const removed = (id: number) => {
    setApplications((prev) => prev?.filter((a) => a.id !== id) ?? prev)
    notifyApplicationsChanged()
    onBack()
  }

  const counts = new Map<string, number>()
  for (const a of applications ?? []) {
    const key = a.status?.key ?? ''
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }

  return (
    <div className="app-page">
      {celebrations > 0 && <Confetti key={celebrations} />}
      {detailOpen &&
        (selected ? (
          <ApplicationView
            key={selected.id}
            application={selected}
            statuses={statuses}
            onChange={replace}
            onDelete={removed}
            onOpenCompany={setCompanyId}
            onBack={onBack}
          />
        ) : (
          <div className="detail-view detail-status">
            {detailError || openId == null ? (
              <>
                <p className="error">Could not load the application: {detailError ?? 'not found'}</p>
                <button type="button" className="secondary small" onClick={onBack}>
                  Back to applications
                </button>
              </>
            ) : (
              <span className="spinner" aria-hidden="true" />
            )}
          </div>
        ))}

      {/* The list stays mounted under an open application so its filters and search survive. */}
      <div hidden={detailOpen}>
        <div ref={toolbarRef} className={stuck ? 'app-toolbar stuck' : 'app-toolbar'}>
        <div className="jobs-controls">
          <input
            type="search"
            className="app-search"
            placeholder="Search company or title…"
            aria-label="Search applications by company or title"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />

          {stage === 'all' && (
            <select
              className="app-status-filter"
              aria-label="Filter by status"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="">All statuses</option>
              {statuses
                .map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label}
                    {!filter && counts.has(s.key) ? ` (${counts.get(s.key)})` : ''}
                  </option>
                ))}
            </select>
          )}
        </div>
        </div>

        {error && <p className="error">{error}</p>}

        {applications !== null && applications.length === 0 && (
          <p className="muted">
            {search
              ? 'No applications match your search.'
              : stage === 'offers'
              ? 'No offers yet.'
              : stage === 'interviews'
              ? 'No interviews yet.'
              : filter
              ? 'No applications with this status.'
              : 'No applications yet. Open a job on the Jobs tab and choose "Create application".'}
          </p>
        )}

        <ul className="app-list">
          {applications?.map((a) => (
            <li key={a.id} className="app-item">
              <button type="button" className="app-row" onClick={() => onOpen(a.id)}>
                <div className="job-main">
                  {a.evaluation && (
                    <RelevanceMeter
                      relevance={a.evaluation.relevance}
                      outdated={a.evaluation.outdated}
                      rescore={{ jobId: a.job.id, onRescored: rescored }}
                    />
                  )}
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
                    <InterviewProgress application={a} compact />
                  </div>
                </div>
                {/* Clicks anywhere around the badge stay with it instead of opening the row. */}
                <div
                  className="app-badges"
                  onClick={(e) => {
                    e.stopPropagation()
                    e.preventDefault()
                  }}
                >
                  <StatusBadge
                    status={a.status}
                    auto={isAutoEvent(currentEvent(a))}
                    nextRound={nextRoundLabel(a)}
                    roundTitle={currentEvent(a)?.title}
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
      </div>

      {companyId != null && (
        <CompanyDialog key={companyId} companyId={companyId} onClose={() => setCompanyId(null)} />
      )}
    </div>
  )
}
