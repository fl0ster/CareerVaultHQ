import { useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import type { GeneratedCv } from '../cv/api.ts'
import CvPipelineDialog from '../cv/CvPipelineDialog.tsx'
import { type Application, type ApplicationStatus } from './api.ts'
import ApplicationDetail from './ApplicationDetail.tsx'

type Props = {
  application: Application
  statuses: ApplicationStatus[]
  onChange: (application: Application) => void
  onDelete: (id: number) => void
  onOpenCompany: (companyId: number) => void
  onBack: () => void
}

/** Full details of one application, shown in place of the list. */
export default function ApplicationView({
  application,
  statuses,
  onChange,
  onDelete,
  onOpenCompany,
  onBack,
}: Props) {
  // "How it was generated" stays a popup over the view.
  const [pipelineCv, setPipelineCv] = useState<GeneratedCv | null>(null)
  const { job } = application

  return (
    <article className="detail-view app-view" aria-labelledby={`application-${application.id}`}>
      <button type="button" className="secondary small detail-back" onClick={onBack}>
        <ArrowLeft size={15} aria-hidden="true" /> Back to applications
      </button>
      <div className="detail-card">
        <div className="job-dialog-head">
          <div className="job-main">
            <h2 id={`application-${application.id}`}>{job.title ?? 'Untitled job'}</h2>
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

        <ApplicationDetail
          key={application.id}
          application={application}
          statuses={statuses}
          onChange={onChange}
          onDelete={onDelete}
          onShowPipeline={setPipelineCv}
        />
      </div>
      {pipelineCv && <CvPipelineDialog key={pipelineCv.id} cv={pipelineCv} onClose={() => setPipelineCv(null)} />}
    </article>
  )
}
