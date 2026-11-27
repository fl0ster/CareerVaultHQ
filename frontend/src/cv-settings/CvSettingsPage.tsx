import { type FormEvent, useEffect, useState } from 'react'
import '../candidate-profile/candidate-profile.css'
import './cv-settings.css'
import { type CvSettings, type CvSettingsInput, type RuleKey, cvSettingsApi } from './api.ts'

type Rule = {
  key: RuleKey
  label: string
  hint: string
  /** Relevance thresholds are 0-1 fractions; the rest are whole numbers. */
  fraction?: boolean
  min: number
  max: number
}

const RULES: Rule[] = [
  {
    key: 'max_entries',
    label: 'Maximum roles listed in full',
    hint: 'Older roles beyond this are condensed into "Additional experience".',
    min: 1,
    max: 20,
  },
  {
    key: 'min_entries',
    label: 'Minimum roles listed in full',
    hint: 'Backfilled with the most relevant condensed roles when the history has enough.',
    min: 0,
    max: 20,
  },
  {
    key: 'high_relevance',
    label: 'High relevance threshold',
    hint: 'A role at or above this may win an overlap as the shorter job.',
    fraction: true,
    min: 0,
    max: 1,
  },
  {
    key: 'irrelevant_relevance',
    label: 'Irrelevant threshold',
    hint: 'A role below this is always condensed, even if it leaves a gap.',
    fraction: true,
    min: 0,
    max: 1,
  },
  {
    key: 'min_months',
    label: 'Minimum months to keep a trimmed role',
    hint: 'A shorter job losing an overlap is trimmed instead of dropped when it covers at least this many months.',
    min: 0,
    max: 120,
  },
]

/** Form values are strings so a field can be cleared while typing; blank = default. */
type Draft = { consent_text: string } & Record<RuleKey, string>

function toDraft(s: CvSettings): Draft {
  const draft = { consent_text: s.consent_text } as Draft
  for (const { key } of RULES) draft[key] = s.overridden.includes(key) ? String(s.rules[key]) : ''
  return draft
}

function toInput(draft: Draft): CvSettingsInput {
  const input = { consent_text: draft.consent_text } as CvSettingsInput
  for (const { key } of RULES) input[key] = draft[key].trim() === '' ? null : Number(draft[key])
  return input
}

export default function CvSettingsPage() {
  const [saved, setSaved] = useState<CvSettings | undefined>(undefined)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [tick, setTick] = useState(0)

  const apply = (s: CvSettings) => {
    setSaved(s)
    setDraft(toDraft(s))
  }

  useEffect(() => {
    let cancelled = false
    cvSettingsApi.get().then(
      (s) => {
        if (cancelled) return
        apply(s)
        setLoadError(null)
      },
      (e) => {
        if (!cancelled) setLoadError(`Could not load CV settings: ${String(e instanceof Error ? e.message : e)}`)
      },
    )
    return () => {
      cancelled = true
    }
  }, [tick])

  if (loadError) {
    return (
      <p className="error">
        {loadError}{' '}
        <button type="button" className="secondary small" onClick={() => setTick((t) => t + 1)}>
          Retry
        </button>
      </p>
    )
  }
  if (!saved || !draft) return <p>Loading…</p>

  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(saved))
  const set = (key: keyof Draft, value: string) => setDraft({ ...draft, [key]: value })

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setSaveError(null)
    try {
      apply(await cvSettingsApi.save(toInput(draft)))
    } catch (err) {
      setSaveError(String(err instanceof Error ? err.message : err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="cp-form cd-form" onSubmit={submit}>
      <h2>Consent clause</h2>
      <label>
        Printed at the end of every generated CV; leave empty to omit.
        <textarea rows={4} value={draft.consent_text} onChange={(e) => set('consent_text', e.target.value)} />
      </label>

      <h2>Experience timeline</h2>
      <p className="cp-status">
        How generated CVs pick which roles to list in full. Leave a field empty to use its default.
      </p>
      <div className="cs-rules">
        {RULES.map((rule) => (
          <label key={rule.key}>
            {rule.label}
            <input
              type="number"
              inputMode={rule.fraction ? 'decimal' : 'numeric'}
              min={rule.min}
              max={rule.max}
              step={rule.fraction ? 0.05 : 1}
              value={draft[rule.key]}
              placeholder={`Default: ${saved.defaults[rule.key]}`}
              onChange={(e) => set(rule.key, e.target.value)}
            />
            <span className="cs-hint">{rule.hint}</span>
          </label>
        ))}
      </div>

      {saveError && <p className="error">{saveError}</p>}

      <div className="cp-actions">
        <button type="submit" disabled={saving || !dirty}>
          {saving ? 'Saving…' : 'Save settings'}
        </button>
        <button type="button" className="secondary" onClick={() => apply(saved)} disabled={saving || !dirty}>
          Discard changes
        </button>
        <button
          type="button"
          className="secondary"
          disabled={saving || RULES.every(({ key }) => draft[key] === '')}
          onClick={() => setDraft({ ...draft, ...Object.fromEntries(RULES.map(({ key }) => [key, ''])) })}
        >
          Reset to defaults
        </button>
      </div>
    </form>
  )
}
