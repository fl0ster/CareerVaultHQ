import { type ReactNode, useState } from 'react'
import './applications.css'
import '../cv/cv.css'
import '../jobs/jobs.css'
import '../companies/tags.css'
import type { Application } from './api.ts'
import CompanyDialog from '../companies/CompanyDialog.tsx'
import ApplicationDetailPane from './ApplicationDetailPane.tsx'
import ApplicationRow from './ApplicationRow.tsx'
import ApplicationsToolbar from './ApplicationsToolbar.tsx'
import Confetti from './Confetti.tsx'
import type { ApplicationList } from './useApplicationList.ts'

type Props = {
  list: ApplicationList
  onOpen: (id: number) => void
  onBack: () => void
  /** Page-specific controls in the toolbar, after the search box. */
  filters?: ReactNode
  /** Shown when the list is empty and no search is active. */
  emptyText: string
  /** The controls on the right of each row. */
  renderActions: (application: Application) => ReactNode
}

/** The frame shared by the application list pages: toolbar, list, the open application in
 * place of the list, and the company popup. */
export default function ApplicationsLayout({ list, onOpen, onBack, filters, emptyText, renderActions }: Props) {
  const { applications, detailOpen } = list
  // Company popup; also opens over the application view.
  const [companyId, setCompanyId] = useState<number | null>(null)

  return (
    <div className="app-page">
      {list.celebrations > 0 && <Confetti key={list.celebrations} />}
      {detailOpen && <ApplicationDetailPane list={list} onOpenCompany={setCompanyId} onBack={onBack} />}

      {/* The list stays mounted under an open application so its filters and search survive. */}
      <div hidden={detailOpen}>
        <ApplicationsToolbar search={list.searchInput} onSearchChange={list.setSearchInput} active={!detailOpen}>
          {filters}
        </ApplicationsToolbar>

        {list.error && <p className="error">{list.error}</p>}

        {applications !== null && applications.length === 0 && (
          <p className="muted">{list.search ? 'No applications match your search.' : emptyText}</p>
        )}

        <ul className="app-list">
          {applications?.map((a) => (
            <ApplicationRow
              key={a.id}
              application={a}
              onOpen={onOpen}
              onOpenCompany={setCompanyId}
              onRescored={list.rescored}
              actions={renderActions(a)}
            />
          ))}
        </ul>
      </div>

      {companyId != null && (
        <CompanyDialog key={companyId} companyId={companyId} onClose={() => setCompanyId(null)} />
      )}
    </div>
  )
}
