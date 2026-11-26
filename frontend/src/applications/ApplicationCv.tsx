import { useEffect, useState } from 'react'
import { FileDown, FilePlus, FileX, RefreshCw } from 'lucide-react'
import { type GeneratedCv, cvApi, describeError, isInProgress } from '../cv/api.ts'
import { type Application, applicationsApi } from './api.ts'

type Props = {
  application: Application
  onChange: (application: Application) => void
}

const formatCreated = (cv: GeneratedCv) =>
  new Date(cv.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

/** The CV section of the application's left column: downloads the latest CV (or generates
 * one when there is none or the last attempt failed, spinning meanwhile), generates a new one,
 * and lists the earlier finished CVs of the job for download. */
export default function ApplicationCv({ application, onChange }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  /** Earlier finished CVs of the job, newest first (`undefined` while loading). */
  const [earlier, setEarlier] = useState<GeneratedCv[] | undefined>(undefined)
  const [showEarlier, setShowEarlier] = useState(false)
  const cv = application.cv
  const generating = busy || (cv != null && isInProgress(cv))

  const jobId = application.job.id
  const latestId = cv?.id ?? null
  useEffect(() => {
    const controller = new AbortController()
    cvApi
      .list({ job_id: jobId, limit: 100 }, controller.signal)
      .then((page) => setEarlier(page.items.filter((c) => c.id !== latestId && c.status === 'finished')))
      .catch(() => {
        // Optional extra: without it only the latest CV is offered.
        if (!controller.signal.aborted) setEarlier([])
      })
    return () => controller.abort()
  }, [jobId, latestId])

  const generate = async () => {
    setBusy(true)
    setError(null)
    try {
      onChange(await applicationsApi.regenerateCv(application.id))
    } catch (e) {
      setError(describeError(e))
    } finally {
      setBusy(false)
    }
  }

  let main
  if (generating) {
    main = (
      <span className="app-cv-main generating" role="status" title="Generating the CV…">
        <span className="spinner" aria-hidden="true" />
        <span className="app-cv-text">Generating…</span>
      </span>
    )
  } else if (cv?.status === 'finished') {
    main = (
      <a className="app-cv-main ready" href={cvApi.pdfUrl(cv.id)} download title="Download the latest CV (PDF)">
        <FileDown size={16} aria-hidden="true" />
        <span className="app-cv-text">Download latest</span>
      </a>
    )
  } else {
    const failed = cv?.status === 'failed'
    main = (
      <button
        type="button"
        className={`app-cv-main${failed ? ' failed' : ''}`}
        onClick={generate}
        title={failed ? `CV generation failed${cv?.error ? `: ${cv.error}` : ''}. Click to try again.` : 'Generate a CV for this job'}
      >
        {failed ? <FileX size={16} aria-hidden="true" /> : <FilePlus size={16} aria-hidden="true" />}
        <span className="app-cv-text">{failed ? 'Retry CV' : 'Generate CV'}</span>
      </button>
    )
  }

  return (
    <section className="app-section app-cv" aria-labelledby={`app-cv-${application.id}`}>
      <h3 id={`app-cv-${application.id}`}>CV</h3>
      <div className="app-cv-control">
        {main}
        {cv?.status === 'finished' && !generating && (
          <button
            type="button"
            className="app-cv-info"
            onClick={generate}
            title="Generate a new CV"
            aria-label="Generate a new CV"
          >
            <RefreshCw size={14} aria-hidden="true" />
          </button>
        )}
      </div>
      {earlier && earlier.length > 0 && (
        <div className="app-cv-earlier">
          <button
            type="button"
            className="app-cv-toggle"
            aria-expanded={showEarlier}
            onClick={() => setShowEarlier((v) => !v)}
          >
            {showEarlier ? 'Hide earlier versions' : `Earlier versions (${earlier.length})`}
          </button>
          {showEarlier && (
            <ul>
              {earlier.map((c) => (
                <li key={c.id}>
                  <a href={cvApi.pdfUrl(c.id)} download title={`Download CV #${c.id} (PDF)`}>
                    <FileDown size={13} aria-hidden="true" /> {formatCreated(c)}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {error && <p className="error app-cv-error">{error}</p>}
    </section>
  )
}
