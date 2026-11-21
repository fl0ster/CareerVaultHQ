import { useEffect, useState } from 'react'
import { APPLICATIONS_CHANGED, INTERVIEW_STATUS, applicationsApi } from './api.ts'

export const OFFER_STATUS = 'OFFER'

export type StageCounts = { interviews: number; offers: number }

/** How many applications are in the interview / offer stages; refreshed whenever applications change. */
export function useStageCounts(): StageCounts | null {
  const [counts, setCounts] = useState<StageCounts | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const bump = () => setTick((t) => t + 1)
    window.addEventListener(APPLICATIONS_CHANGED, bump)
    return () => window.removeEventListener(APPLICATIONS_CHANGED, bump)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const total = (status: string) =>
      applicationsApi.list({ limit: 1, status }, controller.signal).then((page) => page.total)
    Promise.all([total(INTERVIEW_STATUS), total(OFFER_STATUS)])
      .then(([interviews, offers]) => setCounts({ interviews, offers }))
      .catch(() => {})
    return () => controller.abort()
  }, [tick])

  return counts
}
