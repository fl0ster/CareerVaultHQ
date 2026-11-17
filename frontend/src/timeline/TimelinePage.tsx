import { type ReactNode, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import './timeline.css'
import '../jobs/jobs.css'
import {
  type EventsQuery,
  type JobEvaluatedPayload,
  type ScrapeRunPayload,
  type TimelineEvent,
  type TimelineStatus,
  timelineApi,
} from './api.ts'
import { type EvaluatedJob, jobsApi } from '../jobs/api.ts'
import JobDialog from '../jobs/JobDialog.tsx'
import RelevanceMeter from '../jobs/RelevanceMeter.tsx'
import CreateApplicationButton from '../jobs/CreateApplicationButton.tsx'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'

const PAGE_SIZE = 100
const MARK_READ_DELAY = 800
/** Space kept between an element we scroll to and the viewport edge. */
const SCROLL_MARGIN = 24

// --- grouping -------------------------------------------------------------------------

type Item =
  | { kind: 'day'; key: string; label: string }
  | { kind: 'marker'; key: string }
  | { kind: 'event'; key: string; event: TimelineEvent }
  | { kind: 'group'; key: string; events: TimelineEvent[] }

/** Jobs below the relevance threshold are folded together; everything else stands alone. */
function isFoldable(event: TimelineEvent): boolean {
  return event.type === 'job_evaluated' && event.relevant !== true
}

function dayLabel(date: Date): string {
  const today = new Date()
  const yesterday = new Date()
  yesterday.setDate(today.getDate() - 1)
  if (date.toDateString() === today.toDateString()) return 'Today'
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return date.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
}

/** Turn events (ascending, as loaded) into rows, newest first: day separators above each
 * day's events, the "new since your last visit" marker between the unread events (above)
 * and the read ones (below), standalone events and folded runs of non-relevant jobs (also
 * newest first). Separators and the marker always end a folded run. */
function buildItems(events: TimelineEvent[], lastRead: number | null): Item[] {
  const items: Item[] = []
  let day = ''
  let unreadSeen = false
  let markerPlaced = false
  let group: Extract<Item, { kind: 'group' }> | null = null

  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i]
    if (lastRead !== null && !markerPlaced) {
      if (event.id > lastRead) {
        unreadSeen = true
      } else if (unreadSeen) {
        markerPlaced = true
        group = null
        items.push({ kind: 'marker', key: 'marker' })
      }
    }
    const date = new Date(event.occurred_at)
    const nextDay = date.toDateString()
    if (nextDay !== day) {
      day = nextDay
      group = null
      items.push({ kind: 'day', key: `day-${event.id}`, label: dayLabel(date) })
    }
    if (isFoldable(event)) {
      if (group === null) {
        group = { kind: 'group', key: '', events: [] }
        items.push(group)
      }
      group.events.push(event)
      // Keyed by its oldest event, so newly arrived jobs joining the run keep it mounted.
      group.key = `group-${event.id}`
    } else {
      group = null
      items.push({ kind: 'event', key: `event-${event.id}`, event })
    }
  }
  // Everything loaded is unread: the read part (if any) starts below.
  if (!markerPlaced && unreadSeen) items.push({ kind: 'marker', key: 'marker' })
  return sortWithinRuns(items)
}

/** Scrape run a job row belongs to (null for anything else). */
function runOf(item: Item): number | null {
  if (item.kind === 'event') return item.event.type === 'job_evaluated' ? item.event.scrape_run_id : null
  if (item.kind === 'group') return item.events[0].scrape_run_id
  return null
}

/** Within each stretch of adjacent rows from the same scrape run, put the relevant jobs on
 * top and fold all the non-relevant ones into a single group below them. */
function sortWithinRuns(items: Item[]): Item[] {
  const out: Item[] = []
  let i = 0
  while (i < items.length) {
    const run = runOf(items[i])
    if (run === null) {
      out.push(items[i++])
      continue
    }
    let j = i
    while (j < items.length && runOf(items[j]) === run) j++
    const folded: TimelineEvent[] = []
    for (const item of items.slice(i, j)) {
      if (item.kind === 'group') folded.push(...item.events)
      else out.push(item)
    }
    if (folded.length) {
      folded.sort((a, b) => b.id - a.id)
      // Keyed by its oldest event, so newly arrived jobs joining the run keep it mounted.
      out.push({ kind: 'group', key: `group-${folded[folded.length - 1].id}`, events: folded })
    }
    i = j
  }
  return out
}

