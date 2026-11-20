import { type ReactNode, useEffect, useRef, useState } from 'react'
import { type ApplicationStatus, INTERVIEW_STATUS, isFinalStatus, pickableStatuses } from './api.ts'
import './applications.css'

export type PillOption = {
  key: string
  /** Contents of the option in the picker. */
  label: ReactNode
  /** Text used in hints ("Move to …"). */
  text: string
  /** Colour classes of the option (as on the pill); enables the hover preview. */
  className?: string
}

/** What the hover preview shows: the next state's colour. */
export type PillPreview = { className: string }

type PillProps = {
  /** Classes of the pill (badge colour). */
  className: string
  children: ReactNode
  options: PillOption[]
  currentKey: string | null
  /** Option a click on the pill moves to; without it only the ⋮ picker works. */
  nextKey?: string | null
  /** Switches to the option with this key. */
  onSelect: (key: string) => Promise<unknown> | void
  /** Overrides the hover hint of the pill (e.g. to show an error). */
  title?: string
  /** Replaces the ⋮ picker with this content (e.g. read-only extras); `null` shows nothing. */
  extra?: ReactNode
  /** Hover preview of what a click leads to; defaults to the `nextKey` option's label
   * when it differs from the current one. */
  preview?: PillPreview
}

/**
 * Interactive pill: clicking it moves to `nextKey`, the ⋮ part (unless replaced by `extra`)
 * opens a picker with every option. Rendered with spans with button semantics because it may sit inside another
 * button (a list row).
 */
export function PickerPill({ className, children, options, currentKey, nextKey, onSelect, title, extra, preview: previewLabel }: PillProps) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const root = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc, true)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', esc, true)
    }
  }, [open])

  const main = extra === undefined || extra != null ? 'app-status-main' : 'app-status-main alone'
  const next = nextKey != null ? options.find((o) => o.key === nextKey) : undefined
  // Preview only an actual change (an INTERVIEW click stays in INTERVIEW).
  // The pill being clicked: the preview fills it until the change lands.
  const [filling, setFilling] = useState(false)
  const preview: PillPreview | null =
    next == null
      ? null
      : (previewLabel ??
        (next.key !== currentKey && next.className ? { className: next.className } : null))

  const select = async (key: string) => {
    setOpen(false)
    setBusy(true)
    try {
      await onSelect(key)
    } finally {
      setBusy(false)
    }
  }

  // Keep clicks from reaching an enclosing row button.
  const handler = (fn: () => void) => ({
    onClick: (e: React.SyntheticEvent) => {
      e.stopPropagation()
      e.preventDefault()
      fn()
    },
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.stopPropagation()
        e.preventDefault()
        fn()
      }
    },
  })

  return (
    <span ref={root} className={`${className} app-status-control${busy ? ' busy' : ''}`}>
      <span
        role="button"
        tabIndex={next && !busy ? 0 : -1}
        aria-disabled={!next || busy}
        className={`${main}${next ? ' clickable' : ''}`}
        title={title ?? (next ? `Move to ${next.text}` : undefined)}
        {...handler(() => {
          if (next && !busy) {
            setFilling(true)
            void select(next.key).finally(() => setFilling(false))
          }
        })}
      >
        {children}
        {preview != null && (
          // Hover: an arrow in the next state's colour peeks in from the right edge; click: it fills the pill.
          <span className={`app-status-next${filling ? ' filled' : ''}`} aria-hidden="true">
            <span className={preview.className}>→</span>
          </span>
        )}
      </span>
      {extra !== undefined ? (
        extra != null && (
          <>
            <span className="app-status-sep" aria-hidden="true" />
            {extra}
          </>
        )
      ) : (
        <>
          <span className="app-status-sep" aria-hidden="true" />
          <span
            role="button"
            tabIndex={busy ? -1 : 0}
            aria-haspopup="menu"
            aria-expanded={open}
            aria-label="Choose"
            title="Choose"
            className="app-status-more"
            {...handler(() => {
              if (!busy) setOpen((o) => !o)
            })}
          >
            ⋮
          </span>
        </>
      )}
      {open && (
        <span role="menu" className="app-status-menu">
          {options.map((o) => (
            <span
              key={o.key}
              role="menuitem"
              tabIndex={0}
              className={`app-status-option${o.key === currentKey ? ' current' : ''}`}
              {...handler(() => void select(o.key))}
            >
              {o.label}
            </span>
          ))}
        </span>
      )}
    </span>
  )
}

type Props = {
  status: ApplicationStatus | null
  /** All states; needed (with `onSelect`) to make the badge interactive. */
  statuses?: ApplicationStatus[]
  /** Switches the application to the state with this key. Without it the badge is read-only. */
  onSelect?: (key: string) => Promise<unknown> | void
  /** Label of the next planned interview round ("round 2 (Technical)"), if any: a click on
   * an INTERVIEW pill records that round as held (without one it records another round). */
  nextRound?: string
  /** The state was recorded automatically (Gmail rejection monitor): shows a lightning bolt. */
  auto?: boolean
}

function AutoMark() {
  return (
    <span className="app-status-auto" title="Recorded automatically from a Gmail rejection mail" aria-label="automatic">
      ⚡
    </span>
  )
}

/**
 * Application state pill; known states get a colour, custom ones the neutral badge.
 * With `onSelect` it is a `PickerPill`: click moves to the state's `next_key`, ⋮ picks any state.
 */
export default function StatusBadge({ status, statuses = [], onSelect, nextRound, auto = false }: Props) {
  const cls = `badge app-status ${status ? status.key.toLowerCase() : 'none'}`
  const label = (
    <>
      {auto && <AutoMark />}
      {status ? status.label : 'No status'}
    </>
  )
  if (!onSelect) return <span className={cls}>{label}</span>
  const final = isFinalStatus(status)
  // A click on INTERVIEW records the next round; other states whose default successor is
  // themselves are not advanced by a click.
  const interview = status?.key === INTERVIEW_STATUS

  return (
    <PickerPill
      className={cls}
      options={pickableStatuses(statuses, status?.key ?? null).map((s) => ({
        key: s.key,
        text: s.label,
        label: <span className={`badge app-status ${s.key.toLowerCase()}`}>{s.label}</span>,
        className: `app-status ${s.key.toLowerCase()}`,
      }))}
      currentKey={status?.key ?? null}
      nextKey={final || (status?.next_key === status?.key && !interview) ? null : status?.next_key}
      onSelect={onSelect}
      title={interview ? (nextRound ? `Mark ${nextRound} as held` : 'Record another interview round') : undefined}
      extra={final ? null : undefined}
      preview={
        interview
          ? {
              className: 'app-status interview',
            }
          : undefined
      }
    >
      {label}
    </PickerPill>
  )
}
