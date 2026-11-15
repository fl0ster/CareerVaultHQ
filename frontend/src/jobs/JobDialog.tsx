import { useEffect, useRef, useState } from 'react'
import { type EvaluatedJob, type EvaluatedJobDetail, jobsApi } from './api.ts'
import ScoreBadge from './ScoreBadge.tsx'
import '../cv/cv.css'
import { cvApi, describeError, type GeneratedCv, isInProgress } from '../cv/api.ts'
import CvActions from '../cv/CvActions.tsx'
import CvStatusBadge from '../cv/CvStatusBadge.tsx'

const CV_POLL_MS = 3000

/** "Generate CV" button plus the CVs already generated for this job, kept fresh while
 * any of them is still being generated. */
function JobCvSection({ jobId }: { jobId: number }) {
  const [cvs, setCvs] = useState<GeneratedCv[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    cvApi
      .list({ job_id: jobId, limit: 20 }, controller.signal)
      .then((page) => {
        setCvs(page.items)
        setError(null)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(`Could not load generated CVs: ${describeError(e)}`)
      })
    return () => controller.abort()
  }, [jobId, tick])

  const pending = cvs?.some(isInProgress) ?? false
  useEffect(() => {
    if (!pending) return
    const timer = window.setTimeout(() => setTick((t) => t + 1), CV_POLL_MS)
    return () => window.clearTimeout(timer)
  }, [pending, tick])

  const generate = async () => {
    setGenerating(true)
    setError(null)
    try {
      const cv = await cvApi.generate(jobId)
      setCvs((prev) => [cv, ...(prev ?? [])])
    } catch (e) {
      setError(describeError(e))
    } finally {
      setGenerating(false)
    }
  }

  const latest = cvs?.[0]
  return (
    <div className="job-cv">
      <h3>CV for this job</h3>
      <div className="job-cv-controls">
        <button type="button" className="small" onClick={generate} disabled={generating || pending}>
          {generating ? 'Requesting…' : pending ? 'Generating…' : cvs?.length ? 'Generate CV again' : 'Generate CV'}
        </button>
        {cvs === null && !error && <span className="spinner" aria-hidden="true" />}
        {latest && latest.status === 'finished' && (
          <span className="muted">
            Latest: {latest.headline_role ?? 'ready'}
            {latest.core_technologies.length > 0 && ` · ${latest.core_technologies.join(' · ')}`}
          </span>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {cvs && cvs.length > 0 && (
        <ul className="cv-list">
          {cvs.map((cv) => (
            <li key={cv.id} className="cv-item">
              <div className="cv-head">
                <div className="cv-main">
                  <div className="cv-meta">
                    <CvStatusBadge status={cv.status} />
                    <span>#{cv.id}</span>
                    <span>{new Date(cv.created_at).toLocaleString()}</span>
                  </div>
                  {cv.status === 'failed' && cv.error && <pre className="error cv-inline-error">{cv.error}</pre>}
                  {cv.warnings.length > 0 && (
                    <div className="muted">{cv.warnings.length} step(s) kept the original text; see the Generated CV tab.</div>
                  )}
                </div>
                <CvActions cv={cv} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

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

        <JobCvSection jobId={job.id} />

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
