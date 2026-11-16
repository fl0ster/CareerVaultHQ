import { useState } from 'react'
import './App.css'
import JobsPage from './jobs/JobsPage.tsx'
import CandidatePage from './candidate/CandidatePage.tsx'
import CompaniesPage from './companies/CompaniesPage.tsx'
import SourcesPage from './sources/SourcesPage.tsx'
import CostPage from './cost/CostPage.tsx'
import GeneratedCvPage from './cv/GeneratedCvPage.tsx'

const TABS = [
  { id: 'jobs', label: 'Jobs' },
  { id: 'companies', label: 'Companies' },
  { id: 'sources', label: 'Sources' },
  { id: 'candidate', label: 'Candidate' },
  { id: 'generated-cv', label: 'Generated CV' },
  { id: 'cost', label: 'Cost' },
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
      <section hidden={tab !== 'sources'}>
        <SourcesPage />
      </section>
      <section hidden={tab !== 'candidate'}>
        <CandidatePage />
      </section>
      <section hidden={tab !== 'generated-cv'}>
        <GeneratedCvPage />
      </section>
      <section hidden={tab !== 'cost'}>
        <CostPage />
      </section>
    </main>
  )
}

export default App
