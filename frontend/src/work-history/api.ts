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
  /** A position's description built from its work journal; used while `context` is blank. */
  journal_context: string | null
  /** The technologies from its work journal; used while `tech` is empty. */
  journal_tech: string[]
  /** Notes in the position's work journal. */
  journal_count: number
  /** When the latest journal note was logged. */
  last_journal_at: string | null
  /** A current position without a journal note for a week. */
  journal_overdue: boolean
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
  | 'journal_context'
  | 'journal_tech'
  | 'journal_count'
  | 'last_journal_at'
  | 'journal_overdue'
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
  exportJson: () => fetch(`${API}/json`).then((r) => parse<WorkHistoryExport[]>(r)),
  /** Merges into the existing entries (duplicates skipped), or replaces them all; returns the entries created. */
  importJson: (items: WorkHistoryExport[], replace: boolean) =>
    fetch(`${API}/json?replace=${replace}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(items),
    })
      .then((r) => parse<WorkHistoryEntry[]>(r))
      .then(notifyChanged),
}

/** One raw note of a position's work journal, kept exactly as written. */
export type JournalNote = {
  id: number
  /** The day the work happened (ISO date). */
  logged_on: string
  body: string
  created_at: string
  updated_at: string
}

/** The polished summary of one month of notes, generated lazily by the LLM. */
export type JournalMonth = {
  /** First day of the month (ISO date). */
  month: string
  /** Null until generated. */
  summary: string | null
  accomplishments: string[]
  tech: string[]
  generated_at: string | null
  /** The notes changed since the summary was generated (or it never was). */
  stale: boolean
}

export type Journal = {
  role_id: number
  /** Newest first. */
  entries: JournalNote[]
  /** One per month with notes, newest first. */
  months: JournalMonth[]
  journal_context: string | null
  journal_tech: string[]
  /** The user's own description is used instead of `journal_context`. */
  context_overridden: boolean
  /** The user's own technologies are used instead of `journal_tech`. */
  tech_overridden: boolean
  /** The description could not be built truthfully from the current summaries; tried again once the notes change. */
  context_failed: boolean
  /** Something needs regenerating: call `refresh`. */
  stale: boolean
  /** What a refresh could not regenerate (the previous version is kept). */
  warnings: string[]
}

const journalUrl = (roleId: number) => `${API}/${roleId}/journal`

export const journalApi = {
  get: (roleId: number) => fetch(journalUrl(roleId)).then((r) => parse<Journal>(r)),
  /** Regenerates the stale monthly summaries and description with the LLM (may take a while). */
  refresh: (roleId: number) =>
    fetch(`${journalUrl(roleId)}/refresh`, { method: 'POST' })
      .then((r) => parse<Journal>(r))
      .then(notifyChanged),
  add: (roleId: number, body: string, loggedOn?: string) =>
    fetch(journalUrl(roleId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body, logged_on: loggedOn || null }),
    })
      .then((r) => parse<JournalNote>(r))
      .then(notifyChanged),
  update: (roleId: number, noteId: number, changes: { body?: string; logged_on?: string }) =>
    fetch(`${journalUrl(roleId)}/${noteId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(changes),
    })
      .then((r) => parse<JournalNote>(r))
      .then(notifyChanged),
  remove: (roleId: number, noteId: number) =>
    fetch(`${journalUrl(roleId)}/${noteId}`, { method: 'DELETE' })
      .then((r) => parse<void>(r))
      .then(notifyChanged),
}

/** "today", "yesterday", "3 days ago", "2 weeks ago", "4 months ago". */
export function timeAgo(iso: string, now: Date = new Date()): string {
  const days = Math.floor((now.getTime() - new Date(iso).getTime()) / 86_400_000)
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  if (days < 7) return rtf.format(-Math.max(days, 0), 'day')
  if (days < 31) return rtf.format(-Math.floor(days / 7), 'week')
  if (days < 365) return rtf.format(-Math.floor(days / 30), 'month')
  return rtf.format(-Math.floor(days / 365), 'year')
}
