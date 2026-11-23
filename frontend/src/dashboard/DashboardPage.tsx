import type { ComponentType } from 'react'
import './dashboard.css'
import type { DashboardStats } from './api.ts'
import { useDashboardStats } from './useDashboardStats.ts'
import FunnelWidget from './widgets/FunnelWidget.tsx'
import StatTilesWidget from './widgets/StatTilesWidget.tsx'
import UpcomingInterviewsWidget from './widgets/UpcomingInterviewsWidget.tsx'
import WeeklyActivityWidget from './widgets/WeeklyActivityWidget.tsx'

/** The dashboard's widgets, in display order. Each takes the shared stats and picks what it
 * needs; add a widget by appending it here. */
const WIDGETS: { id: string; Component: ComponentType<{ stats: DashboardStats }> }[] = [
  { id: 'stats', Component: StatTilesWidget },
  { id: 'funnel', Component: ({ stats }) => <FunnelWidget funnel={stats.funnel} /> },
  { id: 'weekly', Component: ({ stats }) => <WeeklyActivityWidget weeks={stats.weekly_applied} /> },
  { id: 'upcoming', Component: ({ stats }) => <UpcomingInterviewsWidget rounds={stats.upcoming} /> },
]

/** The home page: widgets summarising the job search. */
export default function DashboardPage() {
  const { stats, error } = useDashboardStats()
  if (!stats) {
    return error ? (
      <p className="dashboard-error" role="alert">
        Could not load the dashboard: {error}
      </p>
    ) : (
      <div className="dashboard" aria-busy="true">
        {WIDGETS.map((w) => (
          <div key={w.id} className={`widget widget--skeleton widget--${w.id}`} />
        ))}
      </div>
    )
  }
  return (
    <div className="dashboard">
      {WIDGETS.map(({ id, Component }) => (
        <Component key={id} stats={stats} />
      ))}
    </div>
  )
}