// --- renderers ------------------------------------------------------------------------

function time(event: TimelineEvent): string {
  return new Date(event.occurred_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function ScrapeRunRow({ event }: { event: TimelineEvent }) {
  const p = event.payload as ScrapeRunPayload
  const failed = p.status === 'failed'
  const partial = !failed && p.failed_sources.length > 0
  return (
    <div className={`tl-row tl-scrape${failed ? ' failed' : ''}`}>
      <span className="tl-icon" aria-hidden="true">
        {failed ? '⚠' : '⟳'}
      </span>
      <div className="tl-body">
        <div>
          {failed ? 'Scrape failed' : 'Scraped'} <strong>{p.source_name ?? 'all sources'}</strong>
          {!failed && (
            <span className="muted">
              {' '}
              · {p.new} new · {p.duplicates} already seen
            </span>
          )}
        </div>
        {partial && <div className="error">Failed sources: {p.failed_sources.join(', ')}</div>}
        {p.error && <div className="error tl-error">{p.error}</div>}
      </div>
      <time className="tl-time">{time(event)}</time>
    </div>
  )
}

/** Company name with its current tag (the tag can change after the event was recorded). */
function Company({ event }: { event: TimelineEvent }) {
  const p = event.payload as JobEvaluatedPayload
  return (
    <>
      {p.company_name ?? 'Unknown company'}{' '}
      <CompanyTagBadge companyId={event.company_id ?? p.company_id} tag={event.company_tag} />
    </>
  )
}

function RelevantJobRow({ event, ctx }: { event: TimelineEvent; ctx: RenderContext }) {
  const p = event.payload as JobEvaluatedPayload
  const evaluationId = event.evaluation_id
  return (
    <div className="tl-job relevant">
      <button type="button" className="tl-row" onClick={() => ctx.onOpenJob(event)}>
        <span className="tl-icon" aria-hidden="true">
          ★
        </span>
        <div className="tl-body">
          <div className="job-title">
            {p.title ?? 'Untitled job'}
            {event.application_id != null && <span className="badge app-status applied">Application</span>}
          </div>
          <div className="muted">
            <Company event={event} />
            {p.source_name && <> · {p.source_name}</>}
          </div>
        </div>
        <time className="tl-time">{time(event)}</time>
      </button>
      <div className="tl-job-side">
        {event.relevance !== null && <RelevanceMeter relevance={event.relevance} />}
        {event.application_id == null && evaluationId != null && event.job_id != null && (
          <CreateApplicationButton
            evaluationId={evaluationId}
            onCreated={(applicationId) => ctx.onApplied(event.job_id!, applicationId)}
          />
        )}
      </div>
    </div>
  )
}

function OtherJobRow({ event, onOpen }: { event: TimelineEvent; onOpen: (e: TimelineEvent) => void }) {
  const p = event.payload as JobEvaluatedPayload
  return (
    <button type="button" className="tl-row tl-job compact" onClick={() => onOpen(event)}>
      <div className="tl-body">
        <span className="tl-job-title">{p.title ?? 'Untitled job'}</span>
        <span className="muted">
          {' '}
          · <Company event={event} />
        </span>
      </div>
      {event.relevance !== null && <RelevanceMeter relevance={event.relevance} />}
    </button>
  )
}

function GenericRow({ event }: { event: TimelineEvent }) {
  return (
    <div className="tl-row">
      <span className="tl-icon" aria-hidden="true">
        •
      </span>
      <div className="tl-body">{event.type.replaceAll('_', ' ')}</div>
      <time className="tl-time">{time(event)}</time>
    </div>
  )
}

type RenderContext = {
  onOpenJob: (e: TimelineEvent) => void
  onApplied: (jobId: number, applicationId: number) => void
}

/** One renderer per event type. A new kind of event only needs an entry here (unknown
 * types fall back to ``GenericRow``). */
const RENDERERS: Record<string, (event: TimelineEvent, ctx: RenderContext) => ReactNode> = {
  scrape_run: (event) => <ScrapeRunRow event={event} />,
  job_evaluated: (event, ctx) => <RelevantJobRow event={event} ctx={ctx} />,
}

function JobGroup({
  events,
  expanded,
  onToggle,
  onOpen,
}: {
  events: TimelineEvent[]
  expanded: boolean
  onToggle: () => void
  onOpen: (e: TimelineEvent) => void
}) {
  const n = events.length
  const sources = [...new Set(events.map((e) => (e.payload as JobEvaluatedPayload).source_name).filter(Boolean))]
  return (
    <div className="tl-group">
      <button type="button" className="tl-row tl-group-toggle" aria-expanded={expanded} onClick={onToggle}>
        <span className="tl-icon" aria-hidden="true">
          {expanded ? '▾' : '▸'}
        </span>
        <div className="tl-body muted">
          {n} other new {n === 1 ? 'job' : 'jobs'} below the relevance threshold
          {sources.length > 0 && <> · {sources.join(', ')}</>}
        </div>
        <time className="tl-time">{time(events[0])}</time>
      </button>
      {expanded && (
        <ul className="tl-group-items">
          {events.map((e) => (
            <li key={e.id}>
              <OtherJobRow event={e} onOpen={onOpen} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// --- page -----------------------------------------------------------------------------

/** The top-most visible item, its distance from the viewport top and the scroll position
 * at the time it was measured. */
type Anchor = { id: string; offset: number; scrollY: number }

type Props = {
  /** Whether the Timeline tab is the visible one. */
  active: boolean
  status: TimelineStatus | null
  onStatus: (status: TimelineStatus) => void
}

function itemElements(list: HTMLElement | null): HTMLElement[] {
  return list ? Array.from(list.querySelectorAll<HTMLElement>('[data-last]')) : []
}

/** Bottom edge of the sticky tab bar + timeline header: content above it is covered. */
function stickyBottom(): number {
  return document.querySelector('.tl-header')?.getBoundingClientRect().bottom ?? 0
}

function scrollToElement(el: HTMLElement, offset = SCROLL_MARGIN, behavior: ScrollBehavior = 'auto') {
  window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - offset - stickyBottom(), behavior })
}

export default function TimelinePage({ active, status, onStatus }: Props) {
  const [events, setEvents] = useState<TimelineEvent[]>([])
  const [hasOlder, setHasOlder] = useState(false)
  const [hasNewer, setHasNewer] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [initialized, setInitialized] = useState(false)
  /** Read cursor as it was when the timeline was opened: where the marker goes. */
  const [unreadFrom, setUnreadFrom] = useState<number | null>(null)
  /** Newest event id when the timeline was opened; anything above it arrived meanwhile. */
  const [openedAtLatest, setOpenedAtLatest] = useState(0)
  /** Furthest event scrolled past (mirrors ``maxSeenRef`` for rendering). */
  const [maxSeen, setMaxSeen] = useState(0)
  const [atTop, setAtTop] = useState(false)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [selected, setSelected] = useState<EvaluatedJob | null>(null)

  const listRef = useRef<HTMLOListElement>(null)
  const topSentinel = useRef<HTMLDivElement>(null)
  const bottomSentinel = useRef<HTMLDivElement>(null)
  // Mirrors for event handlers and observers so they never read stale state.
  const eventsRef = useRef<TimelineEvent[]>([])
  const hasOlderRef = useRef(false)
  const hasNewerRef = useRef(false)
  const loadingRef = useRef(false)
  const activeRef = useRef(active)
  const readyRef = useRef(false)
  const maxSeenRef = useRef(0)
  const sentReadRef = useRef(0)
  const readTimer = useRef<number | undefined>(undefined)
  /** Set when the first page is loaded: scroll to the starting position once it renders. */
  const pendingEntry = useRef(false)
  /** Top-most visible item and its distance from the viewport top, restored on re-entry. */
  const anchorRef = useRef<Anchor | null>(null)

  const applyPage = useCallback((next: TimelineEvent[], older: boolean, newer: boolean) => {
    eventsRef.current = next
    hasOlderRef.current = older
    hasNewerRef.current = newer
    setEvents(next)
    setHasOlder(older)
    setHasNewer(newer)
  }, [])

  // Keep the mirror in step with in-place updates (e.g. an application created from a row).
  useEffect(() => {
    eventsRef.current = events
  }, [events])

  // --- read cursor --------------------------------------------------------------------

  const flushRead = useCallback(
    (keepalive = false) => {
      window.clearTimeout(readTimer.current)
      const id = maxSeenRef.current
      if (id <= sentReadRef.current) return
      sentReadRef.current = id
      timelineApi
        .markRead(id, keepalive)
        .then(onStatus)
        .catch(() => {
          sentReadRef.current = 0 // retry with the next flush
        })
    },
    [onStatus],
  )

  const markSeen = useCallback(
    (id: number) => {
      if (id <= maxSeenRef.current) return
      maxSeenRef.current = id
      setMaxSeen(id)
      window.clearTimeout(readTimer.current)
      readTimer.current = window.setTimeout(() => flushRead(), MARK_READ_DELAY)
    },
    [flushRead],
  )

  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === 'hidden') flushRead(true)
    }
    const onPageHide = () => flushRead(true)
    document.addEventListener('visibilitychange', onHide)
    window.addEventListener('pagehide', onPageHide)
    return () => {
      document.removeEventListener('visibilitychange', onHide)
      window.removeEventListener('pagehide', onPageHide)
    }
  }, [flushRead])

  /** Look at what is on screen. Newer items sit above older ones, so the top-most item
   * whose top edge is visible counts as read along with everything below it; the top-most
   * visible item becomes the anchor to come back to. */
  const inspectViewport = useCallback(() => {
    if (!activeRef.current || !readyRef.current) return
    const viewport = window.innerHeight
    const covered = stickyBottom()
    let seen = 0
    let anchor: Anchor | null = null
    for (const el of itemElements(listRef.current)) {
      const rect = el.getBoundingClientRect()
      if (rect.bottom <= covered) continue
      anchor ??= { id: el.dataset.first!, offset: rect.top - covered, scrollY: window.scrollY }
      if (rect.top >= viewport) break
      if (rect.top >= covered - 1) {
        seen = Number(el.dataset.last)
        break
      }
    }
    if (anchor) anchorRef.current = anchor
    if (seen) markSeen(seen)
    const sentinel = topSentinel.current
    setAtTop(!hasNewerRef.current && !!sentinel && sentinel.getBoundingClientRect().bottom >= covered)
  }, [markSeen])

  useEffect(() => {
    let frame = 0
    const onScroll = () => {
      if (frame) return
      frame = window.requestAnimationFrame(() => {
        frame = 0
        inspectViewport()
      })
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      window.cancelAnimationFrame(frame)
    }
  }, [inspectViewport])

  // --- loading ------------------------------------------------------------------------

  const load = useCallback(async (query: EventsQuery) => {
    loadingRef.current = true
    setLoading(true)
    setError(null)
    try {
      return await timelineApi.events(query, PAGE_SIZE)
    } catch (e) {
      setError(`Could not load the timeline: ${e instanceof Error ? e.message : String(e)}`)
      return null
    } finally {
      loadingRef.current = false
      setLoading(false)
    }
  }, [])

  const loadNewer = useCallback(async () => {
    if (loadingRef.current) return
    const current = eventsRef.current
    const page = await load({ after_id: current.at(-1)?.id ?? maxSeenRef.current })
    if (!page) return
    const merged = [...eventsRef.current, ...page.events]
    applyPage(merged, current.length ? hasOlderRef.current : page.has_older, page.has_newer)
  }, [applyPage, load])

  const loadOlder = useCallback(async () => {
    if (loadingRef.current || !hasOlderRef.current) return
    const first = eventsRef.current[0]
    if (!first) return
    const page = await load({ before_id: first.id })
    if (!page) return
    applyPage([...page.events, ...eventsRef.current], page.has_older, hasNewerRef.current)
  }, [applyPage, load])

  // First time the tab is opened: load around the read cursor.
  useEffect(() => {
    if (!active || initialized || loadingRef.current) return
    let cancelled = false
    ;(async () => {
      loadingRef.current = true
      try {
        const current = await timelineApi.status()
        if (cancelled) return
        onStatus(current)
        loadingRef.current = false
        const page = await load({ around_id: current.last_read_id })
        if (cancelled || !page) return
        maxSeenRef.current = current.last_read_id
        sentReadRef.current = current.last_read_id
        setMaxSeen(current.last_read_id)
        setUnreadFrom(current.last_read_id)
        setOpenedAtLatest(current.latest_id)
        pendingEntry.current = true
        applyPage(page.events, page.has_older, page.has_newer)
        setInitialized(true)
      } catch (e) {
        if (!cancelled) setError(`Could not load the timeline: ${e instanceof Error ? e.message : String(e)}`)
      } finally {
        loadingRef.current = false
      }
    })()
    return () => {
      cancelled = true
    }
  }, [active, initialized, load, applyPage, onStatus])

  // Starting position once the first page renders: the "new since your last visit" marker
  // at the top, so the latest read items are on screen and the unread ones wait above; with
  // nothing unread, the top (the newest event).
  useLayoutEffect(() => {
    if (!pendingEntry.current || !active) return
    pendingEntry.current = false
    const marker = listRef.current?.querySelector<HTMLElement>('[data-marker]')
    if (marker) scrollToElement(marker)
    else window.scrollTo(0, 0)
    readyRef.current = true
    inspectViewport()
  }, [events, active, inspectViewport])

  // Tab switches: the window scroll is shared by all tabs, so remember where we were and
  // go back there when the tab is shown again.
  useLayoutEffect(() => {
    activeRef.current = active
    if (!active) {
      flushRead()
      return
    }
    const anchor = anchorRef.current
    if (!readyRef.current || pendingEntry.current || !anchor) return
    const el = listRef.current?.querySelector<HTMLElement>(`[data-first="${anchor.id}"]`)
    if (el) scrollToElement(el, anchor.offset)
    inspectViewport()
  }, [active, flushRead, inspectViewport])

  // Expose the sticky header's height so the bubble can sit just below it.
  const headerRef = useRef<HTMLElement>(null)
  useEffect(() => {
    const el = headerRef.current
    if (!el) return
    const update = () => document.documentElement.style.setProperty('--tl-header-h', `${el.offsetHeight}px`)
    const observer = new ResizeObserver(update)
    observer.observe(el)
    update()
    return () => observer.disconnect()
  }, [])

  // The page never scrolls on its own: whatever a render changes (newer events inserted
  // above, the header's unread line, a new day label), the item being looked at stays put
  // on screen. Runs after every render. The browser's scroll anchoring is switched off for
  // the timeline (see the CSS) so the two cannot fight; the anchor's offset is adjusted by
  // any scrolling done since it was measured.
  useLayoutEffect(() => {
    const anchor = anchorRef.current
    if (!active || !readyRef.current || pendingEntry.current || !anchor) return
    const el = listRef.current?.querySelector<HTMLElement>(`[data-first="${anchor.id}"]`)
    if (!el) return
    const expected = anchor.offset + stickyBottom() - (window.scrollY - anchor.scrollY)
    const drift = el.getBoundingClientRect().top - expected
    if (Math.abs(drift) >= 1) window.scrollBy(0, drift)
    inspectViewport()
  })

  // New events reported by the status poll are loaded right away when the newest end of the
  // timeline is loaded; they land above the reading position and the bubble points at them.
  const latestId = status?.latest_id ?? 0
  useEffect(() => {
    if (!initialized || hasNewerRef.current) return
    const newest = eventsRef.current.at(-1)?.id ?? 0
    if (latestId > newest) loadNewer()
  }, [latestId, initialized, loadNewer])

  // Infinite scroll in both directions. Recreated whenever the list changes so a sentinel
  // that is still in view after a load triggers the next one.
  useEffect(() => {
    if (!initialized) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (!activeRef.current || !readyRef.current) return
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          if (entry.target === topSentinel.current && hasNewerRef.current) loadNewer()
          if (entry.target === bottomSentinel.current && hasOlderRef.current) loadOlder()
        }
      },
      { rootMargin: '300px' },
    )
    if (topSentinel.current) observer.observe(topSentinel.current)
    if (bottomSentinel.current) observer.observe(bottomSentinel.current)
    return () => observer.disconnect()
  }, [initialized, events, loadOlder, loadNewer])

  // Items that fit on screen without scrolling are read as soon as they render.
  useEffect(() => {
    inspectViewport()
  }, [events, expanded, inspectViewport])

  // --- actions ------------------------------------------------------------------------

  /** Bring the oldest unread item up from the top edge, so reading continues upwards. */
  const jumpToUnread = async () => {
    const oldestUnread = () =>
      itemElements(listRef.current)
        .filter((el) => Number(el.dataset.last) > maxSeenRef.current)
        .at(-1)
    if (!oldestUnread() && hasNewerRef.current) await loadNewer()
    // Wait a frame for the inserted items to render.
    window.requestAnimationFrame(() => {
      const el = oldestUnread()
      if (el) {
        const bottom = el.getBoundingClientRect().bottom + window.scrollY
        window.scrollTo({ top: bottom - window.innerHeight + SCROLL_MARGIN, behavior: 'smooth' })
      } else {
        window.scrollTo({ top: 0, behavior: 'smooth' })
      }
    })
  }

  const markAllRead = () => {
    if (!status) return
    markSeen(status.latest_id)
    flushRead()
  }

  const toggleGroup = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (!next.delete(key)) next.add(key)
      return next
    })

  const openJob = async (event: TimelineEvent) => {
    const link = (event.payload as JobEvaluatedPayload).link
    if (event.job_id === null) {
      window.open(link, '_blank', 'noreferrer')
      return
    }
    try {
      const detail = await jobsApi.get(event.job_id)
      if (detail.evaluation) setSelected({ ...detail, evaluation: detail.evaluation })
      else window.open(link, '_blank', 'noreferrer')
    } catch {
      window.open(link, '_blank', 'noreferrer')
    }
  }

  const applied = (jobId: number, applicationId: number) => {
    setEvents((prev) => prev.map((e) => (e.job_id === jobId ? { ...e, application_id: applicationId } : e)))
    setSelected((prev) => (prev?.id === jobId ? { ...prev, application_id: applicationId } : prev))
  }

  // --- render -------------------------------------------------------------------------

  const items = buildItems(events, unreadFrom)
  const newestLoaded = events.at(-1)?.id ?? 0
  const unreadAbove = hasNewer || newestLoaded > maxSeen
  const arrivedMeanwhile = Math.max(latestId, newestLoaded) > openedAtLatest && maxSeen < Math.max(latestId, newestLoaded)
  const showBubble = active && initialized && unreadAbove && !atTop
  const ctx: RenderContext = { onOpenJob: openJob, onApplied: applied }

  return (
    <div className="timeline">
      <header className="tl-header" ref={headerRef}>
        <p>
          {status === null
            ? 'Loading…'
            : status.unread === 0
              ? null
              : `${status.unread} unread ${status.unread === 1 ? 'event' : 'events'}${
                  status.unread_relevant ? `, ${status.unread_relevant} relevant ${status.unread_relevant === 1 ? 'job' : 'jobs'}` : ''
                }.`}{' '}
          {status !== null && status.unread > 0 && (
            <button type="button" className="secondary small" onClick={markAllRead}>
              Mark all as read
            </button>
          )}
        </p>
      </header>

      {error && <p className="error">{error}</p>}

      <div ref={topSentinel} className="sentinel">
        {loading && (hasNewer || !initialized) && <span className="spinner" aria-hidden="true" />}
        {initialized && !hasNewer && events.length > 0 && <span className="muted">You are all caught up.</span>}
      </div>

      {initialized && events.length === 0 && !hasNewer ? (
        <p className="muted">Nothing here yet. Scrape runs and newly scored jobs will show up as they happen.</p>
      ) : (
        <ol className="tl-list" ref={listRef}>
          {items.map((item) => {
            switch (item.kind) {
              case 'day':
                return (
                  <li key={item.key} className="tl-day">
                    {item.label}
                  </li>
                )
              case 'marker':
                return (
                  <li key={item.key} className="tl-marker" data-marker="">
                    <span>↑ New since your last visit</span>
                  </li>
                )
              case 'group': {
                const first = item.events[item.events.length - 1].id
                const last = item.events[0].id
                return (
                  <li key={item.key} data-first={first} data-last={last} className={last > maxSeen ? 'unread' : undefined}>
                    <JobGroup
                      events={item.events}
                      expanded={expanded.has(item.key)}
                      onToggle={() => toggleGroup(item.key)}
                      onOpen={openJob}
                    />
                  </li>
                )
              }
              case 'event': {
                const render = RENDERERS[item.event.type]
                return (
                  <li
                    key={item.key}
                    data-first={item.event.id}
                    data-last={item.event.id}
                    className={item.event.id > maxSeen ? 'unread' : undefined}
                  >
                    {render ? render(item.event, ctx) : <GenericRow event={item.event} />}
                  </li>
                )
              }
            }
          })}
        </ol>
      )}

      <div ref={bottomSentinel} className="sentinel">
        {loading && initialized && hasOlder && <span className="spinner" aria-hidden="true" />}
        {initialized && !hasOlder && events.length > 0 && <span className="muted">Beginning of the timeline</span>}
      </div>

      {showBubble && (
        <button type="button" className="tl-bubble" onClick={jumpToUnread}>
          {arrivedMeanwhile ? 'New updates!' : 'Unread above'}
          {status && status.unread_relevant > 0 && (
            <span className="tl-bubble-count">★ {status.unread_relevant}</span>
          )}
          <span aria-hidden="true">↑</span>
        </button>
      )}

      {selected && (
        <JobDialog
          key={selected.id}
          job={selected}
          onClose={() => setSelected(null)}
          onApplicationCreated={(applicationId) => applied(selected.id, applicationId)}
        />
      )}
    </div>
  )
}
