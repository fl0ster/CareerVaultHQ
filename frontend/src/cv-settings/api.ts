const API = '/api/cv-settings'

/** How the CV timeline is built from the work history (see `app.tasks.cv.history`). */
export type TimelineRules = {
  max_entries: number
  min_entries: number
  high_relevance: number
  irrelevant_relevance: number
  min_months: number
}

export type RuleKey = keyof TimelineRules

export type CvSettings = {
  consent_text: string
  /** The rules in effect: the overrides, or the defaults. */
  rules: TimelineRules
  defaults: TimelineRules
  /** Rules that differ from their defaults. */
  overridden: RuleKey[]
}

/** A `null` rule goes back to its default. */
export type CvSettingsInput = { consent_text: string } & { [K in RuleKey]: number | null }

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T
  let message = `HTTP ${res.status}`
  try {
    const detail = (await res.json())?.detail
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

export const cvSettingsApi = {
  get: () => fetch(API).then((r) => parse<CvSettings>(r)),
  save: (input: CvSettingsInput) =>
    fetch(API, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }).then((r) => parse<CvSettings>(r)),
}
