import type { ReactNode } from 'react'
import Magpie from './Magpie.tsx'

type Props = {
  children: ReactNode
  /**
   * `page`: an empty list or page, with the whole magpie idling on its stage disc.
   * `inline`: a small empty widget, chart or list end, with the magpie's head in front of the line.
   */
  variant?: 'page' | 'inline'
  className?: string
}

/** Nothing here yet: the magpie keeps the empty spot company. Only for genuinely empty collections. */
export default function EmptyState({ children, variant = 'page', className = '' }: Props) {
  if (variant === 'inline') {
    return (
      <p className={`empty-state inline ${className}`}>
        <span className="empty-stage" aria-hidden="true">
          <Magpie head size={20} />
        </span>
        <span>{children}</span>
      </p>
    )
  }
  return (
    <div className={`empty-state ${className}`}>
      <span className="empty-stage" aria-hidden="true">
        <Magpie mood="idle" size={64} />
      </span>
      <p>{children}</p>
    </div>
  )
}
