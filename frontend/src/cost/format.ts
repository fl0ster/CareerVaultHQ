import type { Granularity } from './api.ts'

/** USD with enough precision for sub-cent LLM calls. */
export function formatUsd(value: number): string {
  if (value === 0) return '$0'
  const abs = Math.abs(value)
  const digits = abs >= 1 ? 2 : abs >= 0.01 ? 4 : 6
  return `$${value.toFixed(digits)}`
}

/** Axis ticks: like ``formatUsd`` but without trailing zeros (``$0.003`` not ``$0.003000``). */
export function formatUsdTick(value: number): string {
  if (value === 0) return '$0'
  return `$${parseFloat(value.toFixed(6)).toString()}`
}

export function formatCount(value: number): string {
  return value.toLocaleString()
}

export function formatCompact(value: number): string {
  return value.toLocaleString(undefined, { notation: 'compact', maximumFractionDigits: 1 })
}

export function formatBucket(iso: string, granularity: Granularity): string {
  const d = new Date(iso)
  switch (granularity) {
    case 'hour':
      return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric' })
    case 'month':
      return d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })
    default:
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }
}
