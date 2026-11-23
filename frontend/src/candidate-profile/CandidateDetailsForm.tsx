import { type ChangeEvent, type FormEvent, useEffect, useRef, useState } from 'react'
import { ImageUp, Trash2, UserRound } from 'lucide-react'
import { type CandidateDetails, type CandidateDetailsInput, candidateDetailsApi, type LanguageEntry } from './api.ts'
import { candidateDetailsStore } from './store.ts'
import { pageHref } from '../shell/nav.ts'

const DEFAULT_CONSENT =
  'I consent to the processing of my personal data for recruitment purposes in accordance with GDPR (Regulation (EU) 2016/679).'

type Draft = CandidateDetailsInput

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
    photo: details?.photo ?? '',
    languages: details?.languages.map((l) => ({ ...EMPTY_LANGUAGE, ...l })) ?? [],
    consent_text: details ? details.consent_text : DEFAULT_CONSENT,
  }
}

/** Longest side of the stored picture; the menu shows it at 40px, the form at 96px. */
const PHOTO_SIZE = 256

/** Reads an image file and returns it centre-cropped to a square and scaled down, as a JPEG data URL. */
async function toPhoto(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file)
  const side = Math.min(bitmap.width, bitmap.height)
  const size = Math.min(PHOTO_SIZE, side)
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Your browser cannot process images')
  ctx.drawImage(bitmap, (bitmap.width - side) / 2, (bitmap.height - side) / 2, side, side, 0, 0, size, size)
  bitmap.close()
  return canvas.toDataURL('image/jpeg', 0.88)
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
  const [photoError, setPhotoError] = useState<string | null>(null)
  const photoInput = useRef<HTMLInputElement>(null)
  // Bumped by Retry; the details are (re)loaded on every change.
  const [tick, setTick] = useState(0)

  const apply = (d: CandidateDetails | null) => {
    setDetails(d)
    setDraft(toDraft(d))
    candidateDetailsStore.set(d)
  }

  useEffect(() => {
    let cancelled = false
    candidateDetailsApi.get().then(
      (d) => {
        if (cancelled) return
        apply(d)
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

  const setLanguage = (index: number, patch: Partial<LanguageEntry>) =>
    set(
      'languages',
      draft.languages.map((l, i) => (i === index ? { ...l, ...patch } : l)),
    )

  const pickPhoto = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setPhotoError(null)
    try {
      set('photo', await toPhoto(file))
    } catch {
      setPhotoError('Could not read that image. Try a PNG, JPEG or WebP file.')
    }
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setSaveError(null)
    try {
      apply(await candidateDetailsApi.save(draft))
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

      <div className="cd-photo">
        <span className="cd-photo-preview" aria-hidden="true">
          {draft.photo ? <img src={draft.photo} alt="" /> : <UserRound size={40} strokeWidth={1.5} />}
        </span>
        <div className="cd-photo-body">
          <span className="cd-photo-label">Profile picture</span>
          <span className="cd-photo-hint">Shown in the menu. Cropped to a square.</span>
          <div className="cd-photo-actions">
            <button type="button" className="secondary small" onClick={() => photoInput.current?.click()}>
              <ImageUp size={15} strokeWidth={1.9} aria-hidden="true" />
              {draft.photo ? 'Change picture' : 'Upload picture'}
            </button>
            {draft.photo && (
              <button type="button" className="secondary small danger" onClick={() => set('photo', '')}>
                <Trash2 size={15} strokeWidth={1.9} aria-hidden="true" />
                Remove
              </button>
            )}
          </div>
          <input
            ref={photoInput}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            hidden
            onChange={pickPhoto}
            aria-label="Profile picture"
          />
          {photoError && <p className="error">{photoError}</p>}
        </div>
      </div>

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

      <p className="cd-note">
        Education and certifications are part of your career timeline: add them in{' '}
        <a href={pageHref('work-history')}>My Career</a>.
      </p>

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
