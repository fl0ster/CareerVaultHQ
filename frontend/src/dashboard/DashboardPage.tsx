import type { ComponentType } from 'react'
import './dashboard.css'
import type { DashboardStats } from './api.ts'
import type { Setup } from '../shell/useSetup.ts'
import Onboarding from './Onboarding.tsx'
import { useDashboardStats } from './useDashboardStats.ts'
import SankeyWidget from './widgets/SankeyWidget.tsx'
import StatTilesWidget from './widgets/StatTilesWidget.tsx'
import UpcomingInterviewsWidget from './widgets/UpcomingInterviewsWidget.tsx'
import WeeklyActivityWidget from './widgets/WeeklyActivityWidget.tsx'

/** The dashboard's widgets, in display order. Each takes the shared stats and picks what it
 * needs; add a widget by appending it here. */
const WIDGETS: { id: string; Component: ComponentType<{ stats: DashboardStats }> }[] = [
  { id: 'stats', Component: StatTilesWidget },
  { id: 'flow', Component: ({ stats }) => <SankeyWidget flow={stats.flow} /> },
  { id: 'weekly', Component: ({ stats }) => <WeeklyActivityWidget weeks={stats.weekly_applied} /> },
  { id: 'upcoming', Component: ({ stats }) => <UpcomingInterviewsWidget rounds={stats.upcoming} /> },
]

type Props = {
  /** First-run checklist (see `useSetup`): shown instead of the widgets until it is complete. */
  setup: Setup | null | undefined
}

/** The home page: widgets summarising the job search, or the setup checklist on a fresh install. */
export default function DashboardPage({ setup }: Props) {
  const { stats, error } = useDashboardStats()
  if (setup && !setup.complete) return <Onboarding setup={setup} />
  if (!stats || setup === undefined) {
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
