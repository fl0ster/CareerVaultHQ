import { useLayoutEffect, useRef, useState } from 'react'
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

  // The list never sets the card's height, so long ones are cut off (and fade out there).
  // Then it starts at the current round, so it and the ones after it show first.
  const listRef = useRef<HTMLOListElement>(null)
  const currentRef = useRef<HTMLLIElement>(null)
  const [cut, setCut] = useState({ top: false, bottom: false })
  const currentId = current?.event.id
  useLayoutEffect(() => {
    const list = listRef.current
    if (!list) return
    const fit = () => {
      const step = currentRef.current
      list.scrollTop = 0
      if (step && list.scrollHeight > list.clientHeight) {
        const ring = 4
        list.scrollTop = step.getBoundingClientRect().top - list.getBoundingClientRect().top - ring
      }
      const top = list.scrollTop > 0
      const bottom = list.scrollTop + list.clientHeight < list.scrollHeight - 1
      setCut((prev) => (prev.top === top && prev.bottom === bottom ? prev : { top, bottom }))
    }
    fit()
    // The height follows the current step beside it (e.g. its notes box being resized).
    const observer = new ResizeObserver(fit)
    observer.observe(list)
    return () => observer.disconnect()
  }, [currentId, rounds.length])

  return (
    <ol
      ref={listRef}
      className={`iv-stepper${final ? ` ${final}` : ''}${cut.top ? ' cut-top' : ''}${cut.bottom ? ' cut-bottom' : ''}`} aria-label={summary}>
      {rounds.map((round) => {
        const isCurrent = round === current
        const state = isCurrent ? 'current' : round.held ? 'held' : 'upcoming'
        const when = round.event.occurred_at ? formatShortDay(serverDate(round.event.occurred_at)) : null
        const label = roundLabel(round.event, round.index)
        const hint = [label, formatDuration(round.event.duration_minutes), round.held ? 'held' : 'planned', when]
          .filter(Boolean)
          .join(' · ')
        return (
          <li
            key={round.event.id}
            ref={isCurrent ? currentRef : undefined}
            className={`iv-step is-${state}${round.held ? ' is-done' : ''}`} title={hint}>
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
