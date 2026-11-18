import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import CandidatePage from './candidate/CandidatePage.tsx'
import SettingsPage from './settings/SettingsPage.tsx'
import QueueWidget from './queue/QueueWidget.tsx'
import ApplicationsPage from './applications/ApplicationsPage.tsx'
import JobsPage from './jobs/JobsPage.tsx'

const TABS = [
  { id: 'jobs', label: 'Jobs' },
  { id: 'applications', label: 'Applications' },
  { id: 'candidate', label: 'Candidate' },
  { id: 'settings', label: 'Settings' },
] as const

type Tab = (typeof TABS)[number]['id']

function App() {
  const [tab, setTab] = useState<Tab>('applications')
  const tabsRef = useRef<HTMLElement>(null)
  const [jobsInbox, setJobsInbox] = useState(0)
  const onJobsInboxChange = useCallback((count: number) => setJobsInbox(count), [])

  // Expose the sticky tab bar's height so pages can stick their own headers below it.
  useEffect(() => {
    const el = tabsRef.current
    if (!el) return
    const update = () => document.documentElement.style.setProperty('--tabs-h', `${el.offsetHeight}px`)
    const observer = new ResizeObserver(update)
    observer.observe(el)
    update()
    return () => observer.disconnect()
  }, [])

  return (
    <main className="page">
      <nav className="tabs" aria-label="Pages" ref={tabsRef}>
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={tab === t.id ? 'tab active' : 'tab'}
            aria-current={tab === t.id ? 'page' : undefined}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.id === 'jobs' && jobsInbox > 0 && (
              <span className="tab-pill" title={`${jobsInbox} relevant jobs to review`}>
                {jobsInbox}
              </span>
            )}
          </button>
        ))}
      </nav>

      {/* All pages stay mounted so in-flight jobs and loaded lists survive tab switches. */}
      <section hidden={tab !== 'jobs'}>
        <JobsPage onInboxCountChange={onJobsInboxChange} />
      </section>
      <section hidden={tab !== 'applications'}>
        <ApplicationsPage />
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
