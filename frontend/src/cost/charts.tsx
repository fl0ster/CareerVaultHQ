import { useState } from 'react'
import type { CostBreakdown, CostBucket, Granularity } from './api.ts'
import { formatBucket, formatCount, formatUsd, formatUsdTick } from './format.ts'

/** SVG viewBox sizes; ``compact`` is for charts shown two per row so text keeps ~1:1 scale. */
const SIZES = {
  wide: { W: 640, H: 220 },
  compact: { W: 320, H: 180 },
} as const
type Size = keyof typeof SIZES
const PAD = { top: 12, right: 16, bottom: 28, left: 56 }

function frame(size: Size) {
  const { W, H } = SIZES[size]
  return { W, H, PLOT_W: W - PAD.left - PAD.right, PLOT_H: H - PAD.top - PAD.bottom }
}

/** Round ``max`` up to a clean tick ceiling and return the tick values. */
function ticks(max: number, count = 4): number[] {
  if (max <= 0) return [0]
  const rough = max / count
  const mag = 10 ** Math.floor(Math.log10(rough))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rough) ?? mag * 10
  const top = Math.ceil(max / step) * step
  const out: number[] = []
  for (let v = 0; v <= top + step / 2; v += step) out.push(v)
  return out
}

type AxesProps = { yTicks: number[]; yMax: number; format: (v: number) => string; size: Size }

function Axes({ yTicks, yMax, format, size }: AxesProps) {
  const { W, PLOT_H } = frame(size)
  return (
    <g className="chart-axes">
      {yTicks.map((t) => {
        const y = PAD.top + PLOT_H - (t / yMax) * PLOT_H
        return (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y} y2={y} />
            <text x={PAD.left - 8} y={y} dy="0.35em" textAnchor="end">
              {format(t)}
            </text>
          </g>
        )
      })}
    </g>
  )
}

type XLabelsProps = { series: CostBucket[]; granularity: Granularity; size: Size }

function XLabels({ series, granularity, size }: XLabelsProps) {
  const { H, PLOT_W } = frame(size)
  const n = series.length
  if (n === 0) return null
  const every = Math.max(1, Math.ceil(n / (size === 'wide' ? 6 : 3)))
  const slot = PLOT_W / n
  return (
    <g className="chart-xlabels">
      {series.map((b, i) =>
        i % every === 0 || i === n - 1 ? (
          <text key={b.bucket} x={PAD.left + slot * (i + 0.5)} y={H - 8} textAnchor="middle">
            {formatBucket(b.bucket, granularity)}
          </text>
        ) : null,
      )}
    </g>
  )
}

type TimeChartProps = {
  series: CostBucket[]
  granularity: Granularity
  metric: 'cumulative_cost' | 'cost' | 'calls'
  kind: 'line' | 'bar'
  title: string
  size?: Size
}

/**
 * Single-series chart over the time buckets. ``line`` draws a 2px line with an area
 * wash (used for the cumulative total); ``bar`` draws one column per bucket.
 */
