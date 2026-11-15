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
}

export type GeneratedCvPage = {
  items: GeneratedCv[]
  total: number
  offset: number
  limit: number
  has_more: boolean
}

export type ListCvParams = {
  offset?: number
  limit?: number
  job_id?: number
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
  list: ({ offset = 0, limit = 50, job_id }: ListCvParams = {}, signal?: AbortSignal) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (job_id !== undefined) params.set('job_id', String(job_id))
    return fetch(`${API}?${params}`, { signal }).then((r) => parse<GeneratedCvPage>(r))
  },
  get: (id: number, signal?: AbortSignal) =>
    fetch(`${API}/${id}`, { signal }).then((r) => parse<GeneratedCv>(r)),
  remove: (id: number) => fetch(`${API}/${id}`, { method: 'DELETE' }).then((r) => parse<void>(r)),
  pdfUrl: (id: number) => `${API}/${id}/pdf`,
  texUrl: (id: number) => `${API}/${id}/tex`,
}
