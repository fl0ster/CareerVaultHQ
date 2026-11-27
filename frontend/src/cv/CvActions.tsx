import { cvApi, type GeneratedCv } from './api.ts'

type Props = {
  cv: GeneratedCv
}

/** Download button for one generated CV, depending on its state. */
export default function CvActions({ cv }: Props) {
  return (
    <div className="cv-actions">
      {cv.status === 'finished' && (
        <>
          <a className="button small" href={cvApi.pdfUrl(cv.id)} download>
            Download
          </a>
        </>
      )}
    </div>
  )
}
