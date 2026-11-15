import { useCallback, useEffect, useRef, useState } from 'react'

const JOBS_API = '/api/jobs'
const PAGE_SIZE = 50
const THRESHOLD_KEY = 'jobs.matchThreshold'
const DEFAULT_THRESHOLD = 70

export type JobEvaluation = {
  id: number
  candidate_profile_id: number
  match_probability: number
  model: string | null
  created_at: string
}

export type EvaluatedJob = {
  id: number
  link: string
  source: string
  scrape_run_id: number | null
  has_html: boolean
  title: string | null
  company: string | null
  parsed_at: string
  evaluation: JobEvaluation
}

type EvaluatedJobDetail = Omit<EvaluatedJob, 'evaluation'> & {
  description: string | null
  evaluation: JobEvaluation | null
}

type JobPage = {
  items: EvaluatedJob[]
  total: number
  offset: number
  limit: number
  has_more: boolean
  candidate_profile_id: number | null
}

type SortOrder = 'newest' | 'match'

function percent(probability: number): number {
  return Math.round(probability * 100)
}

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

function ScoreBadge({ probability, threshold }: { probability: number; threshold: number }) {
  const value = percent(probability)
  return (
    <span
      className={value >= threshold ? 'score match' : 'score'}
      title={`${value}% match (threshold ${threshold}%)`}
    >
      {value}%
    </span>
  )
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
    <li className={matching ? 'job-item match' : 'job-item'}>
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

function JobDialog({
  job,
  threshold,
  onClose,
}: {
  job: EvaluatedJob
  threshold: number
  onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [detail, setDetail] = useState<EvaluatedJobDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [html, setHtml] = useState<string | null>(null)
  const [htmlError, setHtmlError] = useState<string | null>(null)

  useEffect(() => {
    const el = dialog.current
    if (!el) return
    el.showModal()
    return () => el.close()
  }, [])

  useEffect(() => {
    let cancelled = false
    fetch(`${JOBS_API}/${job.id}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return (await res.json()) as EvaluatedJobDetail
      })
      .then((data) => {
        if (!cancelled) setDetail(data)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [job.id])

  const showHtml = async () => {
    if (html !== null) {
      setHtml(null)
      return
    }
    try {
      const res = await fetch(`${JOBS_API}/raw/${job.id}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const raw: { html: string | null } = await res.json()
      setHtml(raw.html ?? '')
    } catch (e) {
      setHtmlError(String(e))
    }
  }

  const evaluation = detail?.evaluation ?? job.evaluation

  return (
    <dialog
      ref={dialog}
      className="job-dialog"
      onClose={onClose}
      onClick={(e) => {
        // Clicks on the backdrop land on the dialog element itself.
        if (e.target === dialog.current) onClose()
      }}
    >
      <div className="job-dialog-body">
        <div className="job-dialog-head">
          <div className="job-main">
            <h2>{job.title ?? 'Untitled job'}</h2>
            <div className="job-meta">
              {job.company && <span className="job-company">{job.company}</span>}
              <span>{job.source}</span>
              {job.scrape_run_id != null && <span>run #{job.scrape_run_id}</span>}
            </div>
          </div>
          <button type="button" className="secondary small" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <dl className="job-facts">
          <dt>Match</dt>
          <dd>
            <ScoreBadge probability={evaluation.match_probability} threshold={threshold} />
            {evaluation.model && <span className="muted">{evaluation.model}</span>}
          </dd>
          <dt>Evaluated</dt>
          <dd>{new Date(evaluation.created_at).toLocaleString()}</dd>
          <dt>Parsed</dt>
          <dd>{new Date(job.parsed_at).toLocaleString()}</dd>
          <dt>Link</dt>
          <dd>
            <a href={job.link} target="_blank" rel="noreferrer">
              {job.link}
            </a>
          </dd>
        </dl>

        {error && <p className="error">Could not load job details: {error}</p>}
        {!detail && !error && <span className="spinner" aria-hidden="true" />}
        {detail && (
          <div className="job-desc">
            {detail.description ? (
              <pre className="description">{detail.description}</pre>
            ) : (
              <p className="muted">No parsed description.</p>
            )}
          </div>
        )}

        {job.has_html && (
          <div className="job-html">
            <button type="button" className="secondary small" onClick={showHtml}>
              {html !== null ? 'Hide raw html' : 'Raw html'}
            </button>
            {htmlError && <p className="error">{htmlError}</p>}
            {html !== null && <pre>{html}</pre>}
          </div>
        )}
      </div>
    </dialog>
  )
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<EvaluatedJob[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [profileId, setProfileId] = useState<number | null>(null)
  const [hasMore, setHasMore] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sort, setSort] = useState<SortOrder>('newest')
  const [threshold, setThreshold] = useState<number>(loadThreshold)
  const [selected, setSelected] = useState<EvaluatedJob | null>(null)
  const sentinel = useRef<HTMLDivElement>(null)
  // Mirrors of state for the observer callback so it never reads stale values.
  const loadingRef = useRef(false)
  const offsetRef = useRef(0)
  const hasMoreRef = useRef(true)
  const sortRef = useRef<SortOrder>('newest')

  const loadMore = useCallback(async () => {
    if (loadingRef.current || !hasMoreRef.current) return
    loadingRef.current = true
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        offset: String(offsetRef.current),
        limit: String(PAGE_SIZE),
        sort: sortRef.current,
      })
      const res = await fetch(`${JOBS_API}?${params}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const page: JobPage = await res.json()
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

  const changeSort = (next: SortOrder) => {
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

  const matchingCount = jobs.filter((j) => percent(j.evaluation.match_probability) >= threshold).length

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
          <select value={sort} onChange={(e) => changeSort(e.target.value as SortOrder)}>
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
        <ul className="job-list">
          {jobs.map((job) => (
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
