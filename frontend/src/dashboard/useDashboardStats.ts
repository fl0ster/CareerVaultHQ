import { useEffect, useState } from 'react'
import { APPLICATIONS_CHANGED } from '../applications/api.ts'
import { JOBS_CHANGED } from '../jobs/api.ts'
import { QUEUE_JOB_FINISHED } from '../queue/api.ts'
import { type DashboardStats, dashboardApi } from './api.ts'

/** Fallback for changes nothing announces (e.g. another device), in ms. */
const POLL_INTERVAL = 60_000

export type StatsState = { stats: DashboardStats | null; error: string | null }

/**
 * The dashboard numbers, reloaded when jobs or applications change here, when the worker
 * finishes a job (scrapes and scoring run there), when the window regains focus, and
 * otherwise every minute while the tab is visible.
 */
export function useDashboardStats(): StatsState {
  const [state, setState] = useState<StatsState>({ stats: null, error: null })

  useEffect(() => {
    let timer: number | undefined
    let controller: AbortController | null = null

    const refresh = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(refresh, POLL_INTERVAL)
      if (document.hidden) return
      controller?.abort()
      const current = new AbortController()
      controller = current
      dashboardApi
        .stats(current.signal)
        .then((stats) => setState({ stats, error: null }))
        .catch((e: unknown) => {
          if (current.signal.aborted) return
          // Keep the last numbers on screen; only report the error when there are none.
          setState((prev) => (prev.stats ? prev : { stats: null, error: e instanceof Error ? e.message : String(e) }))
        })
    }
    const onVisible = () => {
      if (!document.hidden) refresh()
    }

    refresh()
    const events = [APPLICATIONS_CHANGED, JOBS_CHANGED, QUEUE_JOB_FINISHED, 'focus']
    events.forEach((e) => window.addEventListener(e, refresh))
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearTimeout(timer)
      controller?.abort()
      events.forEach((e) => window.removeEventListener(e, refresh))
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  return state
}
