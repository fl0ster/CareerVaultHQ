import { useState } from 'react'
import { Undo2 } from 'lucide-react'
import { describeError } from '../cv/api.ts'
import { type Application, type WorkMode as WorkModeKey, applicationsApi, WORK_MODES } from './api.ts'

type Props = {
  application: Application
  onChange: (application: Application) => void
}

/** The job's work mode as parsed from its page, which can be overridden for this application
 * (and reset back to the parsed value). */
export default function WorkMode({ application, onChange }: Props) {
  const { parsed_work_mode: parsedMode, work_mode_override: modeOverride } = application
  const mode = modeOverride ?? parsedMode
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async (work_mode_override: WorkModeKey | null) => {
    setBusy(true)
    setError(null)
    try {
      onChange(await applicationsApi.setOverrides(application.id, { work_mode_override }))
    } catch (e) {
      setError(describeError(e))
    } finally {
      setBusy(false)
    }
  }

  // Picking the parsed mode again drops the override instead of copying it.
  const pickMode = (key: WorkModeKey) => {
    if (key === mode) return
    void save(key === parsedMode ? null : key)
  }
  const original = WORK_MODES.find((m) => m.key === parsedMode)?.label ?? ''

  return (
    <section className="app-section app-pay" aria-labelledby={`app-mode-${application.id}`}>
      <h3 id={`app-mode-${application.id}`}>Work mode</h3>
      <div className="app-pay-row">
        <div className="app-work-mode" role="radiogroup" aria-label="Work mode">
          {WORK_MODES.map((m) => (
            <button
              key={m.key}
              type="button"
              role="radio"
              aria-checked={mode === m.key}
              onClick={() => pickMode(m.key)}
              disabled={busy}
              title={m.key === parsedMode ? `${m.label} (parsed from the job)` : m.label}
            >
              {m.label}
            </button>
          ))}
        </div>
        {modeOverride && (
          <span className="app-pay-actions">
            <button
              type="button"
              className="app-icon-btn"
              onClick={() => void save(null)}
              disabled={busy}
              title={`Back to the parsed work mode${original ? `: ${original}` : ' (none)'}`}
              aria-label="Back to the parsed work mode"
            >
              <Undo2 size={14} aria-hidden="true" />
            </button>
          </span>
        )}
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  )
}
