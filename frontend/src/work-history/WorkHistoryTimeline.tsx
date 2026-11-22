import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useStuck } from '../shell/useStuck.ts'
import { type Bar, formatDuration, monthLabel, type TimelineModel } from './timeline-model.ts'

/*
 * Horizontal, scrollable timeline of work history positions. It sticks below the top bar
 * while the page scrolls; a pointer line marks the point in time the list underneath is
 * scrolled to. Above the lanes is an event row (joined / left markers, merged when they fall
 * on the same boundary), behind them are shaded career gaps and a "today" line, and below is
 * the year/month axis.
 */

const PAD = 32
const EVENT_ROW = 40
const LANE_H = 48
const LANE_GAP = 10
const AXIS_H = 34
const MIN_PPM = 4
const MAX_PPM = 96
const DEFAULT_PPM = 18
const FOLLOW_MARGIN = 40

export default function WorkHistoryTimeline({
  model,
  today,
  activeId,
  pointer,
  onSelect,
}: {
  model: TimelineModel
  today: number
  activeId: number | null
  pointer: number | null
  onSelect: (id: number) => void
}) {
  const { bars, byId, events, gaps, covered, rangeStart, rangeEnd, lanes } = model
  const [ppm, setPpm] = useState(DEFAULT_PPM)
  const [hoverId, setHoverId] = useState<number | null>(null)
  const section = useRef<HTMLElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const barRefs = useRef(new Map<number, HTMLButtonElement>())
  // Month to keep under a given viewport x after a zoom; applied once the new width is laid out.
  const zoomAnchor = useRef<{ month: number; x: number } | null>(null)
  const drag = useRef<{ x: number; left: number; moved: boolean } | null>(null)
  const stuck = useStuck(section, true)

  const x = (month: number) => PAD + (month - rangeStart) * ppm
  const width = PAD * 2 + (rangeEnd - rangeStart) * ppm
  const lanesTop = EVENT_ROW
  const lanesHeight = lanes * LANE_H + (lanes - 1) * LANE_GAP
  const height = lanesTop + lanesHeight + 14 + AXIS_H

  const zoomTo = (factor: number, viewportX?: number) => {
    const el = scroller.current
    const clamped = Math.min(MAX_PPM, Math.max(MIN_PPM, ppm * factor))
    if (!el || clamped === ppm) return
    const vx = viewportX ?? el.clientWidth / 2
    zoomAnchor.current = { month: (el.scrollLeft + vx - PAD) / ppm + rangeStart, x: vx }
    setPpm(clamped)
  }

  const fit = () => {
    const el = scroller.current
    if (!el) return
    zoomAnchor.current = null
    setPpm(Math.min(MAX_PPM, Math.max(MIN_PPM, (el.clientWidth - PAD * 2) / (rangeEnd - rangeStart))))
    el.scrollLeft = 0
  }

  useLayoutEffect(() => {
    const el = scroller.current
    const anchor = zoomAnchor.current
    if (!el || !anchor) return
    el.scrollLeft = PAD + (anchor.month - rangeStart) * ppm - anchor.x
    zoomAnchor.current = null
  }, [ppm, rangeStart])

  // Start scrolled to the most recent end of the timeline.
  useLayoutEffect(() => {
    const el = scroller.current
    if (el) el.scrollLeft = el.scrollWidth
  }, [])

  // Keep the pointer horizontally in view as the page scrolls (but not while dragging).
  const followRef = useRef<() => void>(() => {})
  useLayoutEffect(() => {
    followRef.current = () => {
      const el = scroller.current
      if (!el || pointer === null || drag.current) return
      const px = x(pointer)
      if (px < el.scrollLeft + FOLLOW_MARGIN || px > el.scrollLeft + el.clientWidth - FOLLOW_MARGIN) {
        el.scrollLeft = px - el.clientWidth / 2
      }
    }
  })
  useLayoutEffect(() => {
    followRef.current()
  }, [pointer])

  // Publish our height so list items can scroll to just below the sticky timeline.
  useLayoutEffect(() => {
    const el = section.current
    const host = el?.parentElement
    if (!el || !host) return
    const update = () => host.style.setProperty('--wh-tl-h', `${el.offsetHeight}px`)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => {
      ro.disconnect()
      host.style.removeProperty('--wh-tl-h')
    }
  }, [])

  // Ctrl/Cmd + wheel (and trackpad pinch) zooms around the cursor. Needs a non-passive listener.
  const zoomRef = useRef(zoomTo)
  useLayoutEffect(() => {
    zoomRef.current = zoomTo
  })
  useEffect(() => {
    const el = scroller.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      zoomRef.current(Math.exp(-e.deltaY * 0.01), e.clientX - el.getBoundingClientRect().left)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  const ordered = useMemo(() => [...bars].sort((a, b) => a.start - b.start), [bars])
  const onBarKey = (e: React.KeyboardEvent, bar: Bar) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const next = ordered[ordered.indexOf(bar) + (e.key === 'ArrowRight' ? 1 : -1)]
    if (!next) return
    barRefs.current.get(next.entry.id)?.focus({ preventScroll: true })
    onSelect(next.entry.id)
  }

  // Mouse drag to pan; touch and trackpads already scroll natively.
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.pointerType !== 'mouse' || e.button !== 0) return
    drag.current = { x: e.clientX, left: e.currentTarget.scrollLeft, moved: false }
  }
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.x
    if (!d.moved && Math.abs(dx) < 4) return
    if (!d.moved) e.currentTarget.setPointerCapture(e.pointerId)
    d.moved = true
    e.currentTarget.scrollLeft = d.left - dx
  }
  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    drag.current = null
    if (d?.moved) {
      e.currentTarget.releasePointerCapture(e.pointerId)
      // Swallow the click that follows a drag so it doesn't select a position.
      const swallow = (ev: MouseEvent) => ev.stopPropagation()
      window.addEventListener('click', swallow, { capture: true, once: true })
      setTimeout(() => window.removeEventListener('click', swallow, { capture: true }), 0)
    }
  }

  const years: number[] = []
  for (let m = rangeStart; m < rangeEnd; m += 12) years.push(m)
  const showMonths = ppm >= 30
  const showMonthTicks = ppm >= 9
  const span = rangeEnd - rangeStart

  const active = hoverId ?? activeId
  const activeBar = active !== null ? byId.get(active) : undefined

  return (
    <section ref={section} className={`wh-tl${stuck ? ' stuck' : ''}`} aria-label="Work history timeline">
      <header className="wh-tl-bar">
        <div className="wh-tl-stats">
          <span>
            <strong>{formatDuration(covered)}</strong> employed
          </span>
          <span>
            <strong>{bars.length}</strong> position{bars.length === 1 ? '' : 's'}
          </span>
          {gaps.length > 0 && (
            <span>
              <strong>{gaps.length}</strong> gap{gaps.length === 1 ? '' : 's'}
            </span>
          )}
        </div>
        <div className="wh-tl-zoom" role="group" aria-label="Zoom">
          <button type="button" className="secondary small" onClick={() => zoomTo(1 / 1.5)} disabled={ppm <= MIN_PPM} aria-label="Zoom out">
            −
          </button>
          <button type="button" className="secondary small" onClick={fit}>
            Fit
          </button>
          <button type="button" className="secondary small" onClick={() => zoomTo(1.5)} disabled={ppm >= MAX_PPM} aria-label="Zoom in">
            +
          </button>
        </div>
      </header>

      <div
        ref={scroller}
        className="wh-tl-scroll"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => (drag.current = null)}
      >
        <div className="wh-tl-canvas" style={{ width, height }}>
          {/* Year grid and axis */}
          {years.map((m) => (
            <div key={m} className="wh-tl-year" style={{ left: x(m), width: 12 * ppm, height }}>
              <span className="wh-tl-year-label" style={{ top: height - AXIS_H + 8 }}>
                {m / 12}
              </span>
            </div>
          ))}
          {showMonthTicks &&
            Array.from({ length: span }, (_, i) => rangeStart + i)
              .filter((m) => m % 12 !== 0)
              .map((m) => (
                <div key={m} className="wh-tl-month" style={{ left: x(m), top: height - AXIS_H }}>
                  {showMonths && <span>{monthLabel(m, 'short')}</span>}
                </div>
              ))}
          <div className="wh-tl-axis" style={{ top: height - AXIS_H, left: PAD, width: span * ppm }} />

          {/* Career gaps */}
          {gaps.map((g) => {
            const w = (g.end - g.start) * ppm
            return (
              <div
                key={g.start}
                className="wh-tl-gap"
                style={{ left: x(g.start), width: w, top: lanesTop - 6, height: lanesHeight + 12 }}
                title={`Gap: ${monthLabel(g.start)} – ${monthLabel(g.end - 1)} (${formatDuration(g.end - g.start)})`}
              >
                {w > 56 && <span>{formatDuration(g.end - g.start)} gap</span>}
              </div>
            )
          })}

          {/* Active/hovered position's span, projected onto the axis */}
          {activeBar && (
            <div
              className={`wh-tl-span tone-${activeBar.tone}`}
              style={{
                left: x(activeBar.start),
                width: (activeBar.end - activeBar.start) * ppm,
                top: lanesTop - 6,
                height: height - lanesTop + 6,
              }}
            />
          )}

          {/* Today */}
          <div className="wh-tl-today" style={{ left: x(today), top: 8, height: height - 8 - AXIS_H }}>
            <span>Today</span>
          </div>

          {/* Positions */}
          {bars.map((bar) => {
            const w = Math.max(6, (bar.end - bar.start) * ppm)
            const { entry } = bar
            const isActive = entry.id === activeId
            const dim = active !== null && entry.id !== active
            return (
              <button
                key={entry.id}
                ref={(el) => {
                  if (el) barRefs.current.set(entry.id, el)
                  else barRefs.current.delete(entry.id)
                }}
                type="button"
                className={`wh-tl-pos tone-${bar.tone}${bar.pending ? ' pending' : bar.ongoing ? ' ongoing' : ''}${isActive ? ' selected' : ''}${dim ? ' dim' : ''}`}
                style={{ left: x(bar.start), width: w, top: lanesTop + bar.lane * (LANE_H + LANE_GAP), height: LANE_H }}
                aria-current={isActive || undefined}
                aria-label={
                  bar.pending
                    ? `${entry.role} at ${entry.employer}, pending, starts ${monthLabel(bar.start)}`
                    : `${entry.role} at ${entry.employer}, ${monthLabel(bar.start)} to ${bar.ongoing ? 'present' : monthLabel(bar.end - 1)}, ${formatDuration(bar.end - bar.start)}`
                }
                title={`${entry.role} at ${entry.employer}${bar.pending ? ' (pending)' : ''}`}
                onClick={() => onSelect(entry.id)}
                onKeyDown={(e) => onBarKey(e, bar)}
                onMouseEnter={() => setHoverId(entry.id)}
                onMouseLeave={() => setHoverId(null)}
              >
                <span className="wh-tl-pos-label">
                  <strong>{entry.role}</strong>
                  <small>
                    {entry.employer} · {bar.pending ? `starts ${monthLabel(bar.start)}` : formatDuration(bar.end - bar.start)}
                  </small>
                </span>
              </button>
            )
          })}

          {/* Events */}
          {events.map((ev) => {
            const involved = ev.items.some((it) => it.bar.entry.id === active)
            const kind = ev.items.every((it) => it.kind === 'start')
              ? 'start'
              : ev.items.every((it) => it.kind === 'end')
                ? 'end'
                : 'switch'
            const alignRight = x(ev.at) > width - 220
            const alignLeft = x(ev.at) < 120
            return (
              <button
                key={ev.at}
                type="button"
                className={`wh-tl-event ${kind}${involved ? ' active' : ''}`}
                style={{ left: x(ev.at), top: EVENT_ROW / 2 - 2 }}
                onClick={() => onSelect(ev.items[ev.items.length - 1].bar.entry.id)}
                aria-label={ev.items
                  .map((it) =>
                    it.kind === 'start'
                      ? `Joined ${it.bar.entry.employer} in ${monthLabel(ev.at)}`
                      : `Left ${it.bar.entry.employer} in ${monthLabel(ev.at - 1)}`,
                  )
                  .join('; ')}
              >
                <span className={`wh-tl-tip${alignRight ? ' right' : alignLeft ? ' left' : ''}`} aria-hidden>
                  {ev.items.map((it) => (
                    <span key={`${it.kind}-${it.bar.entry.id}`} className="wh-tl-tip-row">
                      <i className={`tone-${it.bar.tone}`} />
                      {it.kind === 'start' ? (
                        <>
                          Joined <strong>{it.bar.entry.employer}</strong> as {it.bar.entry.role}
                          <em>{monthLabel(ev.at)}</em>
                        </>
                      ) : (
                        <>
                          Left <strong>{it.bar.entry.employer}</strong>
                          <em>{monthLabel(ev.at - 1)}</em>
                        </>
                      )}
                    </span>
                  ))}
                </span>
              </button>
            )
          })}

          {/* Scroll position pointer */}
          {pointer !== null && (
            <div className="wh-tl-pointer" style={{ left: x(pointer), top: 4, height: height - 4 }} aria-hidden>
              <span>{monthLabel(pointer)}</span>
            </div>
          )}
        </div>
      </div>

      <p className="wh-tl-hint">
        Click a position to jump to it · Drag or scroll to pan · Ctrl/⌘ + scroll to zoom · ← → to step through positions
      </p>
    </section>
  )
}
