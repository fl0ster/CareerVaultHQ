import { type ReactNode, useEffect, useRef, useState } from 'react'
import type { ApplicationStatus } from './api.ts'
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
}

/**
 * Interactive pill: clicking it moves to `nextKey`, the ⋮ part (unless replaced by `extra`)
 * opens a picker with every option. Rendered with spans with button semantics because it may sit inside another
 * button (a list row).
 */
export function PickerPill({ className, children, options, currentKey, nextKey, onSelect, title, extra }: PillProps) {
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
          if (next && !busy) void select(next.key)
        })}
      >
        {children}
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
}

/**
 * Application state pill; known states get a colour, custom ones the neutral badge.
 * With `onSelect` it is a `PickerPill`: click moves to the state's `next_key`, ⋮ picks any state.
 */
export default function StatusBadge({ status, statuses = [], onSelect }: Props) {
  const cls = `badge app-status ${status ? status.key.toLowerCase() : 'none'}`
  const label = status ? status.label : 'No status'
  if (!onSelect) return <span className={cls}>{label}</span>

  return (
    <PickerPill
      className={cls}
      options={statuses.map((s) => ({
        key: s.key,
        text: s.label,
        label: <span className={`badge app-status ${s.key.toLowerCase()}`}>{s.label}</span>,
      }))}
      currentKey={status?.key ?? null}
      nextKey={status?.next_key}
      onSelect={onSelect}
    >
      {label}
    </PickerPill>
  )
}
