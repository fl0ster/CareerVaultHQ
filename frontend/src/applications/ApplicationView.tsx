import { useEffect, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
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
  onOpenCompany,
  onBack,
  onRescored,
}: Props) {
  const { job, evaluation } = application

  // Technologies and the parsed description live on the job's parse result, which only the
  // job detail carries. `undefined`: still loading; `null`: no description (or it failed).
  const [technologies, setTechnologies] = useState<string[]>([])
  const [description, setDescription] = useState<string | null | undefined>(undefined)
  useEffect(() => {
    const controller = new AbortController()
    jobsApi
      .get(job.id, controller.signal)
      .then((detail) => {
        setTechnologies(detail.technologies ?? [])
        setDescription(detail.description)
      })
      .catch(() => {
        // Both are optional: leave the pills out, show "no description".
        if (!controller.signal.aborted) setDescription(null)
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
          description={description}
          onChange={onChange}
          onAccepted={onAccepted}
        />
      </div>
    </article>
  )
}
