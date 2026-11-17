import { useState } from 'react'
import SourcesPage from '../sources/SourcesPage.tsx'
import GeneratedCvPage from '../cv/GeneratedCvPage.tsx'
import CostPage from '../cost/CostPage.tsx'

const SUBTABS = [
  { id: 'sources', label: 'Sources' },
  { id: 'generated-cv', label: 'Generated CV' },
  { id: 'cost', label: 'Cost' },
] as const

type SubTab = (typeof SUBTABS)[number]['id']

export default function SettingsPage() {
  const [subTab, setSubTab] = useState<SubTab>('sources')

  return (
    <>
      <nav className="tabs subtabs" aria-label="Settings sections">
        {SUBTABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={subTab === t.id ? 'tab active' : 'tab'}
            aria-current={subTab === t.id ? 'page' : undefined}
            onClick={() => setSubTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* All subpages stay mounted so loaded state survives subtab switches. */}
      <section hidden={subTab !== 'sources'}>
        <SourcesPage />
      </section>
      <section hidden={subTab !== 'generated-cv'}>
        <GeneratedCvPage />
      </section>
      <section hidden={subTab !== 'cost'}>
        <CostPage />
      </section>
    </>
  )
}
