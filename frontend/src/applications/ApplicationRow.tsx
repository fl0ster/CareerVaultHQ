import type { ReactNode } from 'react'
import { type Application, INTERVIEW_STATUS } from './api.ts'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import InterviewProgress from './InterviewProgress.tsx'
import RelevanceMeter from '../jobs/RelevanceMeter.tsx'
import type { EvaluatedJobDetail } from '../jobs/api.ts'

type Props = {
  application: Application
  onOpen: (id: number) => void
  onOpenCompany: (id: number) => void
  onRescored: (fresh: EvaluatedJobDetail) => void
  /** The controls on the right of the row (status badge, offer answers…). */
  actions: ReactNode
}

/** One application in a list; clicking it opens the application. */
export default function ApplicationRow({ application: a, onOpen, onOpenCompany, onRescored, actions }: Props) {
  return (
    <li className="app-item">
      <button type="button" className="app-row" onClick={() => onOpen(a.id)}>
        <div className="job-main">
          {a.evaluation && (
            <RelevanceMeter
              relevance={a.evaluation.relevance}
              outdated={a.evaluation.outdated}
              explanation={a.evaluation.explanation}
              jobId={a.job.id}
              onRescored={onRescored}
            />
          )}
          <span className="job-title" style={{ marginLeft: '10px' }}>{a.job.title ?? a.job.link}</span>
          <div className="job-meta">
            {a.job.company && (
              <span className="job-company">
                <CompanyTagBadge
                  companyId={a.job.company_id}
                  tag={a.job.company_tag}
                  name={a.job.company}
                  onOpenCompany={onOpenCompany}
                />{' '}
              </span>
            )}
          </div>
        </div>
        {/* Clicks anywhere around the badge stay with it instead of opening the row. */}
        <div
          className="app-badges"
          onClick={(e) => {
            e.stopPropagation()
            e.preventDefault()
          }}
        >
          {a.status?.key === INTERVIEW_STATUS && <InterviewProgress application={a} compact />}
          {actions}
        </div>
      </button>
    </li>
  )
}
