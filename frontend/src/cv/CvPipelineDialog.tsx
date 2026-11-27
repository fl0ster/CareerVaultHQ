import { type ReactNode, useEffect, useState } from 'react'
import { Undo2 } from 'lucide-react'
import {
  type CvOverrides,
  type CvPipeline,
  cvApi,
  describeError,
  type GeneratedCv,
  NO_OVERRIDES,
  type PipelineEntry,
  type RolePlacement,
} from './api.ts'
import { formatUsd } from '../cost/format.ts'
import '../cost/cost.css'
import {
  analyse,
  type Analysis,
  diffTech,
  splitTech,
  formatMonth,
  OUTCOME_ICON,
  OUTCOME_LABEL,
  OUTCOME_OF_PLACEMENT,
  type Outcome,
  type RoleReport,
  withPlacements,
  wordCount,
} from './pipeline.ts'

const OUTCOMES: Outcome[] = ['listed', 'condensed', 'dropped']

function clip(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`
}

const byRelevance = (a: RoleReport, b: RoleReport) => b.role.relevance - a.role.relevance

/** The order the CV prints roles in: newest first by the period it prints (the whole one for
 * a role not in this CV); by relevance for older CVs that recorded no dates. */
const byCvOrder = (a: RoleReport, b: RoleReport) => {
  const sa = a.kept ?? a.original
  const sb = b.kept ?? b.original
  if (!sa || !sb) return byRelevance(a, b)
  return sb.start - sa.start || sb.end - sa.end
}

/** Which collapsible parts are open: the user's choice when they made one, else the default. */
type Folds = {
  isOpen: (id: string, byDefault: boolean) => boolean
  set: (id: string, open: boolean) => void
}

function Fold({
  id,
  folds,
  title,
  className = '',
  byDefault = false,
  children,
}: {
  id: string
  folds: Folds
  title: ReactNode
  className?: string
  byDefault?: boolean
  children: ReactNode
}) {
  const open = folds.isOpen(id, byDefault)
  return (
    <details
      className={`pl-fold ${className}`}
      open={open}
      onToggle={(e) => {
        if (e.currentTarget.open !== open) folds.set(id, e.currentTarget.open)
      }}
    >
      <summary>{title}</summary>
      {open && <div className="pl-fold-body">{children}</div>}
    </details>
  )
}

function OutcomeLegend({ counts }: { counts: Record<Outcome, number> }) {
  return (
    <ul className="pl-legend" aria-label="Outcome legend">
      {OUTCOMES.map((o) => (
        <li key={o} className={`outcome-${o}`}>
          <span className="pl-swatch" aria-hidden="true" />
          {OUTCOME_LABEL[o]} <span className="muted">{counts[o]}</span>
        </li>
      ))}
    </ul>
  )
}

type Tip = { index: number; xPct: number; yPx: number }

function RoleTip({ r, hint }: { r: RoleReport; hint?: string }) {
  return (
    <>
      <strong>{r.role.employer}</strong>
      <span>{r.role.role}</span>
      <span>
        {OUTCOME_ICON[r.outcome]} {OUTCOME_LABEL[r.outcome]}
        {r.pending && ' after regenerating'} · relevance {pct(r.role.relevance)}
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
      {hint && <span className="pl-tip-hint">{hint}</span>}
    </>
  )
}

// ------------------------------------------------------------------ timeline chart

const SCORE_W = 46
const ROW_H = 26
const BAR_H = 14

/** Width of the element the callback ref lands on, so the charts draw at their real pixel
 * size (text stays legible in the narrow CV Settings column instead of being scaled down). */
function useWidth(fallback = 640) {
  const [el, setEl] = useState<HTMLElement | null>(null)
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    if (!el) return
    const observer = new ResizeObserver(([e]) => setWidth(Math.round(e.contentRect.width)))
    observer.observe(el)
    return () => observer.disconnect()
  }, [el])
  return [setEl, Math.max(300, width)] as const
}

/** Room for the "employer role" labels on the left, and how much of each fits: a narrow
 * chart shows only the employer (the role is in the tooltip and the card). */
function labelLayout(W: number) {
  return W < 560 ? { labelW: 140, employer: 19, role: 0 } : { labelW: 210, employer: 18, role: 14 }
}

function RowLabel({ r, x, y, W }: { r: RoleReport; x: number; y: number; W: number }) {
  const l = labelLayout(W)
  return (
    <text x={x} y={y} dy="0.35em" textAnchor="end" className="pl-label">
      {clip(r.role.employer, l.employer)}
      {l.role > 0 && <tspan className="muted"> {clip(r.role.role, l.role)}</tspan>}
    </text>
  )
}

/** One row per role, newest first: the faint bar is the original period from the work
 * history, the solid one what the CV prints (trimmed when overlaps were resolved). The
 * relevance score sits at the end of each row; clicking a row jumps to its card. */
function TimelineChart({ analysis, onSelect }: { analysis: Analysis; onSelect: (r: RoleReport) => void }) {
  const [tip, setTip] = useState<Tip | null>(null)
  const [ref, W] = useWidth()
  const rows = analysis.roles
    .filter((r) => r.original)
    .sort((a, b) => b.original!.start - a.original!.start || b.original!.end - a.original!.end)
  if (rows.length === 0) return null
  const pending = rows.some((r) => r.pending)
  const min = Math.min(...rows.map((r) => r.original!.start))
  const max = Math.max(...rows.map((r) => r.original!.end))
  const top = 20
  const plotX = labelLayout(W).labelW
  const plotW = W - plotX - SCORE_W - 8
  const H = top + rows.length * ROW_H + 4
  const months = max - min + 1
  const x = (m: number) => plotX + ((m - min) / months) * plotW
  const years: number[] = []
  for (let m = Math.ceil(min / 12) * 12; m <= max; m += 12) years.push(m)
  const everyYear = Math.max(1, Math.ceil(years.length / Math.max(1, Math.floor(plotW / 48))))

  return (
    <figure className="chart pl-chart pl-timeline">
      <figcaption>
        {pending ? 'Your work history, as the regenerated CV will tell it' : 'Your work history, as this CV tells it'}
      </figcaption>
      <div className="pl-chart-keys">
        <OutcomeLegend counts={analysis.counts} />
        <ul className="pl-legend pl-span-key" aria-label="Bar legend">
          <li>
            <span className="pl-swatch pl-swatch-faint" aria-hidden="true" /> in your history
          </li>
          <li>
            <span className="pl-swatch" aria-hidden="true" /> printed in the CV
          </li>
          {pending && (
            <li>
              <span className="pl-swatch pl-swatch-pending" aria-hidden="true" /> moved by you
            </li>
          )}
        </ul>
      </div>
      <div className="chart-plot" ref={ref}>
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Role timeline" onMouseLeave={() => setTip(null)}>
          <g className="chart-axes">
            {years.map((m, i) => (
              <g key={m}>
                <line x1={x(m)} x2={x(m)} y1={top - 4} y2={H - 4} />
                {i % everyYear === 0 && (
                  <text x={x(m)} y={10} textAnchor="middle">
                    {Math.floor(m / 12)}
                  </text>
                )}
              </g>
            ))}
            <text x={W} y={10} textAnchor="end">
              match
            </text>
          </g>
          {rows.map((r, i) => {
            const rowY = top + i * ROW_H
            const y = rowY + (ROW_H - BAR_H) / 2
            const o = r.original!
            const k = r.kept
            return (
              <g key={r.key} className={`pl-row outcome-${r.outcome}${r.pending ? ' pending' : ''}${tip?.index === i ? ' hover' : ''}`}>
                <rect className="pl-row-bg" x={0} y={rowY} width={W} height={ROW_H} rx={4} />
                <RowLabel r={r} x={plotX - 10} y={y + BAR_H / 2} W={W} />
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
                <text x={W} y={y + BAR_H / 2} dy="0.35em" textAnchor="end" className="pl-value">
                  {pct(r.role.relevance)}
                </text>
                <rect
                  className="chart-hit pl-hit"
                  x={0}
                  y={rowY}
                  width={W}
                  height={ROW_H}
                  onMouseEnter={() => setTip({ index: i, xPct: (x(o.end + 1) / W) * 100, yPx: rowY })}
                  onClick={() => onSelect(r)}
                />
              </g>
            )
          })}
        </svg>
        {tip && (
          <div className="chart-tip pl-tip" style={{ left: `${Math.min(tip.xPct, 75)}%`, top: `${(tip.yPx / H) * 100}%` }}>
            <RoleTip r={rows[tip.index]} hint="Click to see how the CV describes it" />
          </div>
        )}
      </div>
    </figure>
  )
}

// ------------------------------------------------------------------ relevance chart

/** Horizontal bars, most relevant first, coloured by outcome, with the relevance
 * thresholds the timeline rules use drawn as reference lines. */
function RelevanceChart({ analysis }: { analysis: Analysis }) {
  const [tip, setTip] = useState<Tip | null>(null)
  const [ref, W] = useWidth()
  const rows = [...analysis.roles].sort(byRelevance)
  const top = 22
  const plotX = labelLayout(W).labelW
  const plotW = W - plotX - 48
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
    <div className="pl-chart">
      <p className="pl-hint">
        One LLM call per role gives the probability that the role is relevant experience for this job. Below{' '}
        {t ? pct(t.irrelevant_relevance) : 'the irrelevant threshold'} a role is condensed, unless fewer than{' '}
        {t?.min_entries ?? 'the minimum number of'} roles would be left; then the most relevant of them are listed anyway.
        Never more than {t?.max_entries ?? 'the maximum number of'} roles are listed in full.
      </p>
      <div className="chart-plot" ref={ref}>
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Relevance per role" onMouseLeave={() => setTip(null)}>
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
              <g key={r.key} className={`pl-row outcome-${r.outcome}${r.pending ? ' pending' : ''}${tip?.index === i ? ' hover' : ''}`}>
                <RowLabel r={r} x={plotX - 10} y={y + ROW_H / 2} W={W} />
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
    </div>
  )
}

// ------------------------------------------------------------------ role cards

function techChanges(entry: PipelineEntry) {
  const changes = diffTech(entry.original_tech, entry.tech)
  return {
    changes,
    added: changes.filter((c) => c.change === 'added').length,
    removed: changes.filter((c) => c.change === 'removed').length,
  }
}

/** One line on what happened to the role, readable while its card is closed. */
function gist(r: RoleReport): string[] {
  const e = r.entry
  const parts: string[] = []
  if (r.reason) parts.push(r.reason)
  else if (r.trimmed) parts.push('period trimmed')
  if (!e) return parts.length ? parts : ['not in the CV']
  if (e.original_context !== undefined) {
    const before = wordCount(e.original_context)
    const after = wordCount(e.context)
    parts.push(
      (e.original_context ?? '') === (e.context ?? '')
        ? 'description kept as written'
        : `description ${before} → ${plural(after, 'word')}`,
    )
  }
  if (r.outcome === 'listed' && e.original_tech !== undefined) {
    const { added, removed } = techChanges(e)
    if (removed || added) {
      parts.push(
        `technologies: ${[removed && `${removed} dropped`, added && `${added} added`].filter(Boolean).join(', ')}`,
      )
    }
  }
  return parts
}

function TechDiff({ entry }: { entry: PipelineEntry }) {
  if (entry.original_tech === undefined) {
    return (
      <div className="pl-tech">
        <span className="pl-field">Technologies</span>
        <p>{entry.tech}</p>
      </div>
    )
  }
  const { changes, added, removed } = techChanges(entry)
  return (
    <div className="pl-tech">
      <span className="pl-field">
        Technologies{' '}
        <span className="muted">
          {removed === 0 && added === 0
            ? 'reordered only'
            : [removed && `${removed} dropped`, added && `${added} added`].filter(Boolean).join(', ')}
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

/** The technologies of a listed role as clickable pills: a lit one is in the CV (click to
 * drop it), a struck-through one is not (click to add it back); pills keep their place. Choosing exactly
 * what the CV already shows is no edit at all. */
function TechPicker({ r, entry, editing }: { r: RoleReport; entry: PipelineEntry; editing: ReportEditing }) {
  const id = String(r.role.id)
  const all = editing.pending?.techs ?? {}
  const mine = all[id] ?? null
  const generated = splitTech(entry.tech)
  const original = splitTech(entry.original_tech ?? entry.tech)
  const current = mine ?? generated
  const key = (t: string) => t.toLowerCase()
  const on = new Set(current.map(key))
  const fromHistory = new Set(original.map(key))
  // One fixed order whatever is picked, so pills never move: the LLM's pick, then the rest
  // of the work history's (and anything the user kept that is in neither).
  const shown = [...new Map([...generated, ...original, ...current].map((t) => [key(t), t])).values()]

  const save = (list: string[]) => {
    const next = { ...all }
    if (list.length === generated.length && list.every((t, i) => t === generated[i])) delete next[id]
    else next[id] = list
    editing.onChange({ ...(editing.pending ?? NO_OVERRIDES), techs: next })
  }
  const chip = (name: string, inCv: boolean) => (
    <li key={key(name)}>
      <button
        type="button"
        className={inCv ? (fromHistory.has(key(name)) ? 'chip-kept' : 'chip-added') : 'chip-removed'}
        aria-pressed={inCv}
        title={inCv ? 'In the CV: click to drop it' : 'Not in the CV: click to add it'}
        disabled={editing.busy}
        // The CV lists them in the order shown.
        onClick={() => save(shown.filter((t) => (key(t) === key(name) ? !inCv : on.has(key(t)))))}
      >
        {name}
      </button>
    </li>
  )

  return (
    <div className="pl-tech">
      <div className="pl-edit-head">
        <span className="pl-field">Technologies</span>
        {mine && <span className="pl-edit-dot" title="Edited by you" aria-label="(edited)" />}
        {mine && (
          <button
            type="button"
            className="secondary small pl-revert"
            onClick={() => save(generated)}
            disabled={editing.busy}
            title="Back to the technologies the LLM picked"
          >
            Revert
          </button>
        )}
      </div>
      <ul className="pl-chips pl-chips-edit">{shown.map((t) => chip(t, on.has(key(t))))}</ul>
    </div>
  )
}

function ContextDiff({ entry, condensed }: { entry: PipelineEntry; condensed: boolean }) {
  const empty = <span className="muted">(no description)</span>
  if (entry.original_context === undefined) {
    return <p className="pl-context">{entry.context || empty}</p>
  }
  if ((entry.original_context ?? '') === (entry.context ?? '')) {
    return (
      <div className="pl-context">
        <span className="pl-field">
          Description <span className="muted">kept as written</span>
        </span>
        <p>{entry.context || empty}</p>
      </div>
    )
  }
  return (
    <div className="pl-diff">
      <div className="pl-diff-after">
        <span className="pl-field">
          In the CV{condensed ? ', condensed' : ''}{' '}
          <span className="muted">{plural(wordCount(entry.context), 'word')}</span>
        </span>
        <p>{entry.context || empty}</p>
      </div>
      <div className="pl-diff-before">
        <span className="pl-field">
          Your description <span className="muted">{plural(wordCount(entry.original_context), 'word')}</span>
        </span>
        <p>{entry.original_context || empty}</p>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ editing

/** Lets the report change the choices the next CV is generated with; without it the report
 * is read-only. */
export type ReportEditing = {
  /** The edits saved for the next CV (`null`: none). */
  pending: CvOverrides | null
  busy: boolean
  onChange: (next: CvOverrides) => void
}

const PLACEMENT_OF: Record<Outcome, RolePlacement> = { listed: 'main', condensed: 'early', dropped: 'drop' }
const PLACEMENTS: { value: RolePlacement; label: string; hint: string }[] = [
  { value: 'main', label: 'In full', hint: 'List the role in full, tailored to the job' },
  { value: 'early', label: 'Condensed', hint: 'One sentence in the “Additional experience” block' },
  { value: 'drop', label: 'Left out', hint: 'Leave the role out of this CV' },
]
const PLACEMENT_LABEL = Object.fromEntries(PLACEMENTS.map((p) => [p.value, p.label])) as Record<RolePlacement, string>

/** Where the role goes in the next CV: In full / Condensed / Left out, plus what the choice
 * changes once the CV is regenerated. */
function Placement({ r, editing, applied }: { r: RoleReport; editing: ReportEditing; applied: CvOverrides | null }) {
  if (r.role.id == null) return null
  const id = String(r.role.id)
  const pendingRoles = editing.pending?.roles ?? {}
  const mine = pendingRoles[id]
  const wasMine = applied?.roles?.[id]
  const inCv = PLACEMENT_OF[r.outcome]
  const value = mine ?? inCv

  /** The pending placements with this role's set to `v` (`null`: left to the pipeline). */
  const save = (v: RolePlacement | null) => {
    const roles = { ...pendingRoles }
    if (v) roles[id] = v
    else delete roles[id]
    editing.onChange({ ...(editing.pending ?? NO_OVERRIDES), roles })
  }
  // Picking what the pipeline chose by itself is no edit at all.
  const pick = (v: RolePlacement) => v !== value && save(v === inCv && !wasMine ? null : v)
  const reset = () => save(null)

  const status =
    mine && mine !== inCv ? (
      <span className="pl-pending">{PLACEMENT_LABEL[inCv]} in this CV · moves after regenerating</span>
    ) : !mine && wasMine ? (
      <span className="pl-pending">Back to the automatic choice after regenerating</span>
    ) : mine ? (
      <span className="pl-mine">Your choice</span>
    ) : (
      <span className="muted">Chosen automatically</span>
    )

  return (
    <div className="pl-place">
      <div className="pl-segmented" role="radiogroup" aria-label={`${r.role.employer}: place in the CV`}>
        {PLACEMENTS.map((p) => (
          <button
            key={p.value}
            type="button"
            role="radio"
            aria-checked={value === p.value}
            className={`place-${p.value}`}
            title={p.hint}
            disabled={editing.busy}
            onClick={() => pick(p.value)}
          >
            {p.label}
          </button>
        ))}
      </div>
      {status}
      {mine && (
        <button
          type="button"
          className="pl-link"
          onClick={reset}
          disabled={editing.busy}
          title="Let the pipeline decide again"
        >
          <Undo2 size={13} aria-hidden="true" /> Automatic
        </button>
      )}
    </div>
  )
}

/** A text of the CV (headline, summary, a role's description), clicked to edit it in place.
 * Saving replaces what the LLM wrote in the next CV (a dot by the label marks it edited);
 * Revert lets the LLM write it again. */
function EditableText({
  label,
  mine,
  generated,
  seed,
  busy,
  onSave,
  multiline,
  hint,
  children,
}: {
  label: ReactNode
  /** The user's text (`null`: none). */
  mine: string | null
  /** The text in this CV. */
  generated: string | null
  /** What editing starts from when the CV has no text (a left-out role's own description). */
  seed?: string | null
  busy: boolean
  onSave: (text: string | null) => void
  multiline?: boolean
  hint: string
  /** Shown after the text (the core technologies beside the headline). */
  children?: ReactNode
}) {
  const shown = mine ?? generated ?? ''
  const [draft, setDraft] = useState<string | null>(null)
  const start = () => setDraft(shown || seed || '')

  const save = (text: string | null) => {
    setDraft(null)
    const value = text?.trim() || null
    if (value !== mine) onSave(value)
  }

  return (
    <div className="pl-edit">
      <div className="pl-edit-head">
        <span className="pl-field">{label}</span>
        {mine !== null && <span className="pl-edit-dot" title="Edited by you" aria-label="(edited)" />}
      </div>
      {draft === null ? (
        <button
          type="button"
          className={`pl-edit-text${multiline ? ' cv-summary pl-summary' : ' pl-headline'}`}
          onClick={start}
          disabled={busy}
          title="Click to edit"
        >
          {multiline ? (
            shown || <span className="muted">(not in this CV — click to write one)</span>
          ) : (
            <strong>{shown || '—'}</strong>
          )}
          {children}
        </button>
      ) : (
        <form
          className="pl-edit-form"
          onSubmit={(e) => {
            e.preventDefault()
            save(draft)
          }}
        >
          {multiline ? (
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) save(draft)
                else if (e.key === 'Escape') setDraft(null)
              }}
              rows={4}
              maxLength={2000}
              aria-label={typeof label === 'string' ? label : 'Text'}
              autoFocus
            />
          ) : (
            <input
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === 'Escape' && setDraft(null)}
              maxLength={256}
              aria-label={typeof label === 'string' ? label : 'Text'}
              autoFocus
            />
          )}
          <div className="pl-edit-buttons">
            <button type="submit" className="small" disabled={busy}>
              Save
            </button>
            <button type="button" className="secondary small" onClick={() => setDraft(null)}>
              Cancel
            </button>
            <span className="muted">
              {plural(wordCount(draft), 'word')} · {hint}
            </span>
            {mine !== null && (
              <button
                type="button"
                className="secondary small pl-revert"
                onClick={() => save(null)}
                disabled={busy}
                title="Drop your text: the next CV gets a generated one"
              >
                Revert
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  )
}

function roleDates(r: RoleReport): string | null {
  const e = r.entry
  if (e) return `${e.date_start} – ${e.date_end}`
  return r.role.date_start ? `${r.role.date_start} – ${r.role.date_end}` : null
}

function cardId(r: RoleReport): string {
  return `pl-role-${r.key}`
}

type CardEditing = { editing?: ReportEditing; applied: CvOverrides | null }

/** Where the role sits in the report: where the user put it, else where this CV has it. */
function placedOutcome(r: RoleReport, pending: CvOverrides | null | undefined): Outcome {
  const mine = r.role.id != null ? pending?.roles?.[String(r.role.id)] : undefined
  return mine ? OUTCOME_OF_PLACEMENT[mine] : r.outcome
}

const DESCRIPTION_HINT: Record<Exclude<Outcome, 'dropped'>, string> = {
  listed: 'up to 3 sentences',
  condensed: 'one sentence, about 12 words',
}

/** The role's description in the next CV, edited in place, with the work-history
 * description it started from below for reference. */
function DescriptionEditor({
  r,
  editing,
  where,
}: {
  r: RoleReport
  editing: ReportEditing
  where: Exclude<Outcome, 'dropped'>
}) {
  const id = String(r.role.id)
  const contexts = editing.pending?.contexts ?? {}
  const mine = contexts[id] ?? null
  const generated = r.entry?.context ?? null
  const own = r.entry?.original_context ?? r.role.context ?? null

  const save = (text: string | null) => {
    const next = { ...contexts }
    if (text) next[id] = text
    else delete next[id]
    editing.onChange({ ...(editing.pending ?? NO_OVERRIDES), contexts: next })
  }

  return (
    <>
      <EditableText
        label={where === 'condensed' ? 'Description, condensed' : 'Description'}
        mine={mine}
        generated={generated}
        seed={own}
        busy={editing.busy}
        onSave={save}
        hint={DESCRIPTION_HINT[where]}
        multiline
      />
      {own && own !== (mine ?? generated) && (
        <div className="pl-own">
          <span className="pl-field">
            From your work history <span className="muted">{plural(wordCount(own), 'word')}</span>
          </span>
          <p>{own}</p>
        </div>
      )}
    </>
  )
}

function RoleCard({ r, folds, editing, applied }: { r: RoleReport; folds: Folds } & CardEditing) {
  const e = r.entry
  const dates = roleDates(r)
  const where = placedOutcome(r, editing?.pending)
  const place = editing && <Placement r={r} editing={editing} applied={applied} />
  const head = (
    <>
      <span className="pl-card-head">
        <span className="pl-swatch" aria-hidden="true" />
        <strong>{r.role.employer}</strong>
        <span className="pl-role">{r.role.role}</span>
        <span className="pl-score" title="How relevant the role is to this job">
          {pct(r.role.relevance)}
        </span>
      </span>
      <span className="pl-card-meta">{[dates, ...gist(r)].filter(Boolean).join('  ·  ')}</span>
    </>
  )
  const editable = editing && r.role.id != null
  // A left-out role has nothing to show or edit: just its head and where to put it.
  if (where === 'dropped' || (!e && !editable)) {
    return (
      <li id={cardId(r)} className={`pl-card outcome-${where}`} tabIndex={-1}>
        <div className="pl-card-static">{head}</div>
        {place}
      </li>
    )
  }
  return (
    <li id={cardId(r)} className={`pl-card outcome-${where}`}>
      <Fold id={r.key} folds={folds} title={head} byDefault={r.outcome === 'listed' && !editing}>
        {e && r.trimmed && r.original && (
          <p className="pl-note">
            Trimmed from {formatMonth(r.original.start)} –{' '}
            {r.role.date_end === 'Present' ? 'Present' : formatMonth(r.original.end)} to avoid overlapping another
            role.
          </p>
        )}
        {editable ? (
          <DescriptionEditor r={r} editing={editing} where={where} />
        ) : (
          e && <ContextDiff entry={e} condensed={r.outcome === 'condensed'} />
        )}
        {e &&
          r.outcome === 'listed' &&
          (editable ? (
            // Only while it stays listed: a condensed role shows no technologies.
            where === 'listed' && <TechPicker r={r} entry={e} editing={editing} />
          ) : (
            <TechDiff entry={e} />
          ))}
        {e?.location && <p className="pl-note">Location: {e.location}</p>}
      </Fold>
      {place}
    </li>
  )
}

function RoleCards({ roles, folds, ...edit }: { roles: RoleReport[]; folds: Folds } & CardEditing) {
  return (
    <ul className="pl-cards">
      {roles.map((r) => (
        <RoleCard key={r.key} r={r} folds={folds} {...edit} />
      ))}
    </ul>
  )
}

const GROUP_INTRO: Record<Outcome, string> = {
  listed:
    'Each description was rewritten for this job (at most 3 sentences) and its technologies filtered and reordered. Newest first, as in the CV.',
  condensed: 'Shortened to one sentence each in the “Additional experience” block.',
  dropped: 'Left out of the CV entirely; the reason is on each role.',
}

function groupTitle(outcome: Outcome, count: number) {
  return (
    <h3 className={`outcome-${outcome}`}>
      <span className="pl-swatch" aria-hidden="true" />
      {OUTCOME_LABEL[outcome]} <span className="muted">{count}</span>
    </h3>
  )
}

// ------------------------------------------------------------------ report

/** What the generation of `cv` did (`GET /api/cv/{id}/pipeline`), most useful first: the
 * timeline of what the CV kept, then each role and how its description changed, most
 * relevant first. Condensed and dropped roles, the scoring, the timeline decisions, skill
 * categories and raw data start folded. With `editing`, the headline, the summary and where
 * each role goes can be changed for the next CV. */
export function CvPipelineReport({ cv, editing }: { cv: GeneratedCv; editing?: ReportEditing }) {
  const [pipeline, setPipeline] = useState<CvPipeline | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [toggled, setToggled] = useState<Record<string, boolean>>({})

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

  const folds: Folds = {
    isOpen: (id, byDefault) => toggled[id] ?? byDefault,
    set: (id, open) => setToggled((t) => ({ ...t, [id]: open })),
  }

  const analysis = pipeline ? analyse(pipeline) : null
  const planned = analysis && withPlacements(analysis, editing?.pending?.roles)
  const roles = analysis?.roles ?? []
  // A role the user moved shows in the section it will be in after regenerating.
  const placed = (r: RoleReport) => placedOutcome(r, editing?.pending)
  const group = (o: Outcome) => roles.filter((r) => placed(r) === o).sort(byCvOrder)
  const listed = group('listed')
  const condensed = group('condensed')
  const dropped = group('dropped')
  const decisions = analysis?.log.filter((l) => l.kind !== 'listing' && !(l.kind === 'moved' && l.label)) ?? []
  const cost = pipeline?.cost ?? cv.cost
  const calls = pipeline?.openrouter_calls ?? cv.openrouter_calls
  const warnings = pipeline?.warnings ?? cv.warnings
  const empty = pipeline !== null && roles.length === 0

  /** Open the role's card (and its group) and bring it into view. */
  const select = (r: RoleReport) => {
    setToggled((t) => ({ ...t, [r.key]: true, [`group-${placed(r)}`]: true }))
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    requestAnimationFrame(() => {
      const card = document.getElementById(cardId(r))
      if (!card) return
      card.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
      ;(card.querySelector<HTMLElement>('summary') ?? card).focus({ preventScroll: true })
      card.classList.remove('pl-flash')
      void card.offsetWidth // restart the highlight when the same card is picked twice
      card.classList.add('pl-flash')
    })
  }

  const applied = cv.overrides
  const edit = { editing, applied }
  const coreTech = cv.core_technologies.length > 0 && (
    <span className="muted"> · {cv.core_technologies.join(' · ')}</span>
  )

  return (
    <div className="pl-report">
      {editing ? (
        <div className="pl-texts">
          <EditableText
            label="Headline"
            mine={editing.pending?.headline_role ?? null}
            generated={cv.headline_role}
            busy={editing.busy}
            onSave={(text) => editing.onChange({ ...(editing.pending ?? NO_OVERRIDES), headline_role: text })}
            hint="a job title, up to 6 words"
          >
            {coreTech}
          </EditableText>
          <EditableText
            label="Summary"
            mine={editing.pending?.summary ?? null}
            generated={cv.summary}
            busy={editing.busy}
            onSave={(text) => editing.onChange({ ...(editing.pending ?? NO_OVERRIDES), summary: text })}
            hint="about 50 words"
            multiline
          />
        </div>
      ) : (
        <>
          {cv.headline_role && (
            <p className="pl-headline">
              <strong>{cv.headline_role}</strong>
              {coreTech}
            </p>
          )}
          {cv.summary && <p className="cv-summary pl-summary">{cv.summary}</p>}
        </>
      )}

      {cv.error && <pre className="error cv-inline-error">{cv.error}</pre>}
      {error && <p className="error">Could not load the pipeline report: {error}</p>}
      {!pipeline && !error && <span className="spinner" aria-hidden="true" />}
      {empty && !cv.error && <p className="muted">No pipeline report yet: the generation has not finished.</p>}

      {analysis && roles.length > 0 && (
        <>
          {warnings.length > 0 && (
            <ul className="cv-warnings pl-warnings">
              {warnings.map((w) => (
                <li key={w}>⚠ {w}</li>
              ))}
            </ul>
          )}

          {listed.length > 0 && (
            <section className="pl-section">
              {groupTitle('listed', listed.length)}
              <p className="pl-hint">{GROUP_INTRO.listed}</p>
              <RoleCards roles={listed} folds={folds} {...edit} />
            </section>
          )}

          {([['condensed', condensed], ['dropped', dropped]] as const).map(
            ([outcome, list]) =>
              list.length > 0 && (
                <Fold
                  key={outcome}
                  id={`group-${outcome}`}
                  folds={folds}
                  className="pl-group"
                  title={groupTitle(outcome, list.length)}
                >
                  <p className="pl-hint">{GROUP_INTRO[outcome]}</p>
                  <RoleCards roles={list} folds={folds} {...edit} />
                </Fold>
              ),
          )}

          {/* The work history as the next CV will have it: the pending placements applied. */}
          {planned &&
            (planned.hasSpans ? (
              <TimelineChart analysis={planned} onSelect={select} />
            ) : (
              <figure className="chart pl-chart">
                <figcaption>How each role scored against the job</figcaption>
                <OutcomeLegend counts={planned.counts} />
                <RelevanceChart analysis={planned} />
              </figure>
            ))}

          <div className="pl-more">
            <h3>Behind the scenes</h3>
            {analysis.hasSpans && (
              <Fold id="scores" folds={folds} title="How the roles were scored">
                <RelevanceChart analysis={analysis} />
              </Fold>
            )}
            {decisions.length > 0 && (
              <Fold
                id="decisions"
                folds={folds}
                title={
                  <>
                    Timeline decisions <span className="muted">{decisions.length}</span>
                  </>
                }
              >
                <p className="pl-hint">
                  Overlapping periods are resolved in favour of the longer role unless the shorter one is clearly more
                  relevant. Roles that are a poor fit are listed anyway when fewer than
                  {analysis.thresholds ? ` ${analysis.thresholds.min_entries}` : ' the minimum'} would remain, and
                  older roles past the limit{analysis.thresholds ? ` of ${analysis.thresholds.max_entries}` : ''} are
                  always condensed.
                </p>
                <ul className="pl-decisions">
                  {decisions.map((l, i) => (
                    <li key={i} className={`log-${l.kind}`}>
                      {l.text}
                    </li>
                  ))}
                </ul>
              </Fold>
            )}
            {pipeline?.categories && pipeline.categories.length > 0 && (
              <Fold
                id="categories"
                folds={folds}
                title={
                  <>
                    Skill categories <span className="muted">{pipeline.categories.length}</span>
                  </>
                }
              >
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
              </Fold>
            )}
            <Fold id="raw" folds={folds} title="Raw data">
              <p className="pl-hint">
                {pipeline?.job_description_chars ?? '?'} characters of job description were sent to the model.
              </p>
              {pipeline?.timeline_log && (
                <Fold id="raw-log" folds={folds} title="Full timeline log">
                  <pre className="pl-raw">{pipeline.timeline_log.join('\n')}</pre>
                </Fold>
              )}
              <Fold id="raw-json" folds={folds} title="pipeline.json">
                <pre className="pl-raw">{JSON.stringify(pipeline, null, 2)}</pre>
              </Fold>
            </Fold>
          </div>
        </>
      )}

      {pipeline && (
        <p className="pl-cost">
          {cost === null || cost === undefined ? 'Cost unknown' : `Generated for ${formatUsd(cost)}`} ·{' '}
          {plural(calls ?? 0, 'OpenRouter call')}
        </p>
      )}
    </div>
  )
}
