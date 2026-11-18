import { useState } from 'react'
import { PickerPill } from '../applications/StatusBadge.tsx'
import { describeError } from '../cv/api.ts'
import { OUTCOMES, useCompanyApplicationStats } from './applicationStats.ts'
import { COMPANY_TAGS, nextTag, setCompanyTag, tagInfo, useCompanyTag } from './tags.ts'
import './tags.css'

type Props = {
  companyId: number | null | undefined
  /** The tag as loaded from the server; changes made in this session take precedence. */
  tag: string | null | undefined
}

const NONE = ''

const pill = (key: string) => {
  const info = tagInfo(key)
  return info ? (
    <span className={`badge company-tag tag-${info.key}`}>
      <span aria-hidden="true">{info.icon}</span> {info.label}
    </span>
  ) : (
    <span className="badge company-tag none">
      <span aria-hidden="true">☆</span> No tag
    </span>
  )
}

const OPTIONS = [...COMPANY_TAGS.map((t) => t.key), NONE].map((key) => ({
  key,
  text: tagInfo(key)?.label ?? 'no tag',
  label: pill(key),
}))

/** The company's tag pill. Clicking it cycles the tag (none → each tag → none); its right part
 * counts the applications to the company by outcome, when there are any. Safe to use inside
 * another button. Renders nothing without a company id. */
export function CompanyTagBadge({ companyId, tag }: Props) {
  const current = useCompanyTag(companyId, tag)
  const [error, setError] = useState<string | null>(null)
  const stats = useCompanyApplicationStats(companyId)
  if (companyId == null) return null

  const info = tagInfo(current)
  const select = async (key: string) => {
    setError(null)
    try {
      await setCompanyTag(companyId, key || null, current)
    } catch (err) {
      setError(describeError(err))
    }
  }

  const shown = OUTCOMES.filter((o) => (stats[o.key] ?? 0) > 0)
  const extra = shown.length ? (
    <span className="company-app-stats">
      {shown.map((o) => (
        <span key={o.key} className={`company-app-stat ${o.key.toLowerCase()}`} title={`${o.label}: ${stats[o.key]}`}>
          <span aria-hidden="true">{o.icon}</span>
          {stats[o.key]}
        </span>
      ))}
    </span>
  ) : null

  return (
    <>
      <PickerPill
        className={`badge company-tag ${info ? `tag-${info.key}` : 'none'}`}
        options={OPTIONS}
        currentKey={current ?? NONE}
        nextKey={nextTag(current) ?? NONE}
        onSelect={select}
        extra={extra}
        title={error ? `Could not save the tag: ${error}` : undefined}
      >
        <span aria-hidden="true">{info?.icon ?? '☆'}</span> {info?.label ?? ''}
      </PickerPill>
      {error && <span className="error company-tag-error"> Not saved</span>}
    </>
  )
}
