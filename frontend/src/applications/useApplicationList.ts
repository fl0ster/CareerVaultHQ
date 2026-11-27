import { type Dispatch, type SetStateAction, useCallback, useEffect, useState } from 'react'
import { describeError, isInProgress, isTailoring } from '../cv/api.ts'
import {
  APPLICATIONS_CHANGED,
  type Application,
  type ApplicationStatus,
  ACCEPTED_STATUS,
  DECLINED_STATUS,
  OFFER_STATUS,
  applicationsApi,
  notifyApplicationsChanged,
} from './api.ts'
import type { EvaluatedJobDetail } from '../jobs/api.ts'
import type { Crumb } from '../shell/nav.ts'
import { useDetailScroll } from '../shell/useDetailScroll.ts'

const PAGE_SIZE = 200
const CV_POLL_MS = 3000
const SEARCH_MIN_CHARS = 3
const SEARCH_DEBOUNCE_MS = 300

export type ApplicationListOptions = {
  /** Status key the list is limited to, or undefined for every status. */
  status: string | undefined
  /** Id of the application shown in place of the list (from the URL), or null for the list. */
  detailId: string | null
  /** Changes when the menu counts change (possibly through a background task, e.g. the
   * Gmail monitor); the list is refetched then. Empty until the counts are known. */
  version: string
  /** Leaves the open application (used by the pages' back button, not by the hook). */
  onBack: () => void
  /** Breadcrumb entries after the page name while a detail is open. */
  onCrumbsChange: (crumbs: Crumb[]) => void
}

export type ApplicationList = {
  applications: Application[] | null
  setApplications: Dispatch<SetStateAction<Application[] | null>>
  statuses: ApplicationStatus[]
  error: string | null
  setError: (error: string | null) => void
  searchInput: string
  setSearchInput: (value: string) => void
  /** The term actually sent to the API: debounced, and empty until it has enough characters. */
  search: string
  detailOpen: boolean
  openId: number | null
  selected: Application | null
  detailError: string | null
  /** Bumped when an application reaches the offer stage from this page; replays the confetti. */
  celebrations: number
  /** How many listed applications have each status key. */
  counts: Map<string, number>
  /** An application changed on this page. */
  replace: (updated: Application) => void
  /** An offer was accepted from the open application, which stays on screen. */
  acceptedInView: (updated: Application) => void
  /** The application's job was re-scored from its relevance meter. */
  rescored: (fresh: EvaluatedJobDetail) => void
}

/** Loading, refreshing and updating a list of applications plus the one open in place of it.
 * Shared by the Applications, Interviews and Offers pages. */
