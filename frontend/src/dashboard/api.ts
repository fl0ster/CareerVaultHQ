/** `stage`: the search continues from it; the others are where flows end. */
export type FlowKind = 'stage' | 'drop' | 'rejected' | 'pending' | 'accepted'

export type FlowNode = {
  id: string
  label: string
  /** 0 = scored jobs; each stage one column further right. */
  column: number
  kind: FlowKind
}

export type FlowLink = { source: string; target: string; value: number }

/** Sankey graph of the search, from scored jobs to answered offers. */
export type Flow = { nodes: FlowNode[]; links: FlowLink[] }

export type WeekCount = {
  /** Monday of the week, `YYYY-MM-DD`. */
  week_start: string
  count: number
}

export type UpcomingRound = {
  application_id: number
  job_title: string | null
  company: string | null
  /** Kind of round ("Technical", ...); empty when not named. */
  title: string
  /** 1-based round number. */
  round: number
  scheduled_at: string
}

/** See `GET /api/dashboard/stats`. */
export type DashboardStats = {
  flow: Flow
  jobs_inbox: number
  /** Applications whose current state is not final. */
  active: number
  interviews: number
  offers: number
  /** Applied applications that heard back (interview, rejection or offer). */
  responded: number
  applied: number
  /** Applications sent per week, oldest first. */
  weekly_applied: WeekCount[]
  /** Scheduled interview rounds from now on, soonest first. */
  upcoming: UpcomingRound[]
}

export const dashboardApi = {
  stats: async (signal?: AbortSignal): Promise<DashboardStats> => {
    const res = await fetch('/api/dashboard/stats', { signal })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return (await res.json()) as DashboardStats
  },
}
