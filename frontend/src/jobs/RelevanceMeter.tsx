/** Diverging bar for a relevance in [-1, 1]: it grows right of the centre line above
 * the threshold and left of it below. No numbers; the exact value is in the tooltip. */
export default function RelevanceMeter({ relevance }: { relevance: number }) {
  const value = Math.max(-1, Math.min(1, relevance))
  const width = `${Math.abs(value) * 50}%`
  const above = value > 0
  const label = above ? 'Above the relevance threshold' : value < 0 ? 'Below the relevance threshold' : 'At the relevance threshold'
  return (
    <span
      className={above ? 'relevance above' : 'relevance'}
      role="meter"
      aria-valuemin={-1}
      aria-valuemax={1}
      aria-valuenow={value}
      aria-label={label}
      title={`${label} (${value > 0 ? '+' : ''}${value.toFixed(2)})`}
    >
      <span className="relevance-fill" style={above ? { left: '50%', width } : { right: '50%', width }} />
    </span>
  )
}
