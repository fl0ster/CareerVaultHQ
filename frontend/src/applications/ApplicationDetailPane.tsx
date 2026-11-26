import ApplicationView from './ApplicationView.tsx'
import type { ApplicationList } from './useApplicationList.ts'

type Props = {
  list: ApplicationList
  onOpenCompany: (id: number) => void
  onBack: () => void
}

/** The open application, or its loading / not-found state, shown in place of the list. */
export default function ApplicationDetailPane({ list, onOpenCompany, onBack }: Props) {
  const { selected, detailError, openId } = list
  if (selected) {
    return (
      <ApplicationView
        key={selected.id}
        application={selected}
        statuses={list.statuses}
        onChange={list.replace}
        onAccepted={list.acceptedInView}
        onOpenCompany={onOpenCompany}
        onBack={onBack}
        onRescored={list.rescored}
      />
    )
  }
  return (
    <div className="detail-view detail-status">
      {detailError || openId == null ? (
        <>
          <p className="error">Could not load the application: {detailError ?? 'not found'}</p>
          <button type="button" className="secondary small" onClick={onBack}>
            Back to applications
          </button>
        </>
      ) : (
        <span className="spinner" aria-hidden="true" />
      )}
    </div>
  )
}
