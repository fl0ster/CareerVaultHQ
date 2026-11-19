import { useEffect, useRef, useState } from 'react'
import { type CvPipeline, cvApi, describeError, type GeneratedCv, type PipelineEntry } from './api.ts'
import CvActions from './CvActions.tsx'
import CvStatusBadge from './CvStatusBadge.tsx'
import { formatUsd } from '../cost/format.ts'
import '../cost/cost.css'
import {
  analyse,
  type Analysis,
  diffTech,
  formatMonth,
  OUTCOME_ICON,
  OUTCOME_LABEL,
  type Outcome,
  type RoleReport,
  wordCount,
} from './pipeline.ts'

const OUTCOMES: Outcome[] = ['listed', 'condensed', 'dropped']

function clip(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`
}

// ------------------------------------------------------------------ shared chart bits

function OutcomeLegend({ counts }: { counts: Record<Outcome, number> }) {
  return (
    <ul className="pl-legend" aria-label="Outcome legend">
      {OUTCOMES.map((o) => (
        <li key={o} className={`outcome-${o}`}>
          <span className="pl-swatch" aria-hidden="true" />
          {OUTCOME_ICON[o]} {OUTCOME_LABEL[o]} <span className="muted">({counts[o]})</span>
        </li>
      ))}
    </ul>
  )
}

type Tip = { index: number; xPct: number; yPx: number }

function RoleTip({ r }: { r: RoleReport }) {
  return (
    <>
      <strong>{r.role.employer}</strong>
      <span>{r.role.role}</span>
      <span>
        {OUTCOME_ICON[r.outcome]} {OUTCOME_LABEL[r.outcome]} · relevance {pct(r.role.relevance)}
      </span>
      {r.original && (
        <span className="muted">
          {formatMonth(r.original.start)} – {r.role.date_end === 'Present' ? 'Present' : formatMonth(r.original.end)} ·{' '}
          {r.original.end - r.original.start + 1} mo
        </span>
      )}
      {r.trimmed && r.kept && (
        <span className="muted">
          in CV: {formatMonth(r.kept.start)} – {formatMonth(r.kept.end)}
        </span>
      )}
      {r.reason && <span className="muted">{r.reason}</span>}
    </>
  )
}

// ------------------------------------------------------------------ relevance chart

const W = 640
const LABEL_W = 210
const ROW_H = 24
const BAR_H = 14

/** Horizontal bars, most relevant first, coloured by outcome, with the three relevance
 * thresholds the timeline rules use drawn as reference lines. */
function RelevanceChart({ analysis }: { analysis: Analysis }) {
  const [tip, setTip] = useState<Tip | null>(null)
  const rows = [...analysis.roles].sort((a, b) => b.role.relevance - a.role.relevance)
  const top = 22
  const plotX = LABEL_W
  const plotW = W - LABEL_W - 48
  const H = top + rows.length * ROW_H + 6
  const x = (v: number) => plotX + v * plotW
  const t = analysis.thresholds
  const marks = t
    ? [
        { v: t.irrelevant_relevance, name: 'irrelevant' },
        { v: t.high_relevance, name: 'relevant' },
      ]
    : []

  return (
    <figure className="chart pl-chart">
      <figcaption>How each role scored against the job</figcaption>
      <p className="pl-hint">
        One LLM call per role gives the probability that the role is relevant experience for this job. Below{' '}
        {t ? pct(t.irrelevant_relevance) : 'the irrelevant threshold'} a role is condensed, unless fewer than{' '}
        {t?.min_entries ?? 'the minimum number of'} roles would be left; then the most relevant of them are listed anyway.
        Never more than {t?.max_entries ?? 'the maximum number of'} roles are listed in full.
      </p>
      <OutcomeLegend counts={analysis.counts} />
      <div className="chart-plot">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Relevance per role" onMouseLeave={() => setTip(null)}>
          <g className="chart-axes">
            {[0, 0.25, 0.5, 0.75, 1].map((v) => (
              <line key={v} x1={x(v)} x2={x(v)} y1={top - 4} y2={H - 6} />
            ))}
          </g>
          {marks.map((m) => (
            <g key={m.name} className="pl-threshold">
              <line x1={x(m.v)} x2={x(m.v)} y1={top - 6} y2={H - 6} />
              <text x={x(m.v)} y={10} textAnchor="middle">
                {m.name} {pct(m.v)}
              </text>
            </g>
          ))}
          {rows.map((r, i) => {
            const y = top + i * ROW_H
            const w = Math.max(2, x(r.role.relevance) - plotX)
            return (
              <g key={r.key} className={`pl-row outcome-${r.outcome}${tip?.index === i ? ' hover' : ''}`}>
                <text x={plotX - 10} y={y + ROW_H / 2} dy="0.35em" textAnchor="end" className="pl-label">
                  {clip(r.role.employer, 18)}
                  <tspan className="muted"> {clip(r.role.role, 14)}</tspan>
                </text>
                <rect className="pl-bar" x={plotX} y={y + (ROW_H - BAR_H) / 2} width={w} height={BAR_H} rx={4} />
                {/* square the bar at the baseline */}
                <rect className="pl-bar" x={plotX} y={y + (ROW_H - BAR_H) / 2} width={Math.min(4, w)} height={BAR_H} />
                <text x={plotX + w + 6} y={y + ROW_H / 2} dy="0.35em" className="pl-value">
                  {pct(r.role.relevance)}
                </text>
                <rect
                  className="chart-hit"
                  x={0}
                  y={y}
                  width={W}
                  height={ROW_H}
                  onMouseEnter={() => setTip({ index: i, xPct: ((plotX + w) / W) * 100, yPx: y })}
                />
              </g>
            )
          })}
        </svg>
        {tip && (
          <div className="chart-tip pl-tip" style={{ left: `${tip.xPct}%`, top: `${(tip.yPx / H) * 100}%` }}>
            <RoleTip r={rows[tip.index]} />
          </div>
        )}
      </div>
    </figure>
  )
}

// ------------------------------------------------------------------ timeline chart

/** One row per role, newest first: the faint bar is the original period from the work
 * history, the solid one what the CV prints (trimmed when overlaps were resolved). */
function TimelineChart({ analysis }: { analysis: Analysis }) {
  const [tip, setTip] = useState<Tip | null>(null)
  const rows = analysis.roles
    .filter((r) => r.original)
    .sort((a, b) => b.original!.start - a.original!.start || b.original!.end - a.original!.end)
  if (rows.length === 0) return null
  const min = Math.min(...rows.map((r) => r.original!.start))
  const max = Math.max(...rows.map((r) => r.original!.end))
  const top = 18
  const plotX = LABEL_W
  const plotW = W - LABEL_W - 16
  const H = top + rows.length * ROW_H + 6
  const months = max - min + 1
  const x = (m: number) => plotX + ((m - min) / months) * plotW
  const years: number[] = []
  for (let m = Math.ceil(min / 12) * 12; m <= max; m += 12) years.push(m)
  const everyYear = Math.max(1, Math.ceil(years.length / 8))

  return (
    <figure className="chart pl-chart">
      <figcaption>Timeline: what the CV keeps of each period</figcaption>
      <p className="pl-hint">
        Faint bar: the period from your work history. Solid bar: the period printed in the CV. A solid bar shorter
        than its faint one was trimmed to resolve an overlap with a more relevant role.
      </p>
      <div className="chart-plot">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Role timeline" onMouseLeave={() => setTip(null)}>
          <g className="chart-axes">
            {years.map((m, i) => (
              <g key={m}>
                <line x1={x(m)} x2={x(m)} y1={top - 4} y2={H - 6} />
                {i % everyYear === 0 && (
                  <text x={x(m)} y={10} textAnchor="middle">
                    {Math.floor(m / 12)}
                  </text>
                )}
              </g>
            ))}
          </g>
          {rows.map((r, i) => {
            const y = top + i * ROW_H + (ROW_H - BAR_H) / 2
            const o = r.original!
            const k = r.kept
            return (
              <g key={r.key} className={`pl-row outcome-${r.outcome}${tip?.index === i ? ' hover' : ''}`}>
                <text x={plotX - 10} y={y + BAR_H / 2} dy="0.35em" textAnchor="end" className="pl-label">
                  {clip(r.role.employer, 18)}
                  <tspan className="muted"> {clip(r.role.role, 14)}</tspan>
                </text>
                <rect
                  className="pl-span-original"
                  x={x(o.start)}
                  y={y}
                  width={Math.max(2, x(o.end + 1) - x(o.start))}
                  height={BAR_H}
                  rx={3}
                />
                {k && (
                  <rect
                    className="pl-bar"
                    x={x(k.start)}
                    y={y}
                    width={Math.max(2, x(k.end + 1) - x(k.start))}
                    height={BAR_H}
                    rx={3}
                  />
                )}
                <rect
                  className="chart-hit"
                  x={0}
                  y={top + i * ROW_H}
                  width={W}
                  height={ROW_H}
                  onMouseEnter={() => setTip({ index: i, xPct: (x(o.end + 1) / W) * 100, yPx: top + i * ROW_H })}
                />
              </g>
            )
          })}
        </svg>
        {tip && (
          <div className="chart-tip pl-tip" style={{ left: `${Math.min(tip.xPct, 75)}%`, top: `${(tip.yPx / H) * 100}%` }}>
            <RoleTip r={rows[tip.index]} />
          </div>
        )}
      </div>
    </figure>
  )
}

// ------------------------------------------------------------------ role cards

function TechDiff({ entry }: { entry: PipelineEntry }) {
  if (entry.original_tech === undefined) {
    return <p className="pl-tech">{entry.tech}</p>
  }
  const changes = diffTech(entry.original_tech, entry.tech)
  const added = changes.filter((c) => c.change === 'added').length
  const removed = changes.filter((c) => c.change === 'removed').length
  return (
    <div className="pl-tech">
      <span className="pl-field">
        Technologies{' '}
        <span className="muted">
          {removed > 0 && `${removed} dropped`}
          {removed > 0 && added > 0 && ', '}
          {added > 0 && `${added} added`}
          {removed === 0 && added === 0 && 'reordered only'}
        </span>
      </span>
      <ul className="pl-chips">
        {changes.map((c) => (
          <li key={`${c.change}-${c.name}`} className={`chip-${c.change}`} title={c.change}>
            {c.change === 'added' && '+ '}
            {c.name}
          </li>
        ))}
      </ul>
    </div>
  )
}

function ContextDiff({ entry, condensed }: { entry: PipelineEntry; condensed: boolean }) {
  const hasOriginal = entry.original_context !== undefined
  const unchanged = hasOriginal && (entry.original_context ?? '') === (entry.context ?? '')
  if (!hasOriginal) {
    return <p className="pl-context">{entry.context || <span className="muted">(no description)</span>}</p>
  }
  if (unchanged) {
    return (
      <div className="pl-context">
        <span className="pl-field">
          Description <span className="muted">kept as written</span>
        </span>
        <p>{entry.context || <span className="muted">(no description)</span>}</p>
      </div>
    )
  }
  const before = wordCount(entry.original_context)
  const after = wordCount(entry.context)
  return (
    <div className="pl-diff">
      <div>
        <span className="pl-field">
          Original <span className="muted">{before} words</span>
        </span>
        <p>{entry.original_context || <span className="muted">(empty)</span>}</p>
      </div>
      <div>
        <span className="pl-field">
          {condensed ? 'Condensed' : 'Tailored'} <span className="muted">{after} words</span>
        </span>
        <p>{entry.context}</p>
      </div>
    </div>
  )
}

function RoleCard({ r }: { r: RoleReport }) {
  const e = r.entry
  return (
    <li className={`pl-card outcome-${r.outcome}`}>
      <div className="pl-card-head">
        <span className="pl-swatch" aria-hidden="true" />
        <strong>{r.role.employer}</strong>
        <span className="pl-role">{r.role.role}</span>
        <span className="pl-score">{pct(r.role.relevance)}</span>
      </div>
      <div className="pl-card-meta">
        {e ? (
          <span>
            {e.date_start} – {e.date_end}
            {r.trimmed && r.original && (
              <span className="muted">
                {' '}
                (trimmed from {formatMonth(r.original.start)} – {r.role.date_end === 'Present' ? 'Present' : formatMonth(r.original.end)})
              </span>
            )}
          </span>
        ) : (
          r.role.date_start && (
            <span>
              {r.role.date_start} – {r.role.date_end}
            </span>
          )
        )}
        {e?.location && <span>{e.location}</span>}
        {r.reason && <span className="pl-reason">{r.reason}</span>}
      </div>
      {e && <ContextDiff entry={e} condensed={r.outcome === 'condensed'} />}
      {e && r.outcome === 'listed' && <TechDiff entry={e} />}
    </li>
  )
}

function RoleGroup({ outcome, roles, intro }: { outcome: Outcome; roles: RoleReport[]; intro: string }) {
  if (roles.length === 0) return null
  return (
    <section className="pl-section">
      <h3 className={`outcome-${outcome}`}>
        <span className="pl-swatch" aria-hidden="true" />
        {OUTCOME_ICON[outcome]} {OUTCOME_LABEL[outcome]} <span className="muted">({roles.length})</span>
      </h3>
      <p className="pl-hint">{intro}</p>
      <ul className="pl-cards">
        {roles.map((r) => (
          <RoleCard key={r.key} r={r} />
        ))}
      </ul>
    </section>
  )
}

// ------------------------------------------------------------------ dialog

type Props = { cv: GeneratedCv; onClose: () => void }

export default function CvPipelineDialog({ cv, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [pipeline, setPipeline] = useState<CvPipeline | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showLog, setShowLog] = useState(false)
  const [showRaw, setShowRaw] = useState(false)

  // No close() on cleanup: unmounting removes the dialog anyway, and in dev StrictMode the
  // close event from a cleanup would land after the remount and shut the dialog again.
  useEffect(() => {
    const el = dialog.current
    if (el && !el.open) el.showModal()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    cvApi
      .pipeline(cv.id, controller.signal)
      .then(setPipeline)
      .catch((e) => {
        if (!controller.signal.aborted) setError(describeError(e))
      })
    return () => controller.abort()
  }, [cv.id])

  const analysis = pipeline ? analyse(pipeline) : null
  const roles = analysis?.roles ?? []
  const listed = roles.filter((r) => r.outcome === 'listed')
  const condensed = roles.filter((r) => r.outcome === 'condensed')
  const dropped = roles.filter((r) => r.outcome === 'dropped')
  const decisions = analysis?.log.filter((l) => l.kind !== 'listing' && !(l.kind === 'moved' && l.label)) ?? []
  const cost = pipeline?.cost ?? cv.cost
  const calls = pipeline?.openrouter_calls ?? cv.openrouter_calls
  const warnings = pipeline?.warnings ?? cv.warnings
  const empty = pipeline !== null && roles.length === 0

  return (
    <dialog
      ref={dialog}
      className="job-dialog pl-dialog"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === dialog.current) onClose()
      }}
    >
      <div className="job-dialog-body">
        <div className="job-dialog-head">
          <div className="cv-main">
            <h2>{cv.job.title ?? 'Untitled job'}</h2>
            <div className="cv-meta">
              {cv.job.company && <span className="cv-company">{cv.job.company}</span>}
              <CvStatusBadge status={cv.status} />
              <span>CV #{cv.id}</span>
              <a href={cv.job.link} target="_blank" rel="noreferrer">
                {cv.job.source}
              </a>
            </div>
          </div>
          <button type="button" className="secondary small" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {cv.headline_role && (
          <p className="pl-headline">
            <strong>{cv.headline_role}</strong>
            {cv.core_technologies.length > 0 && <span className="muted"> · {cv.core_technologies.join(' · ')}</span>}
          </p>
        )}
        {cv.summary && <p className="cv-summary pl-summary">{cv.summary}</p>}
        <CvActions cv={cv} />

        {cv.error && <pre className="error cv-inline-error">{cv.error}</pre>}
        {error && <p className="error">Could not load the pipeline report: {error}</p>}
        {!pipeline && !error && <span className="spinner" aria-hidden="true" />}
        {empty && !cv.error && <p className="muted">No pipeline report yet: the generation has not finished.</p>}

        {analysis && roles.length > 0 && (
          <>
            <div className="cost-tiles pl-tiles">
              <div className="cost-tile">
                <span className="cost-tile-label">Generation cost</span>
                <span className="cost-tile-value">{cost === null || cost === undefined ? '—' : formatUsd(cost)}</span>
                <span className="muted">{calls ?? 0} OpenRouter calls</span>
              </div>
              <div className="cost-tile">
                <span className="cost-tile-label">Roles scored</span>
                <span className="cost-tile-value">{roles.length}</span>
                <span className="muted">{pipeline?.job_description_chars ?? '?'} chars of job text</span>
              </div>
              <div className="cost-tile outcome-listed">
                <span className="cost-tile-label">Listed in full</span>
                <span className="cost-tile-value">
                  {analysis.counts.listed}
                  {analysis.thresholds && (
                    <span className="muted"> / {analysis.thresholds.min_entries}–{analysis.thresholds.max_entries}</span>
                  )}
                </span>
                <span className="muted">
                  {roles.filter((r) => r.trimmed).length} trimmed
                  {analysis.counts.backfilled > 0 && `, ${analysis.counts.backfilled} listed to reach the minimum`}
                </span>
              </div>
              <div className="cost-tile">
                <span className="cost-tile-label">Condensed / dropped</span>
                <span className="cost-tile-value">
                  {analysis.counts.condensed} / {analysis.counts.dropped}
                </span>
                <span className="muted">{warnings.length} fallback{warnings.length === 1 ? '' : 's'}</span>
              </div>
            </div>

            {warnings.length > 0 && (
              <ul className="cv-warnings pl-warnings">
                {warnings.map((w) => (
                  <li key={w}>⚠ {w}</li>
                ))}
              </ul>
            )}

            <RelevanceChart analysis={analysis} />
            {analysis.hasSpans && <TimelineChart analysis={analysis} />}

            {decisions.length > 0 && (
              <section className="pl-section">
                <h3>Timeline decisions</h3>
                <p className="pl-hint">
                  Overlapping periods are resolved in favour of the longer role unless the shorter one is clearly more
                  relevant. Roles that are a poor fit are listed anyway when fewer than
                  {analysis.thresholds ? ` ${analysis.thresholds.min_entries}` : ' the minimum'} would remain, and older
                  roles past the limit{analysis.thresholds ? ` of ${analysis.thresholds.max_entries}` : ''} are always
                  condensed.
                </p>
                <ul className="pl-decisions">
                  {decisions.map((l, i) => (
                    <li key={i} className={`log-${l.kind}`}>
                      {l.text}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <RoleGroup
              outcome="listed"
              roles={listed}
              intro="Each of these roles got two LLM calls: one rewrote the description for the job (max 3 sentences), one reordered and filtered its technologies."
            />
            <RoleGroup
              outcome="condensed"
              roles={condensed}
              intro="These roles appear in the “Additional experience” block, each condensed to one sentence."
            />
            <RoleGroup
              outcome="dropped"
              roles={dropped}
              intro="These roles do not appear in the CV at all: they overlapped a longer or more relevant role."
            />

            {pipeline?.categories && pipeline.categories.length > 0 && (
              <section className="pl-section">
                <h3>Skill categories</h3>
                <p className="pl-hint">Technologies of the listed roles, grouped for the job by one more LLM call.</p>
                <dl className="pl-categories">
                  {pipeline.categories.map(([name, techs]) => (
                    <div key={name}>
                      <dt>{name}</dt>
                      <dd>
                        <ul className="pl-chips">
                          {techs.map((t) => (
                            <li key={t} className={cv.core_technologies.includes(t) ? 'chip-core' : 'chip-kept'}>
                              {t}
                            </li>
                          ))}
                        </ul>
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}

            <div className="pl-raw-controls">
              {pipeline?.timeline_log && (
                <button type="button" className="secondary small" onClick={() => setShowLog((v) => !v)}>
                  {showLog ? 'Hide' : 'Show'} full timeline log
                </button>
              )}
              <button type="button" className="secondary small" onClick={() => setShowRaw((v) => !v)}>
                {showRaw ? 'Hide' : 'Show'} pipeline.json
              </button>
            </div>
            {showLog && <pre className="pl-raw">{pipeline?.timeline_log?.join('\n')}</pre>}
            {showRaw && <pre className="pl-raw">{JSON.stringify(pipeline, null, 2)}</pre>}
          </>
        )}
      </div>
    </dialog>
  )
}
