import type { WorkHistoryEntry, WorkHistoryInput } from './api.ts'

/** Editable form state of a position; shared by the edit form and the add-position composer. */
export type Draft = {
  date_start: string
  date_end: string
  current: boolean
  employer: string
  role: string
  location: string
  tech: string
  context: string
}

export function toDraft(entry?: WorkHistoryEntry): Draft {
  return {
    date_start: entry?.date_start ?? '',
    date_end: entry?.date_end ?? '',
    current: entry ? entry.date_end === null : false,
    employer: entry?.employer ?? '',
    role: entry?.role ?? '',
    location: entry?.location ?? '',
    tech: entry?.tech.join(', ') ?? '',
    context: entry?.context ?? '',
  }
}

export function toInput(d: Draft): WorkHistoryInput {
  return {
    date_start: d.date_start,
    date_end: d.current || !d.date_end ? null : d.date_end,
    employer: d.employer.trim(),
    role: d.role.trim(),
    location: d.location.trim() || null,
    tech: d.tech.split(/[,\n]/).map((t) => t.trim()).filter(Boolean),
    context: d.context.trim() || null,
  }
}

/** Client-side validation message, or null when the draft can be submitted. */
export function draftError(d: Draft): string | null {
  if (!d.current && d.date_end && d.date_end < d.date_start) return 'End date must not be earlier than start date.'
  return null
}
