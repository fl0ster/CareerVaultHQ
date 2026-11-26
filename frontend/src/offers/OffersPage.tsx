import '../interviews/interviews.css'
import './offers.css'
import { RefreshCw, Sparkles } from 'lucide-react'
import { type Application, OFFER_STATUS, notifyApplicationsChanged } from '../applications/api.ts'
import ApplicationsLayout from '../applications/ApplicationsLayout.tsx'
import { type ApplicationPageProps, useApplicationList } from '../applications/useApplicationList.ts'
import { pageHref } from '../shell/nav.ts'
import OfferCard from './OfferCard.tsx'
import { type OfferComparisonState, useOfferComparison } from './useOfferComparison.ts'

/** The line above the cards: what the hints on them are, and a way to have them redone. */
function ComparisonBar({ comparison }: { comparison: OfferComparisonState }) {
  return (
    <p className="offer-compare-bar">
      <Sparkles size={14} aria-hidden="true" />
      <span>{comparison.loading ? 'Comparing your offers…' : 'AI comparison of your offers'}</span>
      {comparison.error && <span className="offer-compare-error">· {comparison.error}</span>}
      <button
        type="button"
        className="secondary small offer-compare-refresh"
        onClick={comparison.refresh}
        disabled={comparison.loading}
        title="Compare the offers again"
      >
        <RefreshCw size={13} aria-hidden="true" className={comparison.loading ? 'spinning' : undefined} />
        Refresh
      </button>
    </p>
  )
}

/** Applications with an offer, as cards, each answered right from its card. */
export default function OffersPage({ detailId, version, onOpen, onBack, onCrumbsChange }: ApplicationPageProps) {
  const list = useApplicationList({ status: OFFER_STATUS, detailId, version, onBack, onCrumbsChange })
  const { setApplications } = list
  const comparison = useOfferComparison(list.applications)

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
        <>
          <ComparisonBar comparison={comparison} />
          <ul className="offer-grid">
            {applications.map((a) => (
              <li key={a.id}>
                <OfferCard
                  application={a}
                  statuses={list.statuses}
                  hints={comparison.byId.get(a.id)}
                  hintsLoading={comparison.loading}
                  topPick={comparison.topPickId === a.id ? { reason: comparison.topPickReason } : null}
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
        </>
      )}
    />
  )
}
