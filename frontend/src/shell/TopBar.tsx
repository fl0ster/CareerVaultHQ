import { ChevronRight, Menu } from 'lucide-react'
import WorkerMascot from '../mascot/WorkerMascot.tsx'
import { type Crumb, findPage, type PageId, pageHref } from './nav.ts'

type Props = {
  active: PageId
  /** Entries after the page name, e.g. the open item's title; the last one is the current view. */
  crumbs: Crumb[]
  onOpenMenu: () => void
}

const Sep = () => <ChevronRight size={15} className="crumb-sep" aria-hidden="true" />

export default function TopBar({ active, crumbs, onOpenMenu }: Props) {
  const { group, item } = findPage(active)
  const last = crumbs.length - 1
  return (
    <header className="topbar">
      <button type="button" className="icon-button menu-button" onClick={onOpenMenu} aria-label="Open menu">
        <Menu size={20} />
      </button>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        {group && (
          <>
            <span className="crumb-group">{group.label}</span>
            <Sep />
          </>
        )}
        {crumbs.length > 0 ? (
          <a className="crumb-link" href={pageHref(item.id)}>
            {item.label}
          </a>
        ) : (
          <span className="crumb-page" key={item.id} aria-current="page">
            {item.label}
          </span>
        )}
        {crumbs.map((crumb, i) => (
          <span className="crumb-step" key={`${i}:${crumb.label}`}>
            <Sep />
            {i === last ? (
              <span className="crumb-page" aria-current="page" title={crumb.label}>
                {crumb.label}
              </span>
            ) : crumb.href ? (
              <a className="crumb-link" href={crumb.href}>
                {crumb.label}
              </a>
            ) : (
              <span className="crumb-group">{crumb.label}</span>
            )}
          </span>
        ))}
      </nav>
      <WorkerMascot />
    </header>
  )
}
