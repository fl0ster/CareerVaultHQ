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
import { type Crumb, NAV_ITEMS, type PageId, type Route, pageHref, routeFromHash } from './shell/nav.ts'
import { useStoredState } from './shell/useStoredState.ts'
import { useTheme } from './shell/useTheme.ts'

function App() {
  const [route, setRoute] = useState<Route>(() => routeFromHash(window.location.hash))
  const page = route.page
  const [menuOpen, setMenuOpen] = useState(false)
  const [rail, setRail] = useStoredState('cv-sidebar', ['expanded', 'collapsed'] as const, 'expanded')
  const [theme, setTheme] = useTheme()
  const [jobsInbox, setJobsInbox] = useState(0)
  const onJobsInboxChange = useCallback((count: number) => setJobsInbox(count), [])
  // Breadcrumb entries each page adds after its own name (the open detail's title).
  const [crumbs, setCrumbs] = useState<Partial<Record<PageId, Crumb[]>>>({})
  const onApplicationCrumbs = useCallback((c: Crumb[]) => setCrumbs((all) => ({ ...all, applications: c })), [])
  const onJobCrumbs = useCallback((c: Crumb[]) => setCrumbs((all) => ({ ...all, jobs: c })), [])

  // Pages put back their own scroll position when leaving a detail view.
  useEffect(() => {
    window.history.scrollRestoration = 'manual'
  }, [])

  // The page lives in the URL hash so reloads and the back button keep your place.
  useEffect(() => {
    const onHash = () => {
      setRoute(routeFromHash(window.location.hash))
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
    if (id === page && route.detail === null) return
    const toList = id === page
    window.location.hash = pageHref(id)
    // Returning from a detail to its list: the page restores its own scroll position.
    if (!toList) window.scrollTo({ top: 0 })
  }

  const openApplication = useCallback((id: number) => {
    window.location.hash = pageHref('applications', id)
  }, [])
  const openJob = useCallback((id: number) => {
    window.location.hash = pageHref('jobs', id)
  }, [])
  const backTo = (id: PageId) => () => {
    window.location.hash = pageHref(id)
  }
  const detailOf = (id: PageId) => (route.page === id ? route.detail : null)

  const pages: Record<PageId, ReactNode> = {
    applications: (
      <ApplicationsPage
        detailId={detailOf('applications')}
        active={page === 'applications'}
        onOpen={openApplication}
        onBack={backTo('applications')}
        onCrumbsChange={onApplicationCrumbs}
      />
    ),
    jobs: (
      <JobsPage
        detailId={detailOf('jobs')}
        active={page === 'jobs'}
        onOpen={openJob}
        onBack={backTo('jobs')}
        onCrumbsChange={onJobCrumbs}
        onInboxCountChange={onJobsInboxChange}
      />
    ),
    'candidate-profile': <CandidateProfilePage />,
    'work-history': <WorkHistoryPage />,
    sources: <SourcesPage />,
    'generated-cv': <GeneratedCvPage active={page === 'generated-cv'} />,
    gmail: <GmailMonitorPage />,
    cost: <CostPage active={page === 'cost'} />,
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
        <TopBar
          active={page}
          crumbs={route.detail !== null ? (crumbs[page] ?? []) : []}
          onOpenMenu={() => setMenuOpen(true)}
        />

        <main className="content">
          {/* Every page stays mounted so in-flight jobs and loaded lists survive navigation. */}
          {NAV_ITEMS.map((item) => (
            <section key={item.id} hidden={page !== item.id} aria-labelledby={`page-${item.id}`}>
              <div className="view">
                <header className={item.hideHeader ? 'sr-only' : 'page-header'}>
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
