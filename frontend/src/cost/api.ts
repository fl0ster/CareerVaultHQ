const API = '/api/openrouter'

export type Granularity = 'hour' | 'day' | 'week' | 'month'

export type CostBucket = {
  bucket: string
  cost: number
  cumulative_cost: number
  calls: number
  total_tokens: number
}

export type CostBreakdown = {
  key: string
  cost: number
  calls: number
  total_tokens: number
}

export type CostFacets = {
  sources: string[]
  models: string[]
  kinds: string[]
  statuses: string[]
}

export type CostReport = {
  total_cost: number
  total_calls: number
  total_tokens: number
  prompt_tokens: number
  completion_tokens: number
  first_call_at: string | null
  last_call_at: string | null
  granularity: Granularity
  series: CostBucket[]
  by_source: CostBreakdown[]
  by_model: CostBreakdown[]
  by_kind: CostBreakdown[]
  facets: CostFacets
}

export type CostQuery = {
  source?: string
  kind?: string
  model?: string
  status?: string
  since?: string
  until?: string
  granularity?: Granularity
}

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T
  let message = `HTTP ${res.status}`
  try {
    const detail = (await res.json())?.detail
    if (typeof detail === 'string') message = detail
  } catch {
    /* non-JSON error body, keep the HTTP status message */
  }
  throw new Error(message)
}

export function getCostReport(query: CostQuery, signal?: AbortSignal): Promise<CostReport> {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value) params.set(key, value)
  }
  const qs = params.toString()
  return fetch(`${API}/cost${qs ? `?${qs}` : ''}`, { signal }).then((r) => parse<CostReport>(r))
}
