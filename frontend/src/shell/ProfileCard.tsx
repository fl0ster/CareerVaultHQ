import { useEffect } from 'react'
import { UserRound } from 'lucide-react'
import { candidateDetailsStore, isProfileComplete, loadCandidateDetails } from '../candidate-profile/store.ts'
import { DASHBOARD_PAGE, type PageId, pageHref } from './nav.ts'
import { useStore } from './store.ts'
import type { Setup } from './useSetup.ts'

type Props = {
  /** The dashboard is on screen: the card itself is the current page. */
  dashboardActive: boolean
  collapsed: boolean
  /** Unfinished first-run setup: shown with its progress in place of the greeting. */
  setup: Setup | null
  onNavigate: (id: PageId) => void
}

const initials = (first: string, last: string) => `${first.trim().charAt(0)}${last.trim().charAt(0)}`.toUpperCase()

/**
 * The card at the top of the side menu: the user's picture and name, or the setup progress
 * until the app is set up. Clicking the card opens the dashboard (with the setup checklist
 * while there is one); the personal details are edited in Settings.
 */
export default function ProfileCard({ dashboardActive, collapsed, setup, onNavigate }: Props) {
  const details = useStore(candidateDetailsStore)

  useEffect(() => {
    // A failed load just leaves the card in its setup state; the Personal details tab reports errors.
    loadCandidateDetails().catch(() => {})
  }, [])

  const complete = isProfileComplete(details)
  const name = complete ? `${details!.first_name.trim()} ${details!.last_name.trim()}` : 'Set up your profile'
  const loading = details === undefined
  const setupLabel = setup && `Complete Setup: ${setup.done} of ${setup.steps.length} done`

  return (
    <div
      className={`profile-card${dashboardActive ? ' active' : ''}${loading ? ' loading' : ''}`}
      title={collapsed ? (setupLabel ?? `${DASHBOARD_PAGE.label}: ${name}`) : undefined}
    >
      {/* Covers the whole card: the card is the way to the dashboard. */}
      <a
        href={pageHref(DASHBOARD_PAGE.id)}
        className="profile-card-link"
        aria-current={dashboardActive ? 'page' : undefined}
        aria-label={setupLabel ?? DASHBOARD_PAGE.label}
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
      {setup ? (
        <span className="profile-text profile-setup">
          <span className="profile-name">
            <span>Complete Setup</span>
          </span>
          <progress className="setup-bar" value={setup.done} max={setup.steps.length} aria-hidden="true" />
        </span>
      ) : (
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
      )}
    </div>
  )
}
