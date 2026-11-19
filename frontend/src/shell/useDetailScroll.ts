import { useLayoutEffect, useRef } from 'react'

/**
 * Scroll handling for a page that swaps its list for a detail view: opening a detail starts
 * at the top, and going back puts the list where it was left.
 *
 * `open`: a detail view is shown. `active`: the page is the one on screen (pages stay mounted,
 * and a hidden page must not move the window).
 */
export function useDetailScroll(open: boolean, active: boolean) {
  const listScroll = useRef(0)
  const wasOpen = useRef(open)

  // Track the list's position while it is on screen. A layout effect, so the listener is gone
  // before the list is hidden and the shorter page clamps the scroll position.
  useLayoutEffect(() => {
    if (open || !active) return
    const onScroll = () => {
      listScroll.current = window.scrollY
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [open, active])

  useLayoutEffect(() => {
    if (open === wasOpen.current) return
    wasOpen.current = open
    if (active) window.scrollTo({ top: open ? 0 : listScroll.current })
  }, [open, active])
}
