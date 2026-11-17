import { useState } from 'react'
import { describeError } from '../cv/api.ts'
import { nextTag, setCompanyTag, tagInfo, useCompanyTag } from './tags.ts'

type Props = {
  companyId: number | null | undefined
  /** The tag as loaded from the server; changes made in this session take precedence. */
  tag: string | null | undefined
}

/** Read-only pill with the company's tag; renders nothing when it has none. */
export function CompanyTagBadge({ companyId, tag }: Props) {
  const info = tagInfo(useCompanyTag(companyId, tag))
  if (!info) return null
  return (
    <span className={`badge company-tag tag-${info.key}`}>
      <span aria-hidden="true">{info.icon}</span> {info.label}
    </span>
  )
}

/** Icon button that cycles the company's tag (none → each tag → none), followed by the tag
 * pill. Not for use inside another button: there, use ``CompanyTagBadge``. */
export function CompanyTagToggle({ companyId, tag }: Props) {
  const current = useCompanyTag(companyId, tag)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (companyId == null) return null

  const info = tagInfo(current)
  const next = tagInfo(nextTag(current))
  const hint = `${info ? `Tag: ${info.label}` : 'No tag'} — click for ${next ? next.label : 'no tag'}`

  const cycle = async (e: React.MouseEvent) => {
    e.stopPropagation()
    setBusy(true)
    setError(null)
    try {
      await setCompanyTag(companyId, nextTag(current), current)
    } catch (err) {
      setError(describeError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="company-tag-control">
      <button
        type="button"
        className={`company-tag-toggle ${info ? `tag-${info.key}` : 'none'}`}
        onClick={cycle}
        disabled={busy}
        title={error ? `Could not save the tag: ${error}` : hint}
        aria-label={hint}
      >
        {info?.icon ?? '☆'}
      </button>
      <CompanyTagBadge companyId={companyId} tag={current} />
      {error && <span className="error company-tag-error">Not saved</span>}
    </span>
  )
}
