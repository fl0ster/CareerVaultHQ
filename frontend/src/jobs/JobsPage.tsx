import { Send } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import './jobs.css'
import '../applications/applications.css'
import {
  type EvaluatedJob,
  type EvaluatedJobDetail,
  type JobDecision,
  isRelevant,
  jobsApi,
  notifyJobsChanged,
} from './api.ts'
import { processingStore } from './processingStore.ts'
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
import { useStore } from '../shell/store.ts'
import { useStuck } from '../shell/useStuck.ts'
import EmptyState from '../mascot/EmptyState.tsx'

const PAGE_SIZE = 50
/** Rows per request while polling for newly scored jobs (the API maximum). */
const POLL_PAGE_SIZE = 200
/** How often the tab checks for newly evaluated jobs, in ms. */
const POLL_INTERVAL = 30_000
const SEARCH_MIN_CHARS = 3
const SEARCH_DEBOUNCE_MS = 300
/** How often a manually added job's parse / evaluation is checked, in ms. */
const PROCESSING_POLL_MS = 2_500

/** Feed order: newest job first (stable across re-scores). */
const byIdDesc = (a: EvaluatedJob, b: EvaluatedJob) => b.id - a.id

/** Section a re-scored job stays in until the next full reload, whatever its new score. */
type Section = 'inbox' | 'feed'

/** `jobs` with each score's `outdated` flag recomputed against the profiles built from the
 * current work history (`current`); the same array when nothing changed. */
function withOutdated(jobs: EvaluatedJob[], current: Set<number>): EvaluatedJob[] {
  const isStale = (j: EvaluatedJob) => !current.has(j.evaluation.candidate_profile_id)
  if (jobs.every((j) => isStale(j) === j.evaluation.outdated)) return jobs
  return jobs.map((j) => {
    const outdated = isStale(j)
    return outdated === j.evaluation.outdated ? j : { ...j, evaluation: { ...j.evaluation, outdated } }
  })
}

/** The inbox as the server returned it, except that re-scored jobs pinned to a section stay
 * where they were: pinned-to-inbox jobs keep their previous index (with fresh data when the
 * server still lists them), pinned-to-feed jobs are left out. */
function placeInbox(server: EvaluatedJob[], previous: EvaluatedJob[], pinned: Map<number, Section>): EvaluatedJob[] {
  const result = server.filter((j) => !pinned.has(j.id))
  const byId = new Map(server.map((j) => [j.id, j]))
  previous.forEach((job, index) => {
    if (pinned.get(job.id) === 'inbox') result.splice(Math.min(index, result.length), 0, byId.get(job.id) ?? job)
  })
  return result
}

