import type { WorkHistoryEntry } from './api.ts'

/*
 * Pure layout model shared by the timeline and the list.
 *
 * Time is measured in "month indices" (year * 12 + month0), possibly fractional for today.
 * A position covers [start month, end month + 1), so "Jan 2020 – Mar 2020" spans 3 months.
 * Overlapping positions are packed into separate lanes.
 */

export const TONES = ['accent', 'info', 'success', 'lavender', 'peach', 'warn'] as const
export type Tone = (typeof TONES)[number]

export type Bar = {
  entry: WorkHistoryEntry
  start: number
  end: number
  ongoing: boolean
  lane: number
  tone: Tone
}

export type TimelineEvent = {
  at: number
  items: { kind: 'start' | 'end'; bar: Bar }[]
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
  const byId = new Map(bars.map((b) => [b.entry.id, b]))

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

  return { bars, byId, events, gaps, covered, rangeStart, rangeEnd, lanes: Math.max(1, laneEnds.length) }
}
