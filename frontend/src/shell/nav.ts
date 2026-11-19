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
    { id: 'sources', label: 'Sources', title: 'Scrape sources', icon: Rss },
    { id: 'generated-cv', label: 'Generated CVs', icon: FileText },
    { id: 'gmail', label: 'Gmail monitor', title: 'Gmail rejection monitor', icon: Mail },
    { id: 'cost', label: 'Cost', icon: Coins },
  ],
}

/** Menu sections, separated by a line: the everyday pages, then settings. */
export const NAV_SECTIONS: NavNode[][] = [
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
    PROFILE,
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

export function pageFromHash(hash: string): PageId {
  const id = hash.replace(/^#\/?/, '')
  return NAV_ITEMS.some((i) => i.id === id) ? (id as PageId) : DEFAULT_PAGE
}
