import { useState } from 'react'
import './App.css'
import JobsPage from './jobs/JobsPage.tsx'
import CandidatePage from './candidate/CandidatePage.tsx'
import CompaniesPage from './companies/CompaniesPage.tsx'
import SettingsPage from './settings/SettingsPage.tsx'
import QueueWidget from './queue/QueueWidget.tsx'
import ApplicationsPage from './applications/ApplicationsPage.tsx'

const TABS = [
  { id: 'jobs', label: 'Jobs' },
  { id: 'applications', label: 'Applications' },
  { id: 'companies', label: 'Companies' },
  { id: 'candidate', label: 'Candidate' },
  { id: 'settings', label: 'Settings' },
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
      <section hidden={tab !== 'applications'}>
        <ApplicationsPage />
      </section>
      <section hidden={tab !== 'companies'}>
        <CompaniesPage />
      </section>
      <section hidden={tab !== 'candidate'}>
        <CandidatePage />
      </section>
      <section hidden={tab !== 'settings'}>
        <SettingsPage />
      </section>

      <QueueWidget />
    </main>
  )
}

export default App
