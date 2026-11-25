import { describeError } from '../cv/api.ts'
import {
  type Application,
  type ApplicationStatus,
  applicationsApi,
  currentEvent,
  heldRounds,
  INTERVIEW_STATUS,
  roundLabel,
  isAutoEvent,
  nextRoundLabel,
} from './api.ts'
import StatusBadge from './StatusBadge.tsx'
import { interviewRounds } from '../interviews/interviewRounds.ts'

type Props = {
  application: Application
  statuses: ApplicationStatus[]
  onChange: (updated: Application) => void
  onError: (message: string) => void
}

/** Label of the round the interview stepper highlights as current, so the pill matches it. */
function currentRoundLabel(a: Application): string | undefined {
  if (a.status?.key !== INTERVIEW_STATUS) return undefined
  const { current } = interviewRounds(a)
  return current ? roundLabel(current.event, current.index) : undefined
}

/** A list row's status badge, which also changes the status. */
export default function ApplicationStatusControl({ application: a, statuses, onChange, onError }: Props) {
  return (
    <StatusBadge
      status={a.status}
      auto={isAutoEvent(currentEvent(a))}
      nextRound={nextRoundLabel(a)}
      roundTitle={currentRoundLabel(a)}
      statuses={statuses}
      planRound={a.status?.key === INTERVIEW_STATUS && a.planned_events.length === 0}
      onSelect={(key) =>
        // In the interview stage without a planned round, a click first plans the next round;
        // the following click marks it as held.
        (key === INTERVIEW_STATUS && a.status?.key === INTERVIEW_STATUS && a.planned_events.length === 0
          ? applicationsApi.setInterviewRounds(a.id, heldRounds(a).length + 1)
          : applicationsApi.addEvent(a.id, { status: key })
        )
          .then(onChange)
          .catch((e) => onError(`Could not change status: ${describeError(e)}`))
      }
    />
  )
}
