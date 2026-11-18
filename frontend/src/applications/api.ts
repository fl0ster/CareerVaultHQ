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
}

export type ApplicationEvent = {
  id: number
  status: ApplicationStatus
  note: string
  occurred_at: string
  created_at: string
}

export type Application = {
  id: number
  notes: string
  created_at: string
  updated_at: string
  status: ApplicationStatus | null
  events: ApplicationEvent[]
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

export const applicationsApi = {
  statuses: (signal?: AbortSignal) =>
    fetch(`${API}/statuses`, { signal }).then((r) => parse<ApplicationStatus[]>(r)),
  list: ({ offset = 0, limit = 50, status }: { offset?: number; limit?: number; status?: string } = {}, signal?: AbortSignal) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (status) params.set('status', status)
    return fetch(`${API}?${params}`, { signal }).then((r) => parse<ApplicationPage>(r))
  },
  get: (id: number, signal?: AbortSignal) => fetch(`${API}/${id}`, { signal }).then((r) => parse<Application>(r)),
  create: (payload: CreateApplication) => fetch(API, json('POST', payload)).then((r) => parse<Application>(r)),
  updateNotes: (id: number, notes: string) =>
    fetch(`${API}/${id}`, json('PATCH', { notes })).then((r) => parse<Application>(r)),
  remove: (id: number) => fetch(`${API}/${id}`, { method: 'DELETE' }).then((r) => parse<void>(r)),
  regenerateCv: (id: number) => fetch(`${API}/${id}/cv`, { method: 'POST' }).then((r) => parse<Application>(r)),
  addEvent: (id: number, event: EventInput) =>
    fetch(`${API}/${id}/events`, json('POST', event)).then((r) => parse<Application>(r)),
  updateEvent: (id: number, eventId: number, event: Partial<EventInput>) =>
    fetch(`${API}/${id}/events/${eventId}`, json('PATCH', event)).then((r) => parse<Application>(r)),
  removeEvent: (id: number, eventId: number) =>
    fetch(`${API}/${id}/events/${eventId}`, { method: 'DELETE' }).then((r) => parse<Application>(r)),
}
