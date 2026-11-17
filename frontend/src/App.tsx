import { useEffect, useRef, useState } from 'react'
import './App.css'
import JobsPage from './jobs/JobsPage.tsx'
import CandidatePage from './candidate/CandidatePage.tsx'
import CompaniesPage from './companies/CompaniesPage.tsx'
import SettingsPage from './settings/SettingsPage.tsx'
import QueueWidget from './queue/QueueWidget.tsx'
import ApplicationsPage from './applications/ApplicationsPage.tsx'
import TimelinePage from './timeline/TimelinePage.tsx'
import { useTimelineStatus } from './timeline/useTimelineStatus.ts'

const TABS = [
  { id: 'timeline', label: 'Timeline' },
  { id: 'applications', label: 'Applications' },
  { id: 'candidate', label: 'Candidate' },
  { id: 'settings', label: 'Settings' },
] as const

type Tab = (typeof TABS)[number]['id']

function App() {
  const [tab, setTab] = useState<Tab>('timeline')
  const timeline = useTimelineStatus()
  const unread = timeline.status?.unread ?? 0
  const unreadRelevant = timeline.status?.unread_relevant ?? 0
  const tabsRef = useRef<HTMLElement>(null)

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
            {t.id === 'timeline' && unread > 0 && (
              <span
                className={unreadRelevant > 0 ? 'tab-count relevant' : 'tab-count'}
                title={`${unread} unread, ${unreadRelevant} relevant`}
              >
                {unreadRelevant > 0 ? `★ ${unreadRelevant}` : unread}
              </span>
            )}
          </button>
        ))}
      </nav>

      {/* All pages stay mounted so in-flight jobs and loaded lists survive tab switches. */}
      <section hidden={tab !== 'timeline'}>
        <TimelinePage active={tab === 'timeline'} status={timeline.status} onStatus={timeline.update} />
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
