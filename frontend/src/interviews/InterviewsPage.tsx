import './interviews.css'
import { INTERVIEW_STATUS } from '../applications/api.ts'
import ApplicationsLayout from '../applications/ApplicationsLayout.tsx'
import { type ApplicationPageProps, useApplicationList } from '../applications/useApplicationList.ts'
import InterviewCard from './InterviewCard.tsx'

/** Applications in the interview stage, as cards. */
export default function InterviewsPage({ detailId, version, onOpen, onBack, onCrumbsChange }: ApplicationPageProps) {
  const list = useApplicationList({ status: INTERVIEW_STATUS, detailId, version, onBack, onCrumbsChange })

  return (
    <ApplicationsLayout
      list={list}
      onOpen={onOpen}
      onBack={onBack}
      emptyText="No interviews yet."
      renderList={(applications, onOpenCompany) => (
        <ul className="iv-grid">
          {applications.map((a) => (
            <li key={a.id}>
              <InterviewCard
                application={a}
                statuses={list.statuses}
                onOpen={onOpen}
                onOpenCompany={onOpenCompany}
                onChange={list.replace}
              />
            </li>
          ))}
        </ul>
      )}
    />
  )
}
