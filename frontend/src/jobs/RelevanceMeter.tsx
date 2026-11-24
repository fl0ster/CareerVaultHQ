import { type CSSProperties, type SyntheticEvent, useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { type EvaluatedJobDetail, jobsApi } from './api.ts'
import { describeError } from '../cv/api.ts'

/** How often a re-scored job is checked, in ms. */
const RESCORE_POLL_MS = 2_500
/** Give up waiting for a re-score after this long, in ms. */
const RESCORE_TIMEOUT_MS = 3 * 60_000
/** Width of the hover popup in px (keep in sync with `.relevance-tip` in jobs.css). */
const TIP_WIDTH = 240
/** Width of the popup holding a score explanation in px (`.relevance-tip.wide`). */
const TIP_WIDTH_WIDE = 320
/** Room the popup needs below the meter before it opens above it instead, in px. */
const TIP_ROOM_BELOW = 160
/** Gap between the meter and the popup, and the popup and the viewport edge, in px. */
const TIP_GAP = 8

/** Fixed-position style placing the popup under (or, near the bottom, above) `anchor`,
 * horizontally kept inside the viewport. */
function tipPosition(anchor: DOMRect, width: number): CSSProperties {
  const left = Math.max(TIP_GAP, Math.min(anchor.left - TIP_GAP, window.innerWidth - width - TIP_GAP))
  return anchor.bottom + TIP_ROOM_BELOW > window.innerHeight
    ? { left, bottom: window.innerHeight - anchor.top + TIP_GAP }
    : { left, top: anchor.bottom + TIP_GAP }
}

type Props = {
  relevance: number
  /** Scored against an earlier work history: drawn faded and hatched, and clickable to
   * re-score when `onRescored` is given. */
  outdated?: boolean
  /** The job the score belongs to (`jobs.id`). Makes the meter clickable: a current score
   * explains itself, an outdated one re-scores (with `onRescored`). */
  jobId?: number
  /** Called with the job once it is scored against the latest profile. */
  onRescored?: (job: EvaluatedJobDetail) => void
  /** The score's stored explanation, if one was generated already: shown on hover
   * straight away, without asking the server. */
  explanation?: string | null
}

/** Enqueue a re-score of `jobId` and poll the job until its score is current. */
async function rescoreJob(jobId: number, signal: AbortSignal): Promise<EvaluatedJobDetail> {
  await jobsApi.rescore(jobId)
  const deadline = Date.now() + RESCORE_TIMEOUT_MS
  for (;;) {
    const job = await jobsApi.get(jobId, signal)
    if (job.evaluation && !job.evaluation.outdated) return job
    if (Date.now() > deadline) throw new Error('re-scoring is taking too long, try again later')
    await new Promise((resolve) => window.setTimeout(resolve, RESCORE_POLL_MS))
    signal.throwIfAborted()
  }
}

/** Where the popup is shown and whether a click pinned it open (it then stays open when
 * the pointer leaves, until a click elsewhere, Escape, a scroll or a resize). */
type Tip = { style: CSSProperties; pinned: boolean }

/** The explanation fetched for the score `relevance`; a different score (re-scored job)
 * needs a new one. */
type Explanation = { relevance: number; text: string }

/** Diverging bar for a relevance in [-1, 1]: it grows right of the centre line above
 * the threshold and left of it below. No numbers; the exact value is in the tooltip.
 * An outdated score is drawn faded over a hatched track; clicking it re-scores the job.
 * Clicking a current score shows a short LLM-written explanation of it. */
export default function RelevanceMeter({
  relevance,
  outdated = false,
  jobId,
  onRescored,
  explanation: storedExplanation = null,
}: Props) {
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [explanation, setExplanation] = useState<Explanation | null>(null)
  /** The hover / pinned popup; `null` while it is closed. */
  const [tip, setTip] = useState<Tip | null>(null)
  const tipId = useId()
  const wrapperRef = useRef<HTMLSpanElement>(null)
  const controllerRef = useRef<AbortController | null>(null)
  useEffect(() => () => controllerRef.current?.abort(), [])

  // The popup is fixed to the viewport: close it as soon as anything scrolls or resizes.
  // A pinned popup also closes on Escape and on a click outside the meter.
  const tipOpen = tip !== null
  const tipPinned = tip?.pinned ?? false
  useEffect(() => {
    if (!tipOpen) return
    const close = () => setTip(null)
    const onPointerDown = (e: PointerEvent) => {
      if (!wrapperRef.current?.contains(e.target as Node)) close()
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    if (tipPinned) {
      document.addEventListener('pointerdown', onPointerDown, true)
      document.addEventListener('keydown', onKeyDown)
    }
    return () => {
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
      document.removeEventListener('pointerdown', onPointerDown, true)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [tipOpen, tipPinned])

  const value = Math.max(-1, Math.min(1, relevance))
  const width = `${Math.abs(value) * 50}%`
  const above = value > 0
  const label = above ? 'Above the relevance threshold' : value < 0 ? 'Below the relevance threshold' : 'At the relevance threshold'
  const score = `${label} (${value > 0 ? '+' : ''}${value.toFixed(2)})`

  const rescoreMode = outdated && jobId !== undefined && onRescored !== undefined
  const explainMode = !outdated && jobId !== undefined
  const explained = !explainMode
    ? null
    : explanation?.relevance === relevance
      ? explanation.text
      : storedExplanation

  const classes = ['relevance']
  if (above) classes.push('above')
  if (outdated) classes.push('outdated')
  if (running && rescoreMode) classes.push('rescoring')

  const meter = (
    <span
      className={classes.join(' ')}
      role="meter"
      aria-valuemin={-1}
      aria-valuemax={1}
      aria-valuenow={value}
      aria-label={outdated ? `${label}, scored against an earlier work history` : label}
      title={rescoreMode || explainMode ? undefined : outdated ? `${score}, scored against an earlier work history` : score}
    >
      <span className="relevance-fill" style={above ? { left: '50%', width } : { right: '50%', width }} />
    </span>
  )
  if (jobId === undefined || !(rescoreMode || explainMode)) return meter

  const rescore = async () => {
    if (running || !onRescored) return
    const controller = new AbortController()
    controllerRef.current = controller
    setRunning(true)
    setError(null)
    try {
      onRescored(await rescoreJob(jobId, controller.signal))
    } catch (e) {
      if (!controller.signal.aborted) setError(describeError(e))
    } finally {
      if (!controller.signal.aborted) setRunning(false)
    }
  }

  const explain = async () => {
    if (running || explained) return
    const controller = new AbortController()
    controllerRef.current = controller
    setRunning(true)
    setError(null)
    try {
      const { explanation: text } = await jobsApi.explain(jobId, controller.signal)
      setExplanation({ relevance, text })
    } catch (e) {
      if (!controller.signal.aborted) setError(describeError(e))
    } finally {
      if (!controller.signal.aborted) setRunning(false)
    }
  }

  const position = (el: HTMLElement) =>
    tipPosition(el.getBoundingClientRect(), explainMode ? TIP_WIDTH_WIDE : TIP_WIDTH)

  // A span rather than a <button>: the meter can sit inside a clickable row (itself a
  // button, e.g. on the Applications tab), so the click must not reach the row.
  const activate = (e: SyntheticEvent<HTMLElement>) => {
    e.stopPropagation()
    e.preventDefault()
    if (rescoreMode) {
      rescore()
      return
    }
    // A second click on a pinned explanation closes it.
    if (tip?.pinned) {
      setTip(null)
      return
    }
    setTip({ style: position(e.currentTarget), pinned: true })
    explain()
  }
  // The popup is portalled to <body>: list rows create stacking contexts (opacity,
  // transforms) that would otherwise clip it or paint over it.
  const openTip = (e: SyntheticEvent<HTMLElement>) => {
    const el = e.currentTarget
    setTip((current) => current ?? { style: position(el), pinned: false })
  }
  const closeUnpinnedTip = () => setTip((current) => (current?.pinned ? current : null))

  let tipContent
  if (rescoreMode) {
    tipContent = running ? (
      <>
        <strong>Re-evaluating…</strong>
        <span>Scoring this job against your updated career.</span>
      </>
    ) : error ? (
      <>
        <strong>Re-evaluation failed</strong>
        <span>{error}</span>
        <span className="relevance-tip-action">Click to try again</span>
      </>
    ) : (
      <>
        <strong>Career updated</strong>
        <span>This score is based on your previous work history.</span>
        <span className="relevance-tip-action">Click to re-evaluate now</span>
      </>
    )
  } else {
    tipContent = (
      <>
        <strong>{score}</strong>
        {explained ? (
          <span className="relevance-tip-explanation">{explained}</span>
        ) : running ? (
          <span className="relevance-tip-loading">Working out why this job scored like this…</span>
        ) : error ? (
          <>
            <span className="relevance-tip-error">Could not explain the score: {error}</span>
            <span className="relevance-tip-action">Click to try again</span>
          </>
        ) : (
          <span className="relevance-tip-action">Click to see why</span>
        )}
      </>
    )
  }

  const tipClasses = ['relevance-tip']
  if (explainMode) tipClasses.push('wide')
  if (error && !explained) tipClasses.push('failed')
  const busy = running && rescoreMode

  return (
    <span
      ref={wrapperRef}
      role="button"
      tabIndex={busy ? -1 : 0}
      className={error && rescoreMode ? 'relevance-rescore failed' : 'relevance-rescore'}
      onClick={activate}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') activate(e)
      }}
      onMouseEnter={openTip}
      onMouseLeave={closeUnpinnedTip}
      onFocus={openTip}
      onBlur={() => setTip(null)}
      aria-disabled={busy}
      aria-busy={running}
      aria-expanded={explainMode ? tipPinned : undefined}
      aria-describedby={tip ? tipId : undefined}
      aria-label={
        rescoreMode
          ? running
            ? 'Re-evaluating the job'
            : 'Re-evaluate the job against your updated career'
          : `${score}. Explain this score`
      }
    >
      {meter}
      {tip &&
        createPortal(
          <span
            className={tipClasses.join(' ')}
            role="tooltip"
            id={tipId}
            style={tip.style}
            aria-live={explainMode ? 'polite' : undefined}
          >
            {tipContent}
          </span>,
          document.body,
        )}
    </span>
  )
}
