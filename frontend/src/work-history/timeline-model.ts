import type { EntryKind, WorkHistoryEntry } from './api.ts'
import { isPoint, KIND_ORDER } from './kinds.ts'

/*
 * Pure layout model shared by the timeline and the list.
 *
 * Time is measured in "month indices" (year * 12 + month0), possibly fractional for today.
 * An entry covers [start month, end month + 1), so "Jan 2020 – Mar 2020" spans 3 months.
 * Overlapping entries are packed into separate lanes, and each kind gets its own band of
 * lanes: positions on top, then education, then certificates. A certificate without an
 * end date is a single point (one month wide for the packing). A pending position
 * (starting in the future) is drawn one month wide from its start. Only positions count
 * towards the time employed and the gaps.
 */

export const TONES = ['accent', 'info', 'success', 'warn'] as const
/** Positions rotate through `TONES`; education and certificates have a tone of their own. */
export const KIND_TONES = { education: 'lavender', certificate: 'peach' } as const
export type Tone = (typeof TONES)[number] | (typeof KIND_TONES)[keyof typeof KIND_TONES]

export type Bar = {
  entry: WorkHistoryEntry
  kind: EntryKind
  start: number
  end: number
  ongoing: boolean
  /** A certificate without a duration: drawn as a marker at `start`. */
  point: boolean
  /** Starts in the future (an accepted offer). */
  pending: boolean
  lane: number
  tone: Tone
  /** Where the next entry in the same lane starts (`Infinity` when none); bounds a marker's label. */
  next: number
}

export type EventKind = 'start' | 'end' | 'point'

export type TimelineEvent = {
  at: number
  items: { kind: EventKind; bar: Bar }[]
}

export type TimelineModel = ReturnType<typeof layout>

export function monthIndex(iso: string): number {
  const [y, m] = iso.split('-').map(Number)
  return y * 12 + (m - 1)
}

export function todayIndex(): number {
  const now = new Date()
  const days = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate()
  return now.getFullYear() * 12 + now.getMonth() + (now.getDate() - 1) / days
}

export function monthLabel(index: number, style: 'short' | 'long' = 'long'): string {
  const i = Math.floor(index)
  const d = new Date(Math.floor(i / 12), i % 12, 1)
  return d.toLocaleDateString(undefined, style === 'long' ? { year: 'numeric', month: 'short' } : { month: 'short' })
}

export function formatDuration(months: number): string {
  const total = Math.max(1, Math.round(months))
  const y = Math.floor(total / 12)
  const m = total % 12
  const parts = []
  if (y) parts.push(`${y} yr${y === 1 ? '' : 's'}`)
  if (m) parts.push(`${m} mo${m === 1 ? '' : 's'}`)
  return parts.join(' ')
}

export function layout(entries: WorkHistoryEntry[], today: number) {
  const sorted = [...entries].sort(
    (a, b) => a.date_start.localeCompare(b.date_start) || (a.date_end ?? '9').localeCompare(b.date_end ?? '9'),
  )
  const bars: Bar[] = []
  let lanes = 0
  const counts = { job: 0, education: 0, certificate: 0 } satisfies Record<EntryKind, number>
  for (const kind of KIND_ORDER) {
    const laneEnds: number[] = []
    const laneBars: Bar[][] = []
    sorted
      .filter((entry) => entry.kind === kind)
      .forEach((entry, i) => {
        const start = monthIndex(entry.date_start)
        const point = isPoint(entry)
        const ongoing = entry.date_end === null && !point
        const pending = entry.pending
        const end = point
          ? start + 1
          : ongoing
            ? pending
              ? start + 1
              : Math.max(today, start + 0.5)
            : monthIndex(entry.date_end!) + 1
        let lane = laneEnds.findIndex((e) => e <= start)
        if (lane === -1) lane = laneEnds.length
        laneEnds[lane] = end
        const tone: Tone = kind === 'job' ? TONES[i % TONES.length] : KIND_TONES[kind]
        const bar: Bar = { entry, kind, start, end, ongoing, point, pending, lane: lanes + lane, tone, next: Infinity }
        ;(laneBars[lane] ??= []).push(bar)
        bars.push(bar)
        counts[kind] += 1
      })
    for (const row of laneBars) row.forEach((bar, i) => (bar.next = row[i + 1]?.start ?? Infinity))
    lanes += laneEnds.length
  }
  const byId = new Map(bars.map((b) => [b.entry.id, b]))

  const byAt = new Map<number, TimelineEvent>()
  const push = (at: number, kind: EventKind, bar: Bar) => {
    const ev = byAt.get(at) ?? { at, items: [] }
    ev.items.push({ kind, bar })
    byAt.set(at, ev)
  }
  for (const bar of bars) {
    if (bar.point) {
      push(bar.start, 'point', bar)
      continue
    }
    push(bar.start, 'start', bar)
    if (!bar.ongoing) push(bar.end, 'end', bar)
  }
  const events = [...byAt.values()].sort((a, b) => a.at - b.at)
  const rank: Record<EventKind, number> = { end: 0, start: 1, point: 2 }
  for (const ev of events) ev.items.sort((a, b) => rank[a.kind] - rank[b.kind])

  // Gaps: holes in the union of all positions, plus months employed (for the summary).
  // Education and certificates neither close a gap nor count as employment.
  const gaps: { start: number; end: number }[] = []
  let covered = 0
  let cursor = -Infinity
  let runStart = 0
  for (const bar of bars.filter((b) => b.kind === 'job' && !b.pending).sort((a, b) => a.start - b.start)) {
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

  return { bars, byId, events, gaps, covered, counts, rangeStart, rangeEnd, lanes: Math.max(1, lanes) }
}
