import { cvApi, type GeneratedCv } from './api.ts'

type Props = {
  cv: GeneratedCv
  onDelete?: (cv: GeneratedCv) => void
  deleting?: boolean
}

/** Download / source / delete buttons for one generated CV, depending on its state. */
export default function CvActions({ cv, onDelete, deleting }: Props) {
  const done = cv.status === 'finished' || cv.status === 'failed'
  return (
    <div className="cv-actions">
      {cv.status === 'finished' && (
        <>
          <a className="button small" href={cvApi.pdfUrl(cv.id)} download>
            Download PDF
          </a>
          <a className="button small secondary" href={cvApi.pdfUrl(cv.id)} target="_blank" rel="noreferrer">
            Open
          </a>
          <a className="button small secondary" href={cvApi.texUrl(cv.id)} download>
            .tex
          </a>
        </>
      )}
      {onDelete && done && (
        <button
          type="button"
          className="secondary small danger"
          disabled={deleting}
          onClick={() => onDelete(cv)}
        >
          {deleting ? 'Deleting…' : 'Delete'}
        </button>
      )}
    </div>
  )
}
