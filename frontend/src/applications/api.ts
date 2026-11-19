import { refreshCompanyApplicationStats } from '../companies/applicationStats.ts'
import type { GeneratedCv } from '../cv/api.ts'

const API = '/api/applications'

/** Fired on `window` whenever an application is created, changed or deleted, so pages
 * that stay mounted in other tabs can refresh. */
export const APPLICATIONS_CHANGED = 'applications:changed'

export function notifyApplicationsChanged() {
  window.dispatchEvent(new Event(APPLICATIONS_CHANGED))
}

export type ApplicationStatus = {
  id: number
  key: string
  label: string
  position: number
  /** Default next state (one click on the badge); null when there is none. */
  next_key: string | null
}

export type ApplicationEvent = {
  id: number
  status: ApplicationStatus
  note: string
  /** A planned interview round that has not happened yet (only in `planned_events`). */
  planned: boolean
  /** Kind of interview round ("Culture match", "Technical", ...). */
  title: string
  duration_minutes: number | null
  /** When it happened; for a planned round the optional scheduled time (else null). */
  occurred_at: string | null
  created_at: string
}

export type Application = {
  id: number
  notes: string
  created_at: string
  updated_at: string
  status: ApplicationStatus | null
  /** State history, oldest first (held states only; `occurred_at` is always set). */
  events: ApplicationEvent[]
  /** Interview rounds planned but not held yet, in round order. */
  planned_events: ApplicationEvent[]
  /** Declared number of interview rounds (held + planned); null without a plan. */
  interview_rounds: number | null
  job: {
    id: number
    title: string | null
    company: string | null
    /** Set when the company was resolved; its notes are shared by all its applications. */
    company_id: number | null
    company_notes: string | null
    company_tag: string | null
    link: string
    source: string
  }
  evaluation: { id: number; candidate_profile_id: number; relevance: number } | null
  cv: GeneratedCv | null
}

export type ApplicationPage = {
  items: Application[]
  total: number
  offset: number
  limit: number
  has_more: boolean
}

export type CreateApplication = {
  job_evaluation_id: number
  status?: string | null
  status_note?: string
  notes?: string
}

export type EventInput = {
  status: string
  note?: string
  occurred_at?: string
  title?: string
  duration_minutes?: number | null
}

export type EventUpdate = {
  status?: string
  note?: string
  /** `null` clears the schedule of a planned round. */
  occurred_at?: string | null
  title?: string
  duration_minutes?: number | null
  /** `false` marks a planned round as held. */
  planned?: false
}

/** The API stores UTC timestamps without an offset; read those as UTC, not local time. */
export function serverDate(value: string): Date {
  return new Date(/(Z|[+-]\d\d:?\d\d)$/i.test(value) ? value : `${value}Z`)
}

