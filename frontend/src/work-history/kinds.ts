import { Award, BriefcaseBusiness, GraduationCap, type LucideIcon } from 'lucide-react'
import type { EntryKind, WorkHistoryEntry } from './api.ts'

/*
 * The three kinds of career events on My Career: a position, an education entry and a
 * certificate. They share one record (`role` = title, `employer` = organisation, `context` =
 * details); this table holds what differs per kind: labels, icon and which fields apply.
 */

export type KindInfo = {
  /** Option label of the kind switch and the legend. */
  label: string
  /** "position" in "New position", "Add position", "3 positions". */
  noun: string
  plural: string
  icon: LucideIcon
  /** Label of `role`. */
  title: string
  titlePlaceholder: string
  /** Label of `employer`. */
  organisation: string
  organisationPlaceholder: string
  organisationRequired: boolean
  /** Label of the checkbox that clears the end date. */
  openEnded: string
  /** Shorter version for the compose window. */
  openEndedShort: string
  showLocation: boolean
  showTech: boolean
  contextLabel: string
  contextPlaceholder: string
}

export const KIND_ORDER: readonly EntryKind[] = ['job', 'education', 'certificate']

export const KINDS: Record<EntryKind, KindInfo> = {
  job: {
    label: 'Job',
    noun: 'position',
    plural: 'positions',
    icon: BriefcaseBusiness,
    title: 'Role',
    titlePlaceholder: 'Role',
    organisation: 'Employer',
    organisationPlaceholder: 'Employer',
    organisationRequired: true,
    openEnded: 'Current position',
    openEndedShort: 'Current',
    showLocation: true,
    showTech: true,
    contextLabel: 'Context',
    contextPlaceholder: 'What you did: achievements, team, scope…',
  },
  education: {
    label: 'Education',
    noun: 'education',
    plural: 'education',
    icon: GraduationCap,
    title: 'Degree',
    titlePlaceholder: 'Degree and field of study',
    organisation: 'Institution',
    organisationPlaceholder: 'School or university',
    organisationRequired: false,
    openEnded: 'Currently studying',
    openEndedShort: 'Ongoing',
    showLocation: true,
    showTech: false,
    contextLabel: 'Notes',
    contextPlaceholder: 'Thesis, grade, specialisation…',
  },
  certificate: {
    label: 'Certificate',
    noun: 'certificate',
    plural: 'certificates',
    icon: Award,
    title: 'Certificate',
    titlePlaceholder: 'Certificate or course name',
    organisation: 'Issuer',
    organisationPlaceholder: 'Issuer (optional)',
    organisationRequired: false,
    openEnded: 'Single date (no duration)',
    openEndedShort: 'Single date',
    showLocation: false,
    showTech: false,
    contextLabel: 'Notes',
    contextPlaceholder: 'Credential ID, score, what it covered…',
  },
}

/** A certificate without an end date: a single point on the timeline, not a span. */
export const isPoint = (entry: Pick<WorkHistoryEntry, 'kind' | 'date_end'>) =>
  entry.kind === 'certificate' && entry.date_end === null

/** "Backend Developer at Acme", "MSc Physics at MIT", "CKA · CNCF". */
export function entryTitle(entry: Pick<WorkHistoryEntry, 'kind' | 'role' | 'employer'>): string {
  if (!entry.employer) return entry.role
  return entry.kind === 'certificate' ? `${entry.role} · ${entry.employer}` : `${entry.role} at ${entry.employer}`
}

/** "1 position", "2 certificates", "3 education entries". */
export function countLabel(count: number, kind: EntryKind): string {
  const info = KINDS[kind]
  if (kind === 'education') return `${count} education ${count === 1 ? 'entry' : 'entries'}`
  return `${count} ${count === 1 ? info.noun : info.plural}`
}
