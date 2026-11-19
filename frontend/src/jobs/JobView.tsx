import { useEffect, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { type EvaluatedJob, type EvaluatedJobDetail, jobsApi } from './api.ts'
import RelevanceMeter from './RelevanceMeter.tsx'
import '../applications/applications.css'
import { type Application, applicationsApi, currentEvent, isAutoEvent } from '../applications/api.ts'
import StatusBadge from '../applications/StatusBadge.tsx'
import { describeError } from '../cv/api.ts'
import CreateApplicationButton from './CreateApplicationButton.tsx'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import { pageHref } from '../shell/nav.ts'

/** The job's application, or a button to create one. */
function JobApplicationSection({
  applicationId,
  evaluationId,
  onCreated,
}: {
  applicationId: number | null
  /** The evaluation an application would be created from; none means it cannot be created here. */
  evaluationId: number | null
  onCreated: (applicationId: number) => void
}) {
  const [application, setApplication] = useState<Application | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (applicationId == null) return
    const controller = new AbortController()
    applicationsApi
      .get(applicationId, controller.signal)
      .then(setApplication)
      .catch((e) => {
        if (!controller.signal.aborted) setError(`Could not load the application: ${describeError(e)}`)
      })
    return () => controller.abort()
  }, [applicationId])

  if (applicationId == null && evaluationId == null) return null

  return (
    <div className="job-application">
      <h3>Application</h3>
      {applicationId != null ? (
        application ? (
          <div className="app-buttons">
            <StatusBadge status={application.status} auto={isAutoEvent(currentEvent(application))} />
            <a href={pageHref('applications', application.id)}>Open application #{application.id}</a>
          </div>
        ) : (
          !error && <span className="spinner" aria-hidden="true" />
        )
      ) : (
        evaluationId != null && <CreateApplicationButton evaluationId={evaluationId} onCreated={onCreated} />
      )}
      {error && <p className="error">{error}</p>}
    </div>
  )
}

type Props = {
  jobId: number
  /** The job as shown in the list, for an instant header while the details load. */
  initial: EvaluatedJob | null
  onBack: () => void
  onOpenCompany: (companyId: number) => void
  onApplicationCreated: (applicationId: number) => void
  /** Reports the job's title once known (for the breadcrumb), or null when it could not be loaded. */
  onTitle: (title: string | null) => void
}

/** Full details of one evaluated job, shown in place of the list. */
export default function JobView({ jobId, initial, onBack, onOpenCompany, onApplicationCreated, onTitle }: Props) {
  const [detail, setDetail] = useState<EvaluatedJobDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [html, setHtml] = useState<string | null>(null)
  const [htmlError, setHtmlError] = useState<string | null>(null)
  // Created from this view; the list copy catches up through onApplicationCreated.
  const [createdId, setCreatedId] = useState<number | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    jobsApi
      .get(jobId)
      .then((data) => {
        if (!controller.signal.aborted) setDetail(data)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(describeError(e))
      })
    return () => controller.abort()
  }, [jobId])

  const job = detail ?? initial
  const title = job ? (job.title ?? 'Untitled job') : null
  const failed = error !== null && !job
  useEffect(() => {
    onTitle(failed ? null : title)
  }, [title, failed, onTitle])

  const showHtml = async () => {
    if (html !== null) {
      setHtml(null)
      return
    }
    try {
      const raw = await jobsApi.raw(jobId)
      setHtml(raw.html ?? '')
    } catch (e) {
      setHtmlError(describeError(e))
    }
  }

  const back = (
    <button type="button" className="secondary small detail-back" onClick={onBack}>
      <ArrowLeft size={15} aria-hidden="true" /> Back to jobs
    </button>
  )

  if (!job) {
    return (
      <div className="detail-view detail-status">
        {error ? (
          <>
            <p className="error">Could not load the job: {error}</p>
            {back}
          </>
        ) : (
          <span className="spinner" aria-hidden="true" />
        )}
      </div>
    )
  }

  const evaluation = detail ? detail.evaluation : (initial?.evaluation ?? null)
  const applicationId = createdId ?? job.application_id

  return (
    <article className="detail-view job-view" aria-labelledby={`job-${job.id}`}>
      {back}
      <div className="detail-card">
        <div className="job-dialog-head">
          <div className="job-main">
            <h2 id={`job-${job.id}`}>{title}</h2>
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
              {job.scrape_run_id != null && <span>run #{job.scrape_run_id}</span>}
            </div>
          </div>
        </div>

        <dl className="job-facts">
          {evaluation && (
            <>
              <dt>Relevance</dt>
              <dd>
                <RelevanceMeter relevance={evaluation.relevance} />
                {evaluation.model && <span className="muted">{evaluation.model}</span>}
              </dd>
              <dt>Evaluated</dt>
              <dd>{new Date(evaluation.created_at).toLocaleString()}</dd>
            </>
          )}
          <dt>Parsed</dt>
          <dd>{new Date(job.parsed_at).toLocaleString()}</dd>
          <dt>Link</dt>
          <dd>
            <a href={job.link} target="_blank" rel="noreferrer">
              {job.link}
            </a>
          </dd>
        </dl>

        <JobApplicationSection
          applicationId={applicationId}
          evaluationId={evaluation?.id ?? null}
          onCreated={(id) => {
            setCreatedId(id)
            onApplicationCreated(id)
          }}
        />

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
    </article>
  )
}
