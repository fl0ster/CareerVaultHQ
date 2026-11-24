import { Fragment, useLayoutEffect, useRef, useState } from 'react'
import { ChevronDown, Monitor, Moon, PanelLeftClose, PanelLeftOpen, Sun, X } from 'lucide-react'
import ProfileCard from './ProfileCard.tsx'
import {
  DASHBOARD_PAGE,
  NAV_SECTIONS,
  type NavGroup,
  type NavItem,
  type PageId,
  SETTINGS,
  SETTINGS_PAGE_IDS,
  findPage,
  isGroup,
  isSettingsPage,
} from './nav.ts'
import type { Theme } from './useTheme.ts'

type Badges = Partial<Record<PageId, { count: number; title: string }>>

type Props = {
  active: PageId
  onNavigate: (id: PageId) => void
  /** Opens the settings page on its last-used tab. */
  onOpenSettings: () => void
  badges: Badges
  /** Pages left out of the menu (e.g. Interviews while there are none). */
  hiddenPages?: PageId[]
  collapsed: boolean
  onToggleCollapsed: () => void
  mobileOpen: boolean
  onCloseMobile: () => void
  theme: Theme
  onThemeChange: (theme: Theme) => void
}

type GroupId = NavGroup['id']

const THEME_OPTIONS = [
  { id: 'light', label: 'Light', icon: Sun },
  { id: 'system', label: 'Match system', icon: Monitor },
  { id: 'dark', label: 'Dark', icon: Moon },
] as const

function PageLink({
  item,
  active,
  badge,
  collapsed,
  marked,
  sub = false,
  onNavigate,
}: {
  item: NavItem
  active: boolean
  badge?: Badges[PageId]
  collapsed: boolean
  /** Carries the sliding highlight. */
  marked: boolean
  sub?: boolean
  onNavigate: (id: PageId) => void
}) {
  const Icon = item.icon
  return (
    <a
      href={`#/${item.id}`}
      className={`nav-item${sub ? ' nav-sub-item' : ''}${active ? ' active' : ''}`}
      aria-current={active ? 'page' : undefined}
      data-indicator={marked || undefined}
      title={collapsed ? item.label : undefined}
      onClick={(e) => {
        e.preventDefault()
        onNavigate(item.id)
      }}
    >
      <Icon className="nav-icon" size={sub ? 17 : 19} strokeWidth={1.8} aria-hidden="true" />
      <span className="nav-label">{item.label}</span>
      {badge && badge.count > 0 && (
        <span className="nav-pill" title={badge.title} key={badge.count}>
          {badge.count}
        </span>
      )}
    </a>
  )
}

