import { useEffect } from 'react'
import { UserRound } from 'lucide-react'
import { candidateDetailsStore, isProfileComplete, loadCandidateDetails } from '../candidate-profile/store.ts'
import { DASHBOARD_PAGE, type PageId, pageHref } from './nav.ts'
import { useStore } from './store.ts'

type Props = {
  /** The dashboard is on screen: the card itself is the current page. */
  dashboardActive: boolean
  collapsed: boolean
  onNavigate: (id: PageId) => void
}

const initials = (first: string, last: string) => `${first.trim().charAt(0)}${last.trim().charAt(0)}`.toUpperCase()

/**
 * The card at the top of the side menu: the user's picture and name. Clicking the card opens
 * the dashboard; the personal details are edited in Settings.
 */
export default function ProfileCard({ dashboardActive, collapsed, onNavigate }: Props) {
  const details = useStore(candidateDetailsStore)

  useEffect(() => {
    // A failed load just leaves the card in its setup state; the Personal details tab reports errors.
    loadCandidateDetails().catch(() => {})
  }, [])

  const complete = isProfileComplete(details)
  const name = complete ? `${details!.first_name.trim()} ${details!.last_name.trim()}` : 'Set up your profile'
  const loading = details === undefined

  return (
    <div
      className={`profile-card${dashboardActive ? ' active' : ''}${loading ? ' loading' : ''}`}
      title={collapsed ? `${DASHBOARD_PAGE.label}: ${name}` : undefined}
    >
      {/* Covers the whole card: the card is the way to the dashboard. */}
      <a
        href={pageHref(DASHBOARD_PAGE.id)}
        className="profile-card-link"
        aria-current={dashboardActive ? 'page' : undefined}
        aria-label={DASHBOARD_PAGE.label}
        onClick={(e) => {
          e.preventDefault()
          onNavigate(DASHBOARD_PAGE.id)
        }}
      />
      <span className="profile-avatar" aria-hidden="true">
        {details?.photo ? (
          <img src={details.photo} alt="" />
        ) : complete ? (
          initials(details!.first_name, details!.last_name)
        ) : (
          <UserRound size={20} strokeWidth={1.8} />
        )}
      </span>
      <span className="profile-text">
        <span className="profile-hello">{complete || loading ? 'Hello,' : 'Hello there'}</span>
        {complete ? (
          <span className="profile-name">
            <span>{details!.first_name.trim()}</span>
            <span>{details!.last_name.trim()}</span>
          </span>
        ) : (
          <span className="profile-name">
            <span>{loading ? ' ' : name}</span>
          </span>
        )}
      </span>
    </div>
  )
}
