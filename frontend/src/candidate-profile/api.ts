const API = '/api/candidate-profile'

export type CandidateProfile = {
  id: number
  content: string
  work_history_id: string | null
  created_at: string
  updated_at: string
}

export type CandidateProfileInput = Pick<CandidateProfile, 'content' | 'work_history_id'>

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

export const candidateProfileApi = {
  latest: () => fetch(`${API}/latest`).then((r) => parse<CandidateProfile | null>(r)),
  /** Create a new profile with custom text */
  create: (input: CandidateProfileInput) =>
      fetch(`${API}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input)
      }).then((r) => parse<CandidateProfile>(r)),
  /** Generate a new profile from the work history via the AI service. */
  generate: () => fetch(`${API}/generate`, { method: 'POST' }).then((r) => parse<CandidateProfile>(r)),
  update: (id: number, input: CandidateProfileInput) =>
    fetch(`${API}/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }).then((r) => parse<CandidateProfile>(r)),
}

// --- Candidate details (printed on generated CVs) --------------------------------------

const DETAILS_API = '/api/candidate-details'

export type EducationEntry = {
  degree: string
  institution: string
  date_start: string
  date_end: string
  note: string
}

export type LanguageEntry = {
  language: string
  level: string
}

export type CandidateDetailsInput = {
  first_name: string
  last_name: string
  email: string
  phone: string
  website: string
  github: string
  linkedin: string
  location: string
  education: EducationEntry[]
  certifications: string[]
  languages: LanguageEntry[]
  consent_text: string
}

export type CandidateDetails = CandidateDetailsInput & {
  id: number
  created_at: string
  updated_at: string
}

export const candidateDetailsApi = {
  get: () => fetch(DETAILS_API).then((r) => parse<CandidateDetails | null>(r)),
  save: (input: CandidateDetailsInput) =>
    fetch(DETAILS_API, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }).then((r) => parse<CandidateDetails>(r)),
}
