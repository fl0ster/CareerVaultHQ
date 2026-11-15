import { useEffect, useRef, useState } from 'react'
import { type EvaluatedJob, type EvaluatedJobDetail, jobsApi } from './api.ts'
import ScoreBadge from './ScoreBadge.tsx'

type Props = {
  job: EvaluatedJob
  threshold: number
  onClose: () => void
}

export default function JobDialog({ job, threshold, onClose }: Props) {
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
    jobsApi
      .get(job.id)
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
      const raw = await jobsApi.raw(job.id)
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
