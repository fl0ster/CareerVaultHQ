import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { type CvOverrides, describeError, isInProgress, overrideCount, sameOverrides } from '../cv/api.ts'
import { CvPipelineReport } from '../cv/CvPipelineDialog.tsx'
import { type Application, applicationsApi } from './api.ts'

const edits = (n: number) => `${n} ${n === 1 ? 'edit' : 'edits'}`

/** The "CV Settings" tab: how the CV was generated, with every choice (headline, summary,
 * where each role goes) editable for this application only. Each edit is saved at once;
 * a bar on top says whether the CV already uses them and regenerates it or drops them all. */
export default function CvSettingsPane({
  application,
  onChange,
}: {
  application: Application
  onChange: (application: Application) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cv = application.cv
  const pending = application.cv_overrides
  const count = overrideCount(pending)
  const generating = cv != null && isInProgress(cv)
  const unapplied = cv != null && !sameOverrides(pending, cv.overrides)

  const run = async (fn: () => Promise<Application>) => {
    setBusy(true)
    setError(null)
    try {
      onChange(await fn())
    } catch (e) {
      setError(describeError(e))
    } finally {
      setBusy(false)
    }
  }
  const save = (next: CvOverrides | null) => void run(() => applicationsApi.setCvOverrides(application.id, next))
  const regenerate = () => void run(() => applicationsApi.regenerateCv(application.id))
  const removeAll = () => {
    if (window.confirm(`Remove all ${edits(count)} to this CV? The next CV is generated the usual way.`)) save(null)
  }

  return (
    <div className="app-cv-report" role="tabpanel">
      {count > 0 || unapplied ? (
        <div className={`app-cv-bar${unapplied ? ' is-pending' : ''}`} role="status">
          <p>
            {unapplied ? (
              <>
                <strong>{count ? edits(count) : 'Edits removed'}</strong>
                {generating ? ' — the CV being generated uses them.' : ' — not in this CV yet.'}
              </>
            ) : (
              <>
                <strong>{edits(count)}</strong> in this CV, for this application only.
              </>
            )}
          </p>
          <span className="app-cv-bar-actions">
            {unapplied && !generating && (
              <button type="button" className="small primary" onClick={regenerate} disabled={busy}>
                <RefreshCw size={14} aria-hidden="true" /> Regenerate CV
              </button>
            )}
            {count > 0 && (
              <button type="button" className="secondary small" onClick={removeAll} disabled={busy}>
                Remove all edits
              </button>
            )}
          </span>
        </div>
      ) : (
        cv &&
        !generating && (
          <p className="muted app-cv-intro">
            Change the headline, the summary or where any role goes, then regenerate the CV. Edits apply to this
            application only.
          </p>
        )
      )}
      {error && <p className="error">{error}</p>}

      {!cv ? (
        <p className="muted">No CV generated for this application yet.</p>
      ) : generating ? (
        <p className="muted">The CV is being generated; how it was made shows here once it is done.</p>
      ) : (
        <CvPipelineReport key={cv.id} cv={cv} editing={{ pending, busy, onChange: save }} />
      )}
    </div>
  )
}
