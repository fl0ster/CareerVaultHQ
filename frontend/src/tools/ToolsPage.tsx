import { type FormEvent, useEffect, useRef, useState } from 'react'
import './tools.css'
import { isTerminal, latexApi, type LatexJobInfo } from './api.ts'
import ScrapePanel from './ScrapePanel.tsx'

export default function ToolsPage() {
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [job, setJob] = useState<LatexJobInfo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const jobId = job?.job_id
  const done = job ? isTerminal(job.status) : false

  // Follow the job: SSE first, polling as a fallback.
  useEffect(() => {
    if (!jobId || done) return
    let cancelled = false
    let timer: number | undefined

    const poll = async () => {
      try {
        const info = await latexApi.getJob(jobId)
        if (cancelled) return
        setJob(info)
        if (!isTerminal(info.status)) timer = window.setTimeout(poll, 1000)
      } catch (e) {
        if (!cancelled) setError(`Could not fetch job status: ${String(e)}`)
      }
    }

    const es = new EventSource(latexApi.eventsUrl(jobId))
    es.addEventListener('status', (ev) => {
      const info: LatexJobInfo = JSON.parse((ev as MessageEvent).data)
      setJob(info)
      if (isTerminal(info.status)) es.close()
    })
    es.onerror = () => {
      es.close()
      if (!cancelled) poll()
    }

    return () => {
      cancelled = true
      es.close()
      if (timer) window.clearTimeout(timer)
    }
  }, [jobId, done])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!file) return
    setError(null)
    setJob(null)
    setSubmitting(true)
    try {
      const accepted = await latexApi.compile(file)
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
    setFile(null)
    if (fileInput.current) fileInput.current.value = ''
  }

  const pdfUrl = jobId ? latexApi.pdfUrl(jobId) : null

  return (
    <>
      <h1 className="title">LaTeX → PDF</h1>
      <p>Upload a .tex file and compile it via the API.</p>

      <form onSubmit={submit} className="upload">
        <input
          ref={fileInput}
          type="file"
          accept=".tex,text/x-tex"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          disabled={submitting}
        />
        <button type="submit" disabled={!file || submitting}>
          {submitting ? 'Uploading…' : 'Compile'}
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
            <dd>{job.source ?? '—'}</dd>
            <dt>Status</dt>
            <dd>
              <span className={`badge ${job.status}`}>{job.status}</span>
              {!done && <span className="spinner" aria-hidden="true" />}
            </dd>
            {job.enqueued_at && (<><dt>Enqueued</dt><dd>{new Date(job.enqueued_at).toLocaleTimeString()}</dd></>)}
            {job.started_at && (<><dt>Started</dt><dd>{new Date(job.started_at).toLocaleTimeString()}</dd></>)}
            {job.ended_at && (<><dt>Ended</dt><dd>{new Date(job.ended_at).toLocaleTimeString()}</dd></>)}
          </dl>

          {job.status === 'finished' && pdfUrl && (
            <div className="result">
              <a className="button" href={pdfUrl} target="_blank" rel="noreferrer">
                Open PDF
              </a>
              <a className="button secondary" href={pdfUrl} download>
                Download
              </a>
            </div>
          )}

          {job.status === 'failed' && (
            <div className="result">
              <h2>Compilation failed</h2>
              <pre>{job.error ?? 'No error output available.'}</pre>
            </div>
          )}
        </section>
      )}

      <hr className="divider" />

      <ScrapePanel />
    </>
  )
}
