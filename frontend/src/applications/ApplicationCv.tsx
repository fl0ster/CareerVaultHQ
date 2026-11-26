import { useState } from 'react'
import { FileDown, FilePlus, FileX, Info } from 'lucide-react'
import { cvApi, describeError, isInProgress } from '../cv/api.ts'
import CvPipelineDialog from '../cv/CvPipelineDialog.tsx'
import { type Application, applicationsApi } from './api.ts'

type Props = {
  application: Application
  onChange: (application: Application) => void
}

/** The application's CV as one icon: downloads it when ready, spins while it is generated,
 * generates one when there is none (or the last attempt failed). The info button beside it
 * opens how it was generated (a popup, which can also generate it again). */
export default function ApplicationCv({ application, onChange }: Props) {
  const [busy, setBusy] = useState(false)
  const [showPipeline, setShowPipeline] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cv = application.cv

  const generate = async () => {
    setBusy(true)
    setError(null)
    try {
      onChange(await applicationsApi.regenerateCv(application.id))
    } catch (e) {
      setError(describeError(e))
    } finally {
      setBusy(false)
    }
  }

  let main
  if (busy || (cv && isInProgress(cv))) {
    main = (
      <span className="app-cv-main generating" role="status" title="Generating the CV…">
        <span className="spinner" aria-hidden="true" />
        <span className="app-cv-text">Generating…</span>
      </span>
    )
  } else if (cv?.status === 'finished') {
    main = (
      <a className="app-cv-main ready" href={cvApi.pdfUrl(cv.id)} download title={`Download CV #${cv.id} (PDF)`}>
        <FileDown size={18} aria-hidden="true" />
        <span className="app-cv-text">CV</span>
      </a>
    )
  } else {
    const failed = cv?.status === 'failed'
    main = (
      <button
        type="button"
        className={`app-cv-main${failed ? ' failed' : ''}`}
        onClick={generate}
        title={failed ? `CV generation failed${cv?.error ? `: ${cv.error}` : ''}. Click to try again.` : 'Generate a CV for this job'}
      >
        {failed ? <FileX size={18} aria-hidden="true" /> : <FilePlus size={18} aria-hidden="true" />}
        <span className="app-cv-text">{failed ? 'Retry CV' : 'Generate CV'}</span>
      </button>
    )
  }

  const details = cv && !busy && !isInProgress(cv)
  return (
    <div className="app-cv">
      <div className="app-cv-control">
        {main}
        {details && (
          <button
            type="button"
            className="app-cv-info"
            onClick={() => setShowPipeline(true)}
            title="How it was generated"
            aria-label="How the CV was generated"
          >
            <Info size={16} aria-hidden="true" />
          </button>
        )}
      </div>
      {error && <p className="error app-cv-error">{error}</p>}
      {showPipeline && cv && (
        <CvPipelineDialog
          key={cv.id}
          cv={cv}
          onClose={() => setShowPipeline(false)}
          onRegenerate={() => void generate()}
        />
      )}
    </div>
  )
}
