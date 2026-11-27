import type { MouseEvent } from 'react'

/** Elements that handle a click themselves, and regions marked `data-no-open` (a note being
 * written, a decision to make): a click there never opens the item around them. */
const OWN_CLICK = 'a, button, input, textarea, select, label, summary, form, [role="button"], [role="link"], [data-no-open]'

/** Click handler for a card or list row with an open chevron: a click anywhere on it opens
 * the item, except on its own controls, outside its DOM (a popup rendered through a portal),
 * or at the end of selecting text. Keyboard users open it with its button or link. */
export function openOnClick(open: () => void) {
  return (e: MouseEvent<HTMLElement>) => {
    if (e.defaultPrevented || e.button !== 0) return
    const item = e.currentTarget
    const target = e.target as Element
    if (!item.contains(target)) return
    const own = target.closest(OWN_CLICK)
    if (own && own !== item && item.contains(own)) return
    if (window.getSelection()?.type === 'Range') return
    open()
  }
}
