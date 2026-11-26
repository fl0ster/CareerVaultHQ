import { Check } from 'lucide-react'
import { useEffect, useState } from 'react'
import { workHistoryApi } from '../work-history/api.ts'

/** Comparable form of a technology name: case, spaces and punctuation other than `+` / `#`
 * are ignored, so "Node.js", "NodeJS" and "node js" match while "C++" and "C#" stay apart. */
function techKey(name: string): string {
  return name.toLowerCase().replace(/[^\p{L}\p{N}+#]/gu, '')
}

/** Keys of every technology named in at least one work history entry (empty until loaded,
 * or when the work history cannot be loaded: the pills then simply show no highlight). */
function useUserTech(): Set<string> {
  const [keys, setKeys] = useState<Set<string>>(() => new Set())
  useEffect(() => {
    let cancelled = false
    workHistoryApi
      .list()
      .then((entries) => {
        if (cancelled) return
        // Positions that have not started yet are not experience (yet); education and
        // certificates are not positions.
        const started = entries.filter((e) => e.kind === 'job' && !e.pending)
        // A position's own technologies, else those from its work journal.
        const tech = started.flatMap((e) => (e.tech.length ? e.tech : e.journal_tech))
        setKeys(new Set(tech.map(techKey).filter(Boolean)))
      })
      .catch(() => {
        /* the highlight is optional */
      })
    return () => {
      cancelled = true
    }
  }, [])
  return keys
}

/** The job's technologies; those in the user's tech stack (work history) are highlighted. */
export default function TechPills({ technologies }: { technologies: string[] }) {
  const known = useUserTech()
  if (technologies.length === 0) return null
  return (
    <ul className="job-tech" aria-label="Technologies">
      {technologies.map((name) => {
        const mine = known.has(techKey(name))
        return (
          <li
            key={name}
            className={mine ? 'badge job-tech-pill mine' : 'badge job-tech-pill'}
            title={mine ? 'In your tech stack' : undefined}
          >
            {mine && <Check size={12} strokeWidth={3} aria-hidden="true" />}
            {name}
            {mine && <span className="sr-only"> (in your tech stack)</span>}
          </li>
        )
      })}
    </ul>
  )
}
