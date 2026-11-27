import { useState } from 'react'
import { type CvOverrides, describeError, isInProgress } from '../cv/api.ts'
import { CvPipelineReport } from '../cv/CvPipelineDialog.tsx'
import { type Application, applicationsApi } from './api.ts'

/** The "CV Settings" tab: how the CV was generated, with every choice (headline, summary,
 * where each role goes) editable for this application only. Each edit is saved at once; the
 * CV section of the left column regenerates the CV with them (or removes them all). */
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
  const generating = cv != null && isInProgress(cv)

  const save = async (next: CvOverrides) => {
    setBusy(true)
    setError(null)
    try {
      onChange(await applicationsApi.setCvOverrides(application.id, next))
    } catch (e) {
      setError(describeError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app-cv-report" role="tabpanel">
      {error && <p className="error">{error}</p>}
      {!cv ? (
        <p className="muted">No CV generated for this application yet.</p>
      ) : generating ? (
        <p className="muted">The CV is being generated; how it was made shows here once it is done.</p>
      ) : (
        <>
          <p className="muted app-cv-intro">
            Change the headline, the summary or where any role goes, then regenerate the CV. Edits apply to this
            application only.
          </p>
          <CvPipelineReport
            key={cv.id}
            cv={cv}
            editing={{ pending: application.cv_overrides, busy, onChange: (next) => void save(next) }}
          />
        </>
      )}
    </div>
  )
}
