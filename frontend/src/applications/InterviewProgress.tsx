import { type Application, formatDuration, heldRounds, isFinalStatus, roundLabel } from './api.ts'

/**
 * One segment per interview round: filled when held, dashed while planned (the next one
 * highlighted). Green after an offer, red after a rejection, grey once closed. Nothing without rounds.
 */
export default function InterviewProgress({ application, compact = false }: { application: Application; compact?: boolean }) {
  const held = heldRounds(application).length
  const rounds = [...heldRounds(application), ...application.planned_events]
  if (rounds.length === 0) return null
  const final = isFinalStatus(application.status) ? application.status!.key.toLowerCase() : null
  const summary = `${held} / ${rounds.length} interview rounds${final ? ` (${final})` : ''}`

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
        {rounds.map((round, i) => {
          const state = i < held ? 'held' : final ? 'not held' : 'planned'
          const duration = formatDuration(round.duration_minutes)
          return (
            <span
              key={round.id}
              className={`interview-progress-seg ${i < held ? 'held' : 'planned'}${!final && i === held ? ' next' : ''}`}
              title={[roundLabel(round, i), duration, state].filter(Boolean).join(' · ')}
            />
          )
        })}
      </span>
      {!compact && (
        <span className="interview-progress-text">
          {held}/{rounds.length}
        </span>
      )}
    </span>
  )
}
