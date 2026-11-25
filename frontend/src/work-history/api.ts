const API = '/api/work-history'

/** Fired after entries are added, changed or removed here, so the menu's setup progress and the career marks on company pills follow. */
export const WORK_HISTORY_CHANGED = 'work-history:changed'

function notifyChanged<T>(value: T): T {
  window.dispatchEvent(new Event(WORK_HISTORY_CHANGED))
  return value
}

/** Kind of career event: a position, an education entry or a certificate. */
export type EntryKind = 'job' | 'education' | 'certificate'

/** How a position continues the previous one at the same employer. */
export type Transition = 'promotion' | 'role_change'

export type WorkHistoryEntry = {
  id: number
  kind: EntryKind
  date_start: string
  /** Null: a current position / ongoing education, or a certificate without a duration. */
  date_end: string | null
  /** Employer, institution or issuer (may be blank except for a job). */
  employer: string
  /** Role, degree or certificate name. */
  role: string
  location: string | null
  tech: string[]
  context: string | null
  /** The application whose accepted offer created the entry. */
  application_id: number | null
  /** Starts in the future: left out of CVs and the candidate profile until then. */
  pending: boolean
  /** Filling the entry in from its application with the LLM; null for entries added by hand. */
  prefill_state: 'queued' | 'done' | 'failed' | null
  created_at: string
  updated_at: string
  /** The known company a position's employer matches (null for education and certificates). */
  company_id: number | null
  /** That company's tag. */
  company_tag: string | null
  /** A promotion or role change within the employer of the previous position (positions only). */
  transition: Transition | null
  /** The role a position with a `transition` continues: the latest earlier position at the same
   * employer; null when there is none (the role then stands on its own). */
  previous_role_id: number | null
}

export type WorkHistoryInput = Omit<
  WorkHistoryEntry,
  | 'id'
  | 'application_id'
  | 'pending'
  | 'prefill_state'
  | 'created_at'
  | 'updated_at'
  | 'company_id'
  | 'company_tag'
  | 'previous_role_id'
>

/** Shape of `GET /json`; dates are `Jan 2020` style, tech is comma separated. */
export type WorkHistoryExport = {
  /** Missing in older exports, which hold positions only. */
  kind?: EntryKind
  date_start: string
  date_end: string | null
  employer: string
  role: string
  location: string | null
  tech: string | string[]
  context: string | null
  /** Missing in older exports: a new employment. */
  transition?: Transition | null
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

export const workHistoryApi = {
  list: () => fetch(API).then((r) => parse<WorkHistoryEntry[]>(r)),
  create: (input: WorkHistoryInput) =>
    fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })
      .then((r) => parse<WorkHistoryEntry>(r))
      .then(notifyChanged),
  update: (id: number, input: WorkHistoryInput) =>
    fetch(`${API}/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })
      .then((r) => parse<WorkHistoryEntry>(r))
      .then(notifyChanged),
  remove: (id: number) =>
    fetch(`${API}/${id}`, { method: 'DELETE' })
      .then((r) => parse<void>(r))
      .then(notifyChanged),
  importJson: (items: WorkHistoryExport[], replace: boolean) =>
    fetch(`${API}/json?replace=${replace}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(items),
    })
      .then((r) => parse<WorkHistoryEntry[]>(r))
      .then(notifyChanged),
}
