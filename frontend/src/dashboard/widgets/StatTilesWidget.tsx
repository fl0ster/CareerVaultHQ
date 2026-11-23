import { pageHref } from '../../shell/nav.ts'
import type { DashboardStats } from '../api.ts'

type Tile = { label: string; value: string; hint?: string; href?: string }

function tiles(s: DashboardStats): Tile[] {
  const rate = s.applied > 0 ? `${Math.round((s.responded / s.applied) * 100)}%` : '–'
  return [
    { label: 'Jobs to review', value: String(s.jobs_inbox), href: pageHref('jobs') },
    { label: 'Active applications', value: String(s.active), href: pageHref('applications') },
    { label: 'In interviews', value: String(s.interviews), href: pageHref('interviews') },
    { label: 'Offers', value: String(s.offers), href: pageHref('offers') },
    { label: 'Response rate', value: rate, hint: `${s.responded} of ${s.applied} applied heard back` },
  ]
}

/** Headline numbers, each linking to the page it counts. */
export default function StatTilesWidget({ stats }: { stats: DashboardStats }) {
  return (
    <section className="stat-tiles" aria-label="At a glance">
      {tiles(stats).map((t) => {
        const body = (
          <>
            <span className="stat-value">{t.value}</span>
            <span className="stat-label">{t.label}</span>
            {t.hint && <span className="stat-hint">{t.hint}</span>}
          </>
        )
        return t.href ? (
          <a key={t.label} className="stat-tile" href={t.href}>
            {body}
          </a>
        ) : (
          <div key={t.label} className="stat-tile">
            {body}
          </div>
        )
      })}
    </section>
  )
}
