import { Check } from 'lucide-react'
import { type Application, formatDuration, isFinalStatus, roundLabel, serverDate } from '../applications/api.ts'
import { type Round, formatShortDay } from './interviewRounds.ts'

type Props = {
  application: Application
  rounds: Round[]
  current: Round | null
}

/** The interview rounds top to bottom: held rounds checked, the current one ringed, the rest
 * still to come. */
export default function InterviewStepper({ application, rounds, current }: Props) {
  const final = isFinalStatus(application.status) ? application.status!.key.toLowerCase() : null
  const heldCount = rounds.filter((r) => r.held).length
  const summary = `${heldCount} of ${rounds.length} interview rounds held`

  return (
    <ol className={`iv-stepper${final ? ` ${final}` : ''}`} aria-label={summary}>
      {rounds.map((round) => {
        const isCurrent = round === current
        const state = isCurrent ? 'current' : round.held ? 'held' : 'upcoming'
        const when = round.event.occurred_at ? formatShortDay(serverDate(round.event.occurred_at)) : null
        const label = roundLabel(round.event, round.index)
        const hint = [label, formatDuration(round.event.duration_minutes), round.held ? 'held' : 'planned', when]
          .filter(Boolean)
          .join(' · ')
        return (
          <li key={round.event.id} className={`iv-step ${state}${round.held ? ' done' : ''}`} title={hint}>
            <span className="iv-step-dot" aria-hidden="true">
              {round.held && !isCurrent ? <Check size={12} strokeWidth={3} /> : round.index + 1}
            </span>
            <span className="iv-step-label">
              <span className="iv-step-name">{label}</span>
              <span className="iv-step-when">{when ?? (round.held ? 'held' : 'not scheduled')}</span>
            </span>
            {isCurrent && <span className="sr-only">(current step)</span>}
          </li>
        )
      })}
    </ol>
  )
}
