const QUEUE_API = '/api/queue'

/** Fired on `window` when the worker finishes a job (it may have scraped, scored or moved
 * applications), so data the shell shows outside the current page (the menu badges) can refresh. */
export const QUEUE_JOB_FINISHED = 'queue:job-finished'

export type QueueJob = {
  job_id: string
  kind: string
  description: string
  status: string
  enqueued_at?: string | null
  started_at?: string | null
  meta: Record<string, string | number | boolean>
}

export type QueueStatus = {
  current: QueueJob | null
  pending: QueueJob[]
  pending_count: number
}

export const queueApi = {
  status: async (): Promise<QueueStatus> => {
    const res = await fetch(QUEUE_API)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return (await res.json()) as QueueStatus
  },
}
