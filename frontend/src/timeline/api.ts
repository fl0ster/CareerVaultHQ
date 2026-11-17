const API = '/api/timeline'

/** One timeline entry. ``payload`` is a snapshot whose shape depends on ``type``. */
export type TimelineEvent = {
  id: number
  type: string
  occurred_at: string
  job_id: number | null
  scrape_run_id: number | null
  source_id: number | null
  payload: Record<string, unknown>
  /** Job events only: at or above the relevance threshold. */
  relevant: boolean | null
  /** Job events only: score on the [-1, 1] display scale (0 at the threshold). */
  relevance: number | null
  /** Job events, current state: the job's company, its tag, the evaluation to apply with
   * (latest profile) and an existing application. */
  company_id?: number | null
  company_tag?: string | null
  evaluation_id?: number | null
  application_id?: number | null
}

export type ScrapeRunPayload = {
  status: 'finished' | 'failed' | string
  source_key: string | null
  source_name: string | null
  scraped: number
  new: number
  duplicates: number
  failed_sources: string[]
  error: string | null
}

export type JobEvaluatedPayload = {
  title: string | null
  company_id: number | null
  company_name: string | null
  source_name: string | null
  link: string
  match_probability: number
}

export type TimelinePage = {
  events: TimelineEvent[]
  has_older: boolean
  has_newer: boolean
}

export type TimelineStatus = {
  latest_id: number
  last_read_id: number
  unread: number
  unread_relevant: number
}

export type EventsQuery = { after_id: number } | { before_id: number } | { around_id: number }

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T
  let message = `HTTP ${res.status}`
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') message = body.detail
  } catch {
    /* non-JSON error body, keep the HTTP status message */
  }
  throw new Error(message)
}

export const timelineApi = {
  events: (query: EventsQuery, limit = 50) => {
    const params = new URLSearchParams({ limit: String(limit) })
    for (const [key, value] of Object.entries(query)) params.set(key, String(value))
    return fetch(`${API}/events?${params}`).then((r) => parse<TimelinePage>(r))
  },
  status: () => fetch(`${API}/status`).then((r) => parse<TimelineStatus>(r)),
  /** ``keepalive`` lets the request finish while the page is being unloaded. */
  markRead: (eventId: number, keepalive = false) =>
    fetch(`${API}/read`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: eventId }),
      keepalive,
    }).then((r) => parse<TimelineStatus>(r)),
}
