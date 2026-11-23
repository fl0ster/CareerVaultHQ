import { useCallback, useEffect, useRef, useState } from 'react'
import { Download, Plus, X } from 'lucide-react'
import { type ManualJobInput, type ManualJobStatus, jobsApi } from './api.ts'
import { describeError } from '../cv/api.ts'

const EMPTY: ManualJobInput = { title: '', company: '', link: '', description: '' }
const IMPORTED_FIELDS = ['title', 'company', 'description'] as const

const isHttpLink = (value: string) => {
  try {
    const url = new URL(value.trim())
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

/**
 * Floating "add job" button in the bottom-right corner that morphs into a Gmail-style
 * compose window. Clicking outside minimises it back into the button; the draft is kept.
 *
 * With a link entered, "Import" fetches and parses the page into the draft (nothing is
 * saved until "Add job"). An import is cancelled when the window is minimised, the page is
 * left, the link is edited, or the draft is discarded or submitted, so a late response never
 * fills the form behind the user's back. Fields the user edits while it runs are kept.
 */
export default function AddJobComposer({ onAdded }: { onAdded: (status: ManualJobStatus, input: ManualJobInput) => void }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<ManualJobInput>(EMPTY)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)
  const [importNote, setImportNote] = useState<string | null>(null)
  const importRef = useRef<AbortController | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const titleRef = useRef<HTMLInputElement>(null)

  const cancelImport = useCallback(() => {
    importRef.current?.abort()
    importRef.current = null
    setImporting(false)
  }, [])

  const minimise = useCallback(() => {
    cancelImport()
    setOpen(false)
  }, [cancelImport])

  // Leaving the page unmounts the composer: drop any import still in flight.
  useEffect(() => () => importRef.current?.abort(), [])

  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) minimise()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') minimise()
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    const focus = window.setTimeout(() => titleRef.current?.focus(), 180)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
      window.clearTimeout(focus)
    }
  }, [open, minimise])

  const set = (field: keyof ManualJobInput) => (e: { target: { value: string } }) => {
    if (field === 'link') {
      cancelImport()
      setImportNote(null)
    }
    setDraft((d) => ({ ...d, [field]: e.target.value }))
  }

  const runImport = async () => {
    const link = draft.link.trim()
    if (!isHttpLink(link)) return
    cancelImport()
    const ctrl = new AbortController()
    importRef.current = ctrl
    const before = draft
    setImporting(true)
    setImportNote(null)
    setError(null)
    try {
      const job = await jobsApi.importManual(link, ctrl.signal)
      if (ctrl.signal.aborted) return
      setDraft((d) => {
        const next = { ...d }
        // Replace only the fields the user left alone while the import ran.
        for (const field of IMPORTED_FIELDS) {
          if (job[field] && d[field] === before[field]) next[field] = job[field]
        }
        return next
      })
      setImportNote(`Imported with the ${job.source ?? 'generic'} parser. Review before adding.`)
    } catch (err) {
      if (!ctrl.signal.aborted) setError(describeError(err))
    } finally {
      if (importRef.current === ctrl) {
        importRef.current = null
        setImporting(false)
      }
    }
  }

  const discard = () => {
    cancelImport()
    setImportNote(null)
    setError(null)
    setDraft(EMPTY)
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!draft.title.trim() || saving) return
    cancelImport()
    setSaving(true)
    setError(null)
    try {
      const status = await jobsApi.addManual(draft)
      onAdded(status, draft)
      setDraft(EMPTY)
      setImportNote(null)
      setOpen(false)
    } catch (err) {
      setError(describeError(err))
    } finally {
      setSaving(false)
    }
  }

  const hasDraft = Object.values(draft).some((v) => v.trim() !== '')
  const canImport = isHttpLink(draft.link)

  return (
    <div ref={rootRef} className={open ? 'add-job open' : 'add-job'}>
      <button
        type="button"
        className="add-job-fab"
        onClick={() => setOpen(true)}
        aria-label="Add a job manually"
        title={hasDraft ? 'Continue adding job (draft)' : 'Add a job manually'}
        tabIndex={open ? -1 : 0}
      >
        <Plus size={24} aria-hidden="true" />
        {hasDraft && <span className="add-job-dot" aria-hidden="true" />}
      </button>

      <form className="add-job-panel" onSubmit={submit} aria-hidden={!open} inert={!open}>
        <header className="add-job-head">
          <span>New job</span>
          <button type="button" className="add-job-close" onClick={minimise} aria-label="Minimise">
            <X size={16} aria-hidden="true" />
          </button>
        </header>
        <input ref={titleRef} placeholder="Title" value={draft.title} onChange={set('title')} required />
        <input placeholder="Company" value={draft.company} onChange={set('company')} />
        <div className="add-job-link">
          <input placeholder="Link (optional)" type="url" value={draft.link} onChange={set('link')} />
          {canImport && (
            <button
              type="button"
              className="secondary small"
              onClick={importing ? cancelImport : runImport}
              title={importing ? 'Cancel the import' : 'Fill the form in from this page'}
            >
              {importing ? (
                <>
                  <span className="spinner" aria-hidden="true" /> Cancel
                </>
              ) : (
                <>
                  <Download size={14} aria-hidden="true" /> Import
                </>
              )}
            </button>
          )}
        </div>
        <textarea
          placeholder={importing ? 'Importing the job description…' : 'Paste the job description…'}
          value={draft.description}
          onChange={set('description')}
        />
        {importNote && <p className="add-job-note">{importNote}</p>}
        {error && <p className="error">{error}</p>}
        <footer className="add-job-foot">
          <button type="submit" disabled={saving || !draft.title.trim()}>
            {saving ? 'Adding…' : 'Add job'}
          </button>
          {hasDraft && (
            <button type="button" className="secondary small" onClick={discard}>
              Discard
            </button>
          )}
        </footer>
      </form>
    </div>
  )
}