/** `<input type="datetime-local">` value (local time, minutes) for a server timestamp. */
export function toLocalInput(value: string | Date): string {
  const d = typeof value === 'string' ? serverDate(value) : value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** ISO (UTC) string for a `datetime-local` value, or undefined when it is empty. */
export function fromLocalInput(value: string): string | undefined {
  return value ? new Date(value).toISOString() : undefined
}

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) return (res.status === 204 ? undefined : await res.json()) as T
  let message = `HTTP ${res.status}`
  try {
    const body = await res.json()
    const detail = body?.detail
    if (typeof detail === 'string') message = detail
    else if (Array.isArray(detail)) {
      message = detail
        .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg}`)
        .join('; ')
    }
  } catch {
    /* non-JSON error body, keep the HTTP status message */
  }
  throw new Error(message)
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

/** Passes a mutation's result through, refreshing what depends on the applications. */
function changed<T>(result: T): T {
  refreshCompanyApplicationStats()
  return result
}

export const applicationsApi = {
  statuses: (signal?: AbortSignal) =>
    fetch(`${API}/statuses`, { signal }).then((r) => parse<ApplicationStatus[]>(r)),
  list: (
    { offset = 0, limit = 50, status, q }: { offset?: number; limit?: number; status?: string; q?: string } = {},
    signal?: AbortSignal,
  ) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (status) params.set('status', status)
    if (q) params.set('q', q)
    return fetch(`${API}?${params}`, { signal }).then((r) => parse<ApplicationPage>(r))
  },
  get: (id: number, signal?: AbortSignal) => fetch(`${API}/${id}`, { signal }).then((r) => parse<Application>(r)),
  create: (payload: CreateApplication) => fetch(API, json('POST', payload)).then((r) => parse<Application>(r)).then(changed),
  updateNotes: (id: number, notes: string) =>
    fetch(`${API}/${id}`, json('PATCH', { notes })).then((r) => parse<Application>(r)),
  /** Sets the number of interview rounds; `null` (or 0) clears the plan. */
  setInterviewRounds: (id: number, rounds: number | null) =>
    fetch(`${API}/${id}`, json('PATCH', { interview_rounds: rounds }))
      .then((r) => parse<Application>(r))
      .then(changed),
  remove: (id: number) => fetch(`${API}/${id}`, { method: 'DELETE' }).then((r) => parse<void>(r)).then(changed),
  regenerateCv: (id: number) => fetch(`${API}/${id}/cv`, { method: 'POST' }).then((r) => parse<Application>(r)),
  addEvent: (id: number, event: EventInput) =>
    fetch(`${API}/${id}/events`, json('POST', event)).then((r) => parse<Application>(r)).then(changed),
  updateEvent: (id: number, eventId: number, event: EventUpdate) =>
    fetch(`${API}/${id}/events/${eventId}`, json('PATCH', event)).then((r) => parse<Application>(r)).then(changed),
  removeEvent: (id: number, eventId: number) =>
    fetch(`${API}/${id}/events/${eventId}`, { method: 'DELETE' }).then((r) => parse<Application>(r)).then(changed),
}

/** Recorded only when an application is created; it cannot be added, removed or switched to/from. */
export const INITIAL_ONLY_STATUS = 'SHORTLISTED'

/** Recorded at most once, and only straight after `INITIAL_ONLY_STATUS`. */
export const APPLIED_STATUS = 'APPLIED'

/**
 * States the user can pick for a new event (`current` = key of the current state) or, with
 * `current` omitted, for an edited one.
 */
export const pickableStatuses = (statuses: ApplicationStatus[], current?: string | null) =>
  statuses.filter(
    (s) =>
      s.key !== INITIAL_ONLY_STATUS &&
      (current === undefined || s.key !== APPLIED_STATUS || current === INITIAL_ONLY_STATUS),
  )

/** Terminal states: while one is current no new state can be added (removing it reopens). */
export const FINAL_STATUSES: readonly string[] = ['OFFER', 'REJECTED']

export const isFinalStatus = (status: ApplicationStatus | null | undefined) =>
  status != null && FINAL_STATUSES.includes(status.key)

/** State of interview rounds; planned rounds always have it. */
export const INTERVIEW_STATUS = 'INTERVIEW'

export const MAX_INTERVIEW_ROUNDS = 20

/** One interview round, held or planned, in round order. */
export type InterviewRound = { event: ApplicationEvent; held: boolean }

/** Held interview rounds (chronological) followed by the planned ones. */
export const interviewRounds = (app: Application): InterviewRound[] => [
  ...app.events.filter((e) => e.status.key === INTERVIEW_STATUS).map((event) => ({ event, held: true })),
  ...app.planned_events.map((event) => ({ event, held: false })),
]

/** "1 h 30 min", "45 min"; empty without a duration. */
export function formatDuration(minutes: number | null | undefined): string {
  if (!minutes) return ''
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return [h ? `${h} h` : '', m ? `${m} min` : ''].filter(Boolean).join(' ')
}

/** Label of a round: its title, or "Round n". */
export const roundLabel = (event: ApplicationEvent, index: number) => event.title || `Round ${index + 1}`

/** "round 2 (Technical)" for the next planned round, if there is one. */
export function nextRoundLabel(app: Application): string | undefined {
  const next = app.planned_events[0]
  if (!next) return undefined
  const index = app.events.filter((e) => e.status.key === INTERVIEW_STATUS).length
  return `round ${index + 1}${next.title ? ` (${next.title})` : ''}`
}
