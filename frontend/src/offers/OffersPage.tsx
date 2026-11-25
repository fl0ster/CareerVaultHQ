import '../interviews/interviews.css'
import './offers.css'
import { type Application, OFFER_STATUS, notifyApplicationsChanged } from '../applications/api.ts'
import ApplicationsLayout from '../applications/ApplicationsLayout.tsx'
import { type ApplicationPageProps, useApplicationList } from '../applications/useApplicationList.ts'
import { pageHref } from '../shell/nav.ts'
import OfferCard from './OfferCard.tsx'

/** Applications with an offer, as cards, each answered right from its card. */
export default function OffersPage({ detailId, version, onOpen, onBack, onCrumbsChange }: ApplicationPageProps) {
  const list = useApplicationList({ status: OFFER_STATUS, detailId, version, onBack, onCrumbsChange })
  const { setApplications } = list

  /** An offer was accepted from a card: it leaves the offers, and the page moves on to the
   * position it became in My Career. */
  const accepted = (updated: Application) => {
    setApplications((prev) => prev?.filter((a) => a.id !== updated.id) ?? prev)
    notifyApplicationsChanged()
    window.location.hash = pageHref('work-history', updated.work_history_id)
  }

  /** An offer was declined from a card: it leaves the offers. */
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
      renderList={(applications, onOpenCompany) => (
        <ul className="offer-grid">
          {applications.map((a) => (
            <li key={a.id}>
              <OfferCard
                application={a}
                statuses={list.statuses}
                onOpen={onOpen}
                onOpenCompany={onOpenCompany}
                onAccepted={accepted}
                onDeclined={declined}
                onChange={list.replace}
                onError={list.setError}
              />
            </li>
          ))}
        </ul>
      )}
    />
  )
}
