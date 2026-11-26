import { useState } from 'react'
import { describeError } from '../cv/api.ts'
import './notes.css'

type Props = {
  value: string
  onSave: (notes: string) => Promise<unknown>
  placeholder?: string
  label: string
}

/** Textarea with Save / Discard for a free-text notes field. Keeps its own draft, so it can
 * stay mounted (hidden) while another editor is shown without losing unsaved text. */
export default function NotesEditor({ value, onSave, placeholder, label }: Props) {
  const [draft, setDraft] = useState(value)
  const [base, setBase] = useState(value)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // The saved value changed (saved here or elsewhere): start from the new value.
  if (value !== base) {
    setBase(value)
    setDraft(value)
  }

  const dirty = draft !== value

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await onSave(draft)
    } catch (e) {
      setError(describeError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="notes-editor">
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder={placeholder}
        aria-label={label}
        rows={4}
      />
      <div className="notes-buttons">
        <button type="button" className="small" onClick={save} disabled={!dirty || busy}>
          {busy ? 'Saving…' : 'Save notes'}
        </button>
        {dirty && (
          <button type="button" className="secondary small" onClick={() => setDraft(value)} disabled={busy}>
            Discard
          </button>
        )}
        {dirty && <span className="muted notes-unsaved">Unsaved changes</span>}
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  )
}
