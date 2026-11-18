type Props = {
  name: string
  companyId: number | null
  onOpen: (companyId: number) => void
}

/**
 * Company name that opens the company popup. Rendered as a span with button semantics
 * because it may sit inside another button (the application list row).
 */
export default function CompanyLink({ name, companyId, onOpen }: Props) {
  if (companyId == null) return <>{name}</>
  const open = (e: React.SyntheticEvent) => {
    e.stopPropagation()
    e.preventDefault()
    onOpen(companyId)
  }
  return (
    <span
      role="button"
      tabIndex={0}
      className="company-link"
      title="Show company details"
      aria-haspopup="dialog"
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') open(e)
      }}
    >
      {name}
    </span>
  )
}
