import { useEffect, useState } from 'react'
import { type Application, applicationsApi, formatDuration, historyEvents, serverDate } from '../applications/api.ts'
import StatusBadge from '../applications/StatusBadge.tsx'
import '../applications/applications.css'
import { describeError } from '../cv/api.ts'
import { pageHref } from '../shell/nav.ts'

/** The recruitment steps of the application a work-history entry came from (an accepted
 * offer), loaded when shown, with a link to the full application. */
export default function ApplicationSteps({ applicationId }: { applicationId: number }) {
  const [application, setApplication] = useState<Application | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    applicationsApi
      .get(applicationId, controller.signal)
      .then(setApplication)
      .catch((e) => {
        if (!controller.signal.aborted) setError(describeError(e))
      })
    return () => controller.abort()
  }, [applicationId])

  return (
    <section className="wh-steps" aria-label="Application steps">
      <header>
        <h4>How you got the job</h4>
        <a href={pageHref('applications', applicationId)}>Open application</a>
      </header>
      {error && <p className="error">Could not load the application: {error}</p>}
      {!application && !error && <span className="spinner" aria-hidden="true" />}
      {application && (
        <ol className="wh-steps-list">
          {historyEvents(application).map((event) => (
            <li key={event.id}>
              <StatusBadge status={event.status} />
              {event.title && <strong>{event.title}</strong>}
              {event.duration_minutes && <span className="muted">{formatDuration(event.duration_minutes)}</span>}
              <span className="muted">{serverDate(event.occurred_at).toLocaleDateString()}</span>
              {event.note && <p className="wh-steps-note">{event.note}</p>}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
