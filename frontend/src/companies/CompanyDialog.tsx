import { useEffect, useRef, useState } from 'react'
import { notifyApplicationsChanged } from '../applications/api.ts'
import NotesEditor from '../notes/NotesEditor.tsx'
import { CompanyTagBadge } from './CompanyTag.tsx'
import './companies.css'
import './tags.css'
import { getCompany, updateCompanyNotes, type CompanyDetail } from './api.ts'

const JOBS_LIMIT = 10

function formatDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString()
}

type Props = {
  companyId: number
  onClose: () => void
}

/** Popup with a company's tag, notes and most recently parsed jobs. */
export default function CompanyDialog({ companyId, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [detail, setDetail] = useState<CompanyDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) dialog.showModal()
  }, [])

  // The parent keys this component on ``companyId``, so state starts fresh per company.
  useEffect(() => {
    const controller = new AbortController()
    getCompany(companyId, JOBS_LIMIT, controller.signal)
      .then(setDetail)
      .catch((e) => {
        if (!controller.signal.aborted) setError(String(e))
      })
    return () => controller.abort()
  }, [companyId])

  const closeOnBackdrop = (event: React.MouseEvent<HTMLDialogElement>) => {
    if (event.target === ref.current) onClose()
  }

  return (
    <dialog ref={ref} className="company-dialog" onClose={onClose} onClick={closeOnBackdrop}>
      <header className="company-dialog-head">
        <div className="company-dialog-title">
          <h2>{detail?.name ?? 'Company'}</h2>
          {detail && (
            <div className="company-dialog-meta">
              <CompanyTagBadge companyId={detail.id} tag={detail.tag} />
              <span>
                {detail.job_count} {detail.job_count === 1 ? 'job' : 'jobs'} · first seen{' '}
                {formatDate(detail.created_at)}
              </span>
            </div>
          )}
        </div>
        <button
          type="button"
          className="secondary small company-dialog-close"
          onClick={onClose}
          aria-label="Close"
        >
          ✕
        </button>
      </header>

      <div className="company-dialog-body">
        {error && <p className="error">{error}</p>}
        {!detail && !error && <span className="spinner" aria-hidden="true" />}

        {detail && (
          <>
            <section>
              <h3>Notes</h3>
              <NotesEditor
                label="Company notes"
                value={detail.notes}
                placeholder="Notes about this company (shared with its applications)"
                onSave={async (notes) => {
                  const updated = await updateCompanyNotes(detail.id, notes)
                  setDetail((prev) => (prev ? { ...prev, notes: updated.notes } : prev))
                  // Applications show the company's notes too.
                  notifyApplicationsChanged()
                }}
              />
            </section>

            <section>
              <h3>Recent jobs</h3>
              {detail.jobs.length === 0 ? (
                <p className="muted">No parsed jobs yet.</p>
              ) : (
                <ul className="company-jobs">
                  {detail.jobs.map((job) => (
                    <li key={job.parse_result_id}>
                      <a href={job.link} target="_blank" rel="noreferrer">
                        {job.title || job.link}
                      </a>
                      <span className="company-job-meta">
                        {job.source} · {formatDate(job.parsed_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {detail.job_count > detail.jobs.length && (
                <p className="muted company-jobs-more">
                  Showing the {detail.jobs.length} most recent of {detail.job_count}.
                </p>
              )}
            </section>
          </>
        )}
      </div>
    </dialog>
  )
}
