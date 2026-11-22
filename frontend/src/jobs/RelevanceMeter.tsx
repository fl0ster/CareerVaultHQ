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
/** Room the popup needs below the meter before it opens above it instead, in px. */
const TIP_ROOM_BELOW = 120
/** Gap between the meter and the popup, and the popup and the viewport edge, in px. */
const TIP_GAP = 8

/** Fixed-position style placing the popup under (or, near the bottom, above) `anchor`,
 * horizontally kept inside the viewport. */
function tipPosition(anchor: DOMRect): CSSProperties {
  const left = Math.max(TIP_GAP, Math.min(anchor.left - TIP_GAP, window.innerWidth - TIP_WIDTH - TIP_GAP))
  return anchor.bottom + TIP_ROOM_BELOW > window.innerHeight
    ? { left, bottom: window.innerHeight - anchor.top + TIP_GAP }
    : { left, top: anchor.bottom + TIP_GAP }
}

type Rescore = {
  /** The job the score belongs to (`jobs.id`). */
  jobId: number
  /** Called with the job once it is scored against the latest profile. */
  onRescored: (job: EvaluatedJobDetail) => void
}

type Props = {
  relevance: number
  /** Scored against an earlier work history: drawn faded and hatched, and clickable to
   * re-score when `rescore` is given. */
  outdated?: boolean
  rescore?: Rescore
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

/** Diverging bar for a relevance in [-1, 1]: it grows right of the centre line above
 * the threshold and left of it below. No numbers; the exact value is in the tooltip.
 * An outdated score is drawn faded over a hatched track; clicking it re-scores the job. */
export default function RelevanceMeter({ relevance, outdated = false, rescore }: Props) {
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  /** Where the hover popup is shown; `null` while it is closed. */
  const [tip, setTip] = useState<CSSProperties | null>(null)
  const tipId = useId()
  const controllerRef = useRef<AbortController | null>(null)
  useEffect(() => () => controllerRef.current?.abort(), [])

  // The popup is fixed to the viewport: close it as soon as anything scrolls or resizes.
  const tipOpen = tip !== null
  useEffect(() => {
    if (!tipOpen) return
    const close = () => setTip(null)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [tipOpen])

  const value = Math.max(-1, Math.min(1, relevance))
  const width = `${Math.abs(value) * 50}%`
  const above = value > 0
  const label = above ? 'Above the relevance threshold' : value < 0 ? 'Below the relevance threshold' : 'At the relevance threshold'
  const score = `${label} (${value > 0 ? '+' : ''}${value.toFixed(2)})`

  const classes = ['relevance']
  if (above) classes.push('above')
  if (outdated) classes.push('outdated')
  if (running) classes.push('rescoring')

  const meter = (
    <span
      className={classes.join(' ')}
      role="meter"
      aria-valuemin={-1}
      aria-valuemax={1}
      aria-valuenow={value}
      aria-label={outdated ? `${label}, scored against an earlier work history` : label}
      title={rescore && outdated ? undefined : outdated ? `${score}, scored against an earlier work history` : score}
    >
      <span className="relevance-fill" style={above ? { left: '50%', width } : { right: '50%', width }} />
    </span>
  )
  if (!outdated || !rescore) return meter

  const start = async () => {
    if (running) return
    const controller = new AbortController()
    controllerRef.current = controller
    setRunning(true)
    setError(null)
    try {
      rescore.onRescored(await rescoreJob(rescore.jobId, controller.signal))
    } catch (e) {
      if (!controller.signal.aborted) setError(describeError(e))
    } finally {
      if (!controller.signal.aborted) setRunning(false)
    }
  }

  // A span rather than a <button>: the meter can sit inside a clickable row (itself a
  // button, e.g. on the Applications tab), so the click must not reach the row.
  const activate = (e: SyntheticEvent) => {
    e.stopPropagation()
    e.preventDefault()
    start()
  }
  // The popup is portalled to <body>: list rows create stacking contexts (opacity,
  // transforms) that would otherwise clip it or paint over it.
  const openTip = (e: SyntheticEvent<HTMLElement>) => setTip(tipPosition(e.currentTarget.getBoundingClientRect()))
  const closeTip = () => setTip(null)
  const tipContent = running ? (
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
  return (
    <span
      role="button"
      tabIndex={running ? -1 : 0}
      className={error ? 'relevance-rescore failed' : 'relevance-rescore'}
      onClick={activate}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') activate(e)
      }}
      onMouseEnter={openTip}
      onMouseLeave={closeTip}
      onFocus={openTip}
      onBlur={closeTip}
      aria-disabled={running}
      aria-busy={running}
      aria-describedby={tip ? tipId : undefined}
      aria-label={running ? 'Re-evaluating the job' : 'Re-evaluate the job against your updated career'}
    >
      {meter}
      {tip &&
        createPortal(
          <span className={error ? 'relevance-tip failed' : 'relevance-tip'} role="tooltip" id={tipId} style={tip}>
            {tipContent}
          </span>,
          document.body,
        )}
    </span>
  )
}
