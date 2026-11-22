import { Send } from 'lucide-react'
import { type RefObject, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import './jobs.css'
import '../applications/applications.css'
import { type EvaluatedJob, type JobDecision, isRelevant, jobsApi } from './api.ts'
import JobView from './JobView.tsx'
import RelevanceMeter from './RelevanceMeter.tsx'
import AddJobComposer from './AddJobComposer.tsx'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import '../companies/tags.css'
import CompanyDialog from '../companies/CompanyDialog.tsx'
import { APPLICATIONS_CHANGED, applicationsApi, notifyApplicationsChanged } from '../applications/api.ts'
import { describeError } from '../cv/api.ts'
import type { Crumb } from '../shell/nav.ts'
import { useDetailScroll } from '../shell/useDetailScroll.ts'
import { useStuck } from '../shell/useStuck.ts'

const PAGE_SIZE = 50
/** How often the tab checks for newly evaluated jobs, in ms. */
const POLL_INTERVAL = 30_000
const SEARCH_MIN_CHARS = 3
const SEARCH_DEBOUNCE_MS = 300
/** How often a manually added job's parse / evaluation is checked, in ms. */
const PROCESSING_POLL_MS = 2_500

/** A manually added job that is not parsed and scored yet. */
type ProcessingJob = { jobId: number; title: string; company: string; error: string | null }

/** Vertical offset currently applied by a running transform animation, in px. */
function currentTranslateY(el: HTMLElement): number {
  const transform = getComputedStyle(el).transform
  if (!transform || transform === 'none') return 0
  // matrix(a, b, c, d, tx, ty) — ty is the last component.
  const match = /matrix\(([^)]+)\)/.exec(transform)
  if (!match) return 0
  const parts = match[1].split(',')
  const ty = Number(parts[parts.length - 1])
  return Number.isFinite(ty) ? ty : 0
}

/**
 * FLIP animation: whenever the list re-orders, rows glide from their previous
 * position to the new one instead of jumping. `order` is a key that changes
 * when the ordering does.
 *
 * `previous` holds each row's *layout* position (transform excluded) from the
 * last commit. If a row is still mid-glide when the order changes again, its
 * in-flight offset is read first, the old animation is cancelled, and the new
 * glide starts from where the row visually is.
 */
