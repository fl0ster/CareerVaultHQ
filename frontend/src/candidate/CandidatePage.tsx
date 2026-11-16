import { useState } from 'react'
import WorkHistoryPage from '../work-history/WorkHistoryPage.tsx'
import CandidateProfilePage from '../candidate-profile/CandidateProfilePage.tsx'

const SUBTABS = [
  { id: 'candidate-profile', label: 'Candidate profile' },
  { id: 'work-history', label: 'Work history' },
] as const

type SubTab = (typeof SUBTABS)[number]['id']

export default function CandidatePage() {
  const [subTab, setSubTab] = useState<SubTab>('candidate-profile')

  return (
    <>
      <nav className="tabs subtabs" aria-label="Candidate sections">
        {SUBTABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={subTab === t.id ? 'tab active' : 'tab'}
            aria-current={subTab === t.id ? 'page' : undefined}
            onClick={() => setSubTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* Both subpages stay mounted so loaded state survives subtab switches. */}
      <section hidden={subTab !== 'candidate-profile'}>
        <CandidateProfilePage />
      </section>
      <section hidden={subTab !== 'work-history'}>
        <WorkHistoryPage />
      </section>
    </>
  )
}
