import type { EntryKind, Transition, WorkHistoryEntry, WorkHistoryInput } from './api.ts'
import { KINDS } from './kinds.ts'

/** Editable form state of a career event; shared by the edit form and the add composer. */
export type Draft = {
  kind: EntryKind
  date_start: string
  date_end: string
  /** No end date: a current position / ongoing education, or a single-date certificate. */
  current: boolean
  employer: string
  role: string
  location: string
  tech: string
  context: string
  /** A promotion / role change within the employer of the previous position; '' for a new employment. */
  transition: '' | Transition
}

export function toDraft(entry?: WorkHistoryEntry): Draft {
  return {
    kind: entry?.kind ?? 'job',
    date_start: entry?.date_start ?? '',
    date_end: entry?.date_end ?? '',
    current: entry ? entry.date_end === null : false,
    employer: entry?.employer ?? '',
    role: entry?.role ?? '',
    location: entry?.location ?? '',
    tech: entry?.tech.join(', ') ?? '',
    context: entry?.context ?? '',
    transition: entry?.transition ?? '',
  }
}

/** A draft of the role that follows `entry` at its employer: same employer, location and
 * technologies, a promotion, current; the title and start date are left to fill in. */
export function nextRoleDraft(entry: WorkHistoryEntry): Draft {
  return {
    ...toDraft(),
    employer: entry.employer,
    location: entry.location ?? '',
    tech: entry.tech.join(', '),
    current: true,
    transition: 'promotion',
  }
}

/**
 * The draft switched to another kind. A certificate without an end date defaults to a
 * single date; leaving the certificate kind does not turn that into a current position.
 */
export function withKind(d: Draft, kind: EntryKind): Draft {
  if (kind === d.kind) return d
  const current = kind === 'certificate' ? !d.date_end : d.kind === 'certificate' ? false : d.current
  return { ...d, kind, current }
}

export function toInput(d: Draft): WorkHistoryInput {
  const info = KINDS[d.kind]
  return {
    kind: d.kind,
    date_start: d.date_start,
    date_end: d.current || !d.date_end ? null : d.date_end,
    employer: d.employer.trim(),
    role: d.role.trim(),
    location: info.showLocation ? d.location.trim() || null : null,
    tech: info.showTech ? d.tech.split(/[,\n]/).map((t) => t.trim()).filter(Boolean) : [],
    context: d.context.trim() || null,
    transition: d.kind === 'job' && d.transition ? d.transition : null,
  }
}

/** All required fields are filled in. */
export function draftReady(d: Draft): boolean {
  return !!d.role.trim() && !!d.date_start && (!KINDS[d.kind].organisationRequired || !!d.employer.trim())
}

/** Client-side validation message, or null when the draft can be submitted. */
export function draftError(d: Draft): string | null {
  if (!d.current && d.date_end && d.date_end < d.date_start) return 'End date must not be earlier than start date.'
  return null
}
