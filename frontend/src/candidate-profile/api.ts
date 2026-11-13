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
  update: (id: number, input: CandidateProfileInput) =>
    fetch(`${API}/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }).then((r) => parse<CandidateProfile>(r)),
}
