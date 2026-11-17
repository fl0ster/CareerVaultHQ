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
/** Space kept above an element we scroll to, so it does not sit flush with the edge. */
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

/** Turn events (ascending) into rows: day separators, the "new since your last visit"
 * marker before the first event after ``lastRead``, standalone events and folded runs of
 * non-relevant jobs. Separators and the marker always end a folded run. */
function buildItems(events: TimelineEvent[], lastRead: number | null): Item[] {
  const items: Item[] = []
  let day = ''
  let markerPlaced = false
  let group: TimelineEvent[] | null = null

  for (const event of events) {
    const date = new Date(event.occurred_at)
    const nextDay = date.toDateString()
    if (nextDay !== day) {
      day = nextDay
      group = null
      items.push({ kind: 'day', key: `day-${event.id}`, label: dayLabel(date) })
    }
    if (!markerPlaced && lastRead !== null && event.id > lastRead) {
      markerPlaced = true
      group = null
      items.push({ kind: 'marker', key: 'marker' })
    }
    if (isFoldable(event)) {
      if (group === null) {
        group = [event]
        items.push({ kind: 'group', key: `group-${event.id}`, events: group })
      } else {
        group.push(event)
      }
    } else {
      group = null
      items.push({ kind: 'event', key: `event-${event.id}`, event })
    }
  }
  return items
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
        <time className="tl-time">{time(events[events.length - 1])}</time>
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

type PendingScroll = { kind: 'entry' } | { kind: 'preserve'; prevHeight: number }

type Props = {
  /** Whether the Timeline tab is the visible one. */
  active: boolean
  status: TimelineStatus | null
  onStatus: (status: TimelineStatus) => void
}

function itemElements(list: HTMLElement | null): HTMLElement[] {
  return list ? Array.from(list.querySelectorAll<HTMLElement>('[data-last]')) : []
}

function scrollToElement(el: HTMLElement, offset = SCROLL_MARGIN, behavior: ScrollBehavior = 'auto') {
  window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - offset, behavior })
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
  const [atBottom, setAtBottom] = useState(false)
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
  const pendingScroll = useRef<PendingScroll | null>(null)
  /** Top-most visible item and its distance from the viewport top, restored on re-entry. */
  const anchorRef = useRef<{ id: string; offset: number } | null>(null)

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

  /** Look at what is on screen: everything whose bottom edge is visible counts as read,
   * and the top-most visible item becomes the anchor to come back to. */
  const inspectViewport = useCallback(() => {
    if (!activeRef.current || !readyRef.current) return
    const viewport = window.innerHeight
    let seen = 0
    let anchor: { id: string; offset: number } | null = null
    for (const el of itemElements(listRef.current)) {
      const rect = el.getBoundingClientRect()
      if (anchor === null && rect.bottom > 0) anchor = { id: el.dataset.first!, offset: rect.top }
      if (rect.bottom <= viewport + 1) seen = Number(el.dataset.last)
      else break
    }
    if (anchor) anchorRef.current = anchor
    if (seen) markSeen(seen)
    const sentinel = bottomSentinel.current
    setAtBottom(!hasNewerRef.current && !!sentinel && sentinel.getBoundingClientRect().top <= viewport)
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
    pendingScroll.current = { kind: 'preserve', prevHeight: document.documentElement.scrollHeight }
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
        pendingScroll.current = { kind: 'entry' }
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

  // Scroll after the DOM reflects a load: to the first unread item on entry, or keep the
  // reading position steady when older events were prepended above it.
  useLayoutEffect(() => {
    const pending = pendingScroll.current
    if (!pending || !active) return
    pendingScroll.current = null
    if (pending.kind === 'preserve') {
      window.scrollBy(0, document.documentElement.scrollHeight - pending.prevHeight)
    } else {
      const marker = listRef.current?.querySelector<HTMLElement>('[data-marker]')
      if (marker) scrollToElement(marker)
      else window.scrollTo(0, document.documentElement.scrollHeight)
    }
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
    if (!readyRef.current || pendingScroll.current || !anchor) return
    const el = listRef.current?.querySelector<HTMLElement>(`[data-first="${anchor.id}"]`)
    if (el) scrollToElement(el, anchor.offset)
    inspectViewport()
  }, [active, flushRead, inspectViewport])

  // New events reported by the status poll are appended right away when the end of the
  // timeline is loaded; they land below the reading position and the bubble points at them.
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
          if (entry.target === topSentinel.current && hasOlderRef.current) loadOlder()
          if (entry.target === bottomSentinel.current && hasNewerRef.current) loadNewer()
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

  const jumpToUnread = async () => {
    const firstUnread = () =>
      itemElements(listRef.current).find((el) => Number(el.dataset.last) > maxSeenRef.current)
    if (!firstUnread() && hasNewerRef.current) await loadNewer()
    // Wait a frame for the appended items to render.
    window.requestAnimationFrame(() => {
      const el = firstUnread()
      if (el) scrollToElement(el, SCROLL_MARGIN, 'smooth')
      else window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' })
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
  const unreadBelow = hasNewer || newestLoaded > maxSeen
  const arrivedMeanwhile = Math.max(latestId, newestLoaded) > openedAtLatest && maxSeen < Math.max(latestId, newestLoaded)
  const showBubble = active && initialized && unreadBelow && !atBottom
  const ctx: RenderContext = { onOpenJob: openJob, onApplied: applied }

  return (
    <div className="timeline">
      <header className="tl-header">
        <h1 className="title">Timeline</h1>
        <p>
          {status === null
            ? 'Loading…'
            : status.unread === 0
              ? 'You are up to date.'
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
        {loading && hasOlder && <span className="spinner" aria-hidden="true" />}
        {initialized && !hasOlder && events.length > 0 && <span className="muted">Beginning of the timeline</span>}
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
                    <span>New since your last visit</span>
                  </li>
                )
              case 'group': {
                const first = item.events[0].id
                const last = item.events[item.events.length - 1].id
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
        {loading && <span className="spinner" aria-hidden="true" />}
        {initialized && !hasNewer && events.length > 0 && <span className="muted">You are all caught up.</span>}
      </div>

      {showBubble && (
        <button type="button" className="tl-bubble" onClick={jumpToUnread}>
          {arrivedMeanwhile ? 'New updates!' : 'Unread below'}
          {status && status.unread_relevant > 0 && (
            <span className="tl-bubble-count">★ {status.unread_relevant}</span>
          )}
          <span aria-hidden="true">↓</span>
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
