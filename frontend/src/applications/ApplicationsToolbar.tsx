import { type ReactNode, useRef } from 'react'
import { useStuck } from '../shell/useStuck.ts'

type Props = {
  search: string
  onSearchChange: (value: string) => void
  /** Whether the list is on screen (the toolbar only tracks sticking then). */
  active: boolean
  /** Page-specific controls after the search box (e.g. a status filter). */
  children?: ReactNode
}

/** Search and filters above an application list. It sticks under the top bar, and once stuck
 * gets the top bar's translucent look. */
export default function ApplicationsToolbar({ search, onSearchChange, active, children }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const stuck = useStuck(ref, active)
  return (
    <div ref={ref} className={stuck ? 'app-toolbar stuck' : 'app-toolbar'}>
      <div className="jobs-controls">
        <input
          type="search"
          className="app-search"
          placeholder="Search company or title…"
          aria-label="Search applications by company or title"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
        {children}
      </div>
    </div>
  )
}
