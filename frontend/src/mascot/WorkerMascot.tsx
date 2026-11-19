import { useEffect, useRef, useState } from 'react'
import Magpie, { type Mood } from './Magpie.tsx'
import { useQueueStatus } from '../queue/useQueueStatus.ts'
import type { QueueJob } from '../queue/api.ts'

const KIND_LABELS: Record<string, string> = {
  scrape: 'Scrape',
  parse_job: 'Parse',
  evaluate_parse_results: 'Evaluate',
  evaluate_pending_jobs: 'Evaluate pending',
  compile_latex: 'Compile LaTeX',
  generate_cv: 'Generate CV',
  check_rejection_mails: 'Gmail check',
  cleanup_old_jobs: 'Cleanup',
}

const CELEBRATE_DELAY_MS = 2000

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

function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? '' : 's'}`
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
      {since && <span className="queue-time">{running ? `Running for ${since}` : `Waiting for ${since}`}</span>}
    </li>
  )
}

/**
 * Background worker status, told by the magpie: it works while a job runs, eyes the
 * letters while jobs wait, hops once all queued jobs are finished and frets when the worker is unreachable.
 * Click it for the current and pending jobs.
 */
export default function WorkerMascot() {
  const { status, error, fetchedAt } = useQueueStatus()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)

  const current = status?.current ?? null
  const pending = status?.pending ?? []
  const pendingCount = status?.pending_count ?? 0

  // Hop once the whole batch is done: wait for the queue to stay empty for a moment so
  // jobs scheduled back-to-back don't trigger a celebration after each one.
  const currentId = current?.job_id ?? null
  const busy = currentId !== null || pendingCount > 0
  const hasStatus = status != null
  const hadWork = useRef(false)
  const [hops, setHops] = useState(0)
  const [celebrating, setCelebrating] = useState(false)
  const [prevBusyKey, setPrevBusyKey] = useState(`${currentId}|${pendingCount}`)
  const busyKey = `${currentId}|${pendingCount}`
  if (busyKey !== prevBusyKey) {
    setPrevBusyKey(busyKey)
    // The queue changed: drop any celebration in progress.
    if (celebrating) setCelebrating(false)
  }

  useEffect(() => {
    if (busy) {
      hadWork.current = true
      return
    }
    if (!hadWork.current || !hasStatus || error) return
    const timer = setTimeout(() => {
      hadWork.current = false
      setHops((n) => n + 1)
      setCelebrating(true)
    }, CELEBRATE_DELAY_MS)
    return () => clearTimeout(timer)
  }, [busy, busyKey, hasStatus, error])

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  let mood: Mood
  let title: string
  let sub: string
  if (error) {
    mood = 'error'
    title = "Can't reach the worker"
    sub = 'Retrying in a few seconds'
  } else if (!status) {
    mood = 'loading'
    title = 'Checking on the worker'
    sub = 'One moment'
  } else if (current) {
    mood = 'working'
    title = `Working on ${kindLabel(current)}`
    sub = pendingCount > 0 ? `${plural(pendingCount, 'job')} waiting after this` : current.description
  } else if (pendingCount > 0) {
    mood = 'queued'
    title = `${plural(pendingCount, 'job')} waiting`
    sub = 'Starting shortly'
  } else {
    mood = 'idle'
    title = 'All quiet'
    sub = 'Nothing in the queue'
  }

  return (
    <div ref={root} className={`worker mood-${mood}`}>
      <button
        type="button"
        className="worker-toggle"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={`Background jobs: ${title}. ${sub}`}
      >
        <span className="worker-bubble" key={title} aria-live="polite">
          <span className="worker-bubble-title">{title}</span>
          <span className="worker-bubble-sub" title={sub}>
            {sub}
          </span>
        </span>
        <span className="worker-avatar-wrap">
          <span className="worker-avatar">
            <span
              key={hops}
              className={celebrating ? 'celebrate' : undefined}
              onAnimationEnd={(e) => {
                if (e.animationName === 'mg-hop') setCelebrating(false)
              }}
            >
              <Magpie mood={mood} size={40} />
            </span>
          </span>
          {pendingCount > 0 && (
            <span className="worker-count" key={pendingCount}>
              {pendingCount}
            </span>
          )}
        </span>
      </button>

      {open && (
        <div className="worker-panel" role="dialog" aria-label="Background jobs">
          <div className="worker-panel-head">
            <span className={`worker-stage${celebrating ? ' celebrate' : ''}`}>
              <Magpie mood={mood} size={72} />
            </span>
            <div>
              <h2>{title}</h2>
              <p>{sub}</p>
            </div>
          </div>
          <div className="worker-panel-body">
            {error && <p className="error">{error}</p>}

            <h3>Running now</h3>
            {current ? (
              <ul className="queue-list">
                <JobRow job={current} running now={fetchedAt} />
              </ul>
            ) : (
              <p className="queue-empty">Nothing is running.</p>
            )}

            <h3>
              Waiting {pendingCount > 0 && <span className="badge">{pendingCount}</span>}
            </h3>
            {pending.length > 0 ? (
              <ul className="queue-list">
                {pending.map((job) => (
                  <JobRow key={job.job_id} job={job} now={fetchedAt} />
                ))}
                {pendingCount > pending.length && (
                  <li className="queue-empty">And {pendingCount - pending.length} more</li>
                )}
              </ul>
            ) : (
              <p className="queue-empty">No jobs are waiting.</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
