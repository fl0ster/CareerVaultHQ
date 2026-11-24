import { useEffect, useState } from 'react'
import { ArrowLeft, ArrowUpRight, ExternalLink } from 'lucide-react'
import { type EvaluatedJob, type EvaluatedJobDetail, jobsApi } from './api.ts'
import RelevanceMeter from './RelevanceMeter.tsx'
import '../applications/applications.css'
import { type Application, applicationsApi, currentEvent, isAutoEvent } from '../applications/api.ts'
import StatusBadge from '../applications/StatusBadge.tsx'
import { describeError } from '../cv/api.ts'
import CreateApplicationButton from './CreateApplicationButton.tsx'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import { pageHref } from '../shell/nav.ts'
import TechPills from './TechPills.tsx'

/** Top-right of the job header: the application's status pill (a link to it), or an
 * "Apply" pill that creates one. */
function JobApplicationPill({
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

  if (applicationId == null) {
    if (evaluationId == null) return null
    return (
      <div className="job-apply-pill">
        <CreateApplicationButton evaluationId={evaluationId} onCreated={onCreated} />
      </div>
    )
  }

  return (
    <div className="job-apply-pill">
      <a
        className="job-application-link"
        href={pageHref('applications', applicationId)}
        title={error ?? `Open application #${applicationId}`}
      >
        {application ? (
          <StatusBadge status={application.status} auto={isAutoEvent(currentEvent(application))} />
        ) : error ? (
          <span className="badge">Application #{applicationId}</span>
        ) : (
          <span className="spinner" aria-hidden="true" />
        )}
        <ArrowUpRight size={14} aria-hidden="true" />
        <span className="sr-only">Open application #{applicationId}</span>
      </a>
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
  /** The job was re-scored against the latest profile from this view. */
  onRescored: (job: EvaluatedJobDetail) => void
  /** Reports the job's title once known (for the breadcrumb), or null when it could not be loaded. */
  onTitle: (title: string | null) => void
}

/** Full details of one evaluated job, shown in place of the list. */
export default function JobView({
  jobId,
  initial,
  onBack,
  onOpenCompany,
  onApplicationCreated,
  onRescored,
  onTitle,
}: Props) {
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
  const technologies = detail?.technologies ?? []

  return (
    <article className="detail-view job-view" aria-labelledby={`job-${job.id}`}>
      {back}
      <div className="detail-card">
        <header className="job-view-head">
          <div className="job-main">
            <div className="detail-title">
              {evaluation && (
                <RelevanceMeter
                  relevance={evaluation.relevance}
                  outdated={evaluation.outdated}
                  explanation={evaluation.explanation}
                  jobId={job.id}
                  onRescored={(fresh) => {
                    setDetail(fresh)
                    onRescored(fresh)
                  }}
                />
              )}
              <h2 id={`job-${job.id}`}>{title}</h2>
            </div>
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
              <a className="job-posting-link" href={job.link} target="_blank" rel="noreferrer">
                Job posting <ExternalLink size={12} aria-hidden="true" />
              </a>
            </div>
          </div>
          <JobApplicationPill
            applicationId={applicationId}
            evaluationId={evaluation?.id ?? null}
            onCreated={(id) => {
              setCreatedId(id)
              onApplicationCreated(id)
            }}
          />
        </header>

        <TechPills technologies={technologies} />

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
