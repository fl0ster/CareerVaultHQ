import { useEffect, useSyncExternalStore } from 'react'

/** Outcome buckets, in display order; see ``GET /api/companies/application-stats``. */
export const OUTCOMES = [
  { key: 'APPLIED', label: 'Applied', icon: '✉' },
  { key: 'INTERVIEW', label: 'Interview', icon: '💬' },
  { key: 'REJECTED', label: 'Rejected', icon: '✕' },
  { key: 'OFFER', label: 'Offer', icon: '🏆' },
  // Shown as a greyed, struck-through trophy (see tags.css).
  { key: 'DECLINED', label: 'Declined offer', icon: '🏆' },
] as const

export type CompanyStats = Partial<Record<(typeof OUTCOMES)[number]['key'], number>>

/* Stats of every company, loaded once when first shown and reloaded after any change to the
 * applications (``refreshCompanyApplicationStats``). Replaced, never mutated. */
let stats: Readonly<Record<string, CompanyStats>> = {}
let loaded = false
let request = 0
const listeners = new Set<() => void>()

/** Reloads the stats (called after an application is created, changed or deleted). */
export function refreshCompanyApplicationStats() {
  const id = ++request
  loaded = true
  fetch('/api/companies/application-stats')
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
    .then((data: Record<string, CompanyStats>) => {
      if (id !== request) return
      stats = data
      listeners.forEach((l) => l())
    })
    .catch(() => {
      // Stats are a hint only; keep the previous ones.
    })
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Applications to the company counted by outcome (empty without any). */
export function useCompanyApplicationStats(companyId: number | null | undefined): CompanyStats {
  const all = useSyncExternalStore(subscribe, () => stats)
  useEffect(() => {
    if (!loaded) refreshCompanyApplicationStats()
  }, [])
  return (companyId != null && all[companyId]) || {}
}
