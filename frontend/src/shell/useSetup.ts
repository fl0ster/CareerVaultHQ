import { useEffect, useState } from 'react'
import { candidateDetailsStore, isProfileComplete, loadCandidateDetails } from '../candidate-profile/store.ts'
import type { NavCounts } from './api.ts'
import type { PageId } from './nav.ts'
import { useStore } from './store.ts'

export type SetupStep = {
  id: 'install' | 'details' | 'career'
  label: string
  description: string
  done: boolean
  /** Where the step is done; null when there is nothing to do in the app. */
  page: PageId | null
}

export type Setup = {
  steps: SetupStep[]
  /** Steps done so far. */
  done: number
  complete: boolean
}

/**
 * The first-run checklist: personal details filled in and at least one entry in the work
 * history. Until both are there the dashboard shows the checklist and the menu its progress.
 *
 * `undefined` while the details or the counts are still loading, `null` when the details could
 * not be loaded (the app then behaves as if set up rather than nag on a guess).
 */
export function useSetup(counts: NavCounts | null): Setup | null | undefined {
  const details = useStore(candidateDetailsStore)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    loadCandidateDetails().then(
      () => setFailed(false),
      () => setFailed(true),
    )
  }, [])

  if (failed && details === undefined) return null
  if (details === undefined || counts === null) return undefined

  const steps: SetupStep[] = [
    {
      id: 'install',
      label: 'Install the portal',
      description: 'CareerVaultHQ is up and running.',
      done: true,
      page: null,
    },
    {
      id: 'details',
      label: 'Fill in your details',
      description: 'Your name and contact details, printed on every generated CV.',
      done: isProfileComplete(details),
      page: 'candidate-profile',
    },
    {
      id: 'career',
      label: 'Fill out your career',
      description: 'Add your positions, education and certificates, or import them from an existing CV.',
      done: counts.work_history > 0,
      page: 'work-history',
    },
  ]
  const done = steps.filter((s) => s.done).length
  return { steps, done, complete: done === steps.length }
}
