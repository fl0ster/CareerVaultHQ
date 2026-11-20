import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { WorkHistoryEntry } from './api.ts'

/*
 * Horizontal, scrollable timeline of work history positions.
 *
 * Time is measured in "month indices" (year * 12 + month0), possibly fractional for today.
 * A position covers [start month, end month + 1), so "Jan 2020 – Mar 2020" spans 3 months.
 * Overlapping positions are packed into separate lanes. Above the lanes is an event row
 * (joined / left markers, merged when they fall on the same boundary), behind them are
 * shaded career gaps and a "today" line, and below is the year/month axis.
 */

const PAD = 32
const EVENT_ROW = 40
const LANE_H = 48
const LANE_GAP = 10
const AXIS_H = 34
const MIN_PPM = 4
const MAX_PPM = 96
const DEFAULT_PPM = 18
const TONES = ['accent', 'info', 'success', 'lavender', 'peach', 'warn'] as const

type Bar = {
  entry: WorkHistoryEntry
  start: number
  end: number
  ongoing: boolean
  lane: number
  tone: (typeof TONES)[number]
}

type TimelineEvent = {
  at: number
  items: { kind: 'start' | 'end'; bar: Bar }[]
}

function monthIndex(iso: string): number {
  const [y, m] = iso.split('-').map(Number)
  return y * 12 + (m - 1)
}

function todayIndex(): number {
  const now = new Date()
  const days = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate()
  return now.getFullYear() * 12 + now.getMonth() + (now.getDate() - 1) / days
}

function monthLabel(index: number, style: 'short' | 'long' = 'long'): string {
  const i = Math.floor(index)
  const d = new Date(Math.floor(i / 12), i % 12, 1)
  return d.toLocaleDateString(undefined, style === 'long' ? { year: 'numeric', month: 'short' } : { month: 'short' })
}

function formatDuration(months: number): string {
  const total = Math.max(1, Math.round(months))
  const y = Math.floor(total / 12)
  const m = total % 12
  const parts = []
  if (y) parts.push(`${y} yr${y === 1 ? '' : 's'}`)
  if (m) parts.push(`${m} mo${m === 1 ? '' : 's'}`)
  return parts.join(' ')
}

function layout(entries: WorkHistoryEntry[], today: number) {
  const sorted = [...entries].sort(
    (a, b) => a.date_start.localeCompare(b.date_start) || (a.date_end ?? '9').localeCompare(b.date_end ?? '9'),
  )
  const laneEnds: number[] = []
  const bars: Bar[] = sorted.map((entry, i) => {
    const start = monthIndex(entry.date_start)
    const ongoing = entry.date_end === null
    const end = ongoing ? Math.max(today, start + 0.5) : monthIndex(entry.date_end!) + 1
    let lane = laneEnds.findIndex((e) => e <= start)
    if (lane === -1) lane = laneEnds.length
    laneEnds[lane] = end
    return { entry, start, end, ongoing, lane, tone: TONES[i % TONES.length] }
  })

  const byAt = new Map<number, TimelineEvent>()
  const push = (at: number, kind: 'start' | 'end', bar: Bar) => {
    const ev = byAt.get(at) ?? { at, items: [] }
    ev.items.push({ kind, bar })
    byAt.set(at, ev)
  }
  for (const bar of bars) {
    push(bar.start, 'start', bar)
    if (!bar.ongoing) push(bar.end, 'end', bar)
  }
  const events = [...byAt.values()].sort((a, b) => a.at - b.at)
  for (const ev of events) ev.items.sort((a, b) => (a.kind === b.kind ? 0 : a.kind === 'end' ? -1 : 1))

  // Gaps: holes in the union of all positions, plus months covered (for the summary).
  const gaps: { start: number; end: number }[] = []
  let covered = 0
  let cursor = -Infinity
  let runStart = 0
  for (const bar of [...bars].sort((a, b) => a.start - b.start)) {
    if (bar.start > cursor) {
      if (cursor !== -Infinity) {
        covered += cursor - runStart
        if (bar.start - cursor >= 1) gaps.push({ start: cursor, end: bar.start })
      }
      runStart = bar.start
    }
    cursor = Math.max(cursor, bar.end)
  }
  if (cursor !== -Infinity) covered += cursor - runStart

  const minStart = Math.min(...bars.map((b) => b.start))
  const maxEnd = Math.max(today, ...bars.map((b) => b.end))
  const rangeStart = Math.floor(minStart / 12) * 12
  const rangeEnd = Math.ceil((maxEnd + 0.01) / 12) * 12

  return { bars, events, gaps, covered, rangeStart, rangeEnd, lanes: Math.max(1, laneEnds.length) }
}

