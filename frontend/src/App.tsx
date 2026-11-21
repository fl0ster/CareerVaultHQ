import { type ReactNode, useCallback, useEffect, useState } from 'react'
import './App.css'
import './shell/shell.css'
import ApplicationsPage, { type Stage } from './applications/ApplicationsPage.tsx'
import { useStageCounts } from './applications/useStageCounts.ts'
import JobsPage from './jobs/JobsPage.tsx'
import CandidateProfilePage from './candidate-profile/CandidateProfilePage.tsx'
import WorkHistoryPage from './work-history/WorkHistoryPage.tsx'
import SourcesPage from './sources/SourcesPage.tsx'
import GeneratedCvPage from './cv/GeneratedCvPage.tsx'
import GmailMonitorPage from './gmail/GmailMonitorPage.tsx'
import CostPage from './cost/CostPage.tsx'
import SettingsNav from './shell/SettingsNav.tsx'
import Sidebar from './shell/Sidebar.tsx'
import TopBar from './shell/TopBar.tsx'
import {
  type Crumb,
  NAV_ITEMS,
  type PageId,
  type Route,
  SETTINGS_PAGE_IDS,
  isSettingsPage,
  pageHref,
  routeFromHash,
} from './shell/nav.ts'
import { useStoredState } from './shell/useStoredState.ts'
import { useTheme } from './shell/useTheme.ts'

function App() {
  const [route, setRoute] = useState<Route>(() => routeFromHash(window.location.hash))
  const page = route.page
  const [menuOpen, setMenuOpen] = useState(false)
  const [rail, setRail] = useStoredState('cv-sidebar', ['expanded', 'collapsed'] as const, 'expanded')
  const [theme, setTheme] = useTheme()
  // The Settings entry in the menu reopens whichever settings tab was used last.
  const [settingsTab, setSettingsTab] = useStoredState('cv-settings-tab', SETTINGS_PAGE_IDS, SETTINGS_PAGE_IDS[0])
  if (isSettingsPage(page) && page !== settingsTab) setSettingsTab(page)
  const [jobsInbox, setJobsInbox] = useState(0)
  const onJobsInboxChange = useCallback((count: number) => setJobsInbox(count), [])
  // Breadcrumb entries each page adds after its own name (the open detail's title).
  const [crumbs, setCrumbs] = useState<Partial<Record<PageId, Crumb[]>>>({})
  const onApplicationCrumbs = useCallback((c: Crumb[]) => setCrumbs((all) => ({ ...all, applications: c })), [])
  const onInterviewCrumbs = useCallback((c: Crumb[]) => setCrumbs((all) => ({ ...all, interviews: c })), [])
  const onOfferCrumbs = useCallback((c: Crumb[]) => setCrumbs((all) => ({ ...all, offers: c })), [])
  const stageCounts = useStageCounts()
  // Applications / Interviews / Offers only appear in the menu while they have applications.
  const hiddenPages: PageId[] = [
    ...(stageCounts?.applications ? [] : (['applications'] as const)),
    ...(stageCounts?.interviews ? [] : (['interviews'] as const)),
    ...(stageCounts?.offers ? [] : (['offers'] as const)),
  ]
  const onJobCrumbs = useCallback((c: Crumb[]) => setCrumbs((all) => ({ ...all, jobs: c })), [])

  // The Applications / Interviews / Offers list emptied out: fall back to Applications, or Jobs when there are none.
  const stageEmpty = stageCounts != null && route.detail === null && hiddenPages.includes(page)
  const fallbackPage: PageId = stageCounts?.applications ? 'applications' : 'jobs'
  useEffect(() => {
    if (stageEmpty) window.location.hash = pageHref(fallbackPage)
  }, [stageEmpty, fallbackPage])

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

  const openIn = useCallback(
    (list: PageId) => (id: number) => {
      window.location.hash = pageHref(list, id)
    },
    [],
  )
  const openJob = useCallback((id: number) => {
    window.location.hash = pageHref('jobs', id)
  }, [])
  const backTo = (id: PageId) => () => {
    window.location.hash = pageHref(id)
  }
  const detailOf = (id: PageId) => (route.page === id ? route.detail : null)

  const applicationList = (id: PageId, stage: Stage, onCrumbs: (c: Crumb[]) => void) => (
    <ApplicationsPage
      stage={stage}
      detailId={detailOf(id)}
      active={page === id}
      onOpen={openIn(id)}
      onBack={backTo(id)}
      onCrumbsChange={onCrumbs}
    />
  )

  const pages: Record<PageId, ReactNode> = {
    interviews: applicationList('interviews', 'interviews', onInterviewCrumbs),
    offers: applicationList('offers', 'offers', onOfferCrumbs),
    applications: applicationList('applications', 'all', onApplicationCrumbs),
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
        onOpenSettings={() => navigate(settingsTab)}
        badges={{
          jobs: { count: jobsInbox, title: `${jobsInbox} relevant jobs to review` },
          interviews: { count: stageCounts?.interviews ?? 0, title: 'Applications in the interview stage' },
          offers: { count: stageCounts?.offers ?? 0, title: 'Applications with an offer' },
        }}
        hiddenPages={hiddenPages}
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
                {isSettingsPage(item.id) && <SettingsNav active={page} onNavigate={navigate} />}
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
