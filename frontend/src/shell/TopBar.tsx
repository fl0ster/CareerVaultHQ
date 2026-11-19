import { ChevronRight, Menu } from 'lucide-react'
import WorkerMascot from '../mascot/WorkerMascot.tsx'
import { findPage, type PageId } from './nav.ts'

type Props = {
  active: PageId
  onOpenMenu: () => void
}

export default function TopBar({ active, onOpenMenu }: Props) {
  const { group, item } = findPage(active)
  return (
    <header className="topbar">
      <button type="button" className="icon-button menu-button" onClick={onOpenMenu} aria-label="Open menu">
        <Menu size={20} />
      </button>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <span className="crumb-group">{group.label}</span>
        <ChevronRight size={15} className="crumb-sep" aria-hidden="true" />
        <span className="crumb-page" key={item.id} aria-current="page">
          {item.label}
        </span>
      </nav>
      <WorkerMascot />
    </header>
  )
}
