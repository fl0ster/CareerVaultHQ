const API = '/api/jobs'

export type JobEvaluation = {
  id: number
  candidate_profile_id: number
  match_probability: number
  /** Match mapped onto [-1, 1] around the backend relevance threshold: 0 at the
   * threshold, positive above it. For display only. */
  relevance: number
  model: string | null
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

export const jobsApi = {
  list: ({ offset, limit, sort }: ListJobsParams) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit), sort })
    return fetch(`${API}?${params}`).then((r) => parse<JobPage>(r))
  },
  get: (id: number) => fetch(`${API}/${id}`).then((r) => parse<EvaluatedJobDetail>(r)),
  raw: (id: number) => fetch(`${API}/raw/${id}`).then((r) => parse<{ html: string | null }>(r)),
}
