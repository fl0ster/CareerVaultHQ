import type { ApplicationStatus } from './api.ts'

/** Application state pill; known states get a colour, custom ones the neutral badge. */
export default function StatusBadge({ status }: { status: ApplicationStatus | null }) {
  if (!status) return <span className="badge app-status none">No status</span>
  return <span className={`badge app-status ${status.key.toLowerCase()}`}>{status.label}</span>
}
