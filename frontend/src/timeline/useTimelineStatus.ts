import { useCallback, useEffect, useState } from 'react'
import { timelineApi, type TimelineStatus } from './api.ts'

const INTERVAL = 20000

/**
 * Polls the timeline status (newest event, read cursor, unread counts). Polling pauses
 * while the browser tab is hidden and resumes immediately when it becomes visible.
 * ``update`` lets callers apply a fresher status they got elsewhere (e.g. from marking
 * events read) without waiting for the next poll.
 */
export function useTimelineStatus() {
  const [status, setStatus] = useState<TimelineStatus | null>(null)

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined

    const poll = async () => {
      if (!document.hidden) {
        try {
          const next = await timelineApi.status()
          if (!cancelled) setStatus(next)
        } catch {
          /* keep the last known status; the next poll retries */
        }
      }
      if (!cancelled) timer = window.setTimeout(poll, INTERVAL)
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

  const update = useCallback((next: TimelineStatus) => setStatus(next), [])
  return { status, update }
}