export default function WorkHistoryTimeline({
  entries,
  onEdit,
}: {
  entries: WorkHistoryEntry[]
  onEdit: (entry: WorkHistoryEntry) => void
}) {
  const today = useMemo(() => todayIndex(), [])
  const { bars, events, gaps, covered, rangeStart, rangeEnd, lanes } = useMemo(
    () => layout(entries, today),
    [entries, today],
  )
  const [ppm, setPpm] = useState(DEFAULT_PPM)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [hoverId, setHoverId] = useState<number | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const barRefs = useRef(new Map<number, HTMLButtonElement>())
  // Month to keep under a given viewport x after a zoom; applied once the new width is laid out.
  const zoomAnchor = useRef<{ month: number; x: number } | null>(null)
  const drag = useRef<{ x: number; left: number; moved: boolean } | null>(null)

  const selected = bars.find((b) => b.entry.id === selectedId) ?? null
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

  const select = (id: number | null, focus = false) => {
    setSelectedId(id)
    if (id === null) return
    const btn = barRefs.current.get(id)
    if (!btn) return
    if (focus) btn.focus({ preventScroll: true })
    btn.scrollIntoView({ behavior: 'smooth', inline: 'nearest', block: 'nearest' })
  }

  const ordered = useMemo(() => [...bars].sort((a, b) => a.start - b.start), [bars])
  const onBarKey = (e: React.KeyboardEvent, bar: Bar) => {
    const i = ordered.indexOf(bar)
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      const next = ordered[i + (e.key === 'ArrowRight' ? 1 : -1)]
      if (next) select(next.entry.id, true)
    } else if (e.key === 'Escape') {
      setSelectedId(null)
    }
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
      // Swallow the click that follows a drag so it doesn't select/deselect.
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

  const active = hoverId ?? selectedId

  return (
    <section className="wh-tl" aria-label="Work history timeline">
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
        onClick={(e) => {
          if (e.target === e.currentTarget || (e.target as HTMLElement).classList.contains('wh-tl-canvas')) {
            setSelectedId(null)
          }
        }}
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

          {/* Selected/hovered position's span, projected onto the axis */}
          {active !== null &&
            (() => {
              const b = bars.find((bar) => bar.entry.id === active)
              if (!b) return null
              return (
                <div
                  className={`wh-tl-span tone-${b.tone}`}
                  style={{ left: x(b.start), width: (b.end - b.start) * ppm, top: lanesTop - 6, height: height - lanesTop + 6 }}
                />
              )
            })()}

          {/* Today */}
          <div className="wh-tl-today" style={{ left: x(today), top: 8, height: height - 8 - AXIS_H }}>
            <span>Today</span>
          </div>

          {/* Positions */}
          {bars.map((bar) => {
            const w = Math.max(6, (bar.end - bar.start) * ppm)
            const { entry } = bar
            const isSel = entry.id === selectedId
            const dim = active !== null && entry.id !== active
            return (
              <button
                key={entry.id}
                ref={(el) => {
                  if (el) barRefs.current.set(entry.id, el)
                  else barRefs.current.delete(entry.id)
                }}
                type="button"
                className={`wh-tl-pos tone-${bar.tone}${bar.ongoing ? ' ongoing' : ''}${isSel ? ' selected' : ''}${dim ? ' dim' : ''}`}
                style={{ left: x(bar.start), width: w, top: lanesTop + bar.lane * (LANE_H + LANE_GAP), height: LANE_H }}
                aria-pressed={isSel}
                aria-label={`${entry.role} at ${entry.employer}, ${monthLabel(bar.start)} to ${bar.ongoing ? 'present' : monthLabel(bar.end - 1)}, ${formatDuration(bar.end - bar.start)}`}
                title={`${entry.role} at ${entry.employer}`}
                onClick={() => select(isSel ? null : entry.id)}
                onKeyDown={(e) => onBarKey(e, bar)}
                onMouseEnter={() => setHoverId(entry.id)}
                onMouseLeave={() => setHoverId(null)}
                onFocus={() => setHoverId(entry.id)}
                onBlur={() => setHoverId(null)}
              >
                <span className="wh-tl-pos-label">
                  <strong>{entry.role}</strong>
                  <small>
                    {entry.employer} · {formatDuration(bar.end - bar.start)}
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
                onClick={() => select(ev.items[ev.items.length - 1].bar.entry.id)}
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
        </div>
      </div>

      <p className="wh-tl-hint">Drag or scroll to pan · Ctrl/⌘ + scroll to zoom · ← → to step through positions</p>

      {selected && (
        <div className={`wh-tl-detail tone-${selected.tone}`}>
          <div className="wh-tl-detail-head">
            <div>
              <strong>{selected.entry.role}</strong> at {selected.entry.employer}
              <div className="wh-meta">
                <span>
                  {monthLabel(selected.start)} – {selected.ongoing ? 'present' : monthLabel(selected.end - 1)}
                </span>
                <span>{formatDuration(selected.end - selected.start)}</span>
                {selected.entry.location && <span>{selected.entry.location}</span>}
              </div>
            </div>
            <div className="wh-buttons">
              <button type="button" className="secondary small" onClick={() => onEdit(selected.entry)}>
                Edit
              </button>
              <button type="button" className="secondary small" onClick={() => setSelectedId(null)}>
                Close
              </button>
            </div>
          </div>
          {selected.entry.tech.length > 0 && (
            <div className="wh-tech">
              {selected.entry.tech.map((t) => (
                <span key={t} className="badge">
                  {t}
                </span>
              ))}
            </div>
          )}
          {selected.entry.context && <pre className="wh-context">{selected.entry.context}</pre>}
        </div>
      )}
    </section>
  )
}
