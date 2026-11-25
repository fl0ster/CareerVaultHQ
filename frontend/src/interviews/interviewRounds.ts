import {
  type Application,
  type ApplicationEvent,
  type PlannedRound,
  heldRounds,
  isFinalStatus,
} from '../applications/api.ts'

export type Round = {
  event: ApplicationEvent | PlannedRound
  /** Position among all rounds (0-based). */
  index: number
  held: boolean
}

/** Every interview round, held first then planned, and which one is current: the next planned
 * round, or the last held one once nothing is planned. */
export function interviewRounds(application: Application): { rounds: Round[]; current: Round | null } {
  const held = heldRounds(application)
  const rounds: Round[] = [
    ...held.map((event, index) => ({ event, index, held: true })),
    ...application.planned_events.map((event, i) => ({ event, index: held.length + i, held: false })),
  ]
  const current = isFinalStatus(application.status)
    ? null
    : (rounds.find((r) => !r.held) ?? rounds[rounds.length - 1] ?? null)
  return { rounds, current }
}

/** "Thu, 28 Nov, 14:00" in the user's locale. */
export function formatWhen(value: Date): string {
  return value.toLocaleString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** "28 Nov" in the user's locale. */
export function formatShortDay(value: Date): string {
  return value.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

/** "today", "tomorrow", "in 3 days", "2 days ago". */
export function relativeDay(value: Date, now = new Date()): string {
  const day = (d: Date) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())
  const diff = Math.round((day(value) - day(now)) / 86_400_000)
  if (diff === 0) return 'today'
  if (diff === 1) return 'tomorrow'
  if (diff === -1) return 'yesterday'
  return diff > 0 ? `in ${diff} days` : `${-diff} days ago`
}
