import {
  Building2,
  BriefcaseBusiness,
  CalendarClock,
  Coins,
  Trophy,
  FileText,
  Inbox,
  LayoutDashboard,
  type LucideIcon,
  Mail,
  Rss,
  Send,
  Settings,
  UserRound,
} from 'lucide-react'

export type PageId =
  | 'dashboard'
  | 'interviews'
  | 'offers'
  | 'applications'
  | 'jobs'
  | 'candidate-profile'
  | 'work-history'
  | 'sources'
  | 'generated-cv'
  | 'gmail'
  | 'cost'
  | 'companies'

export type NavItem = {
  id: PageId
  label: string
  icon: LucideIcon
  /** Page heading; defaults to the label. */
  title?: string
  /** Shown under the heading, for pages that have no introduction of their own. */
  description?: string
  /** No visible heading: the page speaks for itself (the heading stays for screen readers). */
  hideHeader?: boolean
}

/** A set of related pages: My profile opens in the menu, Settings switches with tabs inside the page. */
export type NavGroup = {
  id: 'profile' | 'settings'
  label: string
  icon: LucideIcon
  items: NavItem[]
}

export type NavNode = NavItem | NavGroup

export function isGroup(node: NavNode): node is NavGroup {
  return 'items' in node
}

export const SETTINGS: NavGroup = {
  id: 'settings',
  label: 'Settings',
  icon: Settings,
  // Each tab opens with its description as a one-line introduction (see SettingsHeader).
  items: [
    {
      id: 'sources',
      label: 'Sources',
      title: 'Scrape sources',
      icon: Rss,
      description: 'The job boards that get scraped, how often each one runs and how relevant its jobs turn out.',
    },
    {
      id: 'companies',
      label: 'Companies',
      icon: Building2,
    },
    {
      id: 'generated-cv',
      label: 'Generated CVs',
      icon: FileText,
      description: 'Every CV tailored to a job, and how far each one got through generation.',
    },
    {
      id: 'gmail',
      label: 'Gmail monitor',
      title: 'Gmail rejection monitor',
      icon: Mail,
      description: 'Watches a Gmail inbox for rejection e-mails and marks the matching applications as rejected.',
    },
    {
      id: 'cost',
      label: 'Cost',
      icon: Coins,
      description: 'What the AI model calls have cost, broken down by period, source, model and kind.',
    },
  ],
}

/** Its pages are reached from the Settings entry at the bottom of the menu, then by tabs. */
export const SETTINGS_PAGES: NavItem[] = SETTINGS.items
export const SETTINGS_PAGE_IDS: PageId[] = SETTINGS_PAGES.map((i) => i.id)

export const isSettingsPage = (id: PageId) => SETTINGS_PAGE_IDS.includes(id)

/** About me is opened from the profile card at the top of the menu, not from a menu entry. */
export const PROFILE_PAGE: NavItem = { id: 'candidate-profile', label: 'About me', icon: UserRound, hideHeader: true }

/** Menu sections, separated by a line: my career, then the everyday pages. Settings sits apart at the bottom. */
export const NAV_SECTIONS: NavNode[][] = [
  [{ id: 'work-history', label: 'My Career', icon: BriefcaseBusiness }],
  [
    { id: 'jobs', label: 'Jobs', icon: Inbox },
    { id: 'applications', label: 'Applications', icon: Send },
    { id: 'interviews', label: 'Interviews', icon: CalendarClock },
    { id: 'offers', label: 'Offers', icon: Trophy },
  ],
]

/** The home page, opened by clicking the profile card at the top of the menu. */
export const DASHBOARD_PAGE: NavItem = {
  id: 'dashboard',
  label: 'Dashboard',
  icon: LayoutDashboard,
  description: 'Your job search at a glance.',
}

const NODES: NavNode[] = [DASHBOARD_PAGE, PROFILE_PAGE, ...NAV_SECTIONS.flat(), SETTINGS]

export const NAV_ITEMS: NavItem[] = NODES.flatMap((n) => (isGroup(n) ? n.items : [n]))

export const DEFAULT_PAGE: PageId = 'dashboard'

/** The page's menu entry and, for sub-pages, the group it belongs to. */
export function findPage(id: PageId): { group: NavGroup | null; item: NavItem } {
  for (const node of NODES) {
    if (isGroup(node)) {
      const item = node.items.find((i) => i.id === id)
      if (item) return { group: node, item }
    } else if (node.id === id) {
      return { group: null, item: node }
    }
  }
  throw new Error(`Unknown page ${id}`)
}

/** Where the app is: a page and, for pages with detail views, the open item's id. */
export type Route = { page: PageId; detail: string | null }

/** Extra breadcrumb entries a page shows after its own name (e.g. the open item's title). */
export type Crumb = { label: string; href?: string }

/** Parses `#/<page>` and `#/<page>/<id>`; anything unknown falls back to the default page. */
export function routeFromHash(hash: string): Route {
  const [id, detail] = hash.replace(/^#\/?/, '').split('/')
  if (!NAV_ITEMS.some((i) => i.id === id)) return { page: DEFAULT_PAGE, detail: null }
  return { page: id as PageId, detail: detail ? decodeURIComponent(detail) : null }
}

export const pageHref = (page: PageId, detail?: string | number | null) =>
  detail == null ? `#/${page}` : `#/${page}/${encodeURIComponent(String(detail))}`
