import { type FormEvent, useEffect, useState } from 'react'
import {
  type CandidateDetails,
  type CandidateDetailsInput,
  candidateDetailsApi,
  type EducationEntry,
  type LanguageEntry,
} from './api.ts'

const DEFAULT_CONSENT =
  'I consent to the processing of my personal data for recruitment purposes in accordance with GDPR (Regulation (EU) 2016/679).'

type Draft = Omit<CandidateDetailsInput, 'certifications'> & { certifications: string }

const EMPTY_EDUCATION: EducationEntry = { degree: '', institution: '', date_start: '', date_end: '', note: '' }
const EMPTY_LANGUAGE: LanguageEntry = { language: '', level: '' }

function toDraft(details: CandidateDetails | null): Draft {
  return {
    first_name: details?.first_name ?? '',
    last_name: details?.last_name ?? '',
    email: details?.email ?? '',
    phone: details?.phone ?? '',
    website: details?.website ?? '',
    github: details?.github ?? '',
    linkedin: details?.linkedin ?? '',
    location: details?.location ?? '',
    education: details?.education.map((e) => ({ ...EMPTY_EDUCATION, ...e })) ?? [],
    certifications: details?.certifications.join('\n') ?? '',
    languages: details?.languages.map((l) => ({ ...EMPTY_LANGUAGE, ...l })) ?? [],
    consent_text: details ? details.consent_text : DEFAULT_CONSENT,
  }
}

function toInput(d: Draft): CandidateDetailsInput {
  return {
    ...d,
    certifications: d.certifications.split('\n').map((c) => c.trim()).filter(Boolean),
  }
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString()
}

