import { type RefObject, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import './jobs.css'
import { type EvaluatedJob, type JobSortOrder, jobsApi, percent } from './api.ts'
import JobDialog from './JobDialog.tsx'
import ScoreBadge from './ScoreBadge.tsx'

const PAGE_SIZE = 50
const THRESHOLD_KEY = 'jobs.matchThreshold'
const DEFAULT_THRESHOLD = 70

function loadThreshold(): number {
  try {
    const raw = localStorage.getItem(THRESHOLD_KEY)
    const value = raw === null ? NaN : Number(raw)
    if (Number.isFinite(value) && value >= 0 && value <= 100) return value
  } catch {
    /* storage unavailable, use the default */
  }
  return DEFAULT_THRESHOLD
}

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
 * glide starts from where the row visually is, so rapid slider drags stay smooth.
 */
function useFlip(listRef: RefObject<HTMLUListElement | null>, order: string) {
  const previous = useRef(new Map<string, number>())

  useLayoutEffect(() => {
    const list = listRef.current
    if (!list) return
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

function JobRow({
  job,
  threshold,
  onSelect,
}: {
  job: EvaluatedJob
  threshold: number
  onSelect: (job: EvaluatedJob) => void
}) {
  const matching = percent(job.evaluation.match_probability) >= threshold
  return (
    <li className={matching ? 'job-item match' : 'job-item'} data-key={String(job.id)}>
      <button type="button" className="job-row" onClick={() => onSelect(job)}>
        <div className="job-main">
          <span className="job-title">{job.title ?? job.link}</span>
          <div className="job-meta">
            {job.company && <span className="job-company">{job.company}</span>}
            <span>{job.source}</span>
            <span>evaluated {new Date(job.evaluation.created_at).toLocaleDateString()}</span>
          </div>
        </div>
        <ScoreBadge probability={job.evaluation.match_probability} threshold={threshold} />
      </button>
    </li>
  )
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<EvaluatedJob[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [profileId, setProfileId] = useState<number | null>(null)
  const [hasMore, setHasMore] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sort, setSort] = useState<JobSortOrder>('newest')
  const [threshold, setThreshold] = useState<number>(loadThreshold)
  const [selected, setSelected] = useState<EvaluatedJob | null>(null)
  const sentinel = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  // Mirrors of state for the observer callback so it never reads stale values.
  const loadingRef = useRef(false)
  const offsetRef = useRef(0)
  const hasMoreRef = useRef(true)
  const sortRef = useRef<JobSortOrder>('newest')

  const loadMore = useCallback(async () => {
    if (loadingRef.current || !hasMoreRef.current) return
    loadingRef.current = true
    setLoading(true)
    setError(null)
    try {
      const page = await jobsApi.list({ offset: offsetRef.current, limit: PAGE_SIZE, sort: sortRef.current })
      offsetRef.current += page.items.length
      hasMoreRef.current = page.has_more
      setJobs((prev) => [...prev, ...page.items])
      setTotal(page.total)
      setProfileId(page.candidate_profile_id)
      setHasMore(page.has_more)
    } catch (e) {
      setError(`Could not load jobs: ${String(e)}`)
    } finally {
      loadingRef.current = false
      setLoading(false)
    }
  }, [])

  const reload = useCallback(() => {
    offsetRef.current = 0
    hasMoreRef.current = true
    setJobs([])
    setTotal(null)
    setHasMore(true)
    loadMore()
  }, [loadMore])

  const changeSort = (next: JobSortOrder) => {
    sortRef.current = next
    setSort(next)
    reload()
  }

  const changeThreshold = (next: number) => {
    setThreshold(next)
    try {
      localStorage.setItem(THRESHOLD_KEY, String(next))
    } catch {
      /* storage unavailable, keep it for this session only */
    }
  }

  // Load the next page whenever the sentinel below the list scrolls into view.
  useEffect(() => {
    const el = sentinel.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadMore()
      },
      { rootMargin: '400px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [loadMore])

  // Matching jobs go first; each group keeps the server order (newest first by ID).
  const isMatch = (j: EvaluatedJob) => percent(j.evaluation.match_probability) >= threshold
  const matchingJobs = jobs.filter(isMatch)
  const orderedJobs = [...matchingJobs, ...jobs.filter((j) => !isMatch(j))]
  const matchingCount = matchingJobs.length
  useFlip(listRef, orderedJobs.map((j) => j.id).join(','))

  return (
    <>
      <h1 className="title">Evaluated jobs</h1>
      <p>
        {total === null
          ? 'Loading…'
          : profileId === null
            ? 'No candidate profile yet.'
            : `${jobs.length} of ${total} jobs scored against profile #${profileId}, ${matchingCount} loaded at or above the threshold.`}{' '}
        <button type="button" className="secondary small" onClick={reload} disabled={loading}>
          Refresh
        </button>
      </p>

      <div className="jobs-controls">
        <label className="threshold">
          <span>
            Highlight matches ≥ <strong>{threshold}%</strong>
          </span>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={threshold}
            onChange={(e) => changeThreshold(Number(e.target.value))}
          />
        </label>
        <label>
          Sort{' '}
          <select value={sort} onChange={(e) => changeSort(e.target.value as JobSortOrder)}>
            <option value="newest">Newest evaluated</option>
            <option value="match">Best match</option>
          </select>
        </label>
      </div>

      {error && (
        <p className="error">
          {error}{' '}
          <button type="button" className="secondary small" onClick={loadMore}>
            Retry
          </button>
        </p>
      )}

      {total === 0 ? (
        <p>
          {profileId === null
            ? 'Create a candidate profile first; scraped jobs are then scored against it.'
            : 'No evaluated jobs yet. Run a scrape from the Tools tab and wait for the evaluation to finish.'}
        </p>
      ) : (
        <ul className="job-list" ref={listRef}>
          {orderedJobs.map((job) => (
            <JobRow key={job.id} job={job} threshold={threshold} onSelect={setSelected} />
          ))}
        </ul>
      )}

      <div ref={sentinel} className="sentinel">
        {loading && <span className="spinner" aria-hidden="true" />}
        {!hasMore && jobs.length > 0 && <span className="muted">All jobs loaded.</span>}
      </div>

      {selected && (
        <JobDialog
          key={selected.id}
          job={selected}
          threshold={threshold}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  )
}
