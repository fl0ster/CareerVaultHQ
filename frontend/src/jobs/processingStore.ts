import { createStore } from '../shell/store.ts'

/** A manually added job that is not parsed and scored yet. */
export type ProcessingJob = { jobId: number; title: string; company: string; error: string | null }

/** Manually added jobs still going through parse -> evaluate, newest first. Kept outside the
 * Jobs page so they are still listed (and followed) after leaving the page and coming back. */
export const processingStore = createStore<ProcessingJob[]>([])
