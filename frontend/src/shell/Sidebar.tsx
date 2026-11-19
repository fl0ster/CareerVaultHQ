import { useLayoutEffect, useRef } from 'react'
import { Monitor, Moon, PanelLeftClose, PanelLeftOpen, Sun, X } from 'lucide-react'
import Magpie from '../mascot/Magpie.tsx'
import { NAV_GROUPS, type PageId } from './nav.ts'
import type { Theme } from './useTheme.ts'

type Props = {
  active: PageId
  onNavigate: (id: PageId) => void
  badges: Partial<Record<PageId, { count: number; title: string }>>
  collapsed: boolean
  onToggleCollapsed: () => void
  mobileOpen: boolean
  onCloseMobile: () => void
  theme: Theme
  onThemeChange: (theme: Theme) => void
}

const THEME_OPTIONS = [
  { id: 'light', label: 'Light', icon: Sun },
  { id: 'system', label: 'Match system', icon: Monitor },
  { id: 'dark', label: 'Dark', icon: Moon },
] as const

export default function Sidebar({
  active,
  onNavigate,
  badges,
  collapsed,
  onToggleCollapsed,
  mobileOpen,
  onCloseMobile,
  theme,
  onThemeChange,
}: Props) {
  const navRef = useRef<HTMLElement>(null)
  const indicatorRef = useRef<HTMLSpanElement>(null)

  // Slide the highlight to the active item (and follow it when the rail collapses).
  useLayoutEffect(() => {
    const nav = navRef.current
    const indicator = indicatorRef.current
    if (!nav || !indicator) return
    const place = () => {
      const item = nav.querySelector<HTMLElement>('[aria-current="page"]')
      if (!item) return
      indicator.style.transform = `translateY(${item.offsetTop}px)`
      indicator.style.height = `${item.offsetHeight}px`
    }
    place()
    const observer = new ResizeObserver(place)
    observer.observe(nav)
    return () => observer.disconnect()
  }, [active, collapsed])

  return (
    <aside className={`sidebar${collapsed ? ' collapsed' : ''}${mobileOpen ? ' open' : ''}`} aria-label="Main menu">
      <div className="sidebar-brand">
        <span className="brand-mark">
          <Magpie head size={34} />
        </span>
        <span className="brand-name">
          CareerVault HQ
        </span>
        <button type="button" className="icon-button sidebar-close" onClick={onCloseMobile} aria-label="Close menu">
          <X size={18} />
        </button>
      </div>

      <nav className="sidebar-nav" ref={navRef}>
        <span className="nav-indicator" ref={indicatorRef} aria-hidden="true" />
        {NAV_GROUPS.map((group) => (
          <div className="nav-group" key={group.label}>
            <h2 className="nav-group-label">{group.label}</h2>
            <ul>
              {group.items.map((item) => {
                const Icon = item.icon
                const badge = badges[item.id]
                const current = item.id === active
                return (
                  <li key={item.id}>
                    <a
                      href={`#/${item.id}`}
                      className={current ? 'nav-item active' : 'nav-item'}
                      aria-current={current ? 'page' : undefined}
                      title={collapsed ? item.label : undefined}
                      onClick={(e) => {
                        e.preventDefault()
                        onNavigate(item.id)
                      }}
                    >
                      <Icon className="nav-icon" size={19} strokeWidth={1.8} aria-hidden="true" />
                      <span className="nav-label">{item.label}</span>
                      {badge && badge.count > 0 && (
                        <span className="nav-pill" title={badge.title} key={badge.count}>
                          {badge.count}
                        </span>
                      )}
                    </a>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
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
