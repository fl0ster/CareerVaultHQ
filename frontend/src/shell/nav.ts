import {
  Coins,
  FileText,
  History,
  IdCard,
  Inbox,
  type LucideIcon,
  Mail,
  Rss,
  Send,
  Settings,
  UserRound,
} from 'lucide-react'

export type PageId =
  | 'applications'
  | 'jobs'
  | 'candidate-profile'
  | 'work-history'
  | 'sources'
  | 'generated-cv'
  | 'gmail'
  | 'cost'

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

/** A menu entry that opens to show its sub-pages. */
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

const PROFILE: NavGroup = {
  id: 'profile',
  label: 'My profile',
  icon: UserRound,
  items: [
    {
      id: 'candidate-profile',
      label: 'About me',
      icon: IdCard,
      hideHeader: true,
    },
    {
      id: 'work-history',
      label: 'Work history',
      icon: History,
      hideHeader: true,
    },
  ],
}

const SETTINGS: NavGroup = {
  id: 'settings',
  label: 'Settings',
  icon: Settings,
  items: [
    { id: 'sources', label: 'Sources', title: 'Scrape sources', icon: Rss, hideHeader: true },
    { id: 'generated-cv', label: 'Generated CVs', icon: FileText, hideHeader: true },
    { id: 'gmail', label: 'Gmail monitor', title: 'Gmail rejection monitor', icon: Mail, hideHeader: true },
    { id: 'cost', label: 'Cost', icon: Coins, hideHeader: true },
  ],
}

/** Menu sections, separated by a line: the everyday pages, then settings. */
export const NAV_SECTIONS: NavNode[][] = [
  [PROFILE],
  [
    {
      id: 'applications',
      label: 'Applications',
      icon: Send,
      hideHeader: true,
    },
    {
      id: 'jobs',
      label: 'Jobs',
      icon: Inbox,
      hideHeader: true,
    },
  ],
  [SETTINGS],
]

const NODES = NAV_SECTIONS.flat()

export const NAV_ITEMS: NavItem[] = NODES.flatMap((n) => (isGroup(n) ? n.items : [n]))

export const DEFAULT_PAGE: PageId = 'applications'

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
