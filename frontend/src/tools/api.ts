const LATEX_API = '/api/latex'
const SCRAPE_API = '/api/scrape'

/** Fields shared by every background job the API exposes. */
export type BackgroundJob = {
  job_id: string
  status: string
  source?: string | null
  enqueued_at?: string | null
  started_at?: string | null
  ended_at?: string | null
  error?: string | null
}

export type LatexJobInfo = BackgroundJob & {
  pdf_url?: string | null
}

export type ScrapedJob = { link: string; source: string }

export type ScrapeResult = {
  sources: { source: string; ok: boolean; error: string | null; jobs: ScrapedJob[] }[]
  failed: string[]
  jobs: ScrapedJob[]
  count: number
}

export type ScrapeJobInfo = BackgroundJob & {
  count?: number | null
  result?: ScrapeResult | null
}

const TERMINAL = new Set(['finished', 'failed', 'stopped', 'canceled'])

export function isTerminal(status: string): boolean {
  return TERMINAL.has(status)
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

export const latexApi = {
  compile: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return fetch(`${LATEX_API}/compile`, { method: 'POST', body }).then((r) => parse<LatexJobInfo>(r))
  },
  getJob: (jobId: string) => fetch(`${LATEX_API}/jobs/${jobId}`).then((r) => parse<LatexJobInfo>(r)),
  eventsUrl: (jobId: string) => `${LATEX_API}/jobs/${jobId}/events`,
  pdfUrl: (jobId: string) => `${LATEX_API}/jobs/${jobId}/pdf`,
}

export const scrapeApi = {
  start: (source: string | null) =>
    fetch(SCRAPE_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source }),
    }).then((r) => parse<ScrapeJobInfo>(r)),
  getJob: (jobId: string) => fetch(`${SCRAPE_API}/jobs/${jobId}`).then((r) => parse<ScrapeJobInfo>(r)),
}
