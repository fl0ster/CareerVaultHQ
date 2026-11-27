const API = '/api/cv'

export type CvStatus = 'queued' | 'running' | 'finished' | 'failed'

export type CvJob = {
  id: number
  title: string | null
  company: string | null
  link: string
  source: string
}

export type GeneratedCv = {
  id: number
  status: CvStatus
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  headline_role: string | null
  core_technologies: string[]
  summary: string | null
  warnings: string[]
  cost: number | null
  openrouter_calls: number | null
  job: CvJob
  pdf_url: string | null
  tex_url: string | null
  /** The user's edits this CV was generated with (`null`: none). */
  overrides: CvOverrides | null
}

/** Where the user put a role: listed in full, condensed, or left out. */
export type RolePlacement = 'main' | 'early' | 'drop'

/** The user's edits to how one application's CV is generated; `null` fields and missing
 * roles are left to the pipeline. */
export type CvOverrides = {
  headline_role: string | null
  summary: string | null
  /** `work_history.id` -> placement. */
  roles: Record<string, RolePlacement>
  /** `work_history.id` -> the role's description in the CV, used as written. */
  contexts: Record<string, string>
  /** `work_history.id` -> the technologies a listed role shows, in order. */
  techs: Record<string, string[]>
}

export const NO_OVERRIDES: CvOverrides = { headline_role: null, summary: null, roles: {}, contexts: {}, techs: {} }

/** Number of separate edits (headline, summary, each placed role, each description). */
export function overrideCount(o: CvOverrides | null | undefined): number {
  if (!o) return 0
  return (
    (o.headline_role ? 1 : 0) +
    (o.summary ? 1 : 0) +
    Object.keys(o.roles ?? {}).length +
    Object.keys(o.contexts ?? {}).length +
    Object.keys(o.techs ?? {}).length
  )
}

/** Whether two sets of edits would produce the same CV. */
export function sameOverrides(a: CvOverrides | null | undefined, b: CvOverrides | null | undefined): boolean {
  const sorted = (m: Record<string, unknown> | undefined) =>
    Object.entries(m ?? {}).sort(([x], [y]) => Number(x) - Number(y))
  const key = (o: CvOverrides | null | undefined) =>
    JSON.stringify([
      o?.headline_role || null,
      o?.summary || null,
      sorted(o?.roles),
      sorted(o?.contexts),
      sorted(o?.techs),
    ])
  return key(a) === key(b)
}

export type GeneratedCvPage = {
  items: GeneratedCv[]
  total: number
  offset: number
  limit: number
  has_more: boolean
}

/** One ``work_history`` row as scored in step 1 of the pipeline. Dates and months are
 * only present on CVs generated after the pipeline started recording them. */
export type PipelineRole = {
  id: number | null
  employer: string
  role: string
  relevance: number
  date_start?: string
  date_end?: string
  months?: number
  /** The description from the work history (newer CVs only). */
  context?: string | null
  /** The technologies from the work history, comma separated (newer CVs only). */
  tech?: string
}

/** A role as it ends up in the CV: ``main`` entries are tailored, ``early`` ones condensed.
 * ``original_*`` hold the text the LLM started from (newer CVs only). */
export type PipelineEntry = {
  id?: number | null
  date_start: string
  date_end: string
  employer: string
  role: string
  location: string | null
  tech: string
  context: string | null
  relevance: number
  /** Set on a role that continues the previous one at its employer (a promotion or a move). */
  transition?: 'promotion' | 'role_change' | null
  /** Roles sharing a tenure are listed as one employer block on the CV. */
  tenure?: number | null
  months?: number
  original_context?: string | null
  original_tech?: string
}

export type PipelineThresholds = {
  max_entries: number
  min_entries: number
  high_relevance: number
  irrelevant_relevance: number
  min_months: number
}

/** ``GET /api/cv/{id}/pipeline``: what the generation did (``pipeline.json``). */
export type CvPipeline = {
  job_description_chars?: number
  cost?: number
  openrouter_calls?: number
  thresholds?: PipelineThresholds
  relevance?: PipelineRole[]
  main?: PipelineEntry[]
  early?: PipelineEntry[]
  categories?: [string, string[]][]
  timeline_log?: string[]
  warnings?: string[]
  latex_log_tail?: string
}

export type ListCvParams = {
  offset?: number
  limit?: number
  job_id?: number
  /** Job title or company name contains it (case-insensitive). */
  q?: string
}

/** Still being generated: the UI keeps polling while any CV is in this state. */
export function isInProgress(cv: Pick<GeneratedCv, 'status'>): boolean {
  return cv.status === 'queued' || cv.status === 'running'
}

export function describeError(e: unknown): string {
  return String(e instanceof Error ? e.message : e)
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

export const cvApi = {
  generate: (jobId: number) =>
    fetch(`${API}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: jobId }),
    }).then((r) => parse<GeneratedCv>(r)),
  list: ({ offset = 0, limit = 50, job_id, q }: ListCvParams = {}, signal?: AbortSignal) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (job_id !== undefined) params.set('job_id', String(job_id))
    if (q) params.set('q', q)
    return fetch(`${API}?${params}`, { signal }).then((r) => parse<GeneratedCvPage>(r))
  },
  get: (id: number, signal?: AbortSignal) =>
    fetch(`${API}/${id}`, { signal }).then((r) => parse<GeneratedCv>(r)),
  pipeline: (id: number, signal?: AbortSignal) =>
    fetch(`${API}/${id}/pipeline`, { signal }).then((r) => parse<CvPipeline>(r)),
  pdfUrl: (id: number) => `${API}/${id}/pdf`,
  texUrl: (id: number) => `${API}/${id}/tex`,
}
