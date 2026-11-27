const API = '/api/companies'

export type Company = {
  id: number
  name: string
  normalized_name: string
  notes: string
  tag: string | null
  created_at: string
  updated_at: string
  job_count: number
}

export type CompanyAlias = {
  id: number
  alias: string
  normalized_alias: string
  match_kind: string
  similarity: number | null
  source: string | null
  created_at: string
}

export type CompanyJob = {
  job_id: number
  parse_result_id: number
  link: string
  source: string
  title: string | null
  parsed_at: string
}

export type CompanyDetail = Company & {
  aliases: CompanyAlias[]
  jobs: CompanyJob[]
}

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

export function getCompany(id: number, jobsLimit = 20, signal?: AbortSignal): Promise<CompanyDetail> {
  return fetch(`${API}/${id}?jobs_limit=${jobsLimit}`, { signal }).then((res) => parse<CompanyDetail>(res))
}

/** Changes only the fields given; ``tag: null`` clears the tag. */
export function updateCompany(id: number, changes: { notes?: string; tag?: string | null }): Promise<Company> {
  return fetch(`${API}/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  }).then((res) => parse<Company>(res))
}

export function updateCompanyNotes(id: number, notes: string): Promise<Company> {
  return updateCompany(id, { notes })
}
