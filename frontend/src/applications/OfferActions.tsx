import { type ReactNode, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { describeError } from '../cv/api.ts'
import { type Application, applicationsApi, formatDay } from './api.ts'

/** Today as a `YYYY-MM-DD` date input value (local time). */
function today(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** "Title at Company", or empty without either. */
const jobLine = (application: Application) =>
  [application.job.title, application.job.company].filter(Boolean).join(' at ')

/** A modal form answering an offer. Rendered in `document.body`, so it can be opened from
 * inside a list row's button. */
function OfferDialog({
  title,
  application,
  className,
  onSubmit,
  onClose,
  children,
}: {
  title: string
  application: Application
  className?: string
  onSubmit: (event: React.FormEvent) => void
  onClose: () => void
  children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) dialog.showModal()
  }, [])

  const job = jobLine(application)

  // React events bubble through the portal to the opener; keep them from reaching a row.
  return createPortal(
    <dialog
      ref={ref}
      className={`accept-dialog${className ? ` ${className}` : ''}`}
      onClose={onClose}
      onClick={(e) => {
        e.stopPropagation()
        if (e.target === ref.current) onClose()
      }}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <form onSubmit={onSubmit}>
        <h2>{title}</h2>
        {job && <p className="muted accept-dialog-job">{job}</p>}
        {children}
      </form>
    </dialog>,
    document.body,
  )
}

/** Runs `action`, keeping `busy` / `error` for a dialog's submit. */
function useSubmit() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (e) {
      setError(describeError(e))
      setBusy(false)
    }
  }
  return { busy, error, run }
}

type DialogProps = {
  application: Application
  onAccepted: (application: Application) => void
  onClose: () => void
}

/** Asks for the start date of the offered position, then accepts the offer. */
export function AcceptOfferDialog({ application, onAccepted, onClose }: DialogProps) {
  const [startDate, setStartDate] = useState(application.start_date ?? '')
  const { busy, error, run } = useSubmit()

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (!startDate) return
    void run(async () => onAccepted(await applicationsApi.accept(application.id, startDate)))
  }

  const future = startDate !== '' && startDate > today()

  return (
    <OfferDialog title="Accept the offer" application={application} onSubmit={submit} onClose={onClose}>
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
    </OfferDialog>
  )
}

/** Confirms declining the offer, with an optional reason (the note of the `DECLINED` state). */
export function DeclineOfferDialog({
  application,
  onDeclined,
  onClose,
}: {
  application: Application
  onDeclined: (application: Application) => void
  onClose: () => void
}) {
  const [note, setNote] = useState('')
  const { busy, error, run } = useSubmit()

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    void run(async () => onDeclined(await applicationsApi.decline(application.id, note.trim())))
  }

  return (
    <OfferDialog title="Decline the offer" application={application} onSubmit={submit} onClose={onClose}>
      <label className="accept-dialog-field">
        <span>Reason (optional)</span>
        <textarea
          autoFocus
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="e.g. salary, location, a better offer elsewhere"
        />
      </label>
      <p className="muted accept-dialog-hint">
        The application is closed as declined. Remove the “Declined” state later to reopen the offer.
      </p>
      {error && <p className="error">{error}</p>}
      <div className="accept-dialog-buttons">
        <button type="button" className="secondary small" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button type="submit" className="small decline-dialog-submit" disabled={busy}>
          {busy ? 'Declining…' : 'Decline offer'}
        </button>
      </div>
    </OfferDialog>
  )
}

/** A `role="button"` span (not a `<button>`) so it can sit inside a list row's button, like
 * the status pills. */
function PillButton({
  className,
  busy,
  title,
  onActivate,
  children,
}: {
  className: string
  busy: boolean
  title: string
  onActivate: () => void
  children: ReactNode
}) {
  const activate = (e: React.SyntheticEvent) => {
    e.stopPropagation()
    e.preventDefault()
    if (!busy) onActivate()
  }
  return (
    <span
      role="button"
      tabIndex={busy ? -1 : 0}
      aria-disabled={busy}
      aria-busy={busy}
      className={`${className}${busy ? ' busy' : ''}`}
      onClick={activate}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') activate(e)
      }}
      title={title}
    >
      {children}
    </span>
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
 * otherwise after asking for it.
 */
export function AcceptOfferButton({ application, onAccepted, onError, label = 'Accept' }: ButtonProps) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)

  const accept = async () => {
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

  return (
    <>
      <PillButton
        className="accept-offer"
        busy={busy}
        onActivate={() => void accept()}
        title={
          application.start_date
            ? `Accept the offer, starting ${formatDay(application.start_date)}`
            : 'Accept the offer and add the position to My Career'
        }
      >
        <span aria-hidden="true">✓</span> {busy ? 'Accepting…' : label}
      </PillButton>
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

/** Declines the application's offer after confirming it (and asking for an optional reason). */
export function DeclineOfferButton({
  application,
  onDeclined,
  label = 'Decline',
}: {
  application: Application
  onDeclined: (application: Application) => void
  label?: string
}) {
  const [asking, setAsking] = useState(false)

  return (
    <>
      <PillButton
        className="decline-offer"
        busy={false}
        onActivate={() => setAsking(true)}
        title="Decline the offer (closes the application)"
      >
        <span aria-hidden="true">✕</span> {label}
      </PillButton>
      {asking && (
        <DeclineOfferDialog
          application={application}
          onDeclined={(updated) => {
            setAsking(false)
            onDeclined(updated)
          }}
          onClose={() => setAsking(false)}
        />
      )}
    </>
  )
}
