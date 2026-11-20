import { useEffect, useState, type CSSProperties } from 'react'

const PIECES = 70
const DURATION_MS = 2100
const COLORS = [
  'var(--accent)',
  'var(--success-solid)',
  'var(--warn-solid)',
  'var(--info-solid)',
  'var(--danger-solid)',
  'var(--lavender-fg)',
]

type Piece = { id: number; style: CSSProperties }

const makePieces = (): Piece[] =>
  Array.from({ length: PIECES }, (_, id) => {
    const fall = 1300 + Math.random() * 400
    // Each piece starts fading at its own point of the fall and is gone as the fall ends.
    const fadeStart = fall * (0.3 + Math.random() * 0.45)
    return {
      id,
      style: {
        '--x': `${Math.random() * 100}%`,
        // Scattered start heights and times, so the burst doesn't begin as one band at the top.
        '--y': `${-30 + Math.random() * 180}px`,
        '--drift': `${(Math.random() - 0.5) * 160}px`,
        '--spin': `${(Math.random() < 0.5 ? -1 : 1) * (360 + Math.random() * 720)}deg`,
        '--delay': `${Math.random() * 400}ms`,
        '--fall': `${fall}ms`,
        '--fade-delay': `${fadeStart}ms`,
        '--fade': `${fall - fadeStart}ms`,
        '--w': `${5 + Math.random() * 5}px`,
        '--h': `${8 + Math.random() * 7}px`,
        '--color': COLORS[id % COLORS.length],
      } as CSSProperties,
    }
  })

/** A short confetti burst over its (positioned) parent. Remount with a new key to replay. */
export default function Confetti() {
  const [pieces] = useState(makePieces)
  const [done, setDone] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)

  useEffect(() => {
    if (done) return
    const timer = window.setTimeout(() => setDone(true), DURATION_MS + 400)
    return () => window.clearTimeout(timer)
  }, [done])

  if (done) return null
  return (
    <div className="confetti" aria-hidden="true">
      {pieces.map((p) => (
        <span key={p.id} className="confetti-piece" style={p.style} />
      ))}
    </div>
  )
}
