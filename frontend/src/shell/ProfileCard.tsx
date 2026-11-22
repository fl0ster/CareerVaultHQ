import { useEffect } from 'react'
import { ChevronRight, UserRound } from 'lucide-react'
import {
  candidateDetailsStore,
  candidateDraftStore,
  isProfileComplete,
  loadCandidateDetails,
  setupProgress,
} from '../candidate-profile/store.ts'
import { type PageId, PROFILE_PAGE, pageHref } from './nav.ts'
import { useStore } from './store.ts'

type Props = {
  active: boolean
  collapsed: boolean
  onNavigate: (id: PageId) => void
}

const initials = (first: string, last: string) => `${first.trim().charAt(0)}${last.trim().charAt(0)}`.toUpperCase()

/**
 * The card at the top of the side menu: the user's picture and name, opening About me.
 * Until the required details are saved it shows how far the setup has got instead.
 */
export default function ProfileCard({ active, collapsed, onNavigate }: Props) {
  const details = useStore(candidateDetailsStore)
  const draft = useStore(candidateDraftStore)

  useEffect(() => {
    // A failed load just leaves the card in its setup state; the About me page reports errors.
    loadCandidateDetails().catch(() => {})
  }, [])

  const complete = isProfileComplete(details)
  const name = complete ? `${details!.first_name.trim()} ${details!.last_name.trim()}` : 'Set up your profile'
  const progress = setupProgress(draft ?? details)
  const loading = details === undefined

  return (
    <a
      href={pageHref(PROFILE_PAGE.id)}
      className={`profile-card${active ? ' active' : ''}${loading ? ' loading' : ''}`}
      aria-current={active ? 'page' : undefined}
      title={collapsed ? name : undefined}
      onClick={(e) => {
        e.preventDefault()
        onNavigate(PROFILE_PAGE.id)
      }}
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
        <span className="profile-name">{loading ? ' ' : name}</span>
        {complete || loading ? (
          <span className="profile-sub">{PROFILE_PAGE.label}</span>
        ) : (
          <span
            className="profile-progress"
            role="progressbar"
            aria-label="Profile setup"
            aria-valuemin={0}
            aria-valuemax={progress.total}
            aria-valuenow={progress.filled}
            aria-valuetext={`${progress.filled} of ${progress.total} steps done`}
          >
            {Array.from({ length: progress.total }, (_, i) => (
              <span key={i} className={i < progress.filled ? 'filled' : undefined} />
            ))}
          </span>
        )}
      </span>
      <ChevronRight className="profile-chevron" size={16} strokeWidth={2} aria-hidden="true" />
    </a>
  )
}
