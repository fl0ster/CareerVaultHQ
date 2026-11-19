import { Coins, FileText, History, IdCard, Inbox, type LucideIcon, Mail, Rss, Send } from 'lucide-react'

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
}

export type NavGroup = { label: string; items: NavItem[] }

export const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Pipeline',
    items: [
      {
        id: 'applications',
        label: 'Applications',
        icon: Send,
        description: 'Every role you applied for, from the first message to the offer.',
      },
      {
        id: 'jobs',
        label: 'Jobs',
        icon: Inbox,
        description: 'Scraped job offers, scored against your profile. Keep the good ones and dismiss the rest.',
      },
    ],
  },
  {
    label: 'Profile',
    items: [
      {
        id: 'candidate-profile',
        label: 'Candidate profile',
        icon: IdCard,
        description: 'Who you are and what you are looking for. Used to score jobs and to write CVs.',
      },
      {
        id: 'work-history',
        label: 'Work history',
        icon: History,
        description: 'Your positions and achievements. The CV generator picks from these.',
      },
    ],
  },
  {
    label: 'Settings',
    items: [
      { id: 'sources', label: 'Sources', title: 'Scrape sources', icon: Rss },
      { id: 'generated-cv', label: 'Generated CVs', icon: FileText },
      { id: 'gmail', label: 'Gmail monitor', title: 'Gmail rejection monitor', icon: Mail },
      { id: 'cost', label: 'Cost', icon: Coins },
    ],
  },
]

export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items)

export const DEFAULT_PAGE: PageId = 'applications'

export function findPage(id: PageId): { group: NavGroup; item: NavItem } {
  for (const group of NAV_GROUPS) {
    const item = group.items.find((i) => i.id === id)
    if (item) return { group, item }
  }
  throw new Error(`Unknown page ${id}`)
}

export function pageFromHash(hash: string): PageId {
  const id = hash.replace(/^#\/?/, '')
  return NAV_ITEMS.some((i) => i.id === id) ? (id as PageId) : DEFAULT_PAGE
}
