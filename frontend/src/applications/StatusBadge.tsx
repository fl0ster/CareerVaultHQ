import { useEffect, useRef, useState } from 'react'
import type { ApplicationStatus } from './api.ts'

type Props = {
  status: ApplicationStatus | null
  /** All states; needed (with `onSelect`) to make the badge interactive. */
  statuses?: ApplicationStatus[]
  /** Switches the application to the state with this key. Without it the badge is read-only. */
  onSelect?: (key: string) => Promise<unknown> | void
}

/**
 * Application state pill; known states get a colour, custom ones the neutral badge.
 * When `onSelect` is given, clicking the pill moves to the state's default next state
 * (`next_key`), and the ⋮ part opens a picker with every state. Rendered with spans with
 * button semantics because it may sit inside another button (the application list row).
 */
export default function StatusBadge({ status, statuses = [], onSelect }: Props) {
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

  const cls = `badge app-status ${status ? status.key.toLowerCase() : 'none'}`
  const label = status ? status.label : 'No status'
  if (!onSelect) return <span className={cls}>{label}</span>

  const next = status?.next_key ? statuses.find((s) => s.key === status.next_key) : undefined

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
    <span ref={root} className={`${cls} app-status-control${busy ? ' busy' : ''}`}>
      <span
        role="button"
        tabIndex={next && !busy ? 0 : -1}
        aria-disabled={!next || busy}
        className={`app-status-main${next ? ' clickable' : ''}`}
        title={next ? `Move to ${next.label}` : undefined}
        {...handler(() => {
          if (next && !busy) void select(next.key)
        })}
      >
        {label}
      </span>
      <span className="app-status-sep" aria-hidden="true" />
      <span
        role="button"
        tabIndex={busy ? -1 : 0}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Choose status"
        title="Choose status"
        className="app-status-more"
        {...handler(() => {
          if (!busy) setOpen((o) => !o)
        })}
      >
        ⋮
      </span>
      {open && (
        <span role="menu" className="app-status-menu">
          {statuses.map((s) => (
            <span
              key={s.key}
              role="menuitem"
              tabIndex={0}
              className={`app-status-option${s.key === status?.key ? ' current' : ''}`}
              {...handler(() => void select(s.key))}
            >
              <span className={`badge app-status ${s.key.toLowerCase()}`}>{s.label}</span>
            </span>
          ))}
        </span>
      )}
    </span>
  )
}
