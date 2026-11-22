import { type ReactNode, useCallback, useEffect, useState } from 'react'
import './App.css'
import './shell/shell.css'
import ApplicationsPage, { type Stage } from './applications/ApplicationsPage.tsx'
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
  type PageId,
  type Route,
  SETTINGS_PAGE_IDS,
  findPage,
  isSettingsPage,
  pageHref,
  routeFromHash,
} from './shell/nav.ts'
import { useNavCounts } from './shell/useNavCounts.ts'
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
  // Breadcrumb entries each page adds after its own name (the open detail's title).
  const [crumbs, setCrumbs] = useState<Partial<Record<PageId, Crumb[]>>>({})
  const onApplicationCrumbs = useCallback((c: Crumb[]) => setCrumbs((all) => ({ ...all, applications: c })), [])
  const onInterviewCrumbs = useCallback((c: Crumb[]) => setCrumbs((all) => ({ ...all, interviews: c })), [])
  const onOfferCrumbs = useCallback((c: Crumb[]) => setCrumbs((all) => ({ ...all, offers: c })), [])
  const onJobCrumbs = useCallback((c: Crumb[]) => setCrumbs((all) => ({ ...all, jobs: c })), [])
  // Menu badges. Only the page on screen is mounted, so the shell keeps these fresh itself.
  const counts = useNavCounts(page)
  const jobsInbox = counts?.jobs_inbox ?? 0
  // Applications / Interviews / Offers only appear in the menu while they have applications.
  const hiddenPages: PageId[] = [
    ...(counts?.applications ? [] : (['applications'] as const)),
    ...(counts?.interviews ? [] : (['interviews'] as const)),
    ...(counts?.offers ? [] : (['offers'] as const)),
  ]

  // The Applications / Interviews / Offers list emptied out: fall back to Applications, or Jobs when there are none.
  const stageEmpty = counts != null && route.detail === null && hiddenPages.includes(page)
  const fallbackPage: PageId = counts?.applications ? 'applications' : 'jobs'
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

  // A change in the counts (possibly made by a background task) also refreshes the open list.
  const countsVersion = counts ? `${counts.applications}/${counts.interviews}/${counts.offers}` : ''
  const applicationList = (id: PageId, stage: Stage, onCrumbs: (c: Crumb[]) => void) => (
    <ApplicationsPage
      stage={stage}
      detailId={detailOf(id)}
      version={countsVersion}
      onOpen={openIn(id)}
      onBack={backTo(id)}
      onCrumbsChange={onCrumbs}
    />
  )

  /** Only the page on screen is created; entering a page mounts it, so it always loads fresh. */
  const renderPage = (id: PageId): ReactNode => {
    switch (id) {
      case 'interviews':
        return applicationList('interviews', 'interviews', onInterviewCrumbs)
      case 'offers':
        return applicationList('offers', 'offers', onOfferCrumbs)
      case 'applications':
        return applicationList('applications', 'all', onApplicationCrumbs)
      case 'jobs':
        return (
          <JobsPage
            detailId={detailOf('jobs')}
            inboxCount={counts?.jobs_inbox ?? null}
            onOpen={openJob}
            onBack={backTo('jobs')}
            onCrumbsChange={onJobCrumbs}
          />
        )
      case 'candidate-profile':
        return <CandidateProfilePage />
      case 'work-history':
        return <WorkHistoryPage />
      case 'sources':
        return <SourcesPage />
      case 'generated-cv':
        return <GeneratedCvPage />
      case 'gmail':
        return <GmailMonitorPage />
      case 'cost':
        return <CostPage />
    }
  }
  const item = findPage(page).item

  return (
    <div className={`shell${rail === 'collapsed' ? ' rail' : ''}`}>
      <Sidebar
        active={page}
        onNavigate={navigate}
        onOpenSettings={() => navigate(settingsTab)}
        badges={{
          jobs: { count: jobsInbox, title: `${jobsInbox} relevant jobs to review` },
          interviews: { count: counts?.interviews ?? 0, title: 'Applications in the interview stage' },
          offers: { count: counts?.offers ?? 0, title: 'Applications with an offer' },
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
          {/* Only the current page is mounted. The key remounts it on every page change, so
              each entry loads fresh; list <-> detail stays within one mount. State that has to
              outlive a page (running jobs) lives in module-level stores (shell/store.ts). */}
          <section key={page} aria-labelledby={`page-${page}`}>
            <div className="view">
              <header className={item.hideHeader ? 'sr-only' : 'page-header'}>
                <h1 id={`page-${page}`}>{item.title ?? item.label}</h1>
                {item.description && <p>{item.description}</p>}
              </header>
              {isSettingsPage(page) && <SettingsNav active={page} onNavigate={navigate} />}
              {renderPage(page)}
            </div>
          </section>
        </main>
      </div>
    </div>
  )
}

export default App
