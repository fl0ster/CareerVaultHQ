import { useState } from 'react'
import './App.css'
import JobsPage from './JobsPage.tsx'
import ToolsPage from "./ToolsPage.tsx";

const TABS = [
  { id: 'tools', label: 'Tools' },
  { id: 'jobs', label: 'Jobs' },
] as const

type Tab = (typeof TABS)[number]['id']

function App() {
  const [tab, setTab] = useState<Tab>('tools')

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
      <section hidden={tab !== 'tools'}>
        <ToolsPage />
      </section>
      <section hidden={tab !== 'jobs'}>
        <JobsPage />
      </section>
    </main>
  )
}

export default App