export default function CandidateDetailsForm() {
  const [details, setDetails] = useState<CandidateDetails | null | undefined>(undefined)
  const [draft, setDraft] = useState<Draft>(() => toDraft(null))
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  // Bumped by Retry; the details are (re)loaded on every change.
  const [tick, setTick] = useState(0)

  const apply = (d: CandidateDetails | null) => {
    setDetails(d)
    setDraft(toDraft(d))
  }

  useEffect(() => {
    let cancelled = false
    candidateDetailsApi.get().then(
      (d) => {
        if (cancelled) return
        setDetails(d)
        setDraft(toDraft(d))
        setLoadError(null)
      },
      (e) => {
        if (!cancelled) setLoadError(`Could not load candidate details: ${String(e instanceof Error ? e.message : e)}`)
      },
    )
    return () => {
      cancelled = true
    }
  }, [tick])

  const load = () => setTick((t) => t + 1)

  const dirty = details !== undefined && JSON.stringify(draft) !== JSON.stringify(toDraft(details ?? null))

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((prev) => ({ ...prev, [key]: value }))

  const setEducation = (index: number, patch: Partial<EducationEntry>) =>
    set(
      'education',
      draft.education.map((e, i) => (i === index ? { ...e, ...patch } : e)),
    )
  const setLanguage = (index: number, patch: Partial<LanguageEntry>) =>
    set(
      'languages',
      draft.languages.map((l, i) => (i === index ? { ...l, ...patch } : l)),
    )

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setSaveError(null)
    try {
      apply(await candidateDetailsApi.save(toInput(draft)))
    } catch (err) {
      setSaveError(String(err instanceof Error ? err.message : err))
    } finally {
      setSaving(false)
    }
  }

  const reset = () => {
    if (details !== undefined) apply(details)
    setSaveError(null)
  }

  if (loadError) {
    return (
      <p className="error">
        {loadError}{' '}
        <button type="button" className="secondary small" onClick={load}>Retry</button>
      </p>
    )
  }
  if (details === undefined) return <p>Loading…</p>

  return (
    <form className="cp-form cd-form" onSubmit={submit}>
      <h2>Personal details</h2>
      <p className="cp-status">
        Printed on every generated CV.{' '}
        {details ? `Last updated ${formatDate(details.updated_at)}.` : 'Not saved yet.'}
      </p>

      <div className="cd-grid">
        <label>
          First name *
          <input required value={draft.first_name} onChange={(e) => set('first_name', e.target.value)} />
        </label>
        <label>
          Last name *
          <input required value={draft.last_name} onChange={(e) => set('last_name', e.target.value)} />
        </label>
        <label>
          Email
          <input type="email" value={draft.email} onChange={(e) => set('email', e.target.value)} />
        </label>
        <label>
          Phone
          <input value={draft.phone} onChange={(e) => set('phone', e.target.value)} />
        </label>
        <label>
          Website
          <input value={draft.website} onChange={(e) => set('website', e.target.value)} placeholder="example.com" />
        </label>
        <label>
          GitHub
          <input value={draft.github} onChange={(e) => set('github', e.target.value)} placeholder="github.com/you" />
        </label>
        <label>
          LinkedIn
          <input value={draft.linkedin} onChange={(e) => set('linkedin', e.target.value)} placeholder="linkedin.com/in/you" />
        </label>
        <label>
          Location
          <input value={draft.location} onChange={(e) => set('location', e.target.value)} />
        </label>
      </div>

      <fieldset className="cd-fieldset">
        <legend>Education</legend>
        {draft.education.map((entry, i) => (
          <div key={i} className="cd-row">
            <div className="cd-grid">
              <label>
                Degree
                <input value={entry.degree} onChange={(e) => setEducation(i, { degree: e.target.value })} />
              </label>
              <label>
                Institution
                <input value={entry.institution} onChange={(e) => setEducation(i, { institution: e.target.value })} />
              </label>
              <label>
                From
                <input value={entry.date_start} onChange={(e) => setEducation(i, { date_start: e.target.value })} placeholder="Oct 2012" />
              </label>
              <label>
                To
                <input value={entry.date_end} onChange={(e) => setEducation(i, { date_end: e.target.value })} placeholder="May 2015" />
              </label>
            </div>
            <label>
              Note
              <input value={entry.note} onChange={(e) => setEducation(i, { note: e.target.value })} placeholder="Optional remark printed in small type" />
            </label>
            <button
              type="button"
              className="secondary small danger"
              onClick={() => set('education', draft.education.filter((_, j) => j !== i))}
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          className="secondary small"
          onClick={() => set('education', [...draft.education, { ...EMPTY_EDUCATION }])}
        >
          Add education
        </button>
      </fieldset>

      <label>
        Certifications (one per line)
        <textarea
          rows={3}
          value={draft.certifications}
          onChange={(e) => set('certifications', e.target.value)}
        />
      </label>

      <fieldset className="cd-fieldset">
        <legend>Languages</legend>
        {draft.languages.map((entry, i) => (
          <div key={i} className="cd-row cd-row-inline">
            <label>
              Language
              <input value={entry.language} onChange={(e) => setLanguage(i, { language: e.target.value })} />
            </label>
            <label>
              Level
              <input value={entry.level} onChange={(e) => setLanguage(i, { level: e.target.value })} placeholder="Native / C1 / B2" />
            </label>
            <button
              type="button"
              className="secondary small danger"
              onClick={() => set('languages', draft.languages.filter((_, j) => j !== i))}
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          className="secondary small"
          onClick={() => set('languages', [...draft.languages, { ...EMPTY_LANGUAGE }])}
        >
          Add language
        </button>
      </fieldset>

      <label>
        Consent clause (printed at the end of the CV; leave empty to omit)
        <textarea rows={4} value={draft.consent_text} onChange={(e) => set('consent_text', e.target.value)} />
      </label>

      {saveError && <p className="error">{saveError}</p>}

      <div className="cp-actions">
        <button type="submit" disabled={saving || !dirty}>
          {saving ? 'Saving…' : 'Save details'}
        </button>
        <button type="button" className="secondary" onClick={reset} disabled={saving || !dirty}>
          Discard changes
        </button>
      </div>
    </form>
  )
}
