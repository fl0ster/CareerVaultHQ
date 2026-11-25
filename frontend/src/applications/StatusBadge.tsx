import { type ReactNode, useEffect, useRef, useState } from 'react'
import { type ApplicationStatus, INTERVIEW_STATUS, isFinalStatus, pickableStatuses } from './api.ts'
import './applications.css'

export type PillOption = {
  key: string
  /** Contents of the option in the picker. */
  label: ReactNode
  /** Text used in hints ("Move to …"). */
  text: string
}

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
  /** Colour classes of the state a click leads to: on hover an arrow in that colour peeks in
   * over the pill's right edge, on click it fills the pill until the change lands. */
  previewClass?: string
}

/**
 * Interactive pill: clicking it moves to `nextKey`, the ⋮ part (unless replaced by `extra`)
 * opens a picker with every option. Rendered with spans with button semantics because it may sit inside another
 * button (a list row).
 */
export function PickerPill({ className, children, options, currentKey, nextKey, onSelect, title, extra, previewClass }: PillProps) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  // A click on the pill (not the picker) is in flight: the preview fills the pill.
  const [filling, setFilling] = useState(false)
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

  const select = async (key: string, fill = false) => {
    setOpen(false)
    setBusy(true)
    setFilling(fill)
    try {
      await onSelect(key)
    } finally {
      setBusy(false)
      setFilling(false)
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
          if (next && !busy) void select(next.key, true)
        })}
      >
        {children}
        {next && previewClass && (
          <span className={`app-status-next${filling ? ' filled' : ''}`} aria-hidden="true">
            <span className={previewClass}>→</span>
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
  /** Name of the current interview round ("Technical"): shown instead of the INTERVIEW label. */
  roundTitle?: string
  /** A click on the INTERVIEW pill plans the next round (none is planned yet). */
  planRound?: boolean
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
export default function StatusBadge({ status, statuses = [], onSelect, nextRound, auto = false, roundTitle, planRound = false }: Props) {
  const cls = `badge app-status ${status ? status.key.toLowerCase() : 'none'}`
  const label = (
    <>
      {auto && <AutoMark />}
      {status?.key === INTERVIEW_STATUS && roundTitle ? (
        <span className="app-status-round" title={roundTitle}>
          {roundTitle}
        </span>
      ) : status ? (
        status.label
      ) : (
        'No status'
      )}
    </>
  )
  if (!onSelect) return <span className={cls}>{label}</span>
  const final = isFinalStatus(status)
  // A click on INTERVIEW records the next round; other states whose default successor is
  // themselves are not advanced by a click.
  const interview = status?.key === INTERVIEW_STATUS
  const nextKey = final || (status?.next_key === status?.key && !interview) ? null : status?.next_key

  return (
    <PickerPill
      className={cls}
      options={pickableStatuses(statuses, status?.key ?? null).map((s) => ({
        key: s.key,
        text: s.label,
        label: <span className={`badge app-status ${s.key.toLowerCase()}`}>{s.label}</span>,
      }))}
      currentKey={status?.key ?? null}
      nextKey={nextKey}
      onSelect={onSelect}
      title={
        interview
          ? nextRound
            ? `Mark ${nextRound} as held`
            : planRound
              ? 'Plan the next interview round'
              : 'Record another interview round'
          : undefined
      }
      extra={final ? null : undefined}
      previewClass={nextKey ? `app-status ${nextKey.toLowerCase()}` : undefined}
    >
      {label}
    </PickerPill>
  )
}
