import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import './work-history.css'
import { type WorkHistoryEntry, type WorkHistoryExport, type WorkHistoryInput, workHistoryApi } from './api.ts'
import { type Bar, layout, todayIndex } from './timeline-model.ts'
import { useScrollPointer } from './useScrollPointer.ts'
import AddPositionComposer from './AddPositionComposer.tsx'
import WorkHistoryTimeline from './WorkHistoryTimeline.tsx'
import EntryDetail, { EntryPeriod, Organisation, PrefillStatus } from './EntryDetail.tsx'
import type { Crumb } from '../shell/nav.ts'
import CompanyDialog from '../companies/CompanyDialog.tsx'
import { candidateDetailsApi } from '../candidate-profile/api.ts'
import { candidateDetailsStore } from '../candidate-profile/store.ts'
import { isPdf, mergeDetails, parseCv } from './cvImport.ts'
import { countLabel, entryTitle, KIND_ORDER, KINDS } from './kinds.ts'

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

/** One row of the career list; clicking it opens the entry's details. */
function EntryCard({
  entry,
  bar,
  active,
  cardRef,
  onOpen,
  onOpenCompany,
}: {
  entry: WorkHistoryEntry
  bar: Bar | undefined
  active: boolean
  cardRef: (el: HTMLLIElement | null) => void
  onOpen: () => void
  onOpenCompany: (companyId: number) => void
}) {
  const { icon: Icon, label: kindLabel } = KINDS[entry.kind]
  return (
    <li
      ref={cardRef}
      data-id={entry.id}
      className={`wh-item kind-${entry.kind}${bar ? ` tone-${bar.tone}` : ''}${active ? ' active' : ''}`}
      role="link"
      tabIndex={0}
      aria-label={`${entryTitle(entry)}: open details`}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget || (e.key !== 'Enter' && e.key !== ' ')) return
        e.preventDefault()
        onOpen()
      }}
    >
      {entry.kind !== 'job' && (
        <span className="wh-kind-strip" title={kindLabel} aria-label={kindLabel}>
          <Icon size={11} aria-hidden="true" />
        </span>
      )}
      <div className="wh-main">
        <div className="wh-title">
          <strong>{entry.role}</strong>
          <Organisation entry={entry} onOpenCompany={onOpenCompany} />
          {entry.pending && (
            <span
              className="badge wh-pending"
              title="Not started yet: left out of your CVs and candidate profile until the start date."
            >
              Pending
            </span>
          )}
        </div>
        <div className="wh-meta">
          <EntryPeriod entry={entry} bar={bar} />
          {entry.location && <span>{entry.location}</span>}
          {entry.application_id != null && <span className="wh-origin">From an accepted offer</span>}
        </div>
        <PrefillStatus entry={entry} />
      </div>
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

type PageProps = {
  /** Id of the entry whose details are open (from the URL, e.g. right after accepting an offer). */
  detailId?: string | null
  onOpen: (id: number) => void
  onBack: () => void
  onCrumbsChange: (crumbs: Crumb[]) => void
}

