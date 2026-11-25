import { INTERVIEW_STATUS } from '../applications/api.ts'
import ApplicationsLayout from '../applications/ApplicationsLayout.tsx'
import ApplicationStatusControl from '../applications/ApplicationStatusControl.tsx'
import { type ApplicationPageProps, useApplicationList } from '../applications/useApplicationList.ts'

/** Applications in the interview stage. */
export default function InterviewsPage({ detailId, version, onOpen, onBack, onCrumbsChange }: ApplicationPageProps) {
  const list = useApplicationList({ status: INTERVIEW_STATUS, detailId, version, onBack, onCrumbsChange })

  return (
    <ApplicationsLayout
      list={list}
      onOpen={onOpen}
      onBack={onBack}
      emptyText="No interviews yet."
      renderActions={(a) => (
        <ApplicationStatusControl
          application={a}
          statuses={list.statuses}
          onChange={list.replace}
          onError={list.setError}
        />
      )}
    />
  )
}
