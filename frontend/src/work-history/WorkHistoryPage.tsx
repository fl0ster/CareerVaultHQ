import { useEffect, useRef, useState } from 'react'
import './work-history.css'
import { type WorkHistoryEntry, type WorkHistoryExport, type WorkHistoryInput, workHistoryApi } from './api.ts'
import WorkHistoryForm from './WorkHistoryForm.tsx'
import { candidateProfileApi } from '../candidate-profile/api.ts'

function formatMonth(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { year: 'numeric', month: 'short' })
}

function EntryCard({
  entry,
  onEdit,
  onDelete,
}: {
  entry: WorkHistoryEntry
  onEdit: () => void
  onDelete: () => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <li className="wh-item">
      <div className="wh-head">
        <div className="wh-main">
          <strong>{entry.role}</strong> at {entry.employer}
          <div className="wh-meta">
            <span>
              {formatMonth(entry.date_start)} – {entry.date_end ? formatMonth(entry.date_end) : 'present'}
            </span>
            {entry.location && <span>{entry.location}</span>}
          </div>
          {entry.tech.length > 0 && (
            <div className="wh-tech">
              {entry.tech.map((t) => (
                <span key={t} className="badge">{t}</span>
              ))}
            </div>
          )}
        </div>
        <div className="wh-buttons">
          {entry.context && (
            <button type="button" className="secondary small" onClick={() => setOpen((o) => !o)}>
              {open ? 'Hide' : 'Details'}
            </button>
          )}
          <button type="button" className="secondary small" onClick={onEdit}>Edit</button>
          <button type="button" className="secondary small danger" onClick={onDelete}>Delete</button>
        </div>
      </div>
      {open && entry.context && <pre className="wh-context">{entry.context}</pre>}
    </li>
  )
}

type Mode = { kind: 'list' } | { kind: 'create' } | { kind: 'edit'; entry: WorkHistoryEntry }

export default function WorkHistoryPage() {
  const [entries, setEntries] = useState<WorkHistoryEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<Mode>({ kind: 'list' })
  const [generating, setGenerating] = useState(false)
  const [profileStatus, setProfileStatus] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [transfer, setTransfer] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [importing, setImporting] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const load = () =>
    workHistoryApi.list().then(
      (items) => {
        setEntries(items)
        setError(null)
      },
      (e) => setError(`Could not load work history: ${String(e instanceof Error ? e.message : e)}`),
    )

  useEffect(() => {
    load()
  }, [])

  const create = async (input: WorkHistoryInput) => {
    await workHistoryApi.create(input)
    setMode({ kind: 'list' })
    await load()
  }

  const update = (id: number) => async (input: WorkHistoryInput) => {
    await workHistoryApi.update(id, input)
    setMode({ kind: 'list' })
    await load()
  }

  const remove = async (entry: WorkHistoryEntry) => {
    if (!window.confirm(`Delete "${entry.role} at ${entry.employer}"?`)) return
    try {
      await workHistoryApi.remove(entry.id)
      await load()
    } catch (e) {
      setError(`Could not delete: ${String(e instanceof Error ? e.message : e)}`)
    }
  }

  const generateProfile = async () => {
    setGenerating(true)
    setProfileStatus(null)
    try {
      const profile = await candidateProfileApi.generate()
      setProfileStatus({
        kind: 'ok',
        text: `Candidate profile generated (#${profile.id}). See the "Candidate profile" tab.`,
      })
    } catch (e) {
      const message = String(e instanceof Error ? e.message : e)
      const text =
        message === 'missing work history'
            ? 'Add at least one position before generating a profile.'
            : `Could not generate candidate profile: ${message}`
      setProfileStatus({ kind: 'error', text })
    } finally {
      setGenerating(false)
    }
  }

  const canGenerate = !generating && !!entries && entries.length > 0
  const hasEntries = !!entries && entries.length > 0

  const describe = (e: unknown) => String(e instanceof Error ? e.message : e)

  const exportJson = async () => {
    setTransfer(null)
    try {
      const items = await workHistoryApi.exportJson()
      const blob = new Blob([JSON.stringify(items, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `work-history-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setTransfer({ kind: 'error', text: `Could not export work history: ${describe(e)}` })
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
      setTransfer({ kind: 'error', text: `${file.name} must contain a non-empty JSON array of positions.` })
      return
    }
    const replace = hasEntries
      ? window.confirm(
          `Replace the existing ${entries.length} position${entries.length === 1 ? '' : 's'} with the imported ones?\n\n` +
            'OK = replace, Cancel = keep them and add the imported positions.',
        )
      : false
    setImporting(true)
    try {
      const created = await workHistoryApi.importJson(items as WorkHistoryExport[], replace)
      await load()
      setTransfer({
        kind: 'ok',
        text: `Imported ${created.length} position${created.length === 1 ? '' : 's'} from ${file.name}.`,
      })
    } catch (e) {
      setTransfer({ kind: 'error', text: `Could not import ${file.name}: ${describe(e)}` })
    } finally {
      setImporting(false)
    }
  }

  return (
    <>
      <h1 className="title">Work history</h1>

      {mode.kind === 'list' && (
        <p>
          {entries === null ? 'Loading…' : `${entries.length} position${entries.length === 1 ? '' : 's'}.`}{' '}
          <button type="button" className="small" onClick={() => setMode({ kind: 'create' })}>
            Add position
          </button>{' '}
          <button
            type="button"
            className="secondary small"
            disabled={!canGenerate}
            title={entries && entries.length === 0 ? 'Add a position first' : undefined}
            onClick={generateProfile}
          >
            {generating ? 'Generating profile…' : 'Generate candidate profile'}
          </button>{' '}
          <button type="button" className="secondary small" disabled={!hasEntries} onClick={exportJson}>
            Export JSON
          </button>{' '}
          <button
            type="button"
            className="secondary small"
            disabled={importing || entries === null}
            onClick={() => fileInput.current?.click()}
          >
            {importing ? 'Importing…' : 'Import JSON'}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(ev) => {
              const file = ev.target.files?.[0]
              ev.target.value = ''
              if (file) void importJson(file)
            }}
          />
        </p>
      )}

      {mode.kind === 'list' && transfer && (
        <p className={transfer.kind === 'error' ? 'error' : undefined}>
          {transfer.text}{' '}
          <button type="button" className="secondary small" onClick={() => setTransfer(null)}>
            Dismiss
          </button>
        </p>
      )}

      {mode.kind === 'list' && profileStatus && (
        <p className={profileStatus.kind === 'error' ? 'error' : undefined}>
          {profileStatus.text}{' '}
          <button type="button" className="secondary small" onClick={() => setProfileStatus(null)}>
            Dismiss
          </button>
        </p>
      )}

      {error && (
        <p className="error">
          {error}{' '}
          <button type="button" className="secondary small" onClick={load}>Retry</button>
        </p>
      )}

      {mode.kind === 'create' && (
        <WorkHistoryForm onSubmit={create} onCancel={() => setMode({ kind: 'list' })} />
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
        <p>No positions yet. Add your first one above.</p>
      )}
      {mode.kind === 'list' && entries && entries.length > 0 && (
        <ul className="wh-list">
          {entries.map((entry) => (
            <EntryCard
              key={entry.id}
              entry={entry}
              onEdit={() => setMode({ kind: 'edit', entry })}
              onDelete={() => remove(entry)}
            />
          ))}
        </ul>
      )}
    </>
  )
}
