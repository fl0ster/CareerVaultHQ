const API = '/api/companies'

export type Company = {
  id: number
  name: string
  normalized_name: string
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

export type CompanyPage = {
  items: Company[]
  total: number
  offset: number
  limit: number
  has_more: boolean
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

export function listCompanies(
  params: { offset: number; limit: number; q?: string },
  signal?: AbortSignal,
): Promise<CompanyPage> {
  const search = new URLSearchParams({ offset: String(params.offset), limit: String(params.limit) })
  if (params.q) search.set('q', params.q)
  return fetch(`${API}?${search}`, { signal }).then((res) => parse<CompanyPage>(res))
}

export function getCompany(id: number, jobsLimit = 20, signal?: AbortSignal): Promise<CompanyDetail> {
  return fetch(`${API}/${id}?jobs_limit=${jobsLimit}`, { signal }).then((res) => parse<CompanyDetail>(res))
}