export function TimeChart({ series, granularity, metric, kind, title, size = 'wide' }: TimeChartProps) {
  const [hover, setHover] = useState<number | null>(null)
  const { W, H, PLOT_W, PLOT_H } = frame(size)
  const isMoney = metric !== 'calls'
  const fmt = isMoney ? formatUsd : formatCount
  const tickFmt = isMoney ? formatUsdTick : formatCount
  const values = series.map((b) => b[metric])
  const yTicks = ticks(Math.max(0, ...values))
  const yMax = yTicks[yTicks.length - 1] || 1
  const n = series.length
  const slot = n ? PLOT_W / n : PLOT_W
  const x = (i: number) => PAD.left + slot * (i + 0.5)
  const y = (v: number) => PAD.top + PLOT_H - (v / yMax) * PLOT_H

  if (n === 0) {
    return (
      <figure className="chart">
        <figcaption>{title}</figcaption>
        <p className="muted">No calls in this range.</p>
      </figure>
    )
  }

  const linePath = values.map((v, i) => `${i ? 'L' : 'M'}${x(i)},${y(v)}`).join(' ')
  const areaPath = `${linePath} L${x(n - 1)},${y(0)} L${x(0)},${y(0)} Z`
  const barW = Math.min(24, Math.max(2, slot - 2))
  const hovered = hover === null ? null : series[hover]
  const tipLeft = hover === null ? 0 : (x(hover) / W) * 100

  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <div className="chart-plot">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title} onMouseLeave={() => setHover(null)}>
          <Axes yTicks={yTicks} yMax={yMax} format={tickFmt} size={size} />
          <XLabels series={series} granularity={granularity} size={size} />
          {kind === 'line' ? (
            <>
              <path className="chart-area" d={areaPath} />
              <path className="chart-line" d={linePath} />
              {hovered && <line className="chart-crosshair" x1={x(hover!)} x2={x(hover!)} y1={PAD.top} y2={y(0)} />}
              {hovered && <circle className="chart-dot" cx={x(hover!)} cy={y(values[hover!])} r={5} />}
              <circle className="chart-dot" cx={x(n - 1)} cy={y(values[n - 1])} r={4} />
            </>
          ) : (
            values.map((v, i) => (
              <rect
                key={i}
                className={hover === i ? 'chart-bar hover' : 'chart-bar'}
                x={x(i) - barW / 2}
                y={y(v)}
                width={barW}
                height={Math.max(0, y(0) - y(v))}
                rx={Math.min(4, barW / 2)}
              />
            ))
          )}
          {/* Hit targets wider than the marks, one per bucket. */}
          {series.map((_, i) => (
            <rect
              key={i}
              className="chart-hit"
              x={PAD.left + slot * i}
              y={PAD.top}
              width={slot}
              height={PLOT_H}
              onMouseEnter={() => setHover(i)}
            />
          ))}
        </svg>
        {hovered && (
          <div className="chart-tip" style={{ left: `${tipLeft}%` }}>
            <strong>{formatBucket(hovered.bucket, granularity)}</strong>
            <span>{fmt(hovered[metric])}</span>
            {metric !== 'calls' && <span className="muted">{formatCount(hovered.calls)} calls</span>}
          </div>
        )}
      </div>
    </figure>
  )
}

type BreakdownChartProps = {
  rows: CostBreakdown[]
  total: number
  title: string
  limit?: number
}

/** Horizontal bars, highest cost first; rows past ``limit`` fold into "Other". */
export function BreakdownChart({ rows, total, title, limit = 8 }: BreakdownChartProps) {
  const shown = rows.slice(0, limit)
  const rest = rows.slice(limit)
  if (rest.length) {
    shown.push({
      key: `Other (${rest.length})`,
      cost: rest.reduce((s, r) => s + r.cost, 0),
      calls: rest.reduce((s, r) => s + r.calls, 0),
      total_tokens: rest.reduce((s, r) => s + r.total_tokens, 0),
    })
  }
  const max = Math.max(0, ...shown.map((r) => r.cost))
  return (
    <figure className="chart breakdown">
      <figcaption>{title}</figcaption>
      {shown.length === 0 ? (
        <p className="muted">No calls in this range.</p>
      ) : (
        <ol className="breakdown-rows">
          {shown.map((r) => (
            <li key={r.key} title={`${formatCount(r.calls)} calls · ${formatCount(r.total_tokens)} tokens`}>
              <span className="breakdown-key">{r.key}</span>
              <span className="breakdown-bar">
                <span style={{ width: max ? `${(r.cost / max) * 100}%` : 0 }} />
              </span>
              <span className="breakdown-value">
                {formatUsd(r.cost)}
                <span className="muted"> {total ? `${((r.cost / total) * 100).toFixed(0)}%` : ''}</span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </figure>
  )
}
