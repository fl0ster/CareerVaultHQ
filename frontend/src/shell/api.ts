/** The numbers behind the menu badges, from one cheap request. */
export type NavCounts = {
  /** Undecided relevant jobs (the Jobs inbox). */
  jobs_inbox: number
  applications: number
  /** Applications currently in the interview stage. */
  interviews: number
  /** Applications currently with an offer. */
  offers: number
  /** Entries in the work history (My Career). */
  work_history: number
  /** Positions held now (started, no end date). */
  employment: number
}

export const navApi = {
  counts: async (signal?: AbortSignal): Promise<NavCounts> => {
    const res = await fetch('/api/nav/counts', { signal })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return (await res.json()) as NavCounts
  },
}
