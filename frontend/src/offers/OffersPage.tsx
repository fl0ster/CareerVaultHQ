import { type Application, OFFER_STATUS, notifyApplicationsChanged } from '../applications/api.ts'
import ApplicationsLayout from '../applications/ApplicationsLayout.tsx'
import ApplicationStatusControl from '../applications/ApplicationStatusControl.tsx'
import { AcceptOfferButton, DeclineOfferButton } from '../applications/OfferActions.tsx'
import { type ApplicationPageProps, useApplicationList } from '../applications/useApplicationList.ts'
import { pageHref } from '../shell/nav.ts'

/** Applications with an offer, each answered right from its row. */
export default function OffersPage({ detailId, version, onOpen, onBack, onCrumbsChange }: ApplicationPageProps) {
  const list = useApplicationList({ status: OFFER_STATUS, detailId, version, onBack, onCrumbsChange })
  const { setApplications } = list

  /** An offer was accepted from a row: it leaves the offers, and the page moves on to the
   * position it became in My Career. */
  const accepted = (updated: Application) => {
    setApplications((prev) => prev?.filter((a) => a.id !== updated.id) ?? prev)
    notifyApplicationsChanged()
    window.location.hash = pageHref('work-history', updated.work_history_id)
  }

  /** An offer was declined from a row: it leaves the offers. */
  const declined = (updated: Application) => {
    setApplications((prev) => prev?.filter((a) => a.id !== updated.id) ?? prev)
    notifyApplicationsChanged()
  }

  return (
    <ApplicationsLayout
      list={list}
      onOpen={onOpen}
      onBack={onBack}
      emptyText="No offers yet."
      renderActions={(a) =>
        a.status?.key === OFFER_STATUS ? (
          // Every row here is an offer: the one thing left to do is answer it.
          <>
            <DeclineOfferButton application={a} onDeclined={declined} />
            <AcceptOfferButton application={a} onAccepted={accepted} onError={list.setError} />
          </>
        ) : (
          <ApplicationStatusControl
            application={a}
            statuses={list.statuses}
            onChange={list.replace}
            onError={list.setError}
          />
        )
      }
    />
  )
}
