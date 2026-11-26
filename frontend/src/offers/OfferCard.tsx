import { Award, CalendarDays, ChevronRight } from 'lucide-react'
import {
  type Application,
  type ApplicationStatus,
  type OfferHints as Hints,
  OFFER_STATUS,
  formatDay,
} from '../applications/api.ts'
import ApplicationStatusControl from '../applications/ApplicationStatusControl.tsx'
import InterviewProgress from '../applications/InterviewProgress.tsx'
import { AcceptOfferButton, DeclineOfferButton } from '../applications/OfferActions.tsx'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import OfferHints from './OfferHints.tsx'

type Props = {
  application: Application
  statuses: ApplicationStatus[]
  /** AI comparison hints for this offer, once known. */
  hints?: Hints
  hintsLoading?: boolean
  /** Set when the AI comparison picked this offer as the best fit: why. */
  topPick?: { reason: string | null } | null
  onOpen: (id: number) => void
  onOpenCompany: (id: number) => void
  onAccepted: (updated: Application) => void
  onDeclined: (updated: Application) => void
  onChange: (updated: Application) => void
  onError: (message: string) => void
}

/** An application with an offer: the job up top, the decision to make at the bottom. */
export default function OfferCard({
  application: a,
  statuses,
  hints,
  hintsLoading = false,
  topPick = null,
  onOpen,
  onOpenCompany,
  onAccepted,
  onDeclined,
  onChange,
  onError,
}: Props) {
  const isOffer = a.status?.key === OFFER_STATUS

  return (
    <article className={topPick ? 'iv-card offer-card top-pick' : 'iv-card offer-card'}>
      <header className="iv-card-head">
        <div className="iv-card-title">
          <button type="button" className="iv-card-job" onClick={() => onOpen(a.id)}>
            {a.job.title ?? a.job.link}
          </button>
          <div className="iv-card-meta">
            {a.job.company && (
              <CompanyTagBadge
                companyId={a.job.company_id}
                tag={a.job.company_tag}
                name={a.job.company}
                onOpenCompany={onOpenCompany}
              />
            )}
            <InterviewProgress application={a} compact />
            {topPick && (
              <span className="badge offer-top-pick" title={topPick.reason ?? 'The best fit of your offers'}>
                <Award size={13} aria-hidden="true" />
                Top pick
              </span>
            )}
          </div>
        </div>
        <button type="button" className="secondary iv-card-details" onClick={() => onOpen(a.id)}>
          Details <ChevronRight size={16} aria-hidden="true" />
        </button>
      </header>

      <p className="offer-card-start">
        <CalendarDays size={14} aria-hidden="true" />
        {a.start_date ? (
          <span>Starts {formatDay(a.start_date)}</span>
        ) : (
          <span className="muted">Start date not agreed yet</span>
        )}
      </p>

      {isOffer && <OfferHints hints={hints} loading={hintsLoading} />}

      {/* The decision sits at the bottom of every card, so it is plain there is one to make. */}
      <footer className="offer-card-decision">
        {isOffer ? (
          <>
            <span className="offer-card-prompt">Your decision</span>
            <div className="offer-card-buttons">
              <DeclineOfferButton application={a} onDeclined={onDeclined} />
              <AcceptOfferButton application={a} onAccepted={onAccepted} onError={onError} />
            </div>
          </>
        ) : (
          <ApplicationStatusControl application={a} statuses={statuses} onChange={onChange} onError={onError} />
        )}
      </footer>
    </article>
  )
}
