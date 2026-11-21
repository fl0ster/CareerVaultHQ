import { useEffect, useRef, useState } from 'react'
import { Plus, X } from 'lucide-react'
import { type ManualJobInput, type ManualJobStatus, jobsApi } from './api.ts'
import { describeError } from '../cv/api.ts'

const EMPTY: ManualJobInput = { title: '', company: '', link: '', description: '' }

/**
 * Floating "add job" button in the bottom-right corner that morphs into a Gmail-style
 * compose window. Clicking outside minimises it back into the button; the draft is kept.
 */
export default function AddJobComposer({ onAdded }: { onAdded: (status: ManualJobStatus, input: ManualJobInput) => void }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<ManualJobInput>(EMPTY)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const titleRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    const focus = window.setTimeout(() => titleRef.current?.focus(), 180)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
      window.clearTimeout(focus)
    }
  }, [open])

  const set = (field: keyof ManualJobInput) => (e: { target: { value: string } }) =>
    setDraft((d) => ({ ...d, [field]: e.target.value }))

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!draft.title.trim() || saving) return
    setSaving(true)
    setError(null)
    try {
      const status = await jobsApi.addManual(draft)
      onAdded(status, draft)
      setDraft(EMPTY)
      setOpen(false)
    } catch (err) {
      setError(describeError(err))
    } finally {
      setSaving(false)
    }
  }

  const hasDraft = Object.values(draft).some((v) => v.trim() !== '')

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
          <button type="button" className="add-job-close" onClick={() => setOpen(false)} aria-label="Minimise">
            <X size={16} aria-hidden="true" />
          </button>
        </header>
        <input ref={titleRef} placeholder="Title" value={draft.title} onChange={set('title')} required />
        <input placeholder="Company" value={draft.company} onChange={set('company')} />
        <input placeholder="Link (optional)" type="url" value={draft.link} onChange={set('link')} />
        <textarea placeholder="Paste the job description…" value={draft.description} onChange={set('description')} />
        {error && <p className="error">{error}</p>}
        <footer className="add-job-foot">
          <button type="submit" disabled={saving || !draft.title.trim()}>
            {saving ? 'Adding…' : 'Add job'}
          </button>
          {hasDraft && (
            <button type="button" className="secondary small" onClick={() => setDraft(EMPTY)}>
              Discard
            </button>
          )}
        </footer>
      </form>
    </div>
  )
}
