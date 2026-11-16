/** Pure derivations over ``pipeline.json`` for the CV details dialog: which role ended up
 * where, why, and how its text and dates changed. No React, no I/O. */
import type { CvPipeline, PipelineEntry, PipelineRole, PipelineThresholds } from './api.ts'

export type Outcome = 'listed' | 'condensed' | 'dropped'

export const OUTCOME_LABEL: Record<Outcome, string> = {
  listed: 'Listed in full',
  condensed: 'Condensed',
  dropped: 'Dropped',
}

export const OUTCOME_ICON: Record<Outcome, string> = { listed: '✓', condensed: '≈', dropped: '✕' }

/** Month index (``year * 12 + month - 1``) of a ``"Jan 2020"`` label; ``"Present"`` is now. */
export type Span = { start: number; end: number }

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function parseMonth(label: string | undefined | null, now = new Date()): number | null {
  if (!label) return null
  if (label === 'Present') return now.getFullYear() * 12 + now.getMonth()
  const m = /^([A-Z][a-z]{2}) (\d{4})$/.exec(label.trim())
  if (!m) return null
  const month = MONTHS.indexOf(m[1])
  if (month < 0) return null
  return Number(m[2]) * 12 + month
}

export function formatMonth(index: number): string {
  return `${MONTHS[index % 12]} ${Math.floor(index / 12)}`
}

function span(start?: string | null, end?: string | null): Span | null {
  const s = parseMonth(start)
  const e = parseMonth(end)
  return s === null || e === null ? null : { start: s, end: e }
}

export function roleLabel(r: { employer: string; role: string }): string {
  return `${r.employer} / ${r.role}`
}

export type RoleReport = {
  key: string
  role: PipelineRole
  outcome: Outcome
  /** The tailored (``main``) or condensed (``early``) entry; ``null`` when dropped. */
  entry: PipelineEntry | null
  /** Original span from the work history (newer CVs only). */
  original: Span | null
  /** Span printed in the CV, which may be trimmed by the overlap resolution. */
  kept: Span | null
  trimmed: boolean
  /** Why it was condensed / dropped / trimmed, or listed despite a poor fit, taken from
   * the timeline log. */
  reason: string | null
}

/** Match a scored role to its tailored entry: by id when both sides have one (newer
 * CVs), otherwise by employer + role, consuming each entry at most once. */
function takeEntry(role: PipelineRole, pool: PipelineEntry[]): PipelineEntry | null {
  const byId = role.id != null ? pool.findIndex((e) => e.id === role.id) : -1
  const i =
    byId >= 0
      ? byId
      : pool.findIndex((e) => e.id == null && e.employer === role.employer && e.role === role.role)
  if (i < 0) return null
  return pool.splice(i, 1)[0]
}

export type LogKind = 'dropped' | 'trimmed' | 'kept' | 'moved' | 'backfilled' | 'gap' | 'listing' | 'other'

export type LogLine = { kind: LogKind; text: string; label: string | null }

