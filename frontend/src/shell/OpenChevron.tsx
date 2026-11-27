import { ChevronRight } from 'lucide-react'
import './clickable.css'

/** The chevron at the far right of a clickable list row (`.clickable-row`). Decorative: the
 * row's own button or link opens it from the keyboard. */
export function RowChevron() {
  return <ChevronRight className="open-chevron row-chevron" size={18} aria-hidden="true" />
}

/** The chevron in the top right of a clickable card (`.clickable-card`): the card's open
 * button, so it can be reached from the keyboard too. */
export function CardOpenButton({ label, onOpen }: { label: string; onOpen: () => void }) {
  return (
    <button type="button" className="card-open" aria-label={label} title={label} onClick={onOpen}>
      <ChevronRight className="open-chevron" size={20} aria-hidden="true" />
    </button>
  )
}
