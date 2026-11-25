import { useState } from 'react'
import ApplicationsLayout from './ApplicationsLayout.tsx'
import ApplicationStatusControl from './ApplicationStatusControl.tsx'
import { type ApplicationPageProps, useApplicationList } from './useApplicationList.ts'

/** Every application, filterable by status. */
export default function ApplicationsPage({ detailId, version, onOpen, onBack, onCrumbsChange }: ApplicationPageProps) {
  const [filter, setFilter] = useState('')
  const list = useApplicationList({ status: filter || undefined, detailId, version, onBack, onCrumbsChange })
  const { statuses, counts } = list

  return (
    <ApplicationsLayout
      list={list}
      onOpen={onOpen}
      onBack={onBack}
      filters={
        <select
          className="app-status-filter"
          aria-label="Filter by status"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="">All statuses</option>
          {statuses.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
              {!filter && counts.has(s.key) ? ` (${counts.get(s.key)})` : ''}
            </option>
          ))}
        </select>
      }
      emptyText={
        filter
          ? 'No applications with this status.'
          : 'No applications yet. Open a job on the Jobs tab and choose "Create application".'
      }
      renderActions={(a) => (
        <ApplicationStatusControl application={a} statuses={statuses} onChange={list.replace} onError={list.setError} />
      )}
    />
  )
}
