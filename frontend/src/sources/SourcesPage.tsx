import { useEffect, useState } from 'react'
import { MIN_SCRAPE_INTERVAL_SECONDS, sourcesApi, type Source, type SourceUpdate } from './api.ts'
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

/** Seconds as hours for the interval editor, e.g. 5400 -> "1.5". */
function toHours(seconds: number | null): string {
  return seconds === null ? '' : String(Math.round((seconds / 3600) * 100) / 100)
}

function formatInterval(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600} h`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  return `${Math.floor(seconds / 3600)} h ${Math.round((seconds % 3600) / 60)} min`
}

type Props = { source: Source; busy: boolean; onChange: (s: Source) => void; onScrape: () => void; onError: (m: string) => void }

function SourceRow({ source, busy, onChange, onScrape, onError }: Props) {
  const [saving, setSaving] = useState(false)
  // Reset the editor when the row is refreshed from the server (derived-state pattern).
  const [intervalHours, setIntervalHours] = useState(toHours(source.scrape_interval_seconds))
  const [seenInterval, setSeenInterval] = useState(source.scrape_interval_seconds)
  if (seenInterval !== source.scrape_interval_seconds) {
    setSeenInterval(source.scrape_interval_seconds)
    setIntervalHours(toHours(source.scrape_interval_seconds))
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

  const commitInterval = () => {
    const reset = () => setIntervalHours(toHours(source.scrape_interval_seconds))
    if (intervalHours.trim() === '') {
      if (source.scrape_interval_seconds !== null) save({ scrape_interval_seconds: null })
      return
    }
    const hours = Number.parseFloat(intervalHours)
    if (!Number.isFinite(hours)) return reset()
    const seconds = Math.round(hours * 3600)
    if (seconds < MIN_SCRAPE_INTERVAL_SECONDS) {
      onError(`The scrape interval must be at least ${MIN_SCRAPE_INTERVAL_SECONDS / 60} minutes.`)
      return reset()
    }
    if (seconds !== source.scrape_interval_seconds) save({ scrape_interval_seconds: seconds })
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
        <div className="schedule">
          <input
            type="number"
            className="interval"
            min={MIN_SCRAPE_INTERVAL_SECONDS / 3600}
            step="any"
            value={intervalHours}
            placeholder={toHours(source.default_scrape_interval_seconds)}
            disabled={saving}
            onChange={(e) => setIntervalHours(e.target.value)}
            onBlur={commitInterval}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
            }}
            aria-label={`${source.name} scrape interval in hours`}
            title="Hours between scheduled scrapes; empty uses the default"
          />
          <span className="muted">h</span>
        </div>
        <div className="muted">
          {source.scrape_interval_seconds === null &&
            `default ${formatInterval(source.default_scrape_interval_seconds)} · `}
          {!source.enabled || broken
            ? 'not scheduled'
            : source.next_scrape_at
              ? `next ${when(source.next_scrape_at)}`
              : 'planning…'}
        </div>
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
              <th>Every</th>
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
