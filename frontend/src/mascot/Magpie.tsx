import { useId } from 'react'
import './mascot.css'

export type Mood = 'idle' | 'working' | 'queued' | 'error' | 'loading'

type Props = {
  mood?: Mood
  /** Rendered width and height in px. */
  size?: number
  /** Only the head, for the brand mark. Never animated. */
  head?: boolean
  className?: string
}

/**
 * The CareerVault magpie: a round, flat-coloured bird in the spirit of the Suica penguin.
 * Each part has its own class so mascot.css can animate it per mood.
 */
export default function Magpie({ mood = 'idle', size = 48, head = false, className = '' }: Props) {
  const uid = useId().replace(/:/g, '')
  const sheen = `mg-sheen-${uid}`
  const tail = `mg-tail-${uid}`
  const clip = `mg-clip-${uid}`

  return (
    <svg
      className={`magpie ${head ? 'magpie-head' : `mood-${mood}`} ${className}`}
      width={size}
      height={size}
      viewBox={head ? '3 15 54 54' : '0 0 120 120'}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={sheen} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--mag-ink-2)" />
          <stop offset="1" stopColor="var(--mag-sheen)" />
        </linearGradient>
        <linearGradient id={tail} x1="0.8" y1="0" x2="0.2" y2="1">
          <stop offset="0" stopColor="var(--mag-sheen)" />
          <stop offset="0.5" stopColor="var(--mag-sheen-2)" />
          <stop offset="1" stopColor="var(--mag-ink-2)" />
        </linearGradient>
      </defs>

      {!head && <ellipse className="mg-shadow" cx="52" cy="106" rx="24" ry="3.2" />}

      <g className="mg-bird">
        {!head && (
          <>
            {/* The long, graduated tail: the most magpie thing about a magpie */}
            <g className="mg-tail">
              <path
                d="M60 73 C75 62 90 50 104 39 C108 35 115 38 113 44 C106 60 91 75 72 85 Z"
                fill={`url(#${tail})`}
              />
              <path d="M72 78 C84 68 96 56 108 43" stroke="var(--mag-white)" strokeOpacity="0.28" strokeWidth="1.5" fill="none" strokeLinecap="round" />
            </g>
            <g className="mg-feet" stroke="var(--mag-feet)" strokeWidth="2.4" strokeLinecap="round" fill="none">
              <path d="M43 87 v17 M39.5 104 h7.5" />
              <path d="M54 89 v15 M50.5 104 h7.5" />
            </g>
          </>
        )}

        <g className="mg-body">
          {!head && (
            <>
              <clipPath id={clip}>
                <ellipse cx="50" cy="68" rx="24" ry="20" transform="rotate(20 50 68)" />
              </clipPath>
              <ellipse className="mg-ink" cx="50" cy="68" rx="24" ry="20" transform="rotate(20 50 68)" />
              <ellipse className="mg-ink" cx="40" cy="55" rx="14" ry="11" />
              {/* White underside, clipped to the body */}
              <g clipPath={`url(#${clip})`}>
                <ellipse className="mg-belly" cx="38" cy="82" rx="22" ry="14" transform="rotate(20 38 82)" />
              </g>
            </>
          )}
          <circle className="mg-ink" cx="36" cy="40" r="19.5" />
          {/* Gloss on the crown */}
          <path d="M24 28 Q31 21 41 21" stroke="var(--mag-white)" strokeOpacity="0.22" strokeWidth="3" fill="none" strokeLinecap="round" />

          {!head && (
            <g className="mg-wing">
              <ellipse cx="58" cy="66" rx="16.5" ry="9.5" transform="rotate(24 58 66)" fill={`url(#${sheen})`} />
              {/* White shoulder patch */}
              <ellipse cx="52.5" cy="60.5" rx="10.5" ry="3.9" transform="rotate(24 52.5 60.5)" fill="var(--mag-white)" />
            </g>
          )}

          <g className="mg-face">
            <path className="mg-beak" d="M18 36.5 Q11.5 39.5 4.5 42.5 Q11.5 45.5 18 47.5 Z" />
            <ellipse className="mg-cheek" cx="25" cy="47.5" rx="3.6" ry="2.3" />
            <ellipse className="mg-cheek" cx="44.5" cy="46.5" rx="3.6" ry="2.3" />
            <g className="mg-eyes">
              <g className="mg-eye">
                <circle cx="28.5" cy="38" r="5" fill="var(--mag-white)" />
                <circle cx="27.7" cy="38.6" r="3.25" fill="#141c23" />
                <circle cx="28.9" cy="37.2" r="1.1" fill="#fff" />
              </g>
              <g className="mg-eye">
                <circle cx="41.5" cy="37" r="5" fill="var(--mag-white)" />
                <circle cx="40.7" cy="37.6" r="3.25" fill="#141c23" />
                <circle cx="41.9" cy="36.2" r="1.1" fill="#fff" />
              </g>
            </g>
            <g className="mg-brows" stroke="var(--mag-white)" strokeWidth="1.8" strokeLinecap="round">
              <path d="M23.5 30.5 L31.5 29" />
              <path d="M38 28 L45.5 30" />
            </g>
          </g>
        </g>
      </g>

      {/* Mood props */}
      {!head && mood === 'working' && (
        <g className="mg-prop mg-paper">
          <rect x="0" y="85" width="21" height="20" rx="3.5" fill="var(--surface)" stroke="var(--border-strong)" />
          <path className="mg-line l1" d="M4.5 91.5 h12" />
          <path className="mg-line l2" d="M4.5 96 h9" />
          <path className="mg-line l3" d="M4.5 100.5 h11" />
        </g>
      )}
      {!head && mood === 'queued' && (
        <g className="mg-prop mg-letters">
          <g className="mg-letter" transform="translate(-3 93)">
            <rect width="24" height="13" rx="2.5" fill="var(--peach-bg)" stroke="var(--border-strong)" />
            <path d="M1.5 1.5 L12 8 L22.5 1.5" stroke="var(--border-strong)" fill="none" />
          </g>
          <g className="mg-letter" transform="translate(-1 82) rotate(-6)">
            <rect width="24" height="13" rx="2.5" fill="var(--lavender-bg)" stroke="var(--border-strong)" />
            <path d="M1.5 1.5 L12 8 L22.5 1.5" stroke="var(--border-strong)" fill="none" />
          </g>
        </g>
      )}
      {!head && mood === 'error' && (
        <path className="mg-prop mg-drop" d="M60 20 C60 20 54.5 27.5 54.5 31 A5.5 5.5 0 0 0 65.5 31 C65.5 27.5 60 20 60 20 Z" />
      )}
      {!head && (
        <g className="mg-sparkles" aria-hidden="true">
          <path className="mg-spark s1" d="M10 22 l2 -6 l2 6 l6 2 l-6 2 l-2 6 l-2 -6 l-6 -2 Z" />
          <path className="mg-spark s2" d="M98 16 l1.5 -4.5 l1.5 4.5 l4.5 1.5 l-4.5 1.5 l-1.5 4.5 l-1.5 -4.5 l-4.5 -1.5 Z" />
          <path className="mg-spark s3" d="M64 16 l1.2 -3.6 l1.2 3.6 l3.6 1.2 l-3.6 1.2 l-1.2 3.6 l-1.2 -3.6 l-3.6 -1.2 Z" />
        </g>
      )}
    </svg>
  )
}
