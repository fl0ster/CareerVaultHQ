import { refreshCompanyApplicationStats } from '../companies/applicationStats.ts'
import type { CvOverrides, GeneratedCv } from '../cv/api.ts'

const API = '/api/applications'

/** Fired on `window` whenever an application is created, changed or deleted, so the open
 * page and the menu badges can refresh. */
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
  /** Kind of interview round ("Culture match", "Technical", ...). */
  title: string
  duration_minutes: number | null
  occurred_at: string
  /** `gmail` when the Gmail rejection monitor recorded the state automatically. */
  source: EventSource
  /** The INTERVIEW state that entered the interview stage; not a round. */
  stage_entry: boolean
  created_at: string
}

export type EventSource = 'manual' | 'gmail'

/** The state was recorded by an automation rather than by hand. */
export function isAutoEvent(event: { source?: EventSource } | null | undefined): boolean {
  return event?.source === 'gmail'
}

/** The latest held state of the application (its current state), if any. */
export function currentEvent(application: Application): ApplicationEvent | undefined {
  return application.events[application.events.length - 1]
}

/** An interview round planned but not held yet; `occurred_at` is its optional schedule. */
export type PlannedRound = Omit<ApplicationEvent, 'occurred_at'> & { occurred_at: string | null }

export type Application = {
  id: number
  notes: string
  created_at: string
  updated_at: string
  status: ApplicationStatus | null
  /** State history, oldest first (planned rounds left out). */
  events: ApplicationEvent[]
  /** Interview rounds planned but not held yet, in round order. */
  planned_events: PlannedRound[]
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
  /** The job's newest score; `outdated` when made against an earlier work history. */
  evaluation: {
    id: number
    candidate_profile_id: number
    relevance: number
    outdated: boolean
    /** Stored explanation of the score, once generated (`jobsApi.explain`). */
    explanation: string | null
  } | null
  cv: GeneratedCv | null
  /** Agreed start date of the offered position (`YYYY-MM-DD`), if known. */
  start_date: string | null
  /** The My Career entry created by accepting the offer. */
  work_history_id: number | null
  /** Salary found by parsing the job, if any. */
  parsed_salary: Salary | null
  /** Salary entered for this application, replacing `parsed_salary`. */
  salary_override: Salary | null
  /** Work mode found by parsing the job, if any. */
  parsed_work_mode: WorkMode | null
  /** Work mode entered for this application, replacing `parsed_work_mode`. */
  work_mode_override: WorkMode | null
  /** The user's edits to how this application's CV is generated (used by the next one). */
  cv_overrides: CvOverrides | null
}

export type SalaryPeriod = 'hour' | 'day' | 'week' | 'month' | 'year'
export const SALARY_PERIODS: SalaryPeriod[] = ['hour', 'day', 'week', 'month', 'year']

export type Salary = {
  min: number | null
  max: number | null
  currency: string | null
  period: SalaryPeriod | null
  /** `true` gross, `false` net, `null` unknown. */
  gross: boolean | null
  /** The text a parsed salary was found in. */
  raw?: string | null
}

export type WorkMode = 'remote' | 'hybrid' | 'office'
export const WORK_MODES: { key: WorkMode; label: string }[] = [
  { key: 'remote', label: 'Remote' },
  { key: 'hybrid', label: 'Hybrid' },
  { key: 'office', label: 'Office' },
]

/** "15 000 – 20 000 PLN / month, gross"; empty without any amount. */
export function formatSalary(salary: Salary | null): string {
  if (!salary || (salary.min == null && salary.max == null)) return ''
  const n = (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 2 })
  const amount =
    salary.min != null && salary.max != null && salary.min !== salary.max
      ? `${n(salary.min)} – ${n(salary.max)}`
      : salary.min != null && salary.max == null
        ? `from ${n(salary.min)}`
        : salary.min == null && salary.max != null
          ? `up to ${n(salary.max)}`
          : n(salary.min!)
  const head = [amount, salary.currency].filter(Boolean).join(' ')
  const tail = [salary.period ? `/ ${salary.period}` : '', salary.gross == null ? '' : salary.gross ? 'gross' : 'net']
  return [head + (tail[0] ? ` ${tail[0]}` : ''), tail[1]].filter(Boolean).join(', ')
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

