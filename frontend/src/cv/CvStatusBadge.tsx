import type { CvStatus } from './api.ts'

const LABELS: Record<CvStatus, string> = {
  queued: 'Queued',
  running: 'Generating',
  finished: 'Ready',
  failed: 'Failed',
}

export default function CvStatusBadge({ status }: { status: CvStatus }) {
  return (
    <span className={`badge cv-status ${status}`}>
      {LABELS[status]}
      {(status === 'queued' || status === 'running') && <span className="spinner" aria-hidden="true" />}
    </span>
  )
}
