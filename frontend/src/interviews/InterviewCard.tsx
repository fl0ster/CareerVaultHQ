import { useState } from 'react'
import { CalendarClock, ChevronRight } from 'lucide-react'
import { describeError } from '../cv/api.ts'
import {
  type Application,
  type ApplicationStatus,
  applicationsApi,
  formatDuration,
  roundLabel,
  serverDate,
} from '../applications/api.ts'
import ApplicationStatusControl from '../applications/ApplicationStatusControl.tsx'
import { CompanyTagBadge } from '../companies/CompanyTag.tsx'
import InterviewStepper from './InterviewStepper.tsx'
import { type Round, formatWhen, interviewRounds, relativeDay } from './interviewRounds.ts'

type Props = {
  application: Application
  statuses: ApplicationStatus[]
  onOpen: (id: number) => void
  onOpenCompany: (id: number) => void
  onChange: (updated: Application) => void
}

/** An application in the interview stage: the round it is at, its notes, and the way through
 * the rounds to the offer. */
export default function InterviewCard({ application: a, statuses, onOpen, onOpenCompany, onChange }: Props) {
  const { rounds, current } = interviewRounds(a)
  // Requests in flight (a note save can still be running when Mark held is clicked).
  const [inFlight, setInFlight] = useState(0)
  const busy = inFlight > 0
  const [error, setError] = useState<string | null>(null)

  const run = async (fn: () => Promise<Application>) => {
    setInFlight((n) => n + 1)
    setError(null)
    try {
      onChange(await fn())
      return true
    } catch (e) {
      setError(describeError(e))
      return false
    } finally {
      setInFlight((n) => n - 1)
    }
  }

  return (
    <article className="iv-card">
      <header className="iv-card-head">
        <div className="iv-card-title">
          <button type="button" className="iv-card-job" onClick={() => onOpen(a.id)}>
            {a.job.title ?? a.job.link}
          </button>
          <div className="iv-card-meta">
            {a.job.company && (
              <CompanyTagBadge
                companyId={a.job.company_id}
                tag={a.job.company_tag}
                name={a.job.company}
                onOpenCompany={onOpenCompany}
              />
            )}
          </div>
        </div>
        <div className="iv-card-head-actions">
          <button type="button" className="secondary iv-card-details" onClick={() => onOpen(a.id)}>
            Details <ChevronRight size={16} aria-hidden="true" />
          </button>
          <ApplicationStatusControl application={a} statuses={statuses} onChange={onChange} onError={setError} />
        </div>
      </header>

      <div className="iv-card-body">
        <div className="iv-card-side">
          {rounds.length > 0 && (
            <div className="iv-stepper-wrap">
              <InterviewStepper application={a} rounds={rounds} current={current} />
            </div>
          )}
        </div>
        {current ? (
          <CurrentStep
            key={current.event.id}
            application={a}
            round={current}
            total={rounds.length}
            busy={busy}
            onSaveNote={(note) => run(() => applicationsApi.updateEvent(a.id, current.event.id, { note }))}
          />
        ) : (
          <p className="iv-current muted">No interview round to show.</p>
        )}
      </div>

      {error && <p className="error">{error}</p>}

    </article>
  )
}

function CurrentStep({
  application,
  round,
  total,
  busy,
  onSaveNote,
}: {
  application: Application
  round: Round
  total: number
  busy: boolean
  onSaveNote: (note: string) => Promise<boolean>
}) {
  const { event } = round
  const [note, setNote] = useState(event.note)
  const [saved, setSaved] = useState(false)
  const when = event.occurred_at ? serverDate(event.occurred_at) : null
  const duration = formatDuration(event.duration_minutes)
  const kind = event.title || null

  const saveNote = () => {
    if (note === event.note) return
    void onSaveNote(note).then(setSaved)
  }

  return (
    <section className={`iv-current${round.held ? ' held' : ''}`} aria-label="Current interview step">
      <div className="iv-current-head">
        <span className="iv-current-eyebrow">
          {round.held ? 'Last round' : 'Next round'} · {round.index + 1} of {total}
        </span>
        <span className="iv-current-name">{kind ?? roundLabel(event, round.index)}</span>
      </div>
      <p className="iv-current-when">
        <CalendarClock size={14} aria-hidden="true" />
        {when ? (
          <>
            <span>{formatWhen(when)}</span>
            <span className="muted">({relativeDay(when)})</span>
          </>
        ) : (
          <span className="muted">Not scheduled</span>
        )}
        {duration && <span className="muted">· {duration}</span>}
      </p>
      <label className="iv-current-notes">
        <span className="sr-only">Notes for round {round.index + 1} at {application.job.company ?? 'this company'}</span>
        <textarea
          value={note}
          onChange={(e) => {
            setNote(e.target.value)
            setSaved(false)
          }}
          onBlur={saveNote}
          placeholder={round.held ? 'How did it go?' : 'Prep notes: who you meet, topics, questions to ask…'}
          rows={6}
          disabled={busy}
        />
        <span className="iv-saved muted" aria-live="polite">
          {busy ? 'Saving…' : saved ? 'Saved' : ''}
        </span>
      </label>
    </section>
  )
}
