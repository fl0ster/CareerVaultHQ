import { useEffect, useRef, useState } from 'react'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import type { GeneratedCv } from '../cv/api.ts'
import CvPipelineDialog from '../cv/CvPipelineDialog.tsx'
import { type Application, type ApplicationStatus } from './api.ts'
import ApplicationDetail from './ApplicationDetail.tsx'

type Props = {
  application: Application
  statuses: ApplicationStatus[]
  onChange: (application: Application) => void
  onDelete: (id: number) => void
  onOpenCompany: (companyId: number) => void
  onClose: () => void
}

/** Modal with the full details of one application; closes on ✕, Escape or a backdrop click. */
export default function ApplicationDialog({
  application,
  statuses,
  onChange,
  onDelete,
  onOpenCompany,
  onClose,
}: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  // The pipeline breakdown replaces this dialog while open; this one stays mounted (closed)
  // so unsaved drafts survive, and reopens when the breakdown is closed.
  const [pipelineCv, setPipelineCv] = useState<GeneratedCv | null>(null)
  const suspended = useRef(false)

  useEffect(() => {
    const el = dialog.current
    if (!el) return
    el.showModal()
    return () => {
      suspended.current = true
      el.close()
    }
  }, [])

  const showPipeline = (cv: GeneratedCv) => {
    suspended.current = true
    dialog.current?.close()
    setPipelineCv(cv)
  }

  const hidePipeline = () => {
    setPipelineCv(null)
    suspended.current = false
    // The pipeline dialog can report its close twice (user close, then unmount).
    if (dialog.current && !dialog.current.open) dialog.current.showModal()
  }

  const { job } = application

  return (
    <>
      <dialog
        ref={dialog}
        className="job-dialog app-dialog"
        onClose={() => {
          // Closed programmatically to make room for the pipeline dialog: not a user close.
          if (!suspended.current) onClose()
        }}
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
                {job.company && (
                  <span className="job-company">
                    <CompanyTagBadge
                      companyId={job.company_id}
                      tag={job.company_tag}
                      name={job.company}
                      onOpenCompany={onOpenCompany}
                    />{' '}
                  </span>
                )}
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
            onShowPipeline={showPipeline}
          />
        </div>
      </dialog>
      {pipelineCv && <CvPipelineDialog key={pipelineCv.id} cv={pipelineCv} onClose={hidePipeline} />}
    </>
  )
}
