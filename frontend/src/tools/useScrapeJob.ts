import { useEffect, useState } from 'react'
import { isTerminal, scrapeApi, type ScrapeJobInfo } from './api.ts'

/**
 * Starts a scrape job and follows it (polling once a second) until it reaches a terminal
 * state. Shared by the Tools scrape panel and the Sources page.
 */
export function useScrapeJob() {
  const [job, setJob] = useState<ScrapeJobInfo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

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
        setJob(info)
        if (!isTerminal(info.status)) timer = window.setTimeout(poll, 1000)
      } catch (e) {
        if (!cancelled) setError(`Could not fetch job status: ${String(e)}`)
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
    setError(null)
    setJob(null)
    setSubmitting(true)
    try {
      const accepted = await scrapeApi.start(source)
      setJob({ job_id: accepted.job_id, status: accepted.status, source: accepted.source })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const reset = () => {
    setJob(null)
    setError(null)
  }

  return { job, error, done, running, submitting, start, reset }
}
