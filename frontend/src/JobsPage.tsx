import { useCallback, useEffect, useRef, useState } from 'react'

const JOBS_API = '/api/jobs'
const PAGE_SIZE = 50

export type StoredJob = {
  id: number
  link: string
  date_added: string
  source: string
  scraped_at: string
  scrape_run_id: number | null
  has_html: boolean
}

type JobPage = {
  items: StoredJob[]
  total: number
  offset: number
  limit: number
  has_more: boolean
}

type JobDetail = StoredJob & { html: string | null }

function JobRow({ job }: { job: StoredJob }) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<JobDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  const toggle = async () => {
    const next = !open
    setOpen(next)
    if (!next || detail || !job.has_html) return
    try {
      const res = await fetch(`${JOBS_API}/${job.id}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setDetail(await res.json())
    } catch (e) {
      setError(String(e))
    }
  }

  return (
    <li className="job-item">
      <div className="job-head">
        <div className="job-main">
          <a href={job.link} target="_blank" rel="noreferrer">{job.link}</a>
          <div className="job-meta">
            <span>{job.source}</span>
            {job.date_added && <span>posted {job.date_added}</span>}
            <span>scraped {new Date(job.scraped_at).toLocaleString()}</span>
            {job.scrape_run_id != null && <span>run #{job.scrape_run_id}</span>}
          </div>
        </div>
        {job.has_html && (
          <button type="button" className="secondary small" onClick={toggle}>
            {open ? 'Hide' : 'Html'}
          </button>
        )}
      </div>
      {open && job.has_html && (
        <div className="job-desc">
          {error && <p className="error">{error}</p>}
          {!detail && !error && <span className="spinner" aria-hidden="true" />}
          {detail && <pre>{detail.html}</pre>}
        </div>
      )}
    </li>
  )
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<StoredJob[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [hasMore, setHasMore] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sentinel = useRef<HTMLDivElement>(null)
  // Mirrors of state for the observer callback so it never reads stale values.
  const loadingRef = useRef(false)
  const offsetRef = useRef(0)
  const hasMoreRef = useRef(true)

  const loadMore = useCallback(async () => {
    if (loadingRef.current || !hasMoreRef.current) return
    loadingRef.current = true
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ offset: String(offsetRef.current), limit: String(PAGE_SIZE) })
      const res = await fetch(`${JOBS_API}?${params}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const page: JobPage = await res.json()
      offsetRef.current += page.items.length
      hasMoreRef.current = page.has_more
      setJobs((prev) => [...prev, ...page.items])
      setTotal(page.total)
      setHasMore(page.has_more)
    } catch (e) {
      setError(`Could not load jobs: ${String(e)}`)
    } finally {
      loadingRef.current = false
      setLoading(false)
    }
  }, [])

  const reload = () => {
    offsetRef.current = 0
    hasMoreRef.current = true
    setJobs([])
    setTotal(null)
    setHasMore(true)
    loadMore()
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

  return (
    <>
      <h1 className="title">Scraped jobs</h1>
      <p>
        {total === null ? 'Loading…' : `${jobs.length} of ${total} jobs, newest first.`}{' '}
        <button type="button" className="secondary small" onClick={reload} disabled={loading}>
          Refresh
        </button>
      </p>

      {error && (
        <p className="error">
          {error}{' '}
          <button type="button" className="secondary small" onClick={loadMore}>Retry</button>
        </p>
      )}

      {total === 0 ? (
        <p>No jobs yet. Run a scrape from the Tools tab.</p>
      ) : (
        <ul className="job-list">
          {jobs.map((job) => <JobRow key={job.id} job={job} />)}
        </ul>
      )}

      <div ref={sentinel} className="sentinel">
        {loading && <span className="spinner" aria-hidden="true" />}
        {!hasMore && jobs.length > 0 && <span className="muted">All jobs loaded.</span>}
      </div>
    </>
  )
}
