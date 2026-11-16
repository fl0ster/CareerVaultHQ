import { useState } from 'react'
import './queue.css'
import { useQueueStatus } from './useQueueStatus.ts'
import type { QueueJob } from './api.ts'

const KIND_LABELS: Record<string, string> = {
  scrape: 'Scrape',
  parse_job: 'Parse',
  evaluate_parse_results: 'Evaluate',
  evaluate_pending_jobs: 'Evaluate pending',
  compile_latex: 'Compile LaTeX',
  generate_cv: 'Generate CV',
}

function kindLabel(job: QueueJob): string {
  return KIND_LABELS[job.kind] ?? job.kind
}

function elapsed(iso: string | null | undefined, now: number): string | null {
  if (!iso) return null
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${seconds % 60}s`
}

function JobRow({ job, running, now }: { job: QueueJob; running?: boolean; now: number }) {
  const since = elapsed(running ? job.started_at : job.enqueued_at, now)
  return (
    <li className={running ? 'queue-job running' : 'queue-job'}>
      {running && <span className="spinner" aria-hidden="true" />}
      <span className="queue-kind">{kindLabel(job)}</span>
      <span className="queue-desc" title={job.job_id}>
        {job.description}
      </span>
      {since && <span className="queue-time">{running ? `running ${since}` : `waiting ${since}`}</span>}
    </li>
  )
}

export default function QueueWidget() {
  const { status, error, fetchedAt } = useQueueStatus()
  const [open, setOpen] = useState(false)

  const current = status?.current ?? null
  const pending = status?.pending ?? []
  const pendingCount = status?.pending_count ?? 0
  const busy = current !== null || pendingCount > 0

  let summary: string
  if (error) summary = 'Worker status unavailable'
  else if (!status) summary = 'Loading…'
  else if (current) summary = `${kindLabel(current)} · ${pendingCount} pending`
  else if (pendingCount > 0) summary = `${pendingCount} pending`
  else summary = 'Worker idle'

  return (
    <aside className={`queue-widget${open ? ' open' : ''}${busy ? ' busy' : ''}`} aria-label="Background jobs">
      <button
        type="button"
        className="queue-toggle"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        {busy ? <span className="spinner" aria-hidden="true" /> : <span className="queue-dot" aria-hidden="true" />}
        <span className="queue-summary">{summary}</span>
        <span className="queue-chevron" aria-hidden="true">
          {open ? '▾' : '▴'}
        </span>
      </button>

      {open && (
        <div className="queue-body">
          {error && <p className="error">{error}</p>}

          <h4>Current task</h4>
          {current ? (
            <ul className="queue-list">
              <JobRow job={current} running now={fetchedAt} />
            </ul>
          ) : (
            <p className="queue-empty">Nothing running</p>
          )}

          <h4>
            Pending {pendingCount > 0 && <span className="badge">{pendingCount}</span>}
          </h4>
          {pending.length > 0 ? (
            <ul className="queue-list">
              {pending.map((job) => (
                <JobRow key={job.job_id} job={job} now={fetchedAt} />
              ))}
              {pendingCount > pending.length && (
                <li className="queue-empty">…and {pendingCount - pending.length} more</li>
              )}
            </ul>
          ) : (
            <p className="queue-empty">Queue is empty</p>
          )}
        </div>
      )}
    </aside>
  )
}
