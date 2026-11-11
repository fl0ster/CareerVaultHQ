import {type FormEvent, useEffect, useState} from "react";

const SCRAPE_API = '/api/scrape'

type ScrapedJob = { link: string; date_added: string; source: string }

type ScrapeResult = {
  sources: { source: string; ok: boolean; error: string | null; jobs: ScrapedJob[] }[]
  failed: string[]
  jobs: ScrapedJob[]
  count: number
}

type ScrapeJobInfo = {
  job_id: string
  status: string
  source?: string | null
  enqueued_at?: string | null
  started_at?: string | null
  ended_at?: string | null
  count?: number | null
  result?: ScrapeResult | null
  error?: string | null
}

const TERMINAL = new Set(['finished', 'failed', 'stopped', 'canceled'])

export default function ScrapePanel() {
  const [sources, setSources] = useState<string[]>([])
  const [source, setSource] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [job, setJob] = useState<ScrapeJobInfo | null>(null)
  const [error, setError] = useState<string | null>(null)

  const jobId = job?.job_id
  const done = job ? TERMINAL.has(job.status) : false

  useEffect(() => {
    fetch(`${SCRAPE_API}/sources`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((list: string[]) => setSources(list))
      .catch((e) => setError(`Could not load sources: ${String(e)}`))
  }, [])

  // Poll the scrape job until it reaches a terminal state.
  useEffect(() => {
    if (!jobId || done) return
    let cancelled = false
    let timer: number | undefined

    const poll = async () => {
      try {
        const res = await fetch(`${SCRAPE_API}/jobs/${jobId}`)
        if (!res.ok) throw new Error(`status ${res.status}`)
        const info: ScrapeJobInfo = await res.json()
        if (cancelled) return
        setJob(info)
        if (!TERMINAL.has(info.status)) timer = window.setTimeout(poll, 1000)
      } catch (e) {
        if (!cancelled) setError(`Could not fetch job status: ${String(e)}`)
      }
    }
    poll()

    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [jobId, done])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setJob(null)
    setSubmitting(true)
    try {
      const res = await fetch(SCRAPE_API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: source || null }),
      })
      if (!res.ok) {
        const detail = await res.json().catch(() => null)
        throw new Error(detail?.detail ?? `HTTP ${res.status}`)
      }
      const accepted = await res.json()
      setJob({ job_id: accepted.job_id, status: accepted.status, source: accepted.source })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const reset = () => {
    setJob(null)
    setError(null)
  }

  const result = job?.status === 'finished' ? job.result : null

  return (
    <>
      <h1 className="title">Job scraper</h1>
      <p>Run a scraper source in the background and list the jobs it found.</p>

      <form onSubmit={submit} className="upload">
        <select value={source} onChange={(e) => setSource(e.target.value)} disabled={submitting}>
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <button type="submit" disabled={submitting || (!!job && !done)}>
          {submitting ? 'Starting…' : 'Scrape'}
        </button>
        {(job || error) && (
          <button type="button" className="secondary" onClick={reset}>
            Reset
          </button>
        )}
      </form>

      {error && <p className="error">{error}</p>}

      {job && (
        <section className="job">
          <dl>
            <dt>Job</dt>
            <dd><code>{job.job_id}</code></dd>
            <dt>Source</dt>
            <dd>{job.source ?? 'all'}</dd>
            <dt>Status</dt>
            <dd>
              <span className={`badge ${job.status}`}>{job.status}</span>
              {!done && <span className="spinner" aria-hidden="true" />}
            </dd>
            {job.enqueued_at && (<><dt>Enqueued</dt><dd>{new Date(job.enqueued_at).toLocaleTimeString()}</dd></>)}
            {job.started_at && (<><dt>Started</dt><dd>{new Date(job.started_at).toLocaleTimeString()}</dd></>)}
            {job.ended_at && (<><dt>Ended</dt><dd>{new Date(job.ended_at).toLocaleTimeString()}</dd></>)}
            {job.status === 'finished' && (<><dt>Scraped</dt><dd>{job.count ?? 0} jobs</dd></>)}
          </dl>

          {result && (
            <div className="result">
              {result.failed.length > 0 && (
                <p className="error">Failed sources: {result.failed.join(', ')}</p>
              )}
              {result.sources.filter((s) => !s.ok).map((s) => (
                <pre key={s.source}>{s.source}: {s.error}</pre>
              ))}
              {result.jobs.length === 0 ? (
                <p>No jobs found.</p>
              ) : (
                <table className="jobs">
                  <thead>
                    <tr><th>Date</th><th>Source</th><th>Link</th></tr>
                  </thead>
                  <tbody>
                    {result.jobs.map((j) => (
                      <tr key={j.link}>
                        <td>{j.date_added || '—'}</td>
                        <td><a href={j.link} target="_blank" rel="noreferrer">{j.link}</a></td>
                        <td>{j.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {job.status === 'failed' && (
            <div className="result">
              <h2>Scrape failed</h2>
              <pre>{job.error ?? 'No error output available.'}</pre>
            </div>
          )}
        </section>
      )}
    </>
  )
}