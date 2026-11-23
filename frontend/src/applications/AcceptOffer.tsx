import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { describeError } from '../cv/api.ts'
import { type Application, applicationsApi, formatDay } from './api.ts'

/** Today as a `YYYY-MM-DD` date input value (local time). */
function today(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

type DialogProps = {
  application: Application
  onAccepted: (application: Application) => void
  onClose: () => void
}

/** Asks for the start date of the offered position, then accepts the offer. Rendered in
 * `document.body`, so it can be opened from inside a list row's button. */
export function AcceptOfferDialog({ application, onAccepted, onClose }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const [startDate, setStartDate] = useState(application.start_date ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) dialog.showModal()
  }, [])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!startDate) return
    setBusy(true)
    setError(null)
    try {
      onAccepted(await applicationsApi.accept(application.id, startDate))
    } catch (e) {
      setError(describeError(e))
      setBusy(false)
    }
  }

  const job = [application.job.title, application.job.company].filter(Boolean).join(' at ')
  const future = startDate !== '' && startDate > today()

  // React events bubble through the portal to the opener; keep them from reaching a row.
  return createPortal(
    <dialog
      ref={ref}
      className="accept-dialog"
      onClose={onClose}
      onClick={(e) => {
        e.stopPropagation()
        if (e.target === ref.current) onClose()
      }}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <form onSubmit={submit}>
        <h2>Accept the offer</h2>
        {job && <p className="muted accept-dialog-job">{job}</p>}
        <label className="accept-dialog-field">
          <span>Start date</span>
          <input type="date" required autoFocus value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </label>
        <p className="muted accept-dialog-hint">
          The position moves to My Career, filled in from this application.
          {future && ' It stays pending — left out of your CVs and profile — until it starts.'}
        </p>
        {error && <p className="error">{error}</p>}
        <div className="accept-dialog-buttons">
          <button type="button" className="secondary small" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="small accept-dialog-submit" disabled={busy || !startDate}>
            {busy ? 'Accepting…' : 'Accept offer'}
          </button>
        </div>
      </form>
    </dialog>,
    document.body,
  )
}

type ButtonProps = {
  application: Application
  onAccepted: (application: Application) => void
  onError?: (message: string) => void
  label?: string
}

/**
 * Accepts the application's offer: straight away when its start date is already known,
 * otherwise after asking for it. A `role="button"` span (not a `<button>`) so it can sit
 * inside a list row's button, like the status pills.
 */
export function AcceptOfferButton({ application, onAccepted, onError, label = 'Accept' }: ButtonProps) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)

  const accept = async () => {
    if (busy) return
    if (!application.start_date) {
      setAsking(true)
      return
    }
    setBusy(true)
    try {
      onAccepted(await applicationsApi.accept(application.id, application.start_date))
    } catch (e) {
      onError?.(`Could not accept the offer: ${describeError(e)}`)
      setBusy(false)
    }
  }

  const activate = (e: React.SyntheticEvent) => {
    e.stopPropagation()
    e.preventDefault()
    void accept()
  }

  return (
    <>
      <span
        role="button"
        tabIndex={busy ? -1 : 0}
        aria-disabled={busy}
        aria-busy={busy}
        className={`accept-offer${busy ? ' busy' : ''}`}
        onClick={activate}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') activate(e)
        }}
        title={
          application.start_date
            ? `Accept the offer, starting ${formatDay(application.start_date)}`
            : 'Accept the offer and add the position to My Career'
        }
      >
        <span aria-hidden="true">✓</span> {busy ? 'Accepting…' : label}
      </span>
      {asking && (
        <AcceptOfferDialog
          application={application}
          onAccepted={(updated) => {
            setAsking(false)
            onAccepted(updated)
          }}
          onClose={() => setAsking(false)}
        />
      )}
    </>
  )
}