function useFlip(listRef: RefObject<HTMLUListElement | null>, order: string) {
  const previous = useRef(new Map<string, number>())

  useLayoutEffect(() => {
    const list = listRef.current
    if (!list) return
    // Hidden behind a job view: nothing to animate, and hidden rows have no position.
    if (list.offsetParent === null) {
      previous.current.clear()
      return
    }
    const rows = Array.from(list.children) as HTMLElement[]
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const next = new Map<string, number>()
    for (const row of rows) {
      const key = row.dataset.key
      if (!key) continue
      const inFlight = currentTranslateY(row)
      for (const animation of row.getAnimations()) animation.cancel()
      const top = row.getBoundingClientRect().top
      next.set(key, top)
      const before = previous.current.get(key)
      if (before === undefined || reduce) continue
      const delta = before + inFlight - top
      if (Math.abs(delta) < 1) continue
      row.animate(
        [{ transform: `translateY(${delta}px)` }, { transform: 'translateY(0)' }],
        { duration: 350, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' },
      )
    }
    previous.current = next
  }, [listRef, order])
}

/** Feed order: newest evaluation first. */
const byEvaluationDesc = (a: EvaluatedJob, b: EvaluatedJob) => b.evaluation.id - a.evaluation.id

function JobRow({
  job,
  inbox,
  busy,
  error,
  onSelect,
  onDecide,
  onOpenCompany,
}: {
  job: EvaluatedJob
  /** Undecided relevant job: shows the accept / reject buttons. */
  inbox: boolean
  busy: boolean
  error: string | null
  onSelect: (job: EvaluatedJob) => void
  onDecide: (job: EvaluatedJob, decision: JobDecision) => void
  onOpenCompany: (companyId: number) => void
}) {
  const classes = ['job-item']
  if (inbox) classes.push('match')
  else if (!isRelevant(job.evaluation)) classes.push('dimmed')
  if (!inbox && job.decision === 'rejected') classes.push('rejected')
  if (job.application_id != null) classes.push('applied')

  return (
    <li className={classes.join(' ')} data-key={String(job.id)}>
      {job.application_id != null && (
        <span className="job-applied-strip" title="Application created" aria-label="Application created">
          <Send size={11} aria-hidden="true" />
        </span>
      )}
      <div className="job-row-wrap">
        <button type="button" className="job-row" onClick={() => onSelect(job)}>
          <div className="job-main">
            <RelevanceMeter relevance={job.evaluation.relevance} />
            <span className="job-title" style={{ marginLeft: '10px' }}>
              {job.title ?? job.link}
            </span>
            <div className="job-meta">
              {job.company && (
                <span className="job-company">
                  {job.company_id != null ? (
                    <CompanyTagBadge
                      companyId={job.company_id}
                      tag={job.company_tag}
                      name={job.company}
                      onOpenCompany={onOpenCompany}
                    />
                  ) : (
                    job.company
                  )}
                </span>
              )}
              <span>{job.source}</span>
              <span>evaluated {new Date(job.evaluation.created_at).toLocaleDateString()}</span>
            </div>
          </div>
        </button>
        {inbox && (
          <div className="job-side">
            <div className="job-decide">
              <button
                type="button"
                className="small decide accept"
                onClick={() => onDecide(job, 'accepted')}
                disabled={busy}
                title="Create an application for this job"
                aria-label={`Create an application for ${job.title ?? 'this job'}`}
              >
                ✓
              </button>
              <button
                type="button"
                className="small secondary decide reject"
                onClick={() => onDecide(job, 'rejected')}
                disabled={busy}
                title="Not interested"
                aria-label={`Dismiss ${job.title ?? 'this job'}`}
              >
                ✕
              </button>
            </div>
          </div>
        )}
      </div>
      {error && <p className="error">{error}</p>}
    </li>
  )
}

type Props = {
  /** Id of the job shown in place of the list (from the URL), or null for the list. */
  detailId: string | null
  /** The Jobs page is the one on screen. */
  active: boolean
  onOpen: (id: number) => void
  onBack: () => void
  /** Breadcrumb entries after "Jobs" while a detail is open. */
  onCrumbsChange: (crumbs: Crumb[]) => void
  /** Called whenever the number of undecided relevant jobs changes (for the tab badge). */
  onInboxCountChange?: (count: number) => void
}

export default function JobsPage({ detailId, active, onOpen, onBack, onCrumbsChange, onInboxCountChange }: Props) {
  const [inbox, setInbox] = useState<EvaluatedJob[]>([])
  const [inboxCount, setInboxCount] = useState(0)
  const [feed, setFeed] = useState<EvaluatedJob[]>([])
  const [profileId, setProfileId] = useState<number | null | undefined>(undefined)
  const [hasMore, setHasMore] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [companyId, setCompanyId] = useState<number | null>(null)
  const [busy, setBusy] = useState<Set<number>>(new Set())
  const [rowErrors, setRowErrors] = useState<Map<number, string>>(new Map())
  const [searchInput, setSearchInput] = useState('')
  // The term actually sent to the API: debounced, and empty until it has enough characters.
  const [search, setSearch] = useState('')
  /** Search results (null while loading the first page); unused without a search term. */
  const [results, setResults] = useState<EvaluatedJob[] | null>(null)
  const [resultsHasMore, setResultsHasMore] = useState(false)
  const [resultsLoading, setResultsLoading] = useState(false)
  const sentinel = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLUListElement>(null)

  // Mirrors of state for async callbacks so they never read stale values.
  const loadingRef = useRef(false)
  const hasMoreRef = useRef(true)
  const profileRef = useRef<number | null | undefined>(undefined)
  /** Oldest / newest evaluation id the feed endpoint returned (keyset cursors). Rows moved
   * into the feed locally do not move them, so polling and paging never skip a row. */
  const oldestRef = useRef<number | null>(null)
  const newestRef = useRef<number | null>(null)
  const inboxRef = useRef<EvaluatedJob[]>([])
  /** Bumped on every local decision; a poll that started before one is discarded. */
  const mutationRef = useRef(0)
  const pollingRef = useRef(false)

  useEffect(() => {
    inboxRef.current = inbox
  }, [inbox])

  useEffect(() => {
    onInboxCountChange?.(inboxCount)
  }, [inboxCount, onInboxCountChange])

  const detailOpen = detailId != null
  const openId = detailId != null && /^\d+$/.test(detailId) ? Number(detailId) : null
  useDetailScroll(detailOpen, active)
  // The search bar sticks under the top bar; once stuck it gets the top bar's translucent look.
  const toolbarRef = useRef<HTMLDivElement>(null)
  const stuck = useStuck(toolbarRef, active && !detailOpen)

  const onDetailTitle = useCallback(
    (title: string | null) => onCrumbsChange([{ label: title ?? 'Not found' }]),
    [onCrumbsChange],
  )
  useEffect(() => {
    if (!detailOpen) onCrumbsChange([])
    else if (openId == null) onCrumbsChange([{ label: 'Not found' }])
  }, [detailOpen, openId, onCrumbsChange])

  /** Put a job into the loaded part of the feed (replacing an existing copy). A job older
   * than the loaded pages is left out: it arrives with the page it belongs to. */
  const putInFeed = useCallback((job: EvaluatedJob) => {
    setFeed((prev) => {
      const rest = prev.filter((j) => j.id !== job.id)
      const oldest = oldestRef.current
      if (hasMoreRef.current && oldest !== null && job.evaluation.id < oldest) return rest
      return [...rest, job].sort(byEvaluationDesc)
    })
  }, [])

  const mergeFeed = useCallback((items: EvaluatedJob[]) => {
    if (items.length === 0) return
    setFeed((prev) => {
      const incoming = new Map(items.map((j) => [j.id, j]))
      return [...prev.filter((j) => !incoming.has(j.id)), ...items].sort(byEvaluationDesc)
    })
  }, [])

  const loadMore = useCallback(async () => {
    if (loadingRef.current || !hasMoreRef.current || profileRef.current === undefined) return
    loadingRef.current = true
    setLoading(true)
    setError(null)
    try {
      const page = await jobsApi.feed({ before: oldestRef.current ?? undefined, limit: PAGE_SIZE })
      if (page.items.length > 0) {
        oldestRef.current = page.items[page.items.length - 1].evaluation.id
        newestRef.current = Math.max(newestRef.current ?? 0, page.items[0].evaluation.id)
      } else if (newestRef.current === null) {
        newestRef.current = 0
      }
      hasMoreRef.current = page.has_more
      setHasMore(page.has_more)
      mergeFeed(page.items)
    } catch (e) {
      setError(`Could not load jobs: ${describeError(e)}`)
    } finally {
      loadingRef.current = false
      setLoading(false)
    }
  }, [mergeFeed])

  const reset = useCallback(() => {
    oldestRef.current = null
    newestRef.current = null
    hasMoreRef.current = true
    setHasMore(true)
    setFeed([])
    setInbox([])
    setInboxCount(0)
  }, [])

  /** Fetch the inbox and any newer feed rows. Also used for the first load. */
  const poll = useCallback(async () => {
    if (pollingRef.current) return
    pollingRef.current = true
    const version = mutationRef.current
    try {
      const box = await jobsApi.inbox()
      if (box.candidate_profile_id !== profileRef.current) {
        // First load, or a new candidate profile re-scored everything: start over.
        const first = profileRef.current === undefined
        profileRef.current = box.candidate_profile_id
        setProfileId(box.candidate_profile_id)
        if (!first) reset()
      }
      if (version !== mutationRef.current) return

      // Jobs that left the inbox elsewhere (e.g. an application made on another device)
      // move into the feed with their fresh state.
      const stillThere = new Set(box.items.map((j) => j.id))
      const left = inboxRef.current.filter((j) => !stillThere.has(j.id))
      inboxRef.current = box.items
      setInbox(box.items)
      setInboxCount(box.count)
      for (const job of left) {
        jobsApi
          .get(job.id)
          .then((fresh) => {
            if (fresh.evaluation) putInFeed({ ...job, ...fresh, evaluation: fresh.evaluation })
          })
          .catch(() => {
            /* it shows up again on the next reload */
          })
      }

      if (newestRef.current === null) {
        await loadMore()
      } else {
        const fresh = await jobsApi.feed({ after: newestRef.current, limit: 200 })
        if (fresh.items.length > 0) {
          newestRef.current = Math.max(newestRef.current, fresh.items[0].evaluation.id)
          mergeFeed(fresh.items)
        }
      }
      setError(null)
    } catch (e) {
      setError(`Could not load jobs: ${describeError(e)}`)
    } finally {
      pollingRef.current = false
    }
  }, [loadMore, mergeFeed, putInFeed, reset])

  // First load, then check for newly evaluated jobs periodically and whenever the window
  // regains focus or applications change elsewhere in the app.
  useEffect(() => {
    const first = window.setTimeout(poll, 0)
    const timer = window.setInterval(() => {
      if (!document.hidden) poll()
    }, POLL_INTERVAL)
    const onVisible = () => {
      if (!document.hidden) poll()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', onVisible)
    window.addEventListener(APPLICATIONS_CHANGED, onVisible)
    return () => {
      window.clearTimeout(first)
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onVisible)
      window.removeEventListener(APPLICATIONS_CHANGED, onVisible)
    }
  }, [poll])

  useEffect(() => {
    const term = searchInput.trim()
    const next = term.length >= SEARCH_MIN_CHARS ? term : ''
    const timer = window.setTimeout(() => setSearch(next), next ? SEARCH_DEBOUNCE_MS : 0)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  const searchControllerRef = useRef<AbortController | null>(null)
  const resultsRef = useRef<EvaluatedJob[] | null>(null)
  const loadResults = useCallback(
    async (fresh: boolean) => {
      if (!search) return
      if (!fresh && (searchControllerRef.current || !resultsRef.current)) return
      searchControllerRef.current?.abort()
      const controller = new AbortController()
      searchControllerRef.current = controller
      const prev = fresh ? [] : (resultsRef.current ?? [])
      const before = prev.length > 0 ? prev[prev.length - 1].evaluation.id : undefined
      setResultsLoading(true)
      try {
        const page = await jobsApi.feed({ q: search, before, limit: PAGE_SIZE }, controller.signal)
        resultsRef.current = [...prev, ...page.items]
        setResults(resultsRef.current)
        setResultsHasMore(page.has_more)
        setError(null)
      } catch (e) {
        if (!controller.signal.aborted) setError(`Could not search jobs: ${describeError(e)}`)
      } finally {
        if (searchControllerRef.current === controller) searchControllerRef.current = null
        if (!controller.signal.aborted || !searchControllerRef.current) setResultsLoading(false)
      }
    },
    [search],
  )

  // A new term clears the previous results right away; the effect below fetches the new ones.
  const [resultsFor, setResultsFor] = useState('')
  if (resultsFor !== search) {
    setResultsFor(search)
    setResults(null)
    setResultsHasMore(false)
  }
  useEffect(() => {
    resultsRef.current = null
    if (search) loadResults(true)
    return () => searchControllerRef.current?.abort()
  }, [search, loadResults])

  // Load the next page whenever the sentinel below the list scrolls into view.
  useEffect(() => {
    const el = sentinel.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return
        if (search) {
          if (resultsHasMore) loadResults(false)
        } else loadMore()
      },
      { rootMargin: '400px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [loadMore, loadResults, search, resultsHasMore])

  /** Move a decided job out of the inbox into the chronological feed. */
  const leaveInbox = useCallback(
    (job: EvaluatedJob) => {
      mutationRef.current += 1
      if (inboxRef.current.some((j) => j.id === job.id)) {
        inboxRef.current = inboxRef.current.filter((j) => j.id !== job.id)
        setInbox(inboxRef.current)
        setInboxCount((count) => Math.max(0, count - 1))
      }
      putInFeed(job)
      setResults((prev) => prev?.map((j) => (j.id === job.id ? job : j)) ?? prev)
    },
    [putInFeed],
  )

  const setRowBusy = (id: number, on: boolean) =>
    setBusy((prev) => {
      const next = new Set(prev)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })

  const setRowError = (id: number, message: string | null) =>
    setRowErrors((prev) => {
      const next = new Map(prev)
      if (message) next.set(id, message)
      else next.delete(id)
      return next
    })

  const decide = async (job: EvaluatedJob, decision: JobDecision) => {
    setRowBusy(job.id, true)
    setRowError(job.id, null)
    mutationRef.current += 1
    try {
      if (decision === 'accepted') {
        const created = await applicationsApi.create({ job_evaluation_id: job.evaluation.id })
        leaveInbox({ ...job, application_id: created.id, decision: 'accepted' })
        notifyApplicationsChanged()
      } else {
        await jobsApi.decide(job.id, 'rejected')
        leaveInbox({ ...job, decision: 'rejected' })
      }
    } catch (e) {
      setRowError(job.id, describeError(e))
    } finally {
      setRowBusy(job.id, false)
    }
  }

  /** An application was created from the job view ("Apply"). */
  const applicationCreated = (jobId: number, applicationId: number) => {
    const update = (j: EvaluatedJob): EvaluatedJob =>
      j.id === jobId ? { ...j, application_id: applicationId, decision: 'accepted' } : j
    const inInbox = inbox.find((j) => j.id === jobId)
    if (inInbox) leaveInbox(update(inInbox))
    else {
      setFeed((prev) => prev.map(update))
      setResults((prev) => prev?.map(update) ?? prev)
    }
  }

  // Manually added jobs still going through parse -> evaluate, newest first.
  const [processing, setProcessing] = useState<ProcessingJob[]>([])
  const processingRef = useRef<ProcessingJob[]>([])
  useEffect(() => {
    processingRef.current = processing
  }, [processing])
  const hasProcessing = processing.some((p) => !p.error)
  useEffect(() => {
    if (!hasProcessing) return
    const timer = window.setInterval(async () => {
      for (const item of processingRef.current) {
        if (item.error) continue
        try {
          const status = await jobsApi.manualStatus(item.jobId)
          if (status.status === 'FAILED') {
            setProcessing((prev) =>
              prev.map((p) => (p.jobId === item.jobId ? { ...p, error: status.error ?? 'Parsing failed' } : p)),
            )
          } else if (status.status === 'COMPLETED') {
            const job = await jobsApi.get(item.jobId)
            if (job.evaluation) {
              setProcessing((prev) => prev.filter((p) => p.jobId !== item.jobId))
              poll()
            }
          }
        } catch {
          /* try again on the next tick */
        }
      }
    }, PROCESSING_POLL_MS)
    return () => window.clearInterval(timer)
  }, [hasProcessing, poll])

  const searching = search !== ''
  const inboxIds = new Set(inbox.map((j) => j.id))
  const ordered = searching ? (results ?? []) : [...inbox, ...feed]
  const orderedIds = new Set(ordered.map((j) => j.id))
  // Shown in place at the top of the list until the scored row arrives from the API.
  const shownProcessing = searching ? [] : processing.filter((p) => !orderedIds.has(p.jobId))
  useFlip(listRef, [...shownProcessing.map((p) => p.jobId), ...ordered.map((j) => j.id)].join(','))

  const empty =
    profileId !== undefined && inbox.length === 0 && feed.length === 0 && !hasMore && shownProcessing.length === 0

  return (
    <>
      {detailOpen &&
        (openId != null ? (
          <JobView
            key={openId}
            jobId={openId}
            initial={[...inbox, ...feed, ...(results ?? [])].find((j) => j.id === openId) ?? null}
            onBack={onBack}
            onOpenCompany={setCompanyId}
            onApplicationCreated={(applicationId) => applicationCreated(openId, applicationId)}
            onTitle={onDetailTitle}
          />
        ) : (
          <div className="detail-view detail-status">
            <p className="error">Could not load the job: not found</p>
            <button type="button" className="secondary small" onClick={onBack}>
              Back to jobs
            </button>
          </div>
        ))}

      {/* The list stays mounted under an open job so loaded pages and polling survive. */}
      <div hidden={detailOpen}>
        <p>
          {profileId === undefined
            ? 'Loading…'
            : profileId === null
              ? 'No candidate profile yet.'
              : null}
        </p>

        <div ref={toolbarRef} className={stuck ? 'app-toolbar stuck' : 'app-toolbar'}>
        <div className="jobs-controls">
          <input
            type="search"
            className="app-search"
            placeholder="Search company or title…"
            aria-label="Search jobs by company or title"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
        </div>
        </div>

        {error && (
          <p className="error">
            {error}{' '}
            <button
              type="button"
              className="secondary small"
              onClick={() => (searching ? loadResults(true) : poll())}
            >
              Retry
            </button>
          </p>
        )}

        {searching && results !== null && results.length === 0 ? (
          <p className="muted">No jobs match your search.</p>
        ) : !searching && empty ? (
          <p>
            {profileId === null
              ? 'Add your work history first; a candidate profile is built from it and scraped jobs are scored against it.'
              : 'No evaluated jobs yet. New jobs appear here automatically once they are scraped and scored.'}
          </p>
        ) : (
          <ul className="job-list" ref={listRef}>
            {shownProcessing.map((p) => (
              <li
                key={`processing-${p.jobId}`}
                data-key={String(p.jobId)}
                className={p.error ? 'job-item processing failed' : 'job-item processing'}
                aria-busy={!p.error}
              >
                <div className="job-row-wrap">
                  <div className="job-row">
                    <div className="job-main">
                      <span className="job-title">{p.title}</span>
                      <div className="job-meta">
                        {p.company && <span className="job-company">{p.company}</span>}
                        <span>manual</span>
                        <span>{p.error ? 'could not be processed' : 'processing…'}</span>
                      </div>
                    </div>
                  </div>
                  <div className="job-side">
                    {p.error ? (
                      <button
                        type="button"
                        className="small secondary"
                        onClick={() => setProcessing((prev) => prev.filter((x) => x.jobId !== p.jobId))}
                      >
                        Dismiss
                      </button>
                    ) : (
                      <span className="relevance pending" title="Being parsed and scored" />
                    )}
                  </div>
                </div>
                {p.error && <p className="error">{p.error}</p>}
              </li>
            ))}
            {ordered.map((job, index) => {
              const inInbox = searching ? inboxIds.has(job.id) : index < inbox.length
              return (
                <JobRow
                  key={job.id}
                  job={job}
                  inbox={inInbox}
                  busy={busy.has(job.id)}
                  error={rowErrors.get(job.id) ?? null}
                  onSelect={(j) => onOpen(j.id)}
                  onDecide={decide}
                  onOpenCompany={setCompanyId}
                />
              )
            })}
          </ul>
        )}

        <div ref={sentinel} className="sentinel">
          {(searching ? resultsLoading : loading) && <span className="spinner" aria-hidden="true" />}
          {!searching && !hasMore && feed.length > 0 && <span className="muted">All jobs loaded.</span>}
        </div>
      </div>

      {active && !detailOpen && (
        <AddJobComposer
          onAdded={(status, input) =>
            setProcessing((prev) => [
              { jobId: status.job_id, title: input.title.trim(), company: input.company.trim(), error: null },
              ...prev,
            ])
          }
        />
      )}

      {companyId != null && (
        <CompanyDialog key={companyId} companyId={companyId} onClose={() => setCompanyId(null)} />
      )}
    </>
  )
}
