import { percent } from './api.ts'

export default function ScoreBadge({ probability, threshold }: { probability: number; threshold: number }) {
  const value = percent(probability)
  return (
    <span
      className={value >= threshold ? 'score match' : 'score'}
      title={`${value}% match (threshold ${threshold}%)`}
    >
      {value}%
    </span>
  )
}
