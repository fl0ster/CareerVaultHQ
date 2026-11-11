const API = '/api/work-history'

export type WorkHistoryEntry = {
  id: number
  date_start: string
  date_end: string | null
  employer: string
  role: string
  location: string | null
  tech: string[]
  context: string | null
  created_at: string
  updated_at: string
}

export type WorkHistoryInput = Omit<WorkHistoryEntry, 'id' | 'created_at' | 'updated_at'>

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

export const workHistoryApi = {
  list: () => fetch(API).then((r) => parse<WorkHistoryEntry[]>(r)),
  create: (input: WorkHistoryInput) =>
    fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }).then((r) => parse<WorkHistoryEntry>(r)),
  update: (id: number, input: WorkHistoryInput) =>
    fetch(`${API}/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }).then((r) => parse<WorkHistoryEntry>(r)),
  remove: (id: number) => fetch(`${API}/${id}`, { method: 'DELETE' }).then((r) => parse<void>(r)),
}
