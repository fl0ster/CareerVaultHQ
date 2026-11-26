import { Download, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import './import-export.css'
import { describeError } from '../cv/api.ts'
import { type WorkHistoryExport, workHistoryApi } from '../work-history/api.ts'

/** Saves `data` as an indented, human-readable JSON file. */
function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2) + '\n'], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** Today as `YYYY-MM-DD` (local time), for file names. */
function today(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const entries = (n: number) => (n === 1 ? '1 entry' : `${n} entries`)
const duplicates = (n: number) => (n === 1 ? '1 duplicate' : `${n} duplicates`)

/** A work-history file waiting for the user to choose between replacing and merging. */
type PendingImport = { items: WorkHistoryExport[]; existing: number }

type Status = { kind: 'ok' | 'error'; text: string } | null

export default function ImportExportPage() {
  const fileInput = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<Status>(null)
  const [pending, setPending] = useState<PendingImport | null>(null)

  const run = async (action: () => Promise<string>) => {
    setBusy(true)
    setStatus(null)
    try {
      setStatus({ kind: 'ok', text: await action() })
    } catch (e) {
      setStatus({ kind: 'error', text: describeError(e) })
    } finally {
      setBusy(false)
    }
  }

  const exportWorkHistory = () =>
    run(async () => {
      const items = await workHistoryApi.exportJson()
      downloadJson(items, `careervault-work-history-${today()}.json`)
      return `Exported ${entries(items.length)}.`
    })

  const importItems = (items: WorkHistoryExport[], replace: boolean) =>
    run(async () => {
      const created = await workHistoryApi.importJson(items, replace)
      const skipped = items.length - created.length
      const verb = replace ? 'Replaced the work history with' : 'Imported'
      return `${verb} ${entries(created.length)}${skipped > 0 ? ` (${duplicates(skipped)} skipped)` : ''}.`
    })

  const onFile = async (file: File) => {
    setStatus(null)
    let items: unknown
    try {
      items = JSON.parse(await file.text())
    } catch {
      setStatus({ kind: 'error', text: `${file.name} is not a valid JSON file.` })
      return
    }
    if (!Array.isArray(items)) {
      setStatus({ kind: 'error', text: 'Not a work history export: expected a JSON array of entries.' })
      return
    }
    if (items.length === 0) {
      setStatus({ kind: 'error', text: 'The file holds no work history entries.' })
      return
    }
    setBusy(true)
    let existing: number
    try {
      existing = (await workHistoryApi.list()).length
    } catch (e) {
      setStatus({ kind: 'error', text: describeError(e) })
      setBusy(false)
      return
    }
    setBusy(false)
    // The server validates each entry; a malformed one comes back as an error naming it.
    if (existing > 0) setPending({ items: items as WorkHistoryExport[], existing })
    else void importItems(items as WorkHistoryExport[], false)
  }

  return (
    <div className="ie-page">
      <section className="card ie-section">
        <div className="ie-section-text">
          <h2>Work history</h2>
          <p className="muted">
            Positions, education and certificates as a JSON array. A file exported here can be imported again,
            here or on another installation.
          </p>
        </div>
        <div className="ie-actions">
          <button type="button" className="secondary" onClick={exportWorkHistory} disabled={busy}>
            <Download size={16} aria-hidden /> Export
          </button>
          <button type="button" onClick={() => fileInput.current?.click()} disabled={busy}>
            <Upload size={16} aria-hidden /> Import…
          </button>
          <input
            ref={fileInput}
            type="file"
            accept=".json,application/json"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ''
              if (file) void onFile(file)
            }}
          />
        </div>
        {status && (
          <p className={`ie-status ${status.kind === 'error' ? 'error' : 'muted'}`} role="status">
            {status.text}
          </p>
        )}
      </section>

      {pending && (
        <ReplaceOrMergeDialog
          incoming={pending.items.length}
          existing={pending.existing}
          onChoose={(replace) => {
            setPending(null)
            void importItems(pending.items, replace)
          }}
          onClose={() => setPending(null)}
        />
      )}
    </div>
  )
}

/** Asks what to do with the work history already there before importing a file. */
function ReplaceOrMergeDialog({
  incoming,
  existing,
  onChoose,
  onClose,
}: {
  incoming: number
  existing: number
  onChoose: (replace: boolean) => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) dialog.showModal()
  }, [])

  return (
    <dialog
      ref={ref}
      className="ie-dialog"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose()
      }}
    >
      <h2>You already have a work history</h2>
      <p className="muted">
        It holds {entries(existing)}; the file has {entries(incoming)}. What should happen to the current ones?
      </p>
      <ul className="ie-choices">
        <li>
          <strong>Merge</strong> keeps them and adds the entries from the file, skipping the ones already there.
        </li>
        <li>
          <strong>Replace</strong> deletes them and keeps only the entries from the file.
        </li>
      </ul>
      <div className="ie-dialog-buttons">
        <button type="button" className="secondary" onClick={onClose}>
          Cancel
        </button>
        <button type="button" className="ie-danger" onClick={() => onChoose(true)}>
          Replace
        </button>
        <button type="button" onClick={() => onChoose(false)} autoFocus>
          Merge
        </button>
      </div>
    </dialog>
  )
}
