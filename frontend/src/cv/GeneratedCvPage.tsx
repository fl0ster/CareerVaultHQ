import { useEffect, useState } from 'react'
import './cv.css'
import { cvApi, describeError, type GeneratedCv, isInProgress } from './api.ts'
import CvActions from './CvActions.tsx'
import CvStatusBadge from './CvStatusBadge.tsx'
import CvPipelineDialog from './CvPipelineDialog.tsx'
import { formatUsd } from '../cost/format.ts'

const PAGE_SIZE = 50
const POLL_MS = 3000

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString()
}

type RowProps = {
  cv: GeneratedCv
  onDelete: (cv: GeneratedCv) => void
  onOpen: (cv: GeneratedCv) => void
  deleting: boolean
}

function CvRow({ cv, onDelete, onOpen, deleting }: RowProps) {
  const details = cv.status === 'finished' || cv.status === 'failed'
  return (
    <li className="cv-item">
      <div className="cv-head">
        <div className="cv-main">
          <div className="cv-title">
            <strong>{cv.job.title ?? 'Untitled job'}</strong>
            {cv.job.company && <span className="cv-company">{cv.job.company}</span>}
          </div>
          <div className="cv-meta">
            <CvStatusBadge status={cv.status} />
            <span>#{cv.id}</span>
            <span>requested {formatDate(cv.created_at)}</span>
            {cv.finished_at && <span>finished {formatDate(cv.finished_at)}</span>}
            {cv.cost !== null && <span>{formatUsd(cv.cost)}</span>}
            {cv.warnings.length > 0 && (
              <span className="cv-warning-count">
                ⚠ {cv.warnings.length} fallback{cv.warnings.length === 1 ? '' : 's'}
              </span>
            )}
            <a href={cv.job.link} target="_blank" rel="noreferrer">
              {cv.job.source}
            </a>
          </div>
          {cv.headline_role && (
            <div className="cv-headline">
              {cv.headline_role}
              {cv.core_technologies.length > 0 && <span> · {cv.core_technologies.join(' · ')}</span>}
            </div>
          )}
        </div>
        <div className="cv-buttons">
          {details && (
            <button type="button" className="secondary small" onClick={() => onOpen(cv)}>
              Details
            </button>
          )}
          <CvActions cv={cv} onDelete={onDelete} deleting={deleting} />
        </div>
      </div>
    </li>
  )
}

export default function GeneratedCvPage() {
  const [cvs, setCvs] = useState<GeneratedCv[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [openId, setOpenId] = useState<number | null>(null)
  // Bumped by Refresh and by the poll timer; the first page is re-fetched on every change.
  // ``loadedFor`` is the tick whose page was last received, so ``loading`` needs no state.
  const [tick, setTick] = useState(0)
  const [loadedFor, setLoadedFor] = useState(-1)
  const loading = loadedFor !== tick || loadingMore

  useEffect(() => {
    const controller = new AbortController()
    cvApi
      .list({ offset: 0, limit: PAGE_SIZE }, controller.signal)
      .then((page) => {
        setCvs(page.items)
        setTotal(page.total)
        setHasMore(page.has_more)
        setError(null)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(`Could not load generated CVs: ${describeError(e)}`)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadedFor(tick)
      })
    return () => controller.abort()
  }, [tick])

  // Keep polling while any CV is still being generated.
  const pending = cvs.some(isInProgress)
  useEffect(() => {
    if (!pending) return
    const timer = window.setTimeout(() => setTick((t) => t + 1), POLL_MS)
    return () => window.clearTimeout(timer)
  }, [pending, tick])

  const refresh = () => setTick((t) => t + 1)
  // Looked up by id so the dialog follows the row while the list is polled.
  const openCv = openId === null ? null : (cvs.find((c) => c.id === openId) ?? null)

  const loadMore = async () => {
    if (loading || !hasMore) return
    setLoadingMore(true)
    try {
      const page = await cvApi.list({ offset: cvs.length, limit: PAGE_SIZE })
      setCvs((prev) => [...prev, ...page.items])
      setTotal(page.total)
      setHasMore(page.has_more)
    } catch (e) {
      setError(`Could not load generated CVs: ${describeError(e)}`)
    } finally {
      setLoadingMore(false)
    }
  }

  const remove = async (cv: GeneratedCv) => {
    if (!window.confirm(`Delete the CV generated for "${cv.job.title ?? cv.job.link}"?`)) return
    setDeleting(cv.id)
    try {
      await cvApi.remove(cv.id)
      setCvs((prev) => prev.filter((c) => c.id !== cv.id))
      setTotal((t) => (t === null ? t : t - 1))
      setOpenId((id) => (id === cv.id ? null : id))
    } catch (e) {
      setError(`Could not delete: ${describeError(e)}`)
    } finally {
      setDeleting(null)
    }
  }

  return (
    <>
      <h1 className="title">Generated CV</h1>
      <p>
        {total === null
          ? 'Loading…'
          : `${cvs.length} of ${total} CV${total === 1 ? '' : 's'} generated for jobs.`}{' '}
        <button type="button" className="secondary small" onClick={refresh} disabled={loading}>
          Refresh
        </button>
      </p>

      {error && (
        <p className="error">
          {error}{' '}
          <button type="button" className="secondary small" onClick={refresh}>
            Retry
          </button>
        </p>
      )}

      {total === 0 ? (
        <p>No CVs yet. Open a job on the Jobs tab and press "Generate CV".</p>
      ) : (
        <ul className="cv-list">
          {cvs.map((cv) => (
            <CvRow key={cv.id} cv={cv} onDelete={remove} onOpen={(c) => setOpenId(c.id)} deleting={deleting === cv.id} />
          ))}
        </ul>
      )}

      <div className="sentinel">
        {loading && <span className="spinner" aria-hidden="true" />}
        {!loading && hasMore && (
          <button type="button" className="secondary small" onClick={loadMore}>
            Load more
          </button>
        )}
        {!loading && !hasMore && cvs.length > 0 && <span className="muted">All CVs loaded.</span>}
      </div>

      {openCv && <CvPipelineDialog key={openCv.id} cv={openCv} onClose={() => setOpenId(null)} />}
    </>
  )
}
