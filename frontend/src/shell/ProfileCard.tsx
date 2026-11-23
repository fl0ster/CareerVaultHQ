import { useEffect } from 'react'
import { Settings, UserRound } from 'lucide-react'
import { candidateDetailsStore, isProfileComplete, loadCandidateDetails } from '../candidate-profile/store.ts'
import { type PageId, PROFILE_PAGE, pageHref } from './nav.ts'
import { useStore } from './store.ts'

type Props = {
  active: boolean
  collapsed: boolean
  onNavigate: (id: PageId) => void
}

const initials = (first: string, last: string) => `${first.trim().charAt(0)}${last.trim().charAt(0)}`.toUpperCase()

/**
 * The card at the top of the side menu: the user's picture and name. The card itself does
 * nothing; the cog in its corner opens About me, and carries an exclamation mark until the
 * required details are saved.
 */
export default function ProfileCard({ active, collapsed, onNavigate }: Props) {
  const details = useStore(candidateDetailsStore)

  useEffect(() => {
    // A failed load just leaves the card in its setup state; the About me page reports errors.
    loadCandidateDetails().catch(() => {})
  }, [])

  const complete = isProfileComplete(details)
  const name = complete ? `${details!.first_name.trim()} ${details!.last_name.trim()}` : 'Set up your profile'
  const loading = details === undefined
  const needsSetup = !complete && !loading
  const settingsLabel = needsSetup ? `${PROFILE_PAGE.label}: personal details missing` : PROFILE_PAGE.label

  return (
    <div
      className={`profile-card${active ? ' active' : ''}${loading ? ' loading' : ''}`}
      title={collapsed ? name : undefined}
    >
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
      <a
        href={pageHref(PROFILE_PAGE.id)}
        className={`profile-settings${active ? ' active' : ''}`}
        aria-current={active ? 'page' : undefined}
        aria-label={settingsLabel}
        title={settingsLabel}
        onClick={(e) => {
          e.preventDefault()
          onNavigate(PROFILE_PAGE.id)
        }}
      >
        <Settings size={16} strokeWidth={2.1} aria-hidden="true" />
        {needsSetup && (
          <span className="profile-alert" aria-hidden="true">
            !
          </span>
        )}
      </a>
    </div>
  )
}
