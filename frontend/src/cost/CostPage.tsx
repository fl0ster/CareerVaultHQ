import { useEffect, useRef, useState } from 'react'
import './cost.css'
import { getCostReport, type CostQuery, type CostReport, type Granularity } from './api.ts'
import { BreakdownChart, TimeChart } from './charts.tsx'
import { formatBucket, formatCompact, formatCount, formatUsd } from './format.ts'

const RANGES = [
  { id: '24h', label: '24 hours', hours: 24, granularity: 'hour' },
  { id: '7d', label: '7 days', hours: 24 * 7, granularity: 'day' },
  { id: '30d', label: '30 days', hours: 24 * 30, granularity: 'day' },
  { id: '90d', label: '90 days', hours: 24 * 90, granularity: 'week' },
  { id: 'all', label: 'All time', hours: null, granularity: 'month' },
] as const satisfies readonly { id: string; label: string; hours: number | null; granularity: Granularity }[]

type RangeId = (typeof RANGES)[number]['id']

const GRANULARITIES: { id: Granularity; label: string }[] = [
  { id: 'hour', label: 'Hourly' },
  { id: 'day', label: 'Daily' },
  { id: 'week', label: 'Weekly' },
  { id: 'month', label: 'Monthly' },
]

type Filters = {
  range: RangeId
  granularity: Granularity
  source: string
  model: string
  kind: string
  status: string
}

/** What the report should show, plus a counter bumped by every change and on each page visit. */
type Request = { filters: Filters; n: number }

const DEFAULT_FILTERS: Filters = {
  range: '30d',
  granularity: 'day',
  source: '',
  model: '',
  kind: '',
  status: '',
}

function toQuery(f: Filters): CostQuery {
  const range = RANGES.find((r) => r.id === f.range)
  const since = range?.hours ? new Date(Date.now() - range.hours * 3600_000).toISOString() : undefined
  return {
    since,
    granularity: f.granularity,
    source: f.source || undefined,
    model: f.model || undefined,
    kind: f.kind || undefined,
    status: f.status || undefined,
  }
}

export default function CostPage({ active }: { active: boolean }) {
  // ``n`` is bumped by every filter change and each time the page is entered; ``loadedFor`` tracks which
  // request the shown report belongs to, so ``loading`` needs no state of its own.
  const [request, setRequest] = useState<Request>({ filters: DEFAULT_FILTERS, n: 0 })
  const [loadedFor, setLoadedFor] = useState(-1)
  const [report, setReport] = useState<CostReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  const filters = request.filters
  const loading = loadedFor !== request.n

  useEffect(() => {
    const controller = new AbortController()
    getCostReport(toQuery(request.filters), controller.signal)
      .then((r) => {
        setReport(r)
        setError(null)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(`Could not load cost report: ${String(e)}`)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadedFor(request.n)
      })
    return () => controller.abort()
  }, [request])

  // The page stays mounted while hidden, so reload whenever it becomes visible again.
  // Skip the first run: the mount already triggered a load.
  const mounted = useRef(false)
  useEffect(() => {
    if (mounted.current && active) setRequest((prev) => ({ ...prev, n: prev.n + 1 }))
    mounted.current = true
  }, [active])

  const update = (patch: Partial<Filters>) =>
    setRequest((prev) => ({ filters: { ...prev.filters, ...patch }, n: prev.n + 1 }))
  const setRange = (range: RangeId) => {
    const preset = RANGES.find((r) => r.id === range)!
    update({ range, granularity: preset.granularity })
  }
  const filtered = filters.source || filters.model || filters.kind || filters.status
  const facets = report?.facets

  return (
    <>
      <p className="page-intro">Spend on OpenRouter calls, as reported by the API for every logged request.</p>

      <div className="cost-filters" role="group" aria-label="Filters">
        <div className="cost-ranges" role="radiogroup" aria-label="Period">
          {RANGES.map((r) => (
            <button
              key={r.id}
              type="button"
              className={filters.range === r.id ? 'small active' : 'small secondary'}
              aria-pressed={filters.range === r.id}
              onClick={() => setRange(r.id)}
            >
              {r.label}
            </button>
          ))}
        </div>
        <select
          aria-label="Granularity"
          value={filters.granularity}
          onChange={(e) => update({ granularity: e.target.value as Granularity })}
        >
          {GRANULARITIES.map((g) => (
            <option key={g.id} value={g.id}>{g.label}</option>
          ))}
        </select>
        <select aria-label="Source" value={filters.source} onChange={(e) => update({ source: e.target.value })}>
          <option value="">All sources</option>
          {facets?.sources.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select aria-label="Model" value={filters.model} onChange={(e) => update({ model: e.target.value })}>
          <option value="">All models</option>
          {facets?.models.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <select aria-label="Kind" value={filters.kind} onChange={(e) => update({ kind: e.target.value })}>
          <option value="">All kinds</option>
          {facets?.kinds.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <select aria-label="Status" value={filters.status} onChange={(e) => update({ status: e.target.value })}>
          <option value="">All statuses</option>
          {facets?.statuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {filtered && (
          <button type="button" className="small secondary" onClick={() => update({ source: '', model: '', kind: '', status: '' })}>
            Clear
          </button>
        )}
        {loading && <span className="spinner" aria-label="Loading" />}
      </div>

      {error && <p className="error">{error}</p>}

      {report && (
        <div className={loading ? 'cost-report loading' : 'cost-report'}>
          <div className="cost-tiles">
            <div className="cost-tile">
              <span className="cost-tile-label">Total cost</span>
              <span className="cost-tile-value">{formatUsd(report.total_cost)}</span>
            </div>
            <div className="cost-tile">
              <span className="cost-tile-label">Calls</span>
              <span className="cost-tile-value">{formatCount(report.total_calls)}</span>
              <span className="muted">
                {report.total_calls ? `${formatUsd(report.total_cost / report.total_calls)} avg` : '—'}
              </span>
            </div>
            <div className="cost-tile">
              <span className="cost-tile-label">Tokens</span>
              <span className="cost-tile-value">{formatCompact(report.total_tokens)}</span>
              <span className="muted">
                {formatCompact(report.prompt_tokens)} in · {formatCompact(report.completion_tokens)} out
              </span>
            </div>
            <div className="cost-tile">
              <span className="cost-tile-label">Period</span>
              <span className="cost-tile-value small">
                {report.first_call_at
                  ? `${formatBucket(report.first_call_at, 'day')} – ${formatBucket(report.last_call_at!, 'day')}`
                  : '—'}
              </span>
              <span className="muted">{report.series.length} {report.granularity} buckets</span>
            </div>
          </div>

          <TimeChart
            series={report.series}
            granularity={report.granularity}
            metric="cumulative_cost"
            kind="line"
            title="Cumulative cost"
          />
          <div className="cost-grid">
            <TimeChart
              series={report.series}
              granularity={report.granularity}
              metric="cost"
              kind="bar"
              title="Cost per period"
              size="compact"
            />
            <TimeChart
              series={report.series}
              granularity={report.granularity}
              metric="calls"
              kind="bar"
              title="Calls per period"
              size="compact"
            />
          </div>
          <div className="cost-grid">
            <BreakdownChart rows={report.by_source} total={report.total_cost} title="By source" />
            <BreakdownChart rows={report.by_model} total={report.total_cost} title="By model" />
          </div>
        </div>
      )}
    </>
  )
}