export function useApplicationList({
  status,
  detailId,
  version,
  onCrumbsChange,
}: ApplicationListOptions): ApplicationList {
  const [applications, setApplications] = useState<Application[] | null>(null)
  const [statuses, setStatuses] = useState<ApplicationStatus[]>([])
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  // The open application. Kept as its own object (fetched by id) so the view stays put even
  // when the application is not in the current list (filter, search, a deep link).
  const openId = detailId != null && /^\d+$/.test(detailId) ? Number(detailId) : null
  const [selected, setSelected] = useState<Application | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [shownId, setShownId] = useState<number | null>(null)
  if (openId !== shownId) {
    // Show the list's copy right away; the fetch below brings the full, fresh one.
    setShownId(openId)
    setSelected(openId == null ? null : (applications?.find((a) => a.id === openId) ?? null))
    setDetailError(null)
  }
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  const reload = useCallback(() => setTick((t) => t + 1), [])
  const detailOpen = detailId != null
  useDetailScroll(detailOpen)

  // The page mounts (and loads) on entry; while it is open, a change in the menu counts
  // means applications changed somewhere else, so refetch. The counts arriving for the
  // first time is not a change.
  const [seenVersion, setSeenVersion] = useState(version)
  if (version !== seenVersion) {
    setSeenVersion(version)
    if (seenVersion !== '') setTick((t) => t + 1)
  }

  const rescored = (fresh: EvaluatedJobDetail) => {
    const score = fresh.evaluation
    if (!score) return
    const update = (a: Application): Application =>
      a.job.id === fresh.id
        ? {
            ...a,
            evaluation: {
              id: score.id,
              candidate_profile_id: score.candidate_profile_id,
              relevance: score.relevance,
              outdated: score.outdated,
              explanation: score.explanation,
            },
          }
        : a
    setApplications((prev) => prev?.map(update) ?? prev)
    setSelected((prev) => (prev ? update(prev) : prev))
  }

  useEffect(() => {
    const controller = new AbortController()
    applicationsApi
      .statuses(controller.signal)
      .then(setStatuses)
      .catch((e) => {
        if (!controller.signal.aborted) setError(`Could not load statuses: ${describeError(e)}`)
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const term = searchInput.trim()
    const next = term.length >= SEARCH_MIN_CHARS ? term : ''
    const timer = window.setTimeout(() => setSearch(next), next ? SEARCH_DEBOUNCE_MS : 0)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    const controller = new AbortController()
    applicationsApi
      .list({ limit: PAGE_SIZE, status, q: search || undefined }, controller.signal)
      .then((page) => {
        setApplications(page.items)
        setError(null)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(`Could not load applications: ${describeError(e)}`)
      })
    return () => controller.abort()
  }, [status, search, tick])

  // The open application, refetched on every reload so it stays current wherever it was changed.
  useEffect(() => {
    if (openId == null) return
    const controller = new AbortController()
    applicationsApi
      .get(openId, controller.signal)
      .then((a) => {
        setSelected(a)
        setDetailError(null)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setDetailError(describeError(e))
      })
    return () => controller.abort()
  }, [openId, tick])

  const title = selected ? (selected.job.title ?? 'Untitled job') : null
  const placeholder = detailOpen && !selected ? (detailError || openId == null ? 'Not found' : 'Loading…') : null
  useEffect(() => {
    const crumbs: Crumb[] = []
    if (title !== null) crumbs.push({ label: title })
    else if (placeholder) crumbs.push({ label: placeholder })
    onCrumbsChange(crumbs)
  }, [title, placeholder, onCrumbsChange])

  // Applications created or changed elsewhere (e.g. from the job dialog).
  useEffect(() => {
    window.addEventListener(APPLICATIONS_CHANGED, reload)
    return () => window.removeEventListener(APPLICATIONS_CHANGED, reload)
  }, [reload])

  // Keep polling while a CV is being generated, or a moved role tailored for one.
  const pending =
    (applications?.some((a) => a.cv && isInProgress(a.cv)) ?? false) ||
    (selected?.cv != null && isInProgress(selected.cv)) ||
    isTailoring(selected?.cv_overrides)
  useEffect(() => {
    if (!pending) return
    const timer = window.setTimeout(reload, CV_POLL_MS)
    return () => window.clearTimeout(timer)
  }, [pending, tick, reload])

  const [celebrations, setCelebrations] = useState(0)

  const replace = (updated: Application) => {
    const before = selected?.id === updated.id ? selected : applications?.find((a) => a.id === updated.id)
    // Only moving forward into the offer stage celebrates; undoing a decline/accept
    // (back to OFFER) does not.
    const prior = before?.status?.key
    if (updated.status?.key === OFFER_STATUS && prior !== OFFER_STATUS && prior !== DECLINED_STATUS && prior !== ACCEPTED_STATUS) {
      setCelebrations((n) => n + 1)
    }
    setSelected((prev) => (prev?.id === updated.id ? updated : prev))
    setApplications((prev) => prev?.map((a) => (a.id === updated.id ? updated : a)) ?? prev)
    // The current status may have changed, which moves the application between the
    // Interviews / Offers pages and their menu counts.
    notifyApplicationsChanged()
  }

  const acceptedInView = (updated: Application) => {
    setCelebrations((n) => n + 1)
    replace(updated)
  }

  const counts = new Map<string, number>()
  for (const a of applications ?? []) {
    const key = a.status?.key ?? ''
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }

  return {
    applications,
    setApplications,
    statuses,
    error,
    setError,
    searchInput,
    setSearchInput,
    search,
    detailOpen,
    openId,
    selected,
    detailError,
    celebrations,
    counts,
    replace,
    acceptedInView,
    rescored,
  }
}

/** Props App gives each application list page (Applications, Interviews, Offers). */
export type ApplicationPageProps = Omit<ApplicationListOptions, 'status'> & {
  onOpen: (id: number) => void
}