export default function WorkHistoryPage({ detailId = null, onOpen, onBack, onCrumbsChange }: PageProps) {
  const [entries, setEntries] = useState<WorkHistoryEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [transfer, setTransfer] = useState<{ kind: 'ok' | 'error'; text: string; notes?: string[] } | null>(null)
  /** What the dropzone is busy with (`null` when idle). */
  const [importing, setImporting] = useState<string | null>(null)
  const left = useRef(false)
  /** Company shown in the company popup. */
  const [companyId, setCompanyId] = useState<number | null>(null)
  const viewRef = useRef<HTMLDivElement>(null)
  const cardRefs = useRef(new Map<number, HTMLElement>())

  const today = useMemo(() => todayIndex(), [])
  const model = useMemo(() => (entries && entries.length > 0 ? layout(entries, today) : null), [entries, today])
  const order = useMemo(() => entries?.map((e) => e.id) ?? [], [entries])
  const emptyById = useMemo(() => new Map<number, Bar>(), [])
  const listMode = detailId == null
  const openIndex = !listMode && entries ? entries.findIndex((e) => String(e.id) === detailId) : -1
  const open = entries && openIndex >= 0 ? entries[openIndex] : null
  const { activeId, pointer, spacer } = useScrollPointer(
    listMode && !!model,
    viewRef,
    cardRefs,
    order,
    model?.byId ?? emptyById,
  )

  // Publish the sticky page heading's height so the timeline can stick just below it.
  const hasView = !!model
  useLayoutEffect(() => {
    const view = viewRef.current
    const host = view?.closest('.view')
    const head = host?.querySelector<HTMLElement>(':scope > .page-header')
    if (!view || !head) return
    const update = () => view.style.setProperty('--wh-head-h', `${head.offsetHeight}px`)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(head)
    return () => ro.disconnect()
  }, [hasView])

  // The open entry is the breadcrumb after "My Career".
  const crumb = listMode ? null : open ? entryTitle(open) : entries ? 'Not found' : null
  useEffect(() => {
    onCrumbsChange(crumb ? [{ label: crumb }] : [])
  }, [crumb, onCrumbsChange])
  useEffect(() => () => onCrumbsChange([]), [onCrumbsChange])

  // Opening an entry starts its details at the top of the page.
  useEffect(() => {
    if (detailId != null) window.scrollTo({ top: 0 })
  }, [detailId])

  // Back on the list: bring the entry that was open into view.
  const lastOpen = useRef<number | null>(null)
  useEffect(() => {
    if (open) {
      lastOpen.current = open.id
      return
    }
    if (!listMode || lastOpen.current == null) return
    cardRefs.current.get(lastOpen.current)?.scrollIntoView({ block: 'start' })
    lastOpen.current = null
  }, [open, listMode])

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

  const create = async (input: WorkHistoryInput) => {
    await workHistoryApi.create(input)
    await load()
  }

  const update = (id: number) => async (input: WorkHistoryInput) => {
    await workHistoryApi.update(id, input)
    await load()
  }

  const remove = async (entry: WorkHistoryEntry) => {
    const note = entry.application_id != null ? '\n\nThe application stays accepted.' : ''
    if (!window.confirm(`Delete "${entryTitle(entry)}"?${note}`)) return
    try {
      await workHistoryApi.remove(entry.id)
      onBack()
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
      {entries === null && !error && <p>Loading…</p>}

      {listMode && transfer && (
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

      {listMode && entries?.length === 0 && (
        <ImportDropzone busy={importing} onFile={(file) => void (isPdf(file) ? importCv(file) : importJson(file))} />
      )}
      {!listMode && entries && !open && (
        <div className="detail-view">
          <button type="button" className="secondary small detail-back" onClick={onBack}>
            <ArrowLeft size={15} aria-hidden="true" /> Back to career
          </button>
          <p className="detail-status">This career entry does not exist (any more).</p>
        </div>
      )}
      {entries && model && (listMode || open) && (
        <div className="wh-view" ref={viewRef}>
          <WorkHistoryTimeline
            model={model}
            today={today}
            activeId={open ? open.id : activeId}
            pointer={listMode ? pointer : null}
            focusId={open?.id ?? null}
            onSelect={onOpen}
          />
          {open ? (
            <EntryDetail
              key={open.id}
              entry={open}
              bar={model.byId.get(open.id)}
              newer={entries[openIndex - 1] ?? null}
              older={entries[openIndex + 1] ?? null}
              onOpen={onOpen}
              onOpenCompany={setCompanyId}
              onBack={onBack}
              onUpdate={update(open.id)}
              onDelete={() => remove(open)}
            />
          ) : (
            <>
              <ul className="wh-list">
                {entries.map((entry) => (
                  <EntryCard
                    key={entry.id}
                    entry={entry}
                    bar={model.byId.get(entry.id)}
                    active={entry.id === activeId}
                    cardRef={(el) => {
                      if (el) cardRefs.current.set(entry.id, el)
                      else cardRefs.current.delete(entry.id)
                    }}
                    onOpen={() => onOpen(entry.id)}
                    onOpenCompany={setCompanyId}
                  />
                ))}
              </ul>
              <div style={{ height: spacer }} aria-hidden />
            </>
          )}
        </div>
      )}

      {listMode && <AddPositionComposer onSubmit={create} />}

      {companyId != null && (
        <CompanyDialog key={companyId} companyId={companyId} onClose={() => setCompanyId(null)} />
      )}
    </>
  )
}
