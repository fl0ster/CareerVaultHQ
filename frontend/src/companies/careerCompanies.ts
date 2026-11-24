import { useEffect, useSyncExternalStore } from 'react'
import { WORK_HISTORY_CHANGED } from '../work-history/api.ts'

/** A company the candidate held a position at; see ``GET /api/work-history/companies``. */
export type CareerCompany = {
  /** The candidate works there now. */
  current: boolean
  /** Roles held there, most recent first. */
  roles: string[]
}

/* Companies in the career by id, loaded once when first shown and reloaded whenever the
 * work history changes. Replaced, never mutated. */
let companies: Readonly<Record<string, CareerCompany>> = {}
let loaded = false
let request = 0
const listeners = new Set<() => void>()

function refresh() {
  const id = ++request
  loaded = true
  fetch('/api/work-history/companies')
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
    .then((data: Record<string, CareerCompany>) => {
      if (id !== request) return
      companies = data
      listeners.forEach((l) => l())
    })
    .catch(() => {
      // The mark is a hint only; keep the previous data.
    })
}

window.addEventListener(WORK_HISTORY_CHANGED, () => {
  if (loaded) refresh()
})

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** The company's place in the candidate's career, or ``null`` when they never worked there. */
export function useCareerCompany(companyId: number | null | undefined): CareerCompany | null {
  const all = useSyncExternalStore(subscribe, () => companies)
  useEffect(() => {
    if (!loaded) refresh()
  }, [])
  return (companyId != null && all[companyId]) || null
}
