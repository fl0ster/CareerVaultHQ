import type { CandidateDetailsInput } from '../candidate-profile/api.ts'
import type { WorkHistoryExport } from './api.ts'

const API = '/api/cv-import'

/** How often a running CV import is polled. */
const POLL_MS = 2000

/** `GET /api/cv-import/jobs/{id}` `result`: the parsed CV, nothing saved yet. */
export type CvImportResult = {
  /** Ready for `PUT /api/candidate-details` (photo and consent text are blank). */
  candidate_details: CandidateDetailsInput
  /** Positions, education and certificates, ready for `POST /api/work-history/json`; newest first. */
  work_history: WorkHistoryExport[]
  skills: string[]
  summary: string | null
  /** What was dropped or assumed while reading the CV. */
  warnings: string[]
  source: { pages: number; pages_read: number; characters: number; links: string[] }
}

type JobStatus = {
  job_id: string
  status: string
  error: string | null
  result: CvImportResult | null
}

const TERMINAL = new Set(['finished', 'failed', 'stopped', 'canceled'])

export const isPdf = (file: File) => file.type === 'application/pdf' || /\.pdf$/i.test(file.name)

async function detail(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch {
    /* non-JSON error body */
  }
  return `HTTP ${res.status}`
}

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

/**
 * Uploads the CV PDF, waits for the worker to parse it and returns the parsed data.
 * Throws with the server's reason when the upload is rejected or the parsing fails;
 * `cancelled()` stops the polling (e.g. when the page is left).
 */
export async function parseCv(file: File, cancelled: () => boolean = () => false): Promise<CvImportResult> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(API, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await detail(res))
  const { job_id } = (await res.json()) as { job_id: string }

  for (;;) {
    await sleep(POLL_MS)
    if (cancelled()) throw new Error('cancelled')
    const poll = await fetch(`${API}/jobs/${encodeURIComponent(job_id)}`)
    if (!poll.ok) throw new Error(await detail(poll))
    const job = (await poll.json()) as JobStatus
    if (!TERMINAL.has(job.status)) continue
    if (job.status === 'finished' && job.result) return job.result
    throw new Error(job.error ?? `the import ${job.status === 'finished' ? 'returned nothing' : job.status}`)
  }
}

type TextKey = 'first_name' | 'last_name' | 'email' | 'phone' | 'website' | 'github' | 'linkedin' | 'location'
type ListKey = 'languages'

const TEXT_FIELDS: readonly TextKey[] = [
  'first_name',
  'last_name',
  'email',
  'phone',
  'website',
  'github',
  'linkedin',
  'location',
]
const LIST_FIELDS: readonly ListKey[] = ['languages']

const LABELS: Record<TextKey | ListKey, string> = {
  first_name: 'first name',
  last_name: 'last name',
  email: 'e-mail',
  phone: 'phone',
  website: 'website',
  github: 'GitHub',
  linkedin: 'LinkedIn',
  location: 'location',
  languages: 'languages',
}

/**
 * The saved details with only their blank fields (and empty lists) taken from the CV, so
 * nothing the user already entered is overwritten. `filled` names the fields that changed.
 */
export function mergeDetails(
  saved: CandidateDetailsInput | null,
  parsed: CandidateDetailsInput,
): { details: CandidateDetailsInput; filled: string[] } {
  // Extra keys of a saved row (id, timestamps) are ignored by the PUT endpoint.
  const details: CandidateDetailsInput = saved ? { ...saved } : { ...parsed, photo: '', consent_text: '' }
  const filled: string[] = []
  for (const key of TEXT_FIELDS) {
    if (saved && saved[key].trim() !== '') continue
    details[key] = parsed[key]
    if (parsed[key].trim() !== '') filled.push(LABELS[key])
  }
  for (const key of LIST_FIELDS) {
    if (saved && saved[key].length > 0) continue
    Object.assign(details, { [key]: parsed[key] })
    if (parsed[key].length > 0) filled.push(LABELS[key])
  }
  return { details, filled }
}
