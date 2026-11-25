import { describeError } from '../cv/api.ts'
import {
  type Application,
  type ApplicationStatus,
  applicationsApi,
  currentEvent,
  isAutoEvent,
  nextRoundLabel,
} from './api.ts'
import StatusBadge from './StatusBadge.tsx'

type Props = {
  application: Application
  statuses: ApplicationStatus[]
  onChange: (updated: Application) => void
  onError: (message: string) => void
}

/** A list row's status badge, which also changes the status. */
export default function ApplicationStatusControl({ application: a, statuses, onChange, onError }: Props) {
  return (
    <StatusBadge
      status={a.status}
      auto={isAutoEvent(currentEvent(a))}
      nextRound={nextRoundLabel(a)}
      roundTitle={currentEvent(a)?.title}
      statuses={statuses}
      onSelect={(key) =>
        applicationsApi
          .addEvent(a.id, { status: key })
          .then(onChange)
          .catch((e) => onError(`Could not change status: ${describeError(e)}`))
      }
    />
  )
}
