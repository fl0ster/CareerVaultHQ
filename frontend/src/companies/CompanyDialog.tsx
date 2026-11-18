import { useEffect, useRef, useState } from 'react'
import { notifyApplicationsChanged } from '../applications/api.ts'
import NotesEditor from '../notes/NotesEditor.tsx'
import { CompanyTagBadge } from './CompanyTag.tsx'
import './tags.css'
import { getCompany, updateCompanyNotes, type CompanyDetail } from './api.ts'

const JOBS_LIMIT = 20

function formatDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString()
}

type Props = {
  companyId: number
  onClose: () => void
}

/** Popup with a company's details, aliases and most recently parsed jobs. */
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
      <div className="company-dialog-body">
        <div className="company-dialog-head">
          <div className="company-dialog-title">
            <h2 className="title">{detail?.name ?? 'Company'}</h2>
            {detail && <CompanyTagBadge companyId={detail.id} tag={detail.tag} />}
          </div>
          <button type="button" className="secondary small" onClick={onClose} aria-label="Close">
            Close
          </button>
        </div>

        {error && <p className="error">{error}</p>}
        {!detail && !error && <span className="spinner" aria-hidden="true" />}

        {detail && (
          <>
            <dl className="company-facts">
              <dt>Normalised name</dt>
              <dd><code>{detail.normalized_name}</code></dd>
              <dt>Parsed jobs</dt>
              <dd>{detail.job_count}</dd>
              <dt>First seen</dt>
              <dd>{formatDate(detail.created_at)}</dd>
            </dl>

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

            <h3>Aliases</h3>
            {detail.aliases.length === 0 ? (
              <p className="muted">No aliases recorded.</p>
            ) : (
              <ul className="company-aliases">
                {detail.aliases.map((alias) => (
                  <li key={alias.id}>
                    <span className="company-alias-name">{alias.alias}</span>
                    <span className="company-alias-meta">
                      {alias.match_kind}
                      {alias.similarity != null && ` ${Math.round(alias.similarity * 100)}%`}
                      {alias.source && ` · ${alias.source}`}
                    </span>
                  </li>
                ))}
              </ul>
            )}

            <h3>Recent job postings</h3>
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
                      {job.source} · parsed {formatDate(job.parsed_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {detail.job_count > detail.jobs.length && (
              <p className="muted">
                Showing the {detail.jobs.length} most recent of {detail.job_count} jobs.
              </p>
            )}
          </>
        )}
      </div>
    </dialog>
  )
}
