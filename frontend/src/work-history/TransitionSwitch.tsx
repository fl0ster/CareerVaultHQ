import { useId } from 'react'
import { BriefcaseBusiness } from 'lucide-react'
import type { Transition, WorkHistoryEntry } from './api.ts'
import { dayBefore, TRANSITIONS } from './tenure.ts'

const OPTIONS: { value: '' | Transition; label: string; icon: typeof BriefcaseBusiness }[] = [
  { value: '', label: 'New position', icon: BriefcaseBusiness },
  ...(Object.entries(TRANSITIONS) as [Transition, (typeof TRANSITIONS)[Transition]][]).map(([value, info]) => ({
    value,
    label: info.label,
    icon: info.icon,
  })),
]

function formatMonth(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { year: 'numeric', month: 'short' })
}

function formatDay(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/**
 * "New position · Promotion · Role change" for a position at an employer the career already
 * has an earlier position at (`previous`), with a line on what the choice does.
 */
export default function TransitionSwitch({
  value,
  onChange,
  previous,
  dateStart,
  className = '',
}: {
  value: '' | Transition
  onChange: (value: '' | Transition) => void
  previous: WorkHistoryEntry
  /** Start date of the role being entered (ISO), to tell when the previous role ends. */
  dateStart: string
  className?: string
}) {
  const name = useId()
  const period = `${formatMonth(previous.date_start)} – ${previous.date_end ? formatMonth(previous.date_end) : 'present'}`
  return (
    <div className={`wh-transition ${className}`}>
      <div className="wh-kind-switch wh-transition-switch" role="radiogroup" aria-label={`Move within ${previous.employer}`}>
        {OPTIONS.map(({ value: option, label, icon: Icon }) => (
          <label key={option || 'new'} className={value === option ? 'checked' : undefined}>
            <input type="radio" name={name} checked={value === option} onChange={() => onChange(option)} />
            <Icon size={14} aria-hidden="true" />
            {label}
          </label>
        ))}
      </div>
      <p className="wh-transition-note">
        {value ? (
          <>
            Continues <strong>{previous.role}</strong> ({period})
            {previous.date_end === null && dateStart ? `, which will end on ${formatDay(dayBefore(dateStart))}.` : '.'}
          </>
        ) : (
          <>
            You already have <strong>{previous.role}</strong> at {previous.employer} ({period}). Promoted or moved
            within it? Pick that above to show both roles as one employment.
          </>
        )}
      </p>
    </div>
  )
}
