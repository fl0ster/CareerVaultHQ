import { useEffect, useMemo, useRef, useState } from 'react'
import './work-history.css'
import { type WorkHistoryEntry, type WorkHistoryExport, type WorkHistoryInput, workHistoryApi } from './api.ts'
import { type Bar, formatDuration, layout, todayIndex } from './timeline-model.ts'
import { useScrollPointer } from './useScrollPointer.ts'
import WorkHistoryForm from './WorkHistoryForm.tsx'
import AddPositionComposer from './AddPositionComposer.tsx'
import WorkHistoryTimeline from './WorkHistoryTimeline.tsx'
import ApplicationSteps from './ApplicationSteps.tsx'
import { formatDay } from '../applications/api.ts'
import { candidateDetailsApi } from '../candidate-profile/api.ts'
import { candidateDetailsStore } from '../candidate-profile/store.ts'
import { isPdf, mergeDetails, parseCv } from './cvImport.ts'
import { countLabel, entryTitle, isPoint, KIND_ORDER, KINDS } from './kinds.ts'

/** "3 positions, 1 education entry and 2 certificates". */
function importedSummary(entries: { kind?: WorkHistoryEntry['kind'] }[]): string {
  const parts = KIND_ORDER.map((kind) => [kind, entries.filter((e) => (e.kind ?? 'job') === kind).length] as const)
    .filter(([, count]) => count > 0)
    .map(([kind, count]) => countLabel(count, kind))
  if (parts.length === 0) return 'nothing'
  return parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`
}

/** How often the list is reloaded while an entry is being filled in from its application. */
const PREFILL_POLL_MS = 3000

function formatMonth(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { year: 'numeric', month: 'short' })
}

function EntryCard({
  entry,
  bar,
  active,
  flash,
  open,
  cardRef,
  onToggle,
  onFlashEnd,
  onEdit,
  onDelete,
}: {
  entry: WorkHistoryEntry
  bar: Bar | undefined
  active: boolean
  flash: boolean
  open: boolean
  cardRef: (el: HTMLLIElement | null) => void
  onToggle: () => void
  onFlashEnd: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const filling = entry.prefill_state === 'queued'
  const hasDetails = !!entry.context || entry.application_id != null
  const { icon: Icon, label: kindLabel } = KINDS[entry.kind]
  const point = isPoint(entry)
  return (
    <li
      ref={cardRef}
      data-id={entry.id}
      className={`wh-item kind-${entry.kind}${bar ? ` tone-${bar.tone}` : ''}${active ? ' active' : ''}${flash ? ' flash' : ''}`}
      onAnimationEnd={(e) => {
        if (e.animationName === 'wh-flash') onFlashEnd()
      }}
    >
      <div className="wh-head">
        <div className="wh-main">
          <span className="wh-kind-badge" title={kindLabel}>
            <Icon size={13} aria-hidden="true" />
            {kindLabel}
          </span>
          <strong>{entry.role}</strong>
          {entry.employer && (entry.kind === 'certificate' ? ` · ${entry.employer}` : ` at ${entry.employer}`)}
          {entry.pending && (
            <span
              className="badge wh-pending"
              title="Not started yet: left out of your CVs and candidate profile until the start date."
            >
              Pending
            </span>
          )}
          <div className="wh-meta">
            {entry.pending ? (
              <span>
                Starts {formatDay(entry.date_start)}
                {entry.date_end ? ` – ${formatMonth(entry.date_end)}` : ''}
              </span>
            ) : point ? (
              <span>Issued {formatMonth(entry.date_start)}</span>
            ) : (
              <>
                <span>
                  {formatMonth(entry.date_start)} – {entry.date_end ? formatMonth(entry.date_end) : 'present'}
                </span>
                {bar && <span>{formatDuration(bar.end - bar.start)}</span>}
              </>
            )}
            {entry.location && <span>{entry.location}</span>}
            {entry.application_id != null && <span className="wh-origin">From an accepted offer</span>}
          </div>
          {filling && (
            <p className="wh-prefill" role="status">
              <span className="spinner" aria-hidden="true" /> Filling in the details from the application…
            </p>
          )}
          {entry.prefill_state === 'failed' && (
            <p className="wh-prefill failed">Could not fill in the details from the application. Edit them by hand.</p>
          )}
          {entry.tech.length > 0 && (
            <div className="wh-tech">
              {entry.tech.map((t) => (
                <span key={t} className="badge">{t}</span>
              ))}
            </div>
          )}
        </div>
        <div className="wh-buttons">
          {hasDetails && (
            <button type="button" className="secondary small" onClick={onToggle} aria-expanded={open}>
              {open ? 'Hide' : 'Details'}
            </button>
          )}
          <button
            type="button"
            className="secondary small"
            onClick={onEdit}
            disabled={filling}
            title={filling ? 'Available once the details are filled in' : undefined}
          >
            Edit
          </button>
          <button type="button" className="secondary small danger" onClick={onDelete}>Delete</button>
        </div>
      </div>
      {open && entry.context && <pre className="wh-context">{entry.context}</pre>}
      {open && entry.application_id != null && <ApplicationSteps applicationId={entry.application_id} />}
    </li>
  )
}

function ImportDropzone({ busy, onFile }: { busy: string | null; onFile: (file: File) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  return (
    <div
      className={`wh-dropzone${over ? ' over' : ''}${busy ? ' busy' : ''}`}
      role="button"
      tabIndex={0}
      aria-disabled={!!busy}
      onClick={() => !busy && input.current?.click()}
      onKeyDown={(e) => {
        if (busy || (e.key !== 'Enter' && e.key !== ' ')) return
        e.preventDefault()
        input.current?.click()
      }}
      onDragOver={(e) => {
        e.preventDefault()
        if (!busy) setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        const file = e.dataTransfer.files[0]
        if (file && !busy) onFile(file)
      }}
    >
      <strong role={busy ? 'status' : undefined}>
        {busy && <span className="spinner" aria-hidden="true" />}
        {busy ?? 'Your career timeline is empty'}
      </strong>
      <span>
        Drop your CV (a PDF) or a work history JSON file here, or{' '}
        <span className="wh-dropzone-link">pick one from disk</span>.
      </span>
      <span className="wh-dropzone-hint">
        A CV adds your positions, education and certificates, and fills in the blank fields of your personal details. Or add
        them by hand with the + button.
      </span>
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf,application/json,.json"
        hidden
        onChange={(ev) => {
          const file = ev.target.files?.[0]
          ev.target.value = ''
          if (file) onFile(file)
        }}
      />
    </div>
  )
}

type Mode = { kind: 'list' } | { kind: 'edit'; entry: WorkHistoryEntry }

type PageProps = {
  /** Id of an entry to scroll to and open (from the URL, e.g. right after accepting an offer). */
  focusId?: string | null
}

export default function WorkHistoryPage({ focusId = null }: PageProps) {
  const [entries, setEntries] = useState<WorkHistoryEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<Mode>({ kind: 'list' })
  const [transfer, setTransfer] = useState<{ kind: 'ok' | 'error'; text: string; notes?: string[] } | null>(null)
  /** What the dropzone is busy with (`null` when idle). */
  const [importing, setImporting] = useState<string | null>(null)
  const left = useRef(false)
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set())
  const [flashId, setFlashId] = useState<number | null>(null)
  const viewRef = useRef<HTMLDivElement>(null)
  const cardRefs = useRef(new Map<number, HTMLElement>())

  const today = useMemo(() => todayIndex(), [])
  const model = useMemo(() => (entries && entries.length > 0 ? layout(entries, today) : null), [entries, today])
  const order = useMemo(() => entries?.map((e) => e.id) ?? [], [entries])
  const emptyById = useMemo(() => new Map<number, Bar>(), [])
  const { activeId, pointer, spacer } = useScrollPointer(
    mode.kind === 'list' && !!model,
    viewRef,
    cardRefs,
    order,
    model?.byId ?? emptyById,
  )

  const toggle = (id: number, force?: boolean) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (force ?? !next.has(id)) next.add(id)
      else next.delete(id)
      return next
    })

  const selectFromTimeline = (id: number) => {
    const el = cardRefs.current.get(id)
    if (!el) return
    toggle(id, true)
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setFlashId(null)
    requestAnimationFrame(() => setFlashId(id))
  }

  const load = () =>
    workHistoryApi.list().then(
      (items) => {
        setEntries(items)
        setError(null)
      },
      (e) => setError(`Could not load your career: ${String(e instanceof Error ? e.message : e)}`),
    )

  useEffect(() => {
    load()
    left.current = false
    return () => {
      left.current = true
    }
  }, [])

  // Keep reloading while an entry is being filled in from its application in the background.
  const filling = entries?.some((e) => e.prefill_state === 'queued') ?? false
  useEffect(() => {
    if (!filling) return
    const timer = window.setTimeout(load, PREFILL_POLL_MS)
    return () => window.clearTimeout(timer)
  }, [filling, entries])

  // Bring the entry named in the URL into view once, when it is first listed.
  const focused = useRef<string | null>(null)
  useEffect(() => {
    if (focusId == null || focused.current === focusId || !entries) return
    const id = Number(focusId)
    if (!entries.some((e) => e.id === id)) return
    focused.current = focusId
    selectFromTimeline(id)
  })

  const create = async (input: WorkHistoryInput) => {
    await workHistoryApi.create(input)
    await load()
  }

  const update = (id: number) => async (input: WorkHistoryInput) => {
    await workHistoryApi.update(id, input)
    setMode({ kind: 'list' })
    await load()
  }

  const remove = async (entry: WorkHistoryEntry) => {
    const note = entry.application_id != null ? '\n\nThe application stays accepted.' : ''
    if (!window.confirm(`Delete "${entryTitle(entry)}"?${note}`)) return
    try {
      await workHistoryApi.remove(entry.id)
      await load()
    } catch (e) {
      setError(`Could not delete: ${String(e instanceof Error ? e.message : e)}`)
    }
  }

  const importJson = async (file: File) => {
    setTransfer(null)
    let items: unknown
    try {
      items = JSON.parse(await file.text())
    } catch {
      setTransfer({ kind: 'error', text: `${file.name} is not valid JSON.` })
      return
    }
    if (!Array.isArray(items) || items.length === 0) {
      setTransfer({ kind: 'error', text: `${file.name} must contain a non-empty JSON array of entries.` })
      return
    }
    setImporting('Importing…')
    try {
      const created = await workHistoryApi.importJson(items as WorkHistoryExport[], false)
      await load()
      setTransfer({
        kind: 'ok',
        text: `Imported ${importedSummary(created)} from ${file.name}.`,
      })
    } catch (e) {
      setTransfer({ kind: 'error', text: `Could not import ${file.name}: ${String(e instanceof Error ? e.message : e)}` })
    } finally {
      setImporting(null)
    }
  }

  /** Parses a CV PDF, imports its positions, education and certificates and fills the blank personal details fields. */
  const importCv = async (file: File) => {
    setTransfer(null)
    setImporting('Reading your CV… this can take a minute')
    try {
      const cv = await parseCv(file, () => left.current)
      if (cv.work_history.length === 0) {
        setTransfer({
          kind: 'error',
          text: `No positions, education or certificates were found in ${file.name}.`,
          notes: cv.warnings,
        })
        return
      }
      setImporting('Importing…')
      const created = await workHistoryApi.importJson(cv.work_history, false)
      await load()
      const notes = [...cv.warnings]
      let filledText = ''
      try {
        const { details, filled } = mergeDetails(await candidateDetailsApi.get(), cv.candidate_details)
        if (filled.length > 0) {
          candidateDetailsStore.set(await candidateDetailsApi.save(details))
          filledText = ` Filled in personal details: ${filled.join(', ')}.`
        }
      } catch (e) {
        notes.unshift(`Personal details were not updated: ${String(e instanceof Error ? e.message : e)}`)
      }
      setTransfer({
        kind: 'ok',
        text: `Imported ${importedSummary(created)} from ${file.name}.${filledText}`,
        notes,
      })
    } catch (e) {
      if (left.current) return
      setTransfer({ kind: 'error', text: `Could not import ${file.name}: ${String(e instanceof Error ? e.message : e)}` })
    } finally {
      if (!left.current) setImporting(null)
    }
  }

  return (
    <>
      {mode.kind === 'list' && entries === null && !error && <p>Loading…</p>}

      {mode.kind === 'list' && transfer && (
        <div className="wh-transfer">
          <p className={transfer.kind === 'error' ? 'error' : undefined}>
            {transfer.text}{' '}
            <button type="button" className="secondary small" onClick={() => setTransfer(null)}>
              Dismiss
            </button>
          </p>
          {transfer.notes && transfer.notes.length > 0 && (
            <details className="wh-transfer-notes">
              <summary>
                {transfer.notes.length} note{transfer.notes.length === 1 ? '' : 's'} from reading the CV
              </summary>
              <ul>
                {transfer.notes.map((note, i) => (
                  <li key={i}>{note}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {error && (
        <p className="error">
          {error}{' '}
          <button type="button" className="secondary small" onClick={load}>Retry</button>
        </p>
      )}

      {mode.kind === 'edit' && (
        <WorkHistoryForm
          key={mode.entry.id}
          initial={mode.entry}
          onSubmit={update(mode.entry.id)}
          onCancel={() => setMode({ kind: 'list' })}
        />
      )}

      {mode.kind === 'list' && entries?.length === 0 && (
        <ImportDropzone busy={importing} onFile={(file) => void (isPdf(file) ? importCv(file) : importJson(file))} />
      )}
      {mode.kind === 'list' && entries && model && (
        <div className="wh-view" ref={viewRef}>
          <WorkHistoryTimeline
            model={model}
            today={today}
            activeId={activeId}
            pointer={pointer}
            onSelect={selectFromTimeline}
          />
          <ul className="wh-list">
            {entries.map((entry) => (
              <EntryCard
                key={entry.id}
                entry={entry}
                bar={model.byId.get(entry.id)}
                active={entry.id === activeId}
                flash={entry.id === flashId}
                open={expanded.has(entry.id)}
                cardRef={(el) => {
                  if (el) cardRefs.current.set(entry.id, el)
                  else cardRefs.current.delete(entry.id)
                }}
                onToggle={() => toggle(entry.id)}
                onFlashEnd={() => setFlashId(null)}
                onEdit={() => setMode({ kind: 'edit', entry })}
                onDelete={() => remove(entry)}
              />
            ))}
          </ul>
          <div style={{ height: spacer }} aria-hidden />
        </div>
      )}

      {mode.kind === 'list' && <AddPositionComposer onSubmit={create} />}
    </>
  )
}
