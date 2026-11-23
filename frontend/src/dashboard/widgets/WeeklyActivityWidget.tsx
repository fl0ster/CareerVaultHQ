import type { WeekCount } from '../api.ts'
import Widget from '../Widget.tsx'

const weekLabel = (start: string) =>
  new Date(`${start}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })

/** Applications sent per week over the last few weeks, this week last. */
export default function WeeklyActivityWidget({ weeks }: { weeks: WeekCount[] }) {
  const max = Math.max(1, ...weeks.map((w) => w.count))
  const total = weeks.reduce((sum, w) => sum + w.count, 0)
  const thisWeek = weeks[weeks.length - 1]?.count ?? 0
  return (
    <Widget title="Applications sent" span={2}>
      <p className="widget-headline">
        <strong>{thisWeek}</strong> this week{' '}
        <span className="widget-muted">
          · {total} in {weeks.length} weeks
        </span>
      </p>
      <ul className="weekly">
        {weeks.map((w, i) => (
          <li
            key={w.week_start}
            className="weekly-col"
            tabIndex={0}
            aria-label={`Week of ${weekLabel(w.week_start)}: ${w.count} sent`}
          >
            <span className="weekly-tip" aria-hidden>
              {w.count}
            </span>
            <span className="weekly-plot" aria-hidden>
              <span
                className={`weekly-bar${w.count === 0 ? ' weekly-bar--empty' : ''}`}
                style={{ height: `${(w.count / max) * 100}%` }}
              />
            </span>
            <span className="weekly-x" aria-hidden>
              {/* Every other week, always including this one. */}
              {(weeks.length - 1 - i) % 2 === 0 ? weekLabel(w.week_start) : ''}
            </span>
          </li>
        ))}
      </ul>
    </Widget>
  )
}
