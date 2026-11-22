import { useLayoutEffect, useRef, useState } from 'react'
import { type PageId, SETTINGS, SETTINGS_PAGES, pageHref } from './nav.ts'

type Props = {
  active: PageId
  onNavigate: (id: PageId) => void
}

/** Which ends of the tab row have tabs scrolled out of view (narrow screens). */
type Overflow = { start: boolean; end: boolean }

/**
 * Heading and tabs of the settings pages; the side menu only has the one Settings entry.
 * It stays mounted while switching tabs, so the underline slides from one tab to the next.
 */
export default function SettingsHeader({ active, onNavigate }: Props) {
  const navRef = useRef<HTMLElement>(null)
  const indicatorRef = useRef<HTMLSpanElement>(null)
  const [overflow, setOverflow] = useState<Overflow>({ start: false, end: false })

  // Put the underline under the current tab, and keep it there as fonts load or the row resizes.
  useLayoutEffect(() => {
    const nav = navRef.current
    const indicator = indicatorRef.current
    if (!nav || !indicator) return
    const place = () => {
      const tab = nav.querySelector<HTMLElement>('[aria-current="page"]')
      indicator.hidden = !tab
      if (!tab) return
      indicator.style.transform = `translateX(${tab.offsetLeft}px)`
      indicator.style.width = `${tab.offsetWidth}px`
    }
    place()
    // Placed without sliding the first time; afterwards it moves.
    requestAnimationFrame(() => indicator.classList.add('ready'))
    const observer = new ResizeObserver(place)
    observer.observe(nav)
    nav.querySelectorAll('.settings-tab').forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [active])

  // On narrow screens the row scrolls: bring the current tab into view and fade the clipped ends.
  useLayoutEffect(() => {
    const nav = navRef.current
    if (!nav) return
    const tab = nav.querySelector<HTMLElement>('[aria-current="page"]')
    if (tab) {
      // Clear of the 32px edge fade; near either end, scroll all the way so that end stops fading.
      const pad = 40
      const max = nav.scrollWidth - nav.clientWidth
      const left = tab.offsetLeft - pad
      const right = tab.offsetLeft + tab.offsetWidth + pad - nav.clientWidth
      let to = nav.scrollLeft
      if (to > left) to = left
      else if (to < right) to = right
      nav.scrollLeft = to < pad ? 0 : to > max - pad ? max : to
    }
    const measure = () => {
      const max = nav.scrollWidth - nav.clientWidth
      const start = nav.scrollLeft > 1
      const end = nav.scrollLeft < max - 1
      setOverflow((o) => (o.start === start && o.end === end ? o : { start, end }))
    }
    measure()
    nav.addEventListener('scroll', measure, { passive: true })
    const observer = new ResizeObserver(measure)
    observer.observe(nav)
    return () => {
      nav.removeEventListener('scroll', measure)
      observer.disconnect()
    }
  }, [active])

  const fade = [overflow.start && 'fade-start', overflow.end && 'fade-end'].filter(Boolean).join(' ')

  return (
    <header className="settings-header">
      <h1>{SETTINGS.label}</h1>
      <nav
        ref={navRef}
        className={fade ? `settings-tabs ${fade}` : 'settings-tabs'}
        aria-label="Settings sections"
      >
        {SETTINGS_PAGES.map((item) => {
          const Icon = item.icon
          const current = item.id === active
          return (
            <a
              key={item.id}
              href={pageHref(item.id)}
              className={current ? 'settings-tab active' : 'settings-tab'}
              aria-current={current ? 'page' : undefined}
              onClick={(e) => {
                e.preventDefault()
                onNavigate(item.id)
              }}
            >
              <Icon size={16} strokeWidth={1.9} aria-hidden="true" />
              {item.label}
            </a>
          )
        })}
        <span className="settings-tab-indicator" aria-hidden="true" ref={indicatorRef} />
      </nav>
    </header>
  )
}
