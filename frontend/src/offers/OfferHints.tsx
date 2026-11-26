import { type LucideIcon, Sparkles, ThumbsUp, TriangleAlert, Trophy } from 'lucide-react'
import type { OfferHint, OfferHints as Hints } from '../applications/api.ts'

const KINDS: Record<OfferHint['kind'] | 'watch', { label: string; icon: LucideIcon; title: string }> = {
  best: { label: 'Best', icon: Trophy, title: 'Better than every other offer on this' },
  unique: { label: 'Only here', icon: Sparkles, title: 'None of the other offers has this' },
  strength: { label: 'Strength', icon: ThumbsUp, title: 'A strong point of this offer' },
  watch: { label: 'Watch out', icon: TriangleAlert, title: 'Worth weighing before you accept' },
}

function Hint({ kind, text }: { kind: keyof typeof KINDS; text: string }) {
  const { label, icon: Icon, title } = KINDS[kind]
  return (
    <li className={`offer-hint ${kind}`}>
      <span className="offer-hint-kind" title={title}>
        <Icon size={13} aria-hidden="true" />
        {label}
      </span>
      <span className="offer-hint-text">{text}</span>
    </li>
  )
}

type Props = {
  hints: Hints | undefined
  loading: boolean
}

/** What makes the offer stand out against the others, as AI-written one-liners: its best and
 * unique points first, then the one trade-off to weigh. */
export default function OfferHints({ hints, loading }: Props) {
  const empty = !hints || (hints.highlights.length === 0 && !hints.watch_out)
  if (empty && !loading) return null

  return (
    <section className="offer-hints" aria-busy={loading}>
      <span className="offer-hints-label">Why this offer</span>
      {empty ? (
        <div className="offer-hints-skeleton" aria-label="Comparing offers…">
          <span />
          <span />
        </div>
      ) : (
        <ul>
          {hints.highlights.map((h, i) => (
            <Hint key={i} kind={h.kind} text={h.text} />
          ))}
          {hints.watch_out && <Hint kind="watch" text={hints.watch_out} />}
        </ul>
      )}
    </section>
  )
}
