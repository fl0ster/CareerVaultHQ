import { useEffect } from 'react'
import { createStore, useStore } from '../shell/store.ts'
import { isTerminal, scrapeApi, type ScrapeJobInfo } from './api.ts'

type ScrapeState = { job: ScrapeJobInfo | null; error: string | null; submitting: boolean }

/** The last started scrape, kept outside the page so leaving it and coming back still shows
 * a running scrape (and follows it to the end). */
const scrapeStore = createStore<ScrapeState>({ job: null, error: null, submitting: false })
const update = (patch: Partial<ScrapeState>) => scrapeStore.set((prev) => ({ ...prev, ...patch }))

/**
 * Starts a scrape job and follows it (polling once a second, while a page using it is on
 * screen) until it reaches a terminal state. Shared by the Tools scrape panel and the
 * Sources page.
 */
export function useScrapeJob() {
  const { job, error, submitting } = useStore(scrapeStore)

  const jobId = job?.job_id
  const done = job ? isTerminal(job.status) : false
  const running = submitting || (!!job && !done)

  useEffect(() => {
    if (!jobId || done) return
    let cancelled = false
    let timer: number | undefined

    const poll = async () => {
      try {
        const info = await scrapeApi.getJob(jobId)
        if (cancelled) return
        update({ job: info })
        if (!isTerminal(info.status)) timer = window.setTimeout(poll, 1000)
      } catch (e) {
        if (!cancelled) update({ error: `Could not fetch job status: ${String(e)}` })
      }
    }
    poll()

    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [jobId, done])

  /** Enqueue a scrape of one source (`null` = every enabled source). */
  const start = async (source: string | null) => {
    update({ error: null, job: null, submitting: true })
    try {
      const accepted = await scrapeApi.start(source)
      update({ job: { job_id: accepted.job_id, status: accepted.status, source: accepted.source } })
    } catch (err) {
      update({ error: err instanceof Error ? err.message : String(err) })
    } finally {
      update({ submitting: false })
    }
  }

  const reset = () => update({ job: null, error: null })

  return { job, error, done, running, submitting, start, reset }
}
