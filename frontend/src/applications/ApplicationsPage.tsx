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
import RelevanceMeter from '../jobs/RelevanceMeter.tsx'
import { type Crumb, pageHref } from '../shell/nav.ts'
import { useDetailScroll } from '../shell/useDetailScroll.ts'
import { useStuck } from '../shell/useStuck.ts'

const PAGE_SIZE = 200
const CV_POLL_MS = 3000
const SEARCH_MIN_CHARS = 3
const SEARCH_DEBOUNCE_MS = 300
const OFFER_STATUS = 'OFFER'

const SUBTABS = [
  { id: 'pending', label: 'Pending' },
  { id: 'interviews', label: 'Interviews' },
  { id: 'offers', label: 'Offers' },
] as const

type SubTab = (typeof SUBTABS)[number]['id']

type Props = {
  /** Id of the application shown in place of the list (from the URL), or null for the list. */
  detailId: string | null
  /** The Applications page is the one on screen. */
  active: boolean
  onOpen: (id: number) => void
  onBack: () => void
  /** Breadcrumb entries after "Applications" while a detail is open. */
  onCrumbsChange: (crumbs: Crumb[]) => void
}

const subTabOf = (application: Application): SubTab =>
  application.status?.key === OFFER_STATUS
    ? 'offers'
    : application.status?.key === INTERVIEW_STATUS
    ? 'interviews'
    : 'pending'

export default function ApplicationsPage({ detailId, active, onOpen, onBack, onCrumbsChange }: Props) {
  const [applications, setApplications] = useState<Application[] | null>(null)
  const [statuses, setStatuses] = useState<ApplicationStatus[]>([])
  const [subTab, setSubTab] = useState<SubTab>('pending')
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
  // The list behind the open application is the subtab it belongs to, so Back lands next to it.
  if (selected && subTabOf(selected) !== subTab) {
    setApplications(null)
    setSubTab(subTabOf(selected))
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
        subTab === 'offers'
          ? { limit: PAGE_SIZE, status: OFFER_STATUS, q: search || undefined }
          : subTab === 'interviews'
          ? { limit: PAGE_SIZE, status: INTERVIEW_STATUS, q: search || undefined }
          : {
              limit: PAGE_SIZE,
              status: filter || undefined,
              excludeStatus: `${OFFER_STATUS},${INTERVIEW_STATUS}`,
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
  }, [subTab, filter, search, tick])

  // How many applications are in the interview / offer states, unfiltered: a subtab only shows once it has any.
  const [substatesCounts, setSubstatesCounts] = useState<{ interviews: number; offers: number } | null>(null)
  // Bumped each time a subtab's count grows; used as the badge key to replay its bounce.
  const [bumps, setBumps] = useState({ interviews: 0, offers: 0 })
  useEffect(() => {
    const controller = new AbortController()
    const total = (status: string) =>
      applicationsApi.list({ limit: 1, status }, controller.signal).then((page) => page.total)
    Promise.all([total(INTERVIEW_STATUS), total(OFFER_STATUS)])
      .then(([interviews, offers]) => {
        setSubstatesCounts((prev) => {
          // A count that grew (not the first load) bounces its badge so the newcomer is noticed.
          if (prev && (interviews > prev.interviews || offers > prev.offers)) {
            setBumps((b) => ({
              interviews: b.interviews + (interviews > prev.interviews ? 1 : 0),
              offers: b.offers + (offers > prev.offers ? 1 : 0),
            }))
          }
          return { interviews, offers }
        })
      })
      .catch(() => {})
    return () => controller.abort()
  }, [tick, active, subTab, applications?.length])

  const visibleTabs = SUBTABS
      .filter((t) => t.id === 'pending' || (substatesCounts?.[t.id] ?? 0) > 0)
  // The current subtab emptied out (e.g. its last application moved on): fall back to Pending.
  if (substatesCounts && subTab !== 'pending' && substatesCounts[subTab] === 0 && !selected) {
    setApplications(null)
    setSubTab('pending')
  }

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
  const isOffer = selected != null && subTabOf(selected) === 'offers'
  const placeholder = detailOpen && !selected ? (detailError || openId == null ? 'Not found' : 'Loading…') : null
  useEffect(() => {
    const crumbs: Crumb[] = []
    if (isOffer) crumbs.push({ label: 'Offers', href: pageHref('applications') })
    if (title !== null) crumbs.push({ label: title })
    else if (placeholder) crumbs.push({ label: placeholder })
    onCrumbsChange(crumbs)
  }, [isOffer, title, placeholder, onCrumbsChange])

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
    // The current status may have changed; reaching (or leaving) the offer stage moves
    // the application to the other subtab.
    reload()
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
        {visibleTabs.length > 1 && (
        <nav className="segmented centered" aria-label="Application sections">
          {visibleTabs.map((t) => (
            <button
              key={t.id}
              type="button"
              className={subTab === t.id ? 'tab active' : 'tab'}
              aria-current={subTab === t.id ? 'page' : undefined}
              onClick={() => {
                // Re-clicking the current tab would clear the list without refetching it.
                if (t.id === subTab) return
                setApplications(null)
                setSubTab(t.id)
              }}
            >
              {t.label}
              {t.id !== 'pending' && substatesCounts && (
                <span key={bumps[t.id]} className={bumps[t.id] ? 'tab-count bump' : 'tab-count'}>
                  {substatesCounts[t.id]}
                </span>
              )}
            </button>
          ))}
        </nav>
        )}

        <div className="jobs-controls">
          <input
            type="search"
            className="app-search"
            placeholder="Search company or title…"
            aria-label="Search applications by company or title"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />

          {subTab === 'pending' && (
            <select
              className="app-status-filter"
              aria-label="Filter by status"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="">All statuses</option>
              {statuses
                .filter((s) => s.key !== OFFER_STATUS && s.key !== INTERVIEW_STATUS)
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
              : subTab === 'offers'
              ? 'No offers yet.'
              : subTab === 'interviews'
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
