import { useState } from 'react'
import { applicationsApi, notifyApplicationsChanged } from '../applications/api.ts'
import { describeError } from '../cv/api.ts'

type Props = {
  /** The ``job_evaluations`` row the application is created from. */
  evaluationId: number
  onCreated: (applicationId: number) => void
}

/** Creates an application for the job; the backend also queues a tailored CV for it. */
export default function CreateApplicationButton({ evaluationId, onCreated }: Props) {
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const create = async () => {
    setCreating(true)
    setError(null)
    try {
      const created = await applicationsApi.create({ job_evaluation_id: evaluationId })
      onCreated(created.id)
      notifyApplicationsChanged()
    } catch (e) {
      setError(describeError(e))
    } finally {
      setCreating(false)
    }
  }

  return (
    <span className="create-application">
      <button type="button" className="small" onClick={create} disabled={creating}>
        {creating ? 'Creating…' : 'Apply!'}
      </button>
      {error && <span className="error">{error}</span>}
    </span>
  )
}
