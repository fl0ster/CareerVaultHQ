import type { FunnelStage } from '../api.ts'
import Widget from '../Widget.tsx'

/** Share of `part` in `whole` as a whole percentage; empty when there is no base. */
function percent(part: number, whole: number): string {
  return whole > 0 ? `${Math.round((part / whole) * 100)}%` : ''
}

/** From scored jobs down to accepted offers: each stage's count, a bar scaled to the widest
 * stage, and how many of the previous stage made it this far. */
export default function FunnelWidget({ funnel }: { funnel: FunnelStage[] }) {
  const max = Math.max(1, ...funnel.map((s) => s.count))
  return (
    <Widget title="Job search funnel" span={2} href="#/applications" linkLabel="Applications">
      <ol className="funnel">
        {funnel.map((stage, i) => {
          const prev = funnel[i - 1]
          const step = prev ? percent(stage.count, prev.count) : ''
          const width = stage.count > 0 ? Math.max(1.5, (stage.count / max) * 100) : 0
          return (
            <li
              key={stage.key}
              className="funnel-row"
              title={prev && step ? `${stage.count} of ${prev.count} ${prev.label.toLowerCase()} (${step})` : undefined}
            >
              <span className="funnel-label">{stage.label}</span>
              <span className="funnel-track" aria-hidden>
                <span className="funnel-bar" style={{ width: `${width}%` }} />
              </span>
              <span className="funnel-count">{stage.count.toLocaleString()}</span>
              <span className="funnel-step">{step}</span>
            </li>
          )
        })}
      </ol>
    </Widget>
  )
}
