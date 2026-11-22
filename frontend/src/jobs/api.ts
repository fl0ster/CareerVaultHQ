const API = '/api/jobs'

export type JobEvaluation = {
  id: number
  candidate_profile_id: number
  match_probability: number
  /** Match mapped onto [-1, 1] around the backend relevance threshold: 0 at the
   * threshold, positive above it. For display only. */
  relevance: number
  model: string | null
  /** Scored against a profile built from an earlier work history; `jobsApi.rescore` scores
   * it against the latest one. */
  outdated: boolean
  created_at: string
}

export type EvaluatedJob = {
  id: number
  link: string
  source: string
  scrape_run_id: number | null
  has_html: boolean
  title: string | null
  company: string | null
  company_id: number | null
  company_tag: string | null
  parsed_at: string
  evaluation: JobEvaluation
  /** Set when an application was already created for this job. */
  application_id: number | null
  /** The user's call on the Jobs tab; `null` while undecided. */
  decision: JobDecision | null
}

export type JobDecision = 'accepted' | 'rejected'

/** Undecided relevant jobs, best match first. */
export type JobInbox = {
  items: EvaluatedJob[]
  count: number
  candidate_profile_id: number | null
}

/** Every other evaluated job, newest job first (keyset-paginated by job id). */
export type JobFeedPage = {
  items: EvaluatedJob[]
  has_more: boolean
  candidate_profile_id: number | null
}

export type FeedParams = {
  /** Job id: return older rows. */
  before?: number
  /** Job id: return newer rows (polling). */
  after?: number
  limit?: number
  /** Search term: every evaluated job (inbox included) whose title or company contains it. */
  q?: string
}

export type EvaluatedJobDetail = Omit<EvaluatedJob, 'evaluation'> & {
  description: string | null
  evaluation: JobEvaluation | null
}

export type JobPage = {
  items: EvaluatedJob[]
  total: number
  offset: number
  limit: number
  has_more: boolean
  candidate_profile_id: number | null
}

export type JobSortOrder = 'newest' | 'match'

export type ListJobsParams = {
  offset: number
  limit: number
  sort: JobSortOrder
}

/** Highlighted on the jobs list (strictly above the relevance threshold). */
export function isHighlighted(evaluation: Pick<JobEvaluation, 'relevance'>): boolean {
  return evaluation.relevance > 0
}

/** At or above the relevance threshold: an application can be created for it. */
export function isRelevant(evaluation: Pick<JobEvaluation, 'relevance'>): boolean {
  return evaluation.relevance >= 0
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

export type ManualJobInput = {
  title: string
  company: string
  link: string
  description: string
}

/** Parse status of a manually added job. */
export type ManualJobStatus = {
  job_id: number
  status: 'NOT_STARTED' | 'COMPLETED' | 'FAILED'
  error: string | null
}

export const jobsApi = {
  addManual: (input: ManualJobInput) =>
    fetch(`${API}/manual`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }).then((r) => parse<ManualJobStatus>(r)),
  manualStatus: (jobId: number) => fetch(`${API}/manual/${jobId}`).then((r) => parse<ManualJobStatus>(r)),
  list: ({ offset, limit, sort }: ListJobsParams) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit), sort })
    return fetch(`${API}?${params}`).then((r) => parse<JobPage>(r))
  },
  inbox: (signal?: AbortSignal) => fetch(`${API}/inbox`, { signal }).then((r) => parse<JobInbox>(r)),
  feed: ({ before, after, limit, q }: FeedParams, signal?: AbortSignal) => {
    const params = new URLSearchParams()
    if (before !== undefined) params.set('before', String(before))
    if (after !== undefined) params.set('after', String(after))
    if (limit !== undefined) params.set('limit', String(limit))
    if (q) params.set('q', q)
    return fetch(`${API}/feed?${params}`, { signal }).then((r) => parse<JobFeedPage>(r))
  },
  decide: (id: number, decision: JobDecision) =>
    fetch(`${API}/${id}/decision`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    }).then((r) => parse<EvaluatedJobDetail>(r)),
  get: (id: number, signal?: AbortSignal) => fetch(`${API}/${id}`, { signal }).then((r) => parse<EvaluatedJobDetail>(r)),
  /** Enqueue scoring the job against the latest profile; poll `get` until it is not outdated.
   * A 409 (already scored against the latest profile) resolves too: there is nothing to wait for. */
  rescore: (id: number) =>
    fetch(`${API}/${id}/rescore`, { method: 'POST' }).then((r) => (r.status === 409 ? undefined : parse<void>(r))),
  raw: (id: number) => fetch(`${API}/raw/${id}`).then((r) => parse<{ html: string | null }>(r)),
}
