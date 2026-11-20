import { type PageId, SETTINGS_PAGES, pageHref } from './nav.ts'

type Props = {
  active: PageId
  onNavigate: (id: PageId) => void
}

/** Tabs across the top of the settings pages; the side menu only has the one Settings entry. */
export default function SettingsNav({ active, onNavigate }: Props) {
  return (
    <nav className="segmented settings-nav" aria-label="Settings sections">
      {SETTINGS_PAGES.map((item) => {
        const Icon = item.icon
        const current = item.id === active
        return (
          <a
            key={item.id}
            href={pageHref(item.id)}
            className={current ? 'button tab active' : 'button tab'}
            aria-current={current ? 'page' : undefined}
            onClick={(e) => {
              e.preventDefault()
              onNavigate(item.id)
            }}
          >
            <Icon size={15} strokeWidth={1.9} aria-hidden="true" />
            {item.label}
          </a>
        )
      })}
    </nav>
  )
}
