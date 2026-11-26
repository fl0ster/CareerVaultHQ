import { useEffect, useState } from 'react'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import { type Application, type ApplicationStatus } from './api.ts'
import ApplicationCv from './ApplicationCv.tsx'
import ApplicationDetail from './ApplicationDetail.tsx'
import { type EvaluatedJobDetail, jobsApi } from '../jobs/api.ts'
import RelevanceMeter from '../jobs/RelevanceMeter.tsx'
import '../jobs/jobs.css'

type Props = {
  application: Application
  statuses: ApplicationStatus[]
  onChange: (application: Application) => void
  /** The offer was accepted (the application is now `ACCEPTED`). */
  onAccepted: (application: Application) => void
  onDelete: (id: number) => void
  onOpenCompany: (companyId: number) => void
  onBack: () => void
  /** The job was re-scored from the relevance meter. */
  onRescored?: (job: EvaluatedJobDetail) => void
}

/** Full details of one application, shown in place of the list. */
export default function ApplicationView({
  application,
  statuses,
  onChange,
  onAccepted,
  onDelete,
  onOpenCompany,
  onBack,
  onRescored,
}: Props) {
  const { job, evaluation } = application

  // Technologies live on the job's parse result, which only the job detail carries.
  const [technologies, setTechnologies] = useState<string[]>([])
  useEffect(() => {
    const controller = new AbortController()
    jobsApi
      .get(job.id, controller.signal)
      .then((detail) => setTechnologies(detail.technologies ?? []))
      .catch(() => {
        /* the pills are optional: leave them out */
      })
    return () => controller.abort()
  }, [job.id])

  return (
    <article className="detail-view app-view" aria-labelledby={`application-${application.id}`}>
      <button type="button" className="secondary small detail-back" onClick={onBack}>
        <ArrowLeft size={15} aria-hidden="true" /> Back to applications
      </button>
      <div className="detail-card">
        <header className="job-dialog-head app-view-head">
          <div className="job-main">
            <div className="detail-title">
              {evaluation && (
                <RelevanceMeter
                  relevance={evaluation.relevance}
                  outdated={evaluation.outdated}
                  explanation={evaluation.explanation}
                  jobId={job.id}
                  onRescored={onRescored}
                />
              )}
              <h2 id={`application-${application.id}`}>{job.title ?? 'Untitled job'}</h2>
              <a
                className="app-offer-link"
                href={job.link}
                target="_blank"
                rel="noreferrer"
                title={`Open the job offer: ${job.link}`}
                aria-label="Open the job offer"
              >
                <ExternalLink size={16} aria-hidden="true" />
              </a>
            </div>
            <div className="job-meta">
              {job.company && (
                <span className="job-company">
                  <CompanyTagBadge
                    companyId={job.company_id}
                    tag={job.company_tag}
                    name={job.company}
                    onOpenCompany={onOpenCompany}
                  />{' '}
                </span>
              )}
            </div>
          </div>
          <ApplicationCv application={application} onChange={onChange} />
        </header>

        <ApplicationDetail
          key={application.id}
          application={application}
          statuses={statuses}
          technologies={technologies}
          onChange={onChange}
          onAccepted={onAccepted}
          onDelete={onDelete}
        />
      </div>
    </article>
  )
}
