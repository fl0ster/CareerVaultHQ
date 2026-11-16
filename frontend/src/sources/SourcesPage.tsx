import { useEffect, useState } from 'react'
import { sourcesApi, type Source, type SourceUpdate } from './api.ts'
import { useScrapeJob } from '../tools/useScrapeJob.ts'
import './sources.css'

const HEALTH_LABEL: Record<Source['health'], string> = {
  unknown: 'never run',
  healthy: 'healthy',
  degraded: 'degraded',
  failing: 'failing',
  broken: 'broken',
}

function percent(value: number | null): string {
  return value === null ? '—' : `${Math.round(value * 100)}%`
}

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

type Props = { source: Source; busy: boolean; onChange: (s: Source) => void; onScrape: () => void; onError: (m: string) => void }

function SourceRow({ source, busy, onChange, onScrape, onError }: Props) {
  const [priority, setPriority] = useState(String(source.priority))
  const [saving, setSaving] = useState(false)
  // Reset the editor when the row is refreshed from the server (derived-state pattern).
  const [seenPriority, setSeenPriority] = useState(source.priority)
  if (seenPriority !== source.priority) {
    setSeenPriority(source.priority)
    setPriority(String(source.priority))
  }

  const save = async (patch: SourceUpdate) => {
    setSaving(true)
    try {
      onChange(await sourcesApi.update(source.key, patch))
    } catch (e) {
      onError(`Could not update ${source.name}: ${String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  const commitPriority = () => {
    const n = Number.parseInt(priority, 10)
    if (Number.isNaN(n)) {
      setPriority(String(source.priority))
      return
    }
    if (n !== source.priority) save({ priority: n })
  }

  const broken = source.module_error !== null
  const title = source.module_error ?? source.last_error ?? undefined
  const rel = source.relevance

  return (
    <tr className={source.enabled ? undefined : 'disabled'}>
      <td>
        <div className="source-name">
          {source.url ? (
            <a href={source.url} target="_blank" rel="noreferrer">{source.name}</a>
          ) : (
            source.name
          )}
          <code>{source.key}</code>
        </div>
      </td>
      <td>
        <input
          type="checkbox"
          checked={source.enabled}
          disabled={saving}
          onChange={(e) => save({ enabled: e.target.checked })}
          aria-label={`${source.name} enabled`}
        />
      </td>
      <td>
        <span className={`badge health-${source.health}`} title={title}>
          {HEALTH_LABEL[source.health]}
        </span>
        {source.consecutive_failures > 0 && (
          <span className="muted"> ×{source.consecutive_failures}</span>
        )}
        {title && <div className="source-error">{title}</div>}
      </td>
      <td>
        {when(source.last_run_at)}
        {source.last_run_at && (
          <div className="muted">
            {source.last_scraped_count ?? 0} scraped, {source.last_new_count ?? 0} new
          </div>
        )}
      </td>
      <td>
        {rel.evaluated_count > 0 ? (
          <>
            <strong>{percent(rel.avg_match)}</strong> avg
            <div className="muted">
              {percent(rel.good_match_share)} good · {rel.evaluated_count}/{rel.job_count} scored
            </div>
          </>
        ) : (
          <span className="muted">{rel.job_count} jobs, none scored</span>
        )}
      </td>
      <td>
        <input
          type="number"
          className="priority"
          value={priority}
          disabled={saving}
          onChange={(e) => setPriority(e.target.value)}
          onBlur={commitPriority}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
          }}
          aria-label={`${source.name} priority`}
        />
      </td>
      <td>
        <button type="button" className="secondary" disabled={busy || broken} onClick={onScrape}>
          Scrape
        </button>
      </td>
    </tr>
  )
}

export default function SourcesPage() {
  const [sources, setSources] = useState<Source[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)
  const { job, error: jobError, done, running, start } = useScrapeJob()
  // Health and counts change once a scrape finishes, so a finished job id reloads the list.
  const finishedJob = done ? job?.job_id : null

  useEffect(() => {
    const controller = new AbortController()
    sourcesApi
      .list(controller.signal)
      .then((rows) => {
        setSources(rows)
        setError(null)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(`Could not load sources: ${String(e)}`)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoaded(true)
      })
    return () => controller.abort()
  }, [refresh, finishedJob])

  const replace = (row: Source) =>
    setSources((prev) => prev.map((s) => (s.key === row.key ? row : s)))

  const shownError = error ?? jobError

  return (
    <>
      <h1 className="title">Scrape sources</h1>
      <p>
        One row per scraper module in <code>app/tasks/scrape/sources/</code>. Disabled sources are
        skipped by "scrape all" but can still be run here. Higher priority runs first. Relevance is
        how the source's jobs score against the current candidate profile.
      </p>

      <div className="sources-toolbar">
        <button type="button" disabled={running} onClick={() => start(null)}>
          {running ? 'Scraping…' : 'Scrape all enabled'}
        </button>
        <button type="button" className="secondary" onClick={() => setRefresh((n) => n + 1)}>
          Refresh
        </button>
        {job && (
          <span className="muted">
            {job.source ?? 'all'}: <span className={`badge ${job.status}`}>{job.status}</span>
            {!done && <span className="spinner" aria-hidden="true" />}
            {job.status === 'finished' && ` ${job.count ?? 0} jobs`}
          </span>
        )}
      </div>

      {shownError && <p className="error">{shownError}</p>}

      {loaded && sources.length === 0 ? (
        <p>No sources found. Add a module to the sources package and refresh.</p>
      ) : (
        <table className="sources">
          <thead>
            <tr>
              <th>Source</th>
              <th>On</th>
              <th>Health</th>
              <th>Last run</th>
              <th>Relevance</th>
              <th>Priority</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sources.map((s) => (
              <SourceRow
                key={s.key}
                source={s}
                busy={running}
                onChange={replace}
                onScrape={() => start(s.key)}
                onError={setError}
              />
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}
