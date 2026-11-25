import { ArrowRightLeft, type LucideIcon, TrendingUp } from 'lucide-react'
import type { Transition, WorkHistoryEntry } from './api.ts'

/*
 * Roles held one after another at one organisation: a promotion or a role change.
 *
 * A position with a `transition` continues the latest earlier position at the same employer;
 * the API resolves that role (`previous_role_id`). The chain of such roles is a *tenure*,
 * identified by the id of its first role.
 */

export type TransitionInfo = {
  /** Option label of the transition switch. */
  label: string
  /** "Promoted" in the timeline label of the role. */
  past: string
  /** "Promoted to" in the timeline event. */
  to: string
  /** "Promoted from" on the role's card. */
  from: string
  icon: LucideIcon
}

export const TRANSITIONS: Record<Transition, TransitionInfo> = {
  promotion: { label: 'Promotion', past: 'Promoted', to: 'Promoted to ', from: 'Promoted from', icon: TrendingUp },
  role_change: { label: 'Role change', past: 'Moved', to: 'Moved to ', from: 'Moved from', icon: ArrowRightLeft },
}

/** The transition that links a role to its predecessor; null for a role that stands alone. */
export const linkedTransition = (entry: WorkHistoryEntry): Transition | null =>
  entry.previous_role_id != null ? entry.transition : null

export type Tenures = {
  /** Tenure (id of its first role) of every position. */
  rootOf: Map<number, number>
  /** Roles of every tenure, oldest first. */
  chain: Map<number, WorkHistoryEntry[]>
}

const byStart = (a: WorkHistoryEntry, b: WorkHistoryEntry) => a.date_start.localeCompare(b.date_start) || a.id - b.id

export function tenures(entries: WorkHistoryEntry[]): Tenures {
  const byId = new Map(entries.map((e) => [e.id, e]))
  const rootOf = new Map<number, number>()
  const chain = new Map<number, WorkHistoryEntry[]>()
  for (const entry of entries) {
    if (entry.kind !== 'job') continue
    let root = entry
    const seen = new Set<number>()
    while (root.previous_role_id != null && !seen.has(root.id)) {
      seen.add(root.id)
      const previous = byId.get(root.previous_role_id)
      if (!previous) break
      root = previous
    }
    rootOf.set(entry.id, root.id)
    chain.set(root.id, [...(chain.get(root.id) ?? []), entry])
  }
  for (const roles of chain.values()) roles.sort(byStart)
  return { rootOf, chain }
}

/** The roles of the tenure `entry` belongs to, oldest first (just the entry when it stands alone). */
export function tenureOf(t: Tenures, entry: WorkHistoryEntry): WorkHistoryEntry[] {
  const root = t.rootOf.get(entry.id)
  return (root != null && t.chain.get(root)) || [entry]
}

/**
 * The list order: newest first (as the API returns them), except that the roles of a tenure stay
 * together, anchored where its newest role is.
 */
export function orderForList(entries: WorkHistoryEntry[], t: Tenures): WorkHistoryEntry[] {
  const out: WorkHistoryEntry[] = []
  const placed = new Set<number>()
  for (const entry of entries) {
    if (placed.has(entry.id)) continue
    const roles = [...tenureOf(t, entry)].reverse()
    for (const role of roles) {
      if (placed.has(role.id)) continue
      placed.add(role.id)
      out.push(role)
    }
  }
  return out
}

/** Mirror of the backend's `normalize_company_name`: "Acme Sp. z o.o." -> "acme sp z o o". */
export function normalizeEmployer(name: string): string {
  return name
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .replace(/ł/g, 'l')
    .replace(/Ł/g, 'L')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

/**
 * The role a position being added or edited would continue with a transition: the latest earlier
 * position at the same employer (any position there while the start date is still blank).
 */
export function predecessorCandidate(
  entries: WorkHistoryEntry[],
  draft: { kind: string; employer: string; date_start: string },
  selfId?: number,
): WorkHistoryEntry | null {
  const key = normalizeEmployer(draft.employer)
  if (draft.kind !== 'job' || !key) return null
  let best: WorkHistoryEntry | null = null
  for (const entry of entries) {
    if (entry.kind !== 'job' || entry.id === selfId || normalizeEmployer(entry.employer) !== key) continue
    if (draft.date_start && entry.date_start >= draft.date_start) continue
    if (!best || byStart(best, entry) < 0) best = entry
  }
  return best
}

/** The day before an ISO date (`2024-03-01` -> `2024-02-29`): where a promotion ends the previous role. */
export function dayBefore(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() - 1)
  return d.toISOString().slice(0, 10)
}
