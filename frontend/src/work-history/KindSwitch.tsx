import { useId } from 'react'
import type { EntryKind } from './api.ts'
import { KIND_ORDER, KINDS } from './kinds.ts'

/** Segmented Job / Education / Certificate switch of the career event forms. */
export default function KindSwitch({
  value,
  onChange,
  className = '',
}: {
  value: EntryKind
  onChange: (kind: EntryKind) => void
  className?: string
}) {
  const name = useId()
  return (
    <div className={`wh-kind-switch ${className}`} role="radiogroup" aria-label="Type of entry">
      {KIND_ORDER.map((kind) => {
        const { icon: Icon, label } = KINDS[kind]
        return (
          <label key={kind} className={`kind-${kind}${value === kind ? ' checked' : ''}`}>
            <input
              type="radio"
              name={name}
              value={kind}
              checked={value === kind}
              onChange={() => onChange(kind)}
            />
            <Icon size={15} aria-hidden="true" />
            {label}
          </label>
        )
      })}
    </div>
  )
}
