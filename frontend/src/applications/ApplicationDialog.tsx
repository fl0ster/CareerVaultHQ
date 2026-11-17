import { useEffect, useRef } from 'react'
import CvStatusBadge from '../cv/CvStatusBadge.tsx'
import type { Application, ApplicationStatus } from './api.ts'
import ApplicationDetail from './ApplicationDetail.tsx'
import StatusBadge from './StatusBadge.tsx'

type Props = {
  application: Application
  statuses: ApplicationStatus[]
  onChange: (application: Application) => void
  onDelete: (id: number) => void
  onClose: () => void
}

/** Modal with the full details of one application; closes on ✕, Escape or a backdrop click. */
export default function ApplicationDialog({ application, statuses, onChange, onDelete, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const el = dialog.current
    if (!el) return
    el.showModal()
    return () => el.close()
  }, [])

  const { job } = application

  return (
    <dialog
      ref={dialog}
      className="job-dialog app-dialog"
      onClose={onClose}
      onClick={(e) => {
        // Clicks on the backdrop land on the dialog element itself.
        if (e.target === dialog.current) onClose()
      }}
    >
      <div className="job-dialog-body">
        <div className="job-dialog-head">
          <div className="job-main">
            <h2>{job.title ?? 'Untitled job'}</h2>
            <div className="job-meta">
              {job.company && <span className="job-company">{job.company}</span>}
              <span>{job.source}</span>
            </div>
            <div className="app-badges app-dialog-badges">
              <StatusBadge status={application.status} />
              {application.cv && <CvStatusBadge status={application.cv.status} />}
            </div>
          </div>
          <button type="button" className="secondary small" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <ApplicationDetail
          key={application.id}
          application={application}
          statuses={statuses}
          onChange={onChange}
          onDelete={onDelete}
        />
      </div>
    </dialog>
  )
}
