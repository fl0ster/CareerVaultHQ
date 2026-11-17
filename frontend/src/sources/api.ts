const API = '/api/sources'

export type SourceHealth = 'unknown' | 'healthy' | 'degraded' | 'failing' | 'broken'

export type SourceRelevance = {
  job_count: number
  evaluated_count: number
  /** Mean match probability (0-1) of the source's jobs against the latest profile. */
  avg_match: number | null
  /** Share (0-1) of evaluated jobs scored as a good match. */
  good_match_share: number | null
}

export type Source = {
  /** Plugin module name; the stable identifier used by the scrape API. */
  key: string
  name: string
  url: string | null
  enabled: boolean
  /** Import/contract problem of the module; null when it is usable. */
  module_error: string | null
  health: SourceHealth
  last_run_at: string | null
  last_success_at: string | null
  last_error: string | null
  last_scraped_count: number | null
  last_new_count: number | null
  consecutive_failures: number
  /** Per-source scrape interval; null means `default_scrape_interval_seconds` applies. */
  scrape_interval_seconds: number | null
  default_scrape_interval_seconds: number
  /** When the scheduler scrapes the source next; null while disabled or not planned yet. */
  next_scrape_at: string | null
  updated_at: string
  relevance: SourceRelevance
}

export type SourceUpdate = {
  enabled?: boolean
  /** null resets the source to the default interval. */
  scrape_interval_seconds?: number | null
}

/** Shortest interval the API accepts (seconds). */
export const MIN_SCRAPE_INTERVAL_SECONDS = 15 * 60

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T
  let message = `HTTP ${res.status}`
  try {
    const detail = (await res.json())?.detail
    if (typeof detail === 'string') message = detail
  } catch {
    // keep the status message
  }
  throw new Error(message)
}

export const sourcesApi = {
  list: (signal?: AbortSignal) => fetch(API, { signal }).then((r) => parse<Source[]>(r)),
  update: (key: string, patch: SourceUpdate) =>
    fetch(`${API}/${encodeURIComponent(key)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }).then((r) => parse<Source>(r)),
}
