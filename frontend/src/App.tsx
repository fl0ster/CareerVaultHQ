import { type ReactNode, useCallback, useEffect, useState } from 'react'
import './App.css'
import './shell/shell.css'
import ApplicationsPage from './applications/ApplicationsPage.tsx'
import JobsPage from './jobs/JobsPage.tsx'
import CandidateProfilePage from './candidate-profile/CandidateProfilePage.tsx'
import WorkHistoryPage from './work-history/WorkHistoryPage.tsx'
import SourcesPage from './sources/SourcesPage.tsx'
import GeneratedCvPage from './cv/GeneratedCvPage.tsx'
import GmailMonitorPage from './gmail/GmailMonitorPage.tsx'
import CostPage from './cost/CostPage.tsx'
import Sidebar from './shell/Sidebar.tsx'
import TopBar from './shell/TopBar.tsx'
import { NAV_ITEMS, type PageId, pageFromHash } from './shell/nav.ts'
import { useStoredState } from './shell/useStoredState.ts'
import { useTheme } from './shell/useTheme.ts'

function App() {
  const [page, setPage] = useState<PageId>(() => pageFromHash(window.location.hash))
  const [menuOpen, setMenuOpen] = useState(false)
  const [rail, setRail] = useStoredState('cv-sidebar', ['expanded', 'collapsed'] as const, 'expanded')
  const [theme, setTheme] = useTheme()
  const [jobsInbox, setJobsInbox] = useState(0)
  const onJobsInboxChange = useCallback((count: number) => setJobsInbox(count), [])

  // The page lives in the URL hash so reloads and the back button keep your place.
  useEffect(() => {
    const onHash = () => {
      setPage(pageFromHash(window.location.hash))
      setMenuOpen(false)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    if (!menuOpen) return
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [menuOpen])

  const navigate = (id: PageId) => {
    setMenuOpen(false)
    if (id === page) return
    window.location.hash = `/${id}`
    window.scrollTo({ top: 0 })
  }

  const pages: Record<PageId, ReactNode> = {
    applications: <ApplicationsPage />,
    jobs: <JobsPage onInboxCountChange={onJobsInboxChange} />,
    'candidate-profile': <CandidateProfilePage />,
    'work-history': <WorkHistoryPage />,
    sources: <SourcesPage />,
    'generated-cv': <GeneratedCvPage />,
    gmail: <GmailMonitorPage />,
    cost: <CostPage />,
  }

  return (
    <div className={`shell${rail === 'collapsed' ? ' rail' : ''}`}>
      <Sidebar
        active={page}
        onNavigate={navigate}
        badges={{ jobs: { count: jobsInbox, title: `${jobsInbox} relevant jobs to review` } }}
        collapsed={rail === 'collapsed'}
        onToggleCollapsed={() => setRail(rail === 'collapsed' ? 'expanded' : 'collapsed')}
        mobileOpen={menuOpen}
        onCloseMobile={() => setMenuOpen(false)}
        theme={theme}
        onThemeChange={setTheme}
      />
      <div className={`scrim${menuOpen ? ' open' : ''}`} onClick={() => setMenuOpen(false)} aria-hidden="true" />

      <div className="main">
        <TopBar active={page} onOpenMenu={() => setMenuOpen(true)} />

        <main className="content">
          {/* Every page stays mounted so in-flight jobs and loaded lists survive navigation. */}
          {NAV_ITEMS.map((item) => (
            <section key={item.id} hidden={page !== item.id} aria-labelledby={`page-${item.id}`}>
              <div className="view">
                <header className="page-header">
                  <h1 id={`page-${item.id}`}>{item.title ?? item.label}</h1>
                  {item.description && <p>{item.description}</p>}
                </header>
                {pages[item.id]}
              </div>
            </section>
          ))}
        </main>
      </div>
    </div>
  )
}

export default App