function JobRow({
  job,
  inbox,
  busy,
  error,
  onSelect,
  onDecide,
  onRescored,
  onOpenCompany,
}: {
  job: EvaluatedJob
  /** Undecided relevant job: shows the accept / reject buttons. */
  inbox: boolean
  busy: boolean
  error: string | null
  onSelect: (job: EvaluatedJob) => void
  onDecide: (job: EvaluatedJob, decision: JobDecision) => void
  onRescored: (job: EvaluatedJobDetail) => void
  onOpenCompany: (companyId: number) => void
}) {
  const classes = ['job-item']
  if (inbox) classes.push('match')
  else if (!isRelevant(job.evaluation)) classes.push('dimmed')
  if (!inbox && job.decision === 'rejected') classes.push('rejected')
  if (job.application_id != null) classes.push('applied')

  return (
    <li className={classes.join(' ')}>
      {job.application_id != null && (
        <span className="job-applied-strip" title="Application created" aria-label="Application created">
          <Send size={11} aria-hidden="true" />
        </span>
      )}
      <div className="job-row-wrap">
        <button type="button" className="job-row" onClick={() => onSelect(job)}>
          <div className="job-main">
            <RelevanceMeter
              relevance={job.evaluation.relevance}
              outdated={job.evaluation.outdated}
              explanation={job.evaluation.explanation}
              jobId={job.id}
              onRescored={onRescored}
            />
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
  /** The inbox size from the menu badge (null until known). It changing while the page is
   * open means jobs were scored or decided elsewhere, so the page checks right away. */
  inboxCount: number | null
  onOpen: (id: number) => void
  onBack: () => void
  /** Breadcrumb entries after "Jobs" while a detail is open. */
  onCrumbsChange: (crumbs: Crumb[]) => void
}

export default function JobsPage({ detailId, inboxCount, onOpen, onBack, onCrumbsChange }: Props) {
  const [inbox, setInbox] = useState<EvaluatedJob[]>([])
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

  // Mirrors of state for async callbacks so they never read stale values.
  const loadingRef = useRef(false)
  const hasMoreRef = useRef(true)
  const profileRef = useRef<number | null | undefined>(undefined)
  /** Oldest job id the feed endpoint returned: the paging cursor (the feed is ordered by
   * job id, so rows never move). Rows moved into the feed locally do not move it. */
  const oldestRef = useRef<number | null>(null)
  /** Newest evaluation id polled so far: the polling cursor. Separate from the paging one
   * because a job can be scored (or re-scored) long after newer jobs were added. `null`
   * until the first page is loaded. */
  const scoredRef = useRef<number | null>(null)
  const inboxRef = useRef<EvaluatedJob[]>([])
  /** Bumped on every local decision; a poll that started before one is discarded. */
  const mutationRef = useRef(0)
  const pollingRef = useRef(false)
  /** Jobs re-scored here, pinned to the section they were in so they do not move. */
  const pinnedRef = useRef(new Map<number, Section>())

  useEffect(() => {
    inboxRef.current = inbox
  }, [inbox])

  const detailOpen = detailId != null
  const openId = detailId != null && /^\d+$/.test(detailId) ? Number(detailId) : null
  useDetailScroll(detailOpen)
  // The search bar sticks under the top bar; once stuck it gets the top bar's translucent look.
  const toolbarRef = useRef<HTMLDivElement>(null)
  const stuck = useStuck(toolbarRef, !detailOpen)

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
      if (hasMoreRef.current && oldest !== null && job.id < oldest) return rest
      return [...rest, job].sort(byIdDesc)
    })
  }, [])

  /** Merge rows into the feed, replacing existing copies in place (the order is by job id).
   * Rows older than the loaded pages are left out: they arrive with the page they belong
   * to, already up to date. */
  const mergeFeed = useCallback((items: EvaluatedJob[]) => {
    const oldest = oldestRef.current
    const fresh = items.filter(
      (j) =>
        // A job pinned to the inbox stays there even when the server now lists it in the feed.
        pinnedRef.current.get(j.id) !== 'inbox' && !(hasMoreRef.current && oldest !== null && j.id < oldest),
    )
    if (fresh.length === 0) return
    setFeed((prev) => {
      const incoming = new Map(fresh.map((j) => [j.id, j]))
      return [...prev.filter((j) => !incoming.has(j.id)), ...fresh].sort(byIdDesc)
    })
  }, [])

  const loadMore = useCallback(async () => {
    if (loadingRef.current || !hasMoreRef.current || profileRef.current === undefined) return
    loadingRef.current = true
    setLoading(true)
    setError(null)
    try {
      const page = await jobsApi.feed({ before: oldestRef.current ?? undefined, limit: PAGE_SIZE })
      // Only the first page sets the polling cursor. A later (older) page may hold a newer
      // score than some update to an already loaded row that has not been polled yet, and
      // advancing past it would lose that update; polling those rows again is harmless.
      if (scoredRef.current === null) {
        scoredRef.current = page.items.reduce((max, j) => Math.max(max, j.evaluation.id), 0)
      }
      if (page.items.length > 0) oldestRef.current = page.items[page.items.length - 1].id
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
    scoredRef.current = null
    hasMoreRef.current = true
    pinnedRef.current.clear()
    setHasMore(true)
    setFeed([])
    setInbox([])
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
      // move into the feed with their fresh state; jobs that entered it leave the feed.
      // Jobs re-scored here stay in their section (see placeInbox).
      // Rows loaded earlier carry the `outdated` flag of when they were fetched; recompute it
      // so a work history edit shows on every row without reloading them.
      const current = new Set(box.current_profile_ids)
      const nextInbox = withOutdated(placeInbox(box.items, inboxRef.current, pinnedRef.current), current)
      const stillThere = new Set(nextInbox.map((j) => j.id))
      setFeed((prev) =>
        withOutdated(prev.some((j) => stillThere.has(j.id)) ? prev.filter((j) => !stillThere.has(j.id)) : prev, current),
      )
      setResults((prev) => (prev ? withOutdated(prev, current) : prev))
      const left = inboxRef.current.filter((j) => !stillThere.has(j.id))
      inboxRef.current = nextInbox
      setInbox(nextInbox)
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

      if (scoredRef.current === null) {
        await loadMore()
      } else {
        // Every job scored or re-scored since the last poll, oldest score first, page by
        // page; each lands in its place by job id.
        for (;;) {
          const fresh = await jobsApi.feed({ scored_after: scoredRef.current, limit: POLL_PAGE_SIZE })
          if (fresh.items.length === 0) break
          mergeFeed(fresh.items)
          scoredRef.current = fresh.items[fresh.items.length - 1].evaluation.id
          if (!fresh.has_more) break
        }
      }
      setError(null)
    } catch (e) {
      setError(`Could not load jobs: ${describeError(e)}`)
    } finally {
      pollingRef.current = false
    }
  }, [loadMore, mergeFeed, putInFeed, reset])

  // The menu badge saw the inbox change (new jobs scored, a decision made elsewhere): check
  // right away instead of waiting for the next interval. The first value is not a change.
  const seenInboxCount = useRef(inboxCount)
  useEffect(() => {
    const prev = seenInboxCount.current
    seenInboxCount.current = inboxCount
    if (prev === null || prev === inboxCount) return
    const timer = window.setTimeout(poll, 0)
    return () => window.clearTimeout(timer)
  }, [inboxCount, poll])

  // The page mounts on entry, so the first load is always fresh. Then check for newly
  // evaluated jobs periodically and whenever the window regains focus or applications
  // change elsewhere in the app.
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
      const before = prev.length > 0 ? prev[prev.length - 1].id : undefined
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
      pinnedRef.current.delete(job.id)
      if (inboxRef.current.some((j) => j.id === job.id)) {
        inboxRef.current = inboxRef.current.filter((j) => j.id !== job.id)
        setInbox(inboxRef.current)
        notifyJobsChanged()
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

  /** A job was re-scored against the latest profile: show the new score in place. The job
   * keeps its position, even if the new score crosses the relevance threshold, until the
   * next full reload. */
  const rescored = useCallback((fresh: EvaluatedJobDetail) => {
    if (!fresh.evaluation) return
    const evaluation = fresh.evaluation
    const update = (j: EvaluatedJob): EvaluatedJob => (j.id === fresh.id ? { ...j, evaluation } : j)
    mutationRef.current += 1
    const inInbox = inboxRef.current.some((j) => j.id === fresh.id)
    pinnedRef.current.set(fresh.id, inInbox ? 'inbox' : 'feed')
    // Re-scoring may have generated a new profile; it is not a reason to reload the list.
    profileRef.current = evaluation.candidate_profile_id
    setProfileId(evaluation.candidate_profile_id)
    inboxRef.current = inboxRef.current.map(update)
    setInbox(inboxRef.current)
    setFeed((prev) => prev.map(update))
    setResults((prev) => prev?.map(update) ?? prev)
    // The new score may move the job in or out of the inbox: refresh the menu badge.
    notifyJobsChanged()
  }, [])

  // Manually added jobs still going through parse -> evaluate, newest first. Kept in a store
  // so they are still followed after leaving the page and coming back.
  const processing = useStore(processingStore)
  const setProcessing = processingStore.set
  const hasProcessing = processing.some((p) => !p.error)
  useEffect(() => {
    if (!hasProcessing) return
    const timer = window.setInterval(async () => {
      for (const item of processingStore.get()) {
        if (item.error) continue
        try {
          const status = await jobsApi.manualStatus(item.jobId)
          if (status.status === 'FAILED') {
            processingStore.set((prev) =>
              prev.map((p) => (p.jobId === item.jobId ? { ...p, error: status.error ?? 'Parsing failed' } : p)),
            )
          } else if (status.status === 'COMPLETED') {
            const job = await jobsApi.get(item.jobId)
            if (job.evaluation) {
              processingStore.set((prev) => prev.filter((p) => p.jobId !== item.jobId))
              notifyJobsChanged()
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
            onRescored={rescored}
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
          <EmptyState variant="inline">No jobs match your search.</EmptyState>
        ) : !searching && empty ? (
          <EmptyState>
            {profileId === null
              ? 'Add your work history first; a candidate profile is built from it and scraped jobs are scored against it.'
              : 'No evaluated jobs yet. New jobs appear here automatically once they are scraped and scored.'}
          </EmptyState>
        ) : (
          <ul className="job-list">
            {shownProcessing.map((p) => (
              <li
                key={`processing-${p.jobId}`}
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
                  onRescored={rescored}
                  onOpenCompany={setCompanyId}
                />
              )
            })}
          </ul>
        )}

        <div ref={sentinel} className="sentinel">
          {(searching ? resultsLoading : loading) && <span className="spinner" aria-hidden="true" />}
          {!searching && !hasMore && feed.length > 0 && (
            <EmptyState variant="inline">All jobs loaded.</EmptyState>
          )}
        </div>
      </div>

      {!detailOpen && (
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
