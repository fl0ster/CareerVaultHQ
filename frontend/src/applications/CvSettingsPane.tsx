import { useRef, useState } from 'react'
import { type CvOverrides, describeError, isInProgress, type TailoredPlacement } from '../cv/api.ts'
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

  // Both requests rewrite the whole `cv_overrides` on the server, so they run one after the
  // other: sent together (moving a role saves its placement and asks for its tailoring), the
  // later one would write back the overrides from before the other and undo it.
  const queue = useRef<Promise<unknown>>(Promise.resolve())
  const inOrder = (request: () => Promise<Application>) => {
    const run = queue.current.then(async () => {
      setError(null)
      try {
        onChange(await request())
      } catch (e) {
        setError(describeError(e))
      }
    })
    queue.current = run
    return run
  }

  const save = async (next: CvOverrides) => {
    setBusy(true)
    await inOrder(() => applicationsApi.setCvOverrides(application.id, next))
    setBusy(false)
  }

  // Queues it on the worker: the role shows `queued` at once, and the page polls the
  // application until its text is there.
  const tailor = (roleId: number, placement: TailoredPlacement) =>
    inOrder(() => applicationsApi.tailorCvRole(application.id, roleId, placement))

  return (
    <div className="app-cv-report" role="tabpanel">
      {error && <p className="error">{error}</p>}
      {!cv ? (
        <p className="muted">No CV generated for this application yet.</p>
      ) : generating ? (
        <p className="muted">The CV is being generated; how it was made shows here once it is done.</p>
      ) : (
        <CvPipelineReport
          key={cv.id}
          cv={cv}
          editing={{
            pending: application.cv_overrides,
            busy,
            onChange: (next) => void save(next),
            tailor: (roleId, placement) => void tailor(roleId, placement),
          }}
        />
      )}
    </div>
  )
}
