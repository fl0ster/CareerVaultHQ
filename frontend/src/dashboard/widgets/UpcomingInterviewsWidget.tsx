import { CalendarClock } from 'lucide-react'
import { serverDate } from '../../applications/api.ts'
import { pageHref } from '../../shell/nav.ts'
import type { UpcomingRound } from '../api.ts'
import Widget from '../Widget.tsx'

function when(value: string): { day: string; time: string } {
  const d = serverDate(value)
  return {
    day: d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' }),
    time: d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }),
  }
}

/** The next scheduled interview rounds, each opening its application. */
export default function UpcomingInterviewsWidget({ rounds }: { rounds: UpcomingRound[] }) {
  return (
    <Widget title="Upcoming interviews" href={pageHref('interviews')}>
      {rounds.length === 0 ? (
        <p className="widget-empty">
          <CalendarClock size={18} aria-hidden />
          Nothing scheduled. Planned rounds with a date show up here.
        </p>
      ) : (
        <ul className="upcoming">
          {rounds.map((r) => {
            const { day, time } = when(r.scheduled_at)
            return (
              <li key={`${r.application_id}-${r.round}`}>
                <a href={pageHref('interviews', r.application_id)} className="upcoming-item">
                  <span className="upcoming-date">
                    <span>{day}</span>
                    <span className="widget-muted">{time}</span>
                  </span>
                  <span className="upcoming-what">
                    <span className="upcoming-company">{r.company ?? r.job_title ?? 'Unknown company'}</span>
                    <span className="widget-muted">
                      Round {r.round}
                      {r.title && ` · ${r.title}`}
                      {r.company && r.job_title && ` · ${r.job_title}`}
                    </span>
                  </span>
                </a>
              </li>
            )
          })}
        </ul>
      )}
    </Widget>
  )
}
