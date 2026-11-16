import { useEffect, useState } from 'react'
import { queueApi, type QueueStatus } from './api.ts'

const IDLE_INTERVAL = 5000
const BUSY_INTERVAL = 1500

/**
 * Polls the worker queue. Polls faster while something is running or waiting so the
 * widget tracks job completion closely, and backs off when the queue is idle. Polling
 * pauses while the tab is hidden.
 */
export function useQueueStatus() {
  const [status, setStatus] = useState<QueueStatus | null>(null)
  const [fetchedAt, setFetchedAt] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined

    const schedule = (busy: boolean) => {
      timer = window.setTimeout(poll, busy ? BUSY_INTERVAL : IDLE_INTERVAL)
    }

    const poll = async () => {
      if (document.hidden) {
        schedule(false)
        return
      }
      try {
        const next = await queueApi.status()
        if (cancelled) return
        setStatus(next)
        setFetchedAt(Date.now())
        setError(null)
        schedule(next.current !== null || next.pending_count > 0)
      } catch (e) {
        if (cancelled) return
        setError(e instanceof Error ? e.message : String(e))
        schedule(false)
      }
    }

    const onVisible = () => {
      if (document.hidden) return
      if (timer) window.clearTimeout(timer)
      poll()
    }

    poll()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  return { status, error, fetchedAt }
}