/** Classify every ``timeline_log`` line; ``label`` is the ``employer / role`` it is about. */
export function classifyLog(lines: string[]): LogLine[] {
  const out: LogLine[] = []
  // Header of the indented "- label [score]" block the cursor is in, if any.
  let block: 'moved' | 'backfilled' | null = null
  for (const raw of lines) {
    const text = raw.trim()
    let kind: LogKind = 'other'
    let label: string | null = null
    let m: RegExpExecArray | null
    if ((m = /^(dropped|trimmed)\s+(.+?) \(/.exec(text))) {
      kind = m[1] as LogKind
      label = m[2]
      block = null
    } else if ((m = /^keeping\s+(.+?): /.exec(text))) {
      kind = 'kept'
      label = m[1]
      block = null
    } else if (/^moved \d+ /.test(text)) {
      kind = 'moved'
      block = 'moved'
    } else if (/^only \d+ role\(s\) left, minimum is \d+/.test(text)) {
      kind = 'backfilled'
      block = 'backfilled'
    } else if (block && (m = /^- (.+?) \[\d/.exec(text))) {
      kind = block
      label = m[1]
    } else if (/^note: /.test(text)) {
      kind = 'gap'
      block = null
    } else if (/^[A-Z][a-z]{2} \d{4} - /.test(text)) {
      kind = 'listing'
      block = null
    } else {
      block = null
    }
    out.push({ kind, text, label })
  }
  return out
}

export type Analysis = {
  roles: RoleReport[]
  counts: Record<Outcome, number> & { backfilled: number }
  thresholds: PipelineThresholds | null
  log: LogLine[]
  /** Spans are only known for CVs whose pipeline recorded dates. */
  hasSpans: boolean
}

export function analyse(p: CvPipeline): Analysis {
  const main = [...(p.main ?? [])]
  const early = [...(p.early ?? [])]
  const log = classifyLog(p.timeline_log ?? [])

  // Reason per role label: the header of the "moved ..." / "only N left ..." block the
  // role sits under (the last one wins, a backfilled role may be condensed again later),
  // or the dropped/trimmed line that names it.
  const reasons = new Map<string, string>()
  let header = ''
  for (const line of log) {
    if (line.kind === 'moved' && line.label === null) header = /irrelevant/.test(line.text) ? 'irrelevant for this job' : 'too far back in the timeline'
    else if (line.kind === 'backfilled' && line.label === null) header = 'poor fit, listed to reach the minimum'
    else if ((line.kind === 'moved' || line.kind === 'backfilled') && line.label) reasons.set(line.label, header)
    else if ((line.kind === 'dropped' || line.kind === 'trimmed') && line.label) {
      const short = /shorter than (\d+) months/.exec(line.text)
      if (short) {
        reasons.set(line.label, `shorter than ${short[1]} months after trimming`)
        continue
      }
      const m = /in favour of (.+?) \[/.exec(line.text)
      const by = m?.[1] ?? (/listed roles/.test(line.text) ? 'the listed roles' : 'another role')
      reasons.set(line.label, `${line.kind === 'dropped' ? 'overlapped' : 'overlap trimmed'} by ${by}`)
    }
  }

  // Older CVs recorded no dates, so a trim is only visible in the log there.
  const trimmedLabels = new Set(log.filter((l) => l.kind === 'trimmed').map((l) => l.label))

  const roles: RoleReport[] = (p.relevance ?? []).map((role, i) => {
    let outcome: Outcome = 'dropped'
    let entry = takeEntry(role, main)
    if (entry) outcome = 'listed'
    else {
      entry = takeEntry(role, early)
      if (entry) outcome = 'condensed'
    }
    const original = span(role.date_start, role.date_end)
    const kept = entry ? span(entry.date_start, entry.date_end) : null
    const trimmed =
      (!!original && !!kept && (original.start !== kept.start || original.end !== kept.end)) ||
      trimmedLabels.has(roleLabel(role))
    return {
      key: role.id != null ? `id-${role.id}` : `i-${i}`,
      role,
      outcome,
      entry,
      original,
      kept,
      trimmed,
      reason: reasons.get(roleLabel(role)) ?? null,
    }
  })

  const backfilled = new Set(log.filter((l) => l.kind === 'backfilled' && l.label).map((l) => l.label))
  const counts = { listed: 0, condensed: 0, dropped: 0, backfilled: 0 }
  for (const r of roles) {
    counts[r.outcome]++
    if (r.outcome === 'listed' && backfilled.has(roleLabel(r.role))) counts.backfilled++
  }
  return {
    roles,
    counts,
    thresholds: p.thresholds ?? null,
    log,
    hasSpans: roles.length > 0 && roles.every((r) => r.original !== null),
  }
}

/** Comma separated technology list -> trimmed, non-empty names. */
export function splitTech(text: string | null | undefined): string[] {
  return (text ?? '')
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean)
}

export type TechChange = { name: string; change: 'kept' | 'added' | 'removed' }

/** Diff of the tailored technology list against the original, in the tailored order with
 * removed ones appended. */
export function diffTech(original: string | null | undefined, tailored: string): TechChange[] {
  const before = splitTech(original)
  const after = splitTech(tailored)
  const beforeKeys = new Set(before.map((t) => t.toLowerCase()))
  const afterKeys = new Set(after.map((t) => t.toLowerCase()))
  return [
    ...after.map<TechChange>((name) => ({ name, change: beforeKeys.has(name.toLowerCase()) ? 'kept' : 'added' })),
    ...before.filter((t) => !afterKeys.has(t.toLowerCase())).map<TechChange>((name) => ({ name, change: 'removed' })),
  ]
}

export function wordCount(text: string | null | undefined): number {
  return (text ?? '').trim().split(/\s+/).filter(Boolean).length
}