/** A `YYYY-MM-DD` date (no time zone) for display, in the user's locale. */
export function formatDay(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString()
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
    {
      offset = 0,
      limit = 50,
      status,
      excludeStatus,
      q,
    }: {
      offset?: number
      limit?: number
      status?: string
      excludeStatus?: string
      q?: string
    } = {},
    signal?: AbortSignal,
  ) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (status) params.set('status', status)
    if (excludeStatus) params.set('exclude_status', excludeStatus)
    if (q) params.set('q', q)
    return fetch(`${API}?${params}`, { signal }).then((r) => parse<ApplicationPage>(r))
  },
  get: (id: number, signal?: AbortSignal) => fetch(`${API}/${id}`, { signal }).then((r) => parse<Application>(r)),
  create: (payload: CreateApplication) => fetch(API, json('POST', payload)).then((r) => parse<Application>(r)).then(changed),
  updateNotes: (id: number, notes: string) =>
    fetch(`${API}/${id}`, json('PATCH', { notes })).then((r) => parse<Application>(r)),
  /** Sets (or, with `null`, clears) the agreed start date of the offered position. */
  /** Overrides the parsed salary and/or work mode (`null` falls back to the parsed one). */
  setOverrides: (id: number, changes: { salary_override?: Salary | null; work_mode_override?: WorkMode | null }) =>
    fetch(`${API}/${id}`, json('PATCH', changes)).then((r) => parse<Application>(r)),
  /** Replaces (or, with `null`, removes) the edits the next CV is generated with. */
  setCvOverrides: (id: number, overrides: CvOverrides | null) =>
    fetch(`${API}/${id}`, json('PATCH', { cv_overrides: overrides })).then((r) => parse<Application>(r)),
  setStartDate: (id: number, startDate: string | null) =>
    fetch(`${API}/${id}`, json('PATCH', { start_date: startDate })).then((r) => parse<Application>(r)),
  /** Accepts the offer: the application becomes `ACCEPTED` and the position is added to My
   * Career, starting on `startDate` (the stored `start_date` when omitted). */
  accept: (id: number, startDate?: string) =>
    fetch(`${API}/${id}/accept`, json('POST', startDate ? { start_date: startDate } : {}))
      .then((r) => parse<Application>(r))
      .then(changed),
  /** Declines the offer: the application becomes `DECLINED` (final), with `note` as the
   * reason. */
  decline: (id: number, note = '') =>
    fetch(`${API}/${id}/decline`, json('POST', { note }))
      .then((r) => parse<Application>(r))
      .then(changed),
  /** Sets the number of interview rounds (held + planned); 0 drops the planned ones. */
  setInterviewRounds: (id: number, rounds: number) =>
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

/** State of interview rounds; every one is a round, planned rounds always have it. */
export const INTERVIEW_STATUS = 'INTERVIEW'
export const OFFER_STATUS = 'OFFER'

/** The company turned the application down. */
export const REJECTED_STATUS = 'REJECTED'

/** The application was closed (final, like a rejection). */
export const CLOSED_STATUS = 'CLOSED'

/** The offer was accepted; only set by `applicationsApi.accept`, never picked as a state. */
export const ACCEPTED_STATUS = 'ACCEPTED'

/** The offer was declined; only set by `applicationsApi.decline`, never picked as a state. */
export const DECLINED_STATUS = 'DECLINED'

/**
 * States the user can pick for a new event (`current` = key of the current state) or, with
 * `current` omitted, for an edited one.
 */
export const pickableStatuses = (statuses: ApplicationStatus[], current?: string | null) =>
  statuses.filter(
    (s) =>
      s.key !== INITIAL_ONLY_STATUS &&
      s.key !== ACCEPTED_STATUS &&
      s.key !== DECLINED_STATUS &&
      (current === undefined ||
        s.key !== APPLIED_STATUS ||
        current === INITIAL_ONLY_STATUS ||
        // Back to Applied: every held round becomes planned again.
        current === INTERVIEW_STATUS),
  )

/** Terminal states: while one is current no new state can be added (removing it reopens). */
export const FINAL_STATUSES: readonly string[] = [
  OFFER_STATUS,
  ACCEPTED_STATUS,
  DECLINED_STATUS,
  REJECTED_STATUS,
  CLOSED_STATUS,
]

export const isFinalStatus = (status: ApplicationStatus | null | undefined) =>
  status != null && FINAL_STATUSES.includes(status.key)


export const MAX_INTERVIEW_ROUNDS = 20

/** The states shown in a status history: the stage entry (entering INTERVIEW before any round
 * is held) is left out, since no interview happened then. */
export const historyEvents = (app: Application) => app.events.filter((e) => !e.stage_entry)

/** Interview rounds already held, oldest first (the stage entry is not a round). */
export const heldRounds = (app: Application) =>
  app.events.filter((e) => e.status.key === INTERVIEW_STATUS && !e.stage_entry)

/** "1 h 30 min", "45 min"; empty without a duration. */
export function formatDuration(minutes: number | null): string {
  if (!minutes) return ''
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return [h ? `${h} h` : '', m ? `${m} min` : ''].filter(Boolean).join(' ')
}

/** Name of the round at `index` (0-based): its title, or "Round n". */
export const roundLabel = (round: { title: string }, index: number) => round.title || `Round ${index + 1}`

/** "round 2 (Technical)" for the next planned round, if there is one. Only once the application
 * is in the interview stage: recording INTERVIEW before that just enters the stage. */
export function nextRoundLabel(app: Application): string | undefined {
  const next = app.planned_events[0]
  if (!next || app.status?.key !== INTERVIEW_STATUS) return undefined
  return `round ${heldRounds(app).length + 1}${next.title ? ` (${next.title})` : ''}`
}
