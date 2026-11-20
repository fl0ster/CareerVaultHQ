import { type RefObject, useEffect, useState } from 'react'
import type { Bar } from './timeline-model.ts'

const READ_OFFSET = 12

type ScrollPointer = { activeId: number | null; pointer: number | null; spacer: number }
const IDLE: ScrollPointer = { activeId: null, pointer: null, spacer: 0 }

/**
 * Maps the page scroll position onto the work history timeline.
 *
 * The "reading line" sits just below the sticky timeline. The list item it crosses is the
 * active position, and how far through that item the line is gives a point in time: the
 * item's top is the position's end, its bottom is its start (the list is newest first).
 *
 * Also returns `spacer`: the height of padding needed after the list so the last item can still
 * scroll up to the reading line.
 */
export function useScrollPointer(
  enabled: boolean,
  view: RefObject<HTMLElement | null>,
  cards: RefObject<Map<number, HTMLElement>>,
  order: number[],
  byId: Map<number, Bar>,
): ScrollPointer {
  const [state, setState] = useState<ScrollPointer>(IDLE)

  useEffect(() => {
    if (!enabled || order.length === 0) return
    let frame = 0
    const measure = () => {
      frame = 0
      const timeline = view.current?.querySelector<HTMLElement>('.wh-tl')
      if (!timeline) return
      const tlRect = timeline.getBoundingClientRect()
      const line = tlRect.bottom + READ_OFFSET

      const els = order.map((id) => cards.current.get(id))
      const last = els[els.length - 1]
      const stickyTop = parseFloat(getComputedStyle(timeline).top) || 0
      const spacer = last
        ? Math.max(0, Math.ceil(window.innerHeight - (stickyTop + tlRect.height + READ_OFFSET) - last.offsetHeight))
        : 0

      let id = order[0]
      let f = 0
      for (let i = 0; i < els.length; i++) {
        const el = els[i]
        if (!el) continue
        const r = el.getBoundingClientRect()
        if (line < r.top) break
        id = order[i]
        f = Math.min(1, (line - r.top) / Math.max(1, r.height))
      }
      const bar = byId.get(id)
      if (!bar) return
      const pointer = bar.end - f * (bar.end - bar.start)
      setState((s) =>
        s.activeId === id && s.spacer === spacer && Math.abs((s.pointer ?? -1) - pointer) < 0.01
          ? s
          : { activeId: id, pointer, spacer },
      )
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(measure)
    }
    measure()
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    const ro = new ResizeObserver(schedule)
    for (const id of order) {
      const el = cards.current.get(id)
      if (el) ro.observe(el)
    }
    return () => {
      if (frame) cancelAnimationFrame(frame)
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', schedule)
      ro.disconnect()
    }
  }, [enabled, view, cards, order, byId])

  return enabled ? state : IDLE
}
