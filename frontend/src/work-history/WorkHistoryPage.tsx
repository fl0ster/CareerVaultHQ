import { useEffect, useState } from 'react'
import './work-history.css'
import { type WorkHistoryEntry, type WorkHistoryInput, workHistoryApi } from './api.ts'
import WorkHistoryForm from './WorkHistoryForm.tsx'

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

  return (
    <>
      <h1 className="title">Work history</h1>

      {mode.kind === 'list' && (
        <p>
          {entries === null ? 'Loading…' : `${entries.length} position${entries.length === 1 ? '' : 's'}.`}{' '}
          <button type="button" className="small" onClick={() => setMode({ kind: 'create' })}>
            Add position
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
