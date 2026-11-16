import { type FormEvent, useEffect, useState } from 'react'
import { sourcesApi, type Source } from '../sources/api.ts'
import { useScrapeJob } from './useScrapeJob.ts'

function optionLabel(s: Source): string {
  if (s.module_error) return `${s.name} (broken)`
  if (!s.enabled) return `${s.name} (disabled)`
  return s.name
}

export default function ScrapePanel() {
  const [sources, setSources] = useState<Source[]>([])
  const [source, setSource] = useState<string>('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const { job, error, done, running, submitting, start, reset } = useScrapeJob()

  useEffect(() => {
    sourcesApi
      .list()
      .then(setSources)
      .catch((e) => setLoadError(`Could not load sources: ${String(e)}`))
  }, [])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    start(source || null)
  }

  const result = job?.status === 'finished' ? job.result : null
  const shownError = error ?? loadError

  return (
    <>
      <h1 className="title">Job scraper</h1>
      <p>
        Run a scraper source in the background and list the jobs it found. "All sources" runs
        every enabled source; a disabled source can still be run by picking it here.
      </p>

      <form onSubmit={submit} className="upload">
        <select value={source} onChange={(e) => setSource(e.target.value)} disabled={submitting}>
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s.key} value={s.key} disabled={!!s.module_error}>
              {optionLabel(s)}
            </option>
          ))}
        </select>
        <button type="submit" disabled={running}>
          {submitting ? 'Starting…' : 'Scrape'}
        </button>
        {(job || error) && (
          <button type="button" className="secondary" onClick={reset}>
            Reset
          </button>
        )}
      </form>

      {shownError && <p className="error">{shownError}</p>}

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
                    <tr><th>Link</th><th>Source</th></tr>
                  </thead>
                  <tbody>
                    {result.jobs.map((j) => (
                      <tr key={j.link}>
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
