import { useState } from 'react'
import './App.css'
import JobsPage from './JobsPage.tsx'
import ToolsPage from "./ToolsPage.tsx";
import WorkHistoryPage from './work-history/WorkHistoryPage.tsx'
import CandidateProfilePage from './candidate-profile/CandidateProfilePage.tsx'
import CompaniesPage from './companies/CompaniesPage.tsx'

const TABS = [
  { id: 'jobs', label: 'Jobs' },
  { id: 'companies', label: 'Companies' },
  { id: 'work-history', label: 'Work history' },
  { id: 'candidate-profile', label: 'Candidate profile' },
  { id: 'tools', label: 'Tools' },
] as const

type Tab = (typeof TABS)[number]['id']

function App() {
  const [tab, setTab] = useState<Tab>('jobs')

  return (
    <main className="page">
      <nav className="tabs" aria-label="Pages">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={tab === t.id ? 'tab active' : 'tab'}
            aria-current={tab === t.id ? 'page' : undefined}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* Both pages stay mounted so in-flight jobs and loaded lists survive tab switches. */}
      <section hidden={tab !== 'jobs'}>
        <JobsPage />
      </section>
      <section hidden={tab !== 'companies'}>
        <CompaniesPage />
      </section>
      <section hidden={tab !== 'work-history'}>
        <WorkHistoryPage />
      </section>
      <section hidden={tab !== 'candidate-profile'}>
        <CandidateProfilePage />
      </section>
      <section hidden={tab !== 'tools'}>
        <ToolsPage />
      </section>
    </main>
  )
}

export default App
