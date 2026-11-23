import type { ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'

type Props = {
  title: string
  /** Columns the widget spans on wide screens (the grid collapses to one on phones);
   * `full` takes the whole row. */
  span?: 1 | 2 | 'full'
  /** Page the widget summarises; shown as a link in the header. */
  href?: string
  linkLabel?: string
  children: ReactNode
}

/** Card frame shared by every dashboard widget. */
export default function Widget({ title, span = 1, href, linkLabel = 'View all', children }: Props) {
  return (
    <section className={`widget${span === 2 ? ' widget--wide' : span === 'full' ? ' widget--full' : ''}`} aria-label={title}>
      <header className="widget-head">
        <h2>{title}</h2>
        {href && (
          <a className="widget-link" href={href}>
            {linkLabel}
            <ChevronRight size={14} aria-hidden />
          </a>
        )}
      </header>
      {children}
    </section>
  )
}
