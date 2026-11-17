import { useSyncExternalStore } from 'react'
import { type Company, updateCompany } from './api.ts'

export type CompanyTag = 'favourite' | 'interested' | 'avoid'

/** The tags a company can have, in the order a click cycles through them (then back to none).
 * Keep in sync with ``Company.TAGS`` in the backend. */
export const COMPANY_TAGS: { key: CompanyTag; label: string; icon: string }[] = [
  { key: 'favourite', label: 'Favourite', icon: '★' },
  { key: 'interested', label: 'Interested', icon: '●' },
  { key: 'avoid', label: 'Avoid', icon: '⊘' },
]

export function tagInfo(tag: string | null | undefined) {
  return COMPANY_TAGS.find((t) => t.key === tag) ?? null
}

export function nextTag(tag: string | null | undefined): CompanyTag | null {
  const i = COMPANY_TAGS.findIndex((t) => t.key === tag)
  return i === COMPANY_TAGS.length - 1 ? null : COMPANY_TAGS[i + 1].key
}

/* Tags changed in this browser session, by company id. Lists loaded before the change still
 * carry the old tag from the server; this overrides it everywhere without refetching.
 * Never mutated: every change swaps in a new Map, so the snapshot returned to React changes
 * identity (the React Compiler memoizes on it; reading a mutated Map would serve stale tags). */
let overrides: ReadonlyMap<number, string | null> = new Map()
const listeners = new Set<() => void>()

function setOverride(companyId: number, tag: string | null) {
  overrides = new Map(overrides).set(companyId, tag)
  listeners.forEach((l) => l())
}

const getSnapshot = () => overrides

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** The current tag of a company: the latest one set in this session, else ``serverTag``. */
export function useCompanyTag(companyId: number | null | undefined, serverTag: string | null | undefined) {
  const current = useSyncExternalStore(subscribe, getSnapshot)
  if (companyId != null && current.has(companyId)) return current.get(companyId) ?? null
  return serverTag ?? null
}

/** Saves the tag, updating every place the company is shown right away (rolled back on error). */
export async function setCompanyTag(companyId: number, tag: string | null, previous: string | null): Promise<Company> {
  setOverride(companyId, tag)
  try {
    const updated = await updateCompany(companyId, { tag })
    setOverride(companyId, updated.tag)
    return updated
  } catch (e) {
    setOverride(companyId, previous)
    throw e
  }
}
