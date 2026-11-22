import { createStore } from '../shell/store.ts'
import { type CandidateDetails, candidateDetailsApi } from './api.ts'

/**
 * The saved candidate details, shared by the side menu's profile card and the About me form
 * so a save shows up in the card straight away. `undefined` until loaded, `null` when nothing
 * was saved yet.
 */
export const candidateDetailsStore = createStore<CandidateDetails | null | undefined>(undefined)

let loading: Promise<CandidateDetails | null> | null = null

/** Loads the details once; later calls reuse the result (or the request in flight). */
export function loadCandidateDetails(): Promise<CandidateDetails | null> {
  loading ??= candidateDetailsApi.get().then(
    (d) => {
      candidateDetailsStore.set(d)
      return d
    },
    (e) => {
      loading = null
      throw e
    },
  )
  return loading
}

/** Fields that must be filled for the profile to count as set up (the starred form fields). */
export const REQUIRED_FIELDS = ['first_name', 'last_name'] as const satisfies readonly (keyof CandidateDetails)[]

export type RequiredValues = Pick<CandidateDetails, (typeof REQUIRED_FIELDS)[number]>

/**
 * The required fields as currently typed into the About me form (before saving), so the
 * menu's setup progress follows along. `null` while the form is not open.
 */
export const candidateDraftStore = createStore<RequiredValues | null>(null)

export const isProfileComplete = (d: RequiredValues | null | undefined) =>
  !!d && REQUIRED_FIELDS.every((f) => d[f].trim() !== '')

/**
 * Setup progress in segments: one per required field plus a starting segment that is always
 * filled, so the bar never looks empty.
 */
export function setupProgress(d: RequiredValues | null | undefined): { filled: number; total: number } {
  const done = d ? REQUIRED_FIELDS.filter((f) => d[f].trim() !== '').length : 0
  return { filled: done + 1, total: REQUIRED_FIELDS.length + 1 }
}
