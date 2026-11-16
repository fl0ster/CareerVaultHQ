const QUEUE_API = '/api/queue'

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
