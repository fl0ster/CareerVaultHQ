import { CalendarDays } from 'lucide-react'
import { type Application, type ApplicationStatus, OFFER_STATUS, formatDay } from '../applications/api.ts'
import ApplicationStatusControl from '../applications/ApplicationStatusControl.tsx'
import InterviewProgress from '../applications/InterviewProgress.tsx'
import { AcceptOfferButton, DeclineOfferButton } from '../applications/OfferActions.tsx'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import { CardOpenButton } from '../shell/OpenChevron.tsx'
import { openOnClick } from '../shell/openOnClick.ts'

type Props = {
  application: Application
  statuses: ApplicationStatus[]
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
  onOpen,
  onOpenCompany,
  onAccepted,
  onDeclined,
  onChange,
  onError,
}: Props) {
  const isOffer = a.status?.key === OFFER_STATUS

  return (
    <article className="iv-card offer-card clickable-card" onClick={openOnClick(() => onOpen(a.id))}>
      <header className="iv-card-head">
        <div className="iv-card-title">
          <button type="button" className="iv-card-job item-title" onClick={() => onOpen(a.id)}>
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
          </div>
        </div>
        <CardOpenButton label="Open application" onOpen={() => onOpen(a.id)} />
      </header>

      <p className="offer-card-start">
        <CalendarDays size={14} aria-hidden="true" />
        {a.start_date ? (
          <span>Starts {formatDay(a.start_date)}</span>
        ) : (
          <span className="muted">Start date not agreed yet</span>
        )}
      </p>

      {/* The decision sits at the bottom of every card, so it is plain there is one to make. */}
      <footer className="offer-card-decision" data-no-open>
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