export default function Sidebar({
  active,
  onNavigate,
  onOpenSettings,
  badges,
  hiddenPages = [],
  collapsed,
  onToggleCollapsed,
  mobileOpen,
  onCloseMobile,
  theme,
  onThemeChange,
}: Props) {
  const navRef = useRef<HTMLElement>(null)
  const indicatorRef = useRef<HTMLSpanElement>(null)
  // Only menu groups (My profile) open in place; Settings is a single entry with tabs in the page.
  const pageGroup = findPage(active).group?.id ?? null
  const activeGroup = pageGroup === 'settings' ? null : pageGroup
  const onSettings = isSettingsPage(active)
  const SettingsIcon = SETTINGS.icon

  // My profile opens on click, and by itself when it holds the current page.
  const [open, setOpen] = useState<GroupId[]>(activeGroup ? [activeGroup] : [])
  const [prevGroup, setPrevGroup] = useState(activeGroup)
  if (activeGroup !== prevGroup) {
    setPrevGroup(activeGroup)
    if (activeGroup && !open.includes(activeGroup)) setOpen([...open, activeGroup])
  }

  // Which entries are in the menu: one appearing or leaving moves the entries below it.
  const shownKey = hiddenPages.filter((id) => id !== active).join()

  const toggle = (id: GroupId) => setOpen((o) => (o.includes(id) ? o.filter((g) => g !== id) : [...o, id]))

  // Slide the highlight to the current page, or to its group while that group is closed.
  // The observer keeps it in place while groups open and close; entries appearing or leaving
  // (e.g. Applications once there is one) do not resize the nav, so they re-run this instead.
  useLayoutEffect(() => {
    const nav = navRef.current
    const indicator = indicatorRef.current
    if (!nav || !indicator) return
    const place = () => {
      const item = nav.querySelector<HTMLElement>('[data-indicator]')
      // The dashboard is opened from the profile card, outside the menu: no entry to highlight.
      indicator.hidden = !item
      if (!item) return
      indicator.style.transform = `translate(${item.offsetLeft}px, ${item.offsetTop}px)`
      indicator.style.width = `${item.offsetWidth}px`
      indicator.style.height = `${item.offsetHeight}px`
    }
    place()
    const observer = new ResizeObserver(place)
    observer.observe(nav)
    nav.querySelectorAll('.nav-sub').forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [active, collapsed, open, shownKey])

  return (
    <aside className={`sidebar${collapsed ? ' collapsed' : ''}${mobileOpen ? ' open' : ''}`} aria-label="Main menu">
      <div className="sidebar-head">
        <ProfileCard
          dashboardActive={active === DASHBOARD_PAGE.id}
          collapsed={collapsed}
          onNavigate={onNavigate}
        />
        <button type="button" className="icon-button sidebar-close" onClick={onCloseMobile} aria-label="Close menu">
          <X size={18} />
        </button>
      </div>

      <nav className="sidebar-nav" ref={navRef}>
        <span className="nav-indicator" aria-hidden="true" ref={indicatorRef} />
        {NAV_SECTIONS.map((section, i) => (
          <Fragment key={i}>
            {i > 0 && <hr className="nav-divider" />}
            <ul className="nav-list">
              {section.map((node) => {
                if (!isGroup(node)) {
                  if (hiddenPages.includes(node.id) && node.id !== active) return null
                  return (
                    <li key={node.id}>
                      <PageLink
                        item={node}
                        active={node.id === active}
                        marked={node.id === active}
                        badge={badges[node.id]}
                        collapsed={collapsed}
                        onNavigate={onNavigate}
                      />
                    </li>
                  )
                }
                const expanded = open.includes(node.id)
                const holdsActive = node.id === activeGroup
                const Icon = node.icon
                return (
                  <li key={node.id} className={`nav-group${expanded ? ' expanded' : ''}`}>
                    <button
                      type="button"
                      className={`nav-item nav-parent${holdsActive ? ' active' : ''}`}
                      aria-expanded={expanded}
                      aria-controls={`nav-sub-${node.id}`}
                      data-indicator={(holdsActive && !expanded) || undefined}
                      title={collapsed ? node.label : undefined}
                      onClick={() => toggle(node.id)}
                    >
                      <Icon className="nav-icon" size={19} strokeWidth={1.8} aria-hidden="true" />
                      <span className="nav-label">{node.label}</span>
                      <ChevronDown className="nav-chevron" size={16} strokeWidth={2} aria-hidden="true" />
                    </button>
                    <div className="nav-sub" id={`nav-sub-${node.id}`} inert={!expanded}>
                      <ul className="nav-sub-inner">
                        {node.items.map((item) => (
                          <li key={item.id}>
                            <PageLink
                              item={item}
                              sub
                              active={item.id === active}
                              marked={item.id === active && expanded}
                              badge={badges[item.id]}
                              collapsed={collapsed}
                              onNavigate={onNavigate}
                            />
                          </li>
                        ))}
                      </ul>
                    </div>
                  </li>
                )
              })}
            </ul>
          </Fragment>
        ))}

        <ul className="nav-list nav-bottom">
          <li>
            <a
              href={`#/${SETTINGS_PAGE_IDS[0]}`}
              className={`nav-item${onSettings ? ' active' : ''}`}
              aria-current={onSettings ? 'page' : undefined}
              data-indicator={onSettings || undefined}
              title={collapsed ? SETTINGS.label : undefined}
              onClick={(e) => {
                e.preventDefault()
                onOpenSettings()
              }}
            >
              <SettingsIcon className="nav-icon" size={19} strokeWidth={1.8} aria-hidden="true" />
              <span className="nav-label">{SETTINGS.label}</span>
            </a>
          </li>
        </ul>
      </nav>

      <div className="sidebar-foot">
        <div className="theme-switch" role="radiogroup" aria-label="Colour theme">
          {THEME_OPTIONS.map((o) => {
            const Icon = o.icon
            return (
              <button
                key={o.id}
                type="button"
                role="radio"
                aria-checked={theme === o.id}
                className={theme === o.id ? 'active' : undefined}
                title={o.label}
                aria-label={o.label}
                onClick={() => onThemeChange(o.id)}
              >
                <Icon size={15} strokeWidth={1.9} />
              </button>
            )
          })}
        </div>
        <button
          type="button"
          className="icon-button collapse-toggle"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Expand menu' : 'Collapse menu'}
          title={collapsed ? 'Expand menu' : 'Collapse menu'}
        >
          {collapsed ? <PanelLeftOpen size={18} strokeWidth={1.8} /> : <PanelLeftClose size={18} strokeWidth={1.8} />}
        </button>
      </div>
    </aside>
  )
}
