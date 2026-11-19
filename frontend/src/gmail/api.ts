import type { BackgroundJob } from '../tools/api.ts'

const API = '/api/gmail-monitor'

export type MonitorSummary = {
  fetched: number
  skipped: number
  failed: number
  outcomes: Record<string, number>
  applied: { message_id: string; application_id: number | null; company: string | null; role: string | null }[]
}

export type MonitorSettings = {
  enabled: boolean
  /** The monitored address and the web app URL are both set. */
  configured: boolean
  email: string
  script_url: string
  /** Last characters of the shared secret embedded in the script. */
  secret_hint: string
  label: string
  interval_seconds: number
  lookback_days: number
  /** Minimum rejection probability (0-1) to act on a mail. */
  threshold: number
  next_run_at: string | null
  last_run_at: string | null
  last_status: 'ok' | 'failed' | null
  last_error: string | null
  last_summary: MonitorSummary | null
  job_id: string
}

export type MonitorSettingsUpdate = Partial<
  Pick<MonitorSettings, 'enabled' | 'email' | 'script_url' | 'label' | 'interval_seconds' | 'lookback_days' | 'threshold'>
>

export type ConnectionTest = {
  ok: boolean
  email: string | null
  matches_configured: boolean
  error: string | null
}

export type MonitorJob = BackgroundJob & { result?: MonitorSummary | null }

export type MailOutcome =
  | 'applied'
  | 'not_rejection'
  | 'extraction_failed'
  | 'no_match'
  | 'ambiguous'
  | 'mark_failed'
  | 'error'

export type ProcessedMail = {
  id: number
  message_id: string
  subject: string
  sender: string
  received_at: string | null
  outcome: MailOutcome
  probability: number | null
  company: string | null
  role: string | null
  application_id: number | null
  application_title: string | null
  error: string | null
  created_at: string
}

export const OUTCOME_LABEL: Record<MailOutcome, string> = {
  applied: 'Rejection registered',
  not_rejection: 'Not a rejection',
  extraction_failed: 'Company not found in mail',
  no_match: 'No matching application',
  ambiguous: 'Ambiguous match',
  mark_failed: 'Registered, label failed',
  error: 'Error',
}

/** Longest lookback the Apps Script allows (days). */
export const MAX_LOOKBACK_DAYS = 30

/** Label names the Apps Script accepts. */
export const LABEL_PATTERN = /^[\w ./-]{1,128}$/

/** Shortest interval the API accepts (seconds). */
export const MIN_INTERVAL_SECONDS = 60

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T
  let message = `HTTP ${res.status}`
  try {
    const detail = (await res.json())?.detail
    if (typeof detail === 'string') message = detail
    else if (Array.isArray(detail)) message = detail.map((d: { msg?: string }) => d.msg).join('; ')
  } catch {
    // keep the status message
  }
  throw new Error(message)
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

export const gmailMonitorApi = {
  settings: (signal?: AbortSignal) => fetch(`${API}/settings`, { signal }).then((r) => parse<MonitorSettings>(r)),
  update: (patch: MonitorSettingsUpdate) =>
    fetch(`${API}/settings`, json('PATCH', patch)).then((r) => parse<MonitorSettings>(r)),
  rotateSecret: () => fetch(`${API}/settings/rotate-secret`, json('POST')).then((r) => parse<MonitorSettings>(r)),
  script: () =>
    fetch(`${API}/apps-script`).then(async (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.text()
    }),
  test: () => fetch(`${API}/test`, json('POST')).then((r) => parse<ConnectionTest>(r)),
  run: () => fetch(`${API}/run`, json('POST')).then((r) => parse<MonitorJob>(r)),
  job: (jobId: string) => fetch(`${API}/jobs/${jobId}`).then((r) => parse<MonitorJob>(r)),
  mails: (signal?: AbortSignal) => fetch(`${API}/mails?limit=50`, { signal }).then((r) => parse<ProcessedMail[]>(r)),
}
