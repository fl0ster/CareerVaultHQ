import { type Application, formatDuration, interviewRounds, isFinalStatus, roundLabel } from './api.ts'

type Props = {
  application: Application
  /** Smaller variant for list rows. */
  compact?: boolean
}

/**
 * Interview progress of an application with a plan (`interview_rounds` set): one segment per
 * round, filled when held, dashed while planned. Renders nothing without a plan.
 */
export default function InterviewProgress({ application, compact = false }: Props) {
  if (application.interview_rounds == null) return null
  const rounds = interviewRounds(application)
  const held = rounds.filter((r) => r.held).length
  const final = isFinalStatus(application.status) ? application.status!.key.toLowerCase() : null
  const summary = `${held} / ${rounds.length} interview rounds${
    final === 'rejected' ? ' (rejected)' : final === 'offer' ? ' (offer)' : ''
  }`

  return (
    <span
      className={`interview-progress${compact ? ' compact' : ''}${final ? ` ${final}` : ''}`}
      role="meter"
      aria-valuemin={0}
      aria-valuemax={rounds.length}
      aria-valuenow={held}
      aria-label={summary}
      title={summary}
    >
      <span className="interview-progress-track">
        {rounds.map(({ event, held: done }, i) => {
          const next = !done && !final && i === held
          const duration = formatDuration(event.duration_minutes)
          return (
            <span
              key={event.id}
              className={`interview-progress-seg${done ? ' held' : ' planned'}${next ? ' next' : ''}`}
              title={`${roundLabel(event, i)}${duration ? ` · ${duration}` : ''}${
                done ? ' · held' : final ? ' · not held' : ' · planned'
              }`}
            />
          )
        })}
      </span>
      <span className="interview-progress-text">
        {held}/{rounds.length}
      </span>
    </span>
  )
}
