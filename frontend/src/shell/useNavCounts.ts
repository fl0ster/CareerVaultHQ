import { useEffect, useState } from 'react'
import { APPLICATIONS_CHANGED } from '../applications/api.ts'
import { JOBS_CHANGED } from '../jobs/api.ts'
import { QUEUE_JOB_FINISHED } from '../queue/api.ts'
import { WORK_HISTORY_CHANGED } from '../work-history/api.ts'
import { type NavCounts, navApi } from './api.ts'

/** Fallback for changes nothing announces (e.g. another device), in ms. */
const POLL_INTERVAL = 15_000

/**
 * The menu badge counts. Only the page on screen is mounted, so the shell keeps these up
 * to date by itself: right away when something here changes jobs, applications or the work
 * history, when the worker finishes a job (scrapes, scoring and the Gmail monitor run there),
 * when the window comes back into view, when `refreshKey` changes (pass the current page), and otherwise
 * every few seconds while the tab is visible.
 */
export function useNavCounts(refreshKey: unknown): NavCounts | null {
  const [counts, setCounts] = useState<NavCounts | null>(null)

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
      navApi
        .counts(current.signal)
        .then((next) =>
          // Keep the same object while nothing changed, so dependants do not re-run.
          setCounts((prev) =>
            prev &&
            prev.jobs_inbox === next.jobs_inbox &&
            prev.applications === next.applications &&
            prev.interviews === next.interviews &&
            prev.offers === next.offers &&
            prev.work_history === next.work_history
              ? prev
              : next,
          ),
        )
        .catch(() => {
          /* keep the last counts; the next refresh tries again */
        })
    }
    const onVisible = () => {
      if (!document.hidden) refresh()
    }

    refresh()
    const events = [APPLICATIONS_CHANGED, JOBS_CHANGED, QUEUE_JOB_FINISHED, WORK_HISTORY_CHANGED, 'focus']
    events.forEach((e) => window.addEventListener(e, refresh))
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearTimeout(timer)
      controller?.abort()
      events.forEach((e) => window.removeEventListener(e, refresh))
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [refreshKey])

  return counts
}
