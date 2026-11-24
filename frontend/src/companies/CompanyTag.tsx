import { BriefcaseBusiness } from 'lucide-react'
import { useState } from 'react'
import CompanyLink from '../applications/CompanyLink.tsx'
import { PickerPill } from '../applications/StatusBadge.tsx'
import { describeError } from '../cv/api.ts'
import { OUTCOMES, useCompanyApplicationStats } from './applicationStats.ts'
import { useCareerCompany } from './careerCompanies.ts'
import { COMPANY_TAGS, nextTag, setCompanyTag, tagInfo, useCompanyTag } from './tags.ts'
import './tags.css'

type Props = {
  companyId: number | null | undefined
  /** The tag as loaded from the server; changes made in this session take precedence. */
  tag: string | null | undefined
  /** When given, the company name is shown inside the pill, between the tag icon and the stats. */
  name?: string
  /** Opens the company popup when the name is clicked. */
  onOpenCompany?: (companyId: number) => void
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

/** The company's tag pill. With `name`, the pill reads: tag icon | company name | career mark |
 * stats. Clicking the tag cycles the tag (none → each tag → none); the career mark (a briefcase)
 * shows when the candidate worked or works there; the right part counts the applications to the
 * company by outcome, when there are any. Safe to use inside another button. Renders nothing
 * without a company id. */
export function CompanyTagBadge({ companyId, tag, name, onOpenCompany }: Props) {
  const current = useCompanyTag(companyId, tag)
  const [error, setError] = useState<string | null>(null)
  const stats = useCompanyApplicationStats(companyId)
  const career = useCareerCompany(companyId)
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
  const statsEl = shown.length ? (
    <span className="company-app-stats">
      {shown.map((o) => (
        <span key={o.key} className={`company-app-stat ${o.key.toLowerCase()}`} title={`${o.label}: ${stats[o.key]}`}>
          <span className="company-app-stat-icon" aria-hidden="true">
            {o.icon}
          </span>
          {stats[o.key]}
        </span>
      ))}
    </span>
  ) : null
  const careerText = career
    ? `${career.current ? 'Your current employer' : 'You worked here'}: ${career.roles.join(', ')}`
    : ''
  const careerEl = career ? (
    <span className={`company-career${career.current ? ' current' : ''}`} title={careerText}>
      <BriefcaseBusiness size={12} aria-hidden="true" />
      <span className="visually-hidden">{careerText}</span>
    </span>
  ) : null
  const sep = <span className="app-status-sep" aria-hidden="true" />
  const extra =
    name != null ? (
      <>
        <span className="company-tag-name" title={name}>
          {onOpenCompany ? <CompanyLink name={name} companyId={companyId} onOpen={onOpenCompany} /> : name}
        </span>
        {careerEl}
        {statsEl && (
          <>
            {sep}
            {statsEl}
          </>
        )}
      </>
    ) : careerEl || statsEl ? (
      <>
        {careerEl}
        {careerEl && statsEl && sep}
        {statsEl}
      </>
    ) : null
  const tagTitle = info ? info.label : 'No tag'

  return (
    <>
      <PickerPill
        className={`badge company-tag ${info ? `tag-${info.key}` : 'none'}`}
        options={OPTIONS}
        currentKey={current ?? NONE}
        nextKey={nextTag(current) ?? NONE}
        onSelect={select}
        extra={extra}
        title={error ? `Could not save the tag: ${error}` : `${tagTitle} — click to change`}
      >
        <span aria-hidden="true">{info?.icon ?? '☆'}</span>
        <span className="visually-hidden">{tagTitle}</span>
      </PickerPill>
      {error && <span className="error company-tag-error"> Not saved</span>}
    </>
  )
}
