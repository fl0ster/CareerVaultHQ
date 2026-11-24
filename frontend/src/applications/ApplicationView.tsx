import { useEffect, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import type { GeneratedCv } from '../cv/api.ts'
import CvPipelineDialog from '../cv/CvPipelineDialog.tsx'
import { type Application, type ApplicationStatus } from './api.ts'
import ApplicationDetail from './ApplicationDetail.tsx'
import { type EvaluatedJobDetail, jobsApi } from '../jobs/api.ts'
import RelevanceMeter from '../jobs/RelevanceMeter.tsx'
import '../jobs/jobs.css'
import TechPills from '../jobs/TechPills.tsx'

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
  // "How it was generated" stays a popup over the view.
  const [pipelineCv, setPipelineCv] = useState<GeneratedCv | null>(null)
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
        <div className="job-dialog-head">
          <div className="job-main">
            <div className="detail-title">
              {evaluation && (
                <RelevanceMeter
                  relevance={evaluation.relevance}
                  outdated={evaluation.outdated}
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
        </div>

        <TechPills technologies={technologies} />

        <ApplicationDetail
          key={application.id}
          application={application}
          statuses={statuses}
          onChange={onChange}
          onAccepted={onAccepted}
          onDelete={onDelete}
          onShowPipeline={setPipelineCv}
        />
      </div>
      {pipelineCv && <CvPipelineDialog key={pipelineCv.id} cv={pipelineCv} onClose={() => setPipelineCv(null)} />}
    </article>
  )
}
