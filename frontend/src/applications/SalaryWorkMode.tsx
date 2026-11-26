import { useState } from 'react'
import { Pencil, Undo2 } from 'lucide-react'
import { describeError } from '../cv/api.ts'
import {
  type Application,
  type Salary,
  type SalaryPeriod,
  type WorkMode,
  applicationsApi,
  formatSalary,
  SALARY_PERIODS,
  WORK_MODES,
} from './api.ts'

type Props = {
  application: Application
  onChange: (application: Application) => void
}

type Draft = { min: string; max: string; currency: string; period: string; gross: string }

const toDraft = (s: Salary | null): Draft => ({
  min: s?.min != null ? String(s.min) : '',
  max: s?.max != null ? String(s.max) : '',
  currency: s?.currency ?? '',
  period: s?.period ?? '',
  gross: s?.gross == null ? '' : s.gross ? 'gross' : 'net',
})

const fromDraft = (d: Draft): Salary => ({
  min: d.min.trim() ? Number(d.min) : null,
  max: d.max.trim() ? Number(d.max) : null,
  currency: d.currency.trim().toUpperCase() || null,
  period: (d.period || null) as SalaryPeriod | null,
  gross: d.gross ? d.gross === 'gross' : null,
})

/** The job's salary and work mode as parsed from its page, each of which can be overridden
 * for this application (and reset back to the parsed value). */
export default function SalaryWorkMode({ application, onChange }: Props) {
  const { parsed_salary: parsedSalary, salary_override: salaryOverride } = application
  const { parsed_work_mode: parsedMode, work_mode_override: modeOverride } = application
  const salary = salaryOverride ?? parsedSalary
  const mode = modeOverride ?? parsedMode
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Draft>(() => toDraft(salary))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async (changes: Parameters<typeof applicationsApi.setOverrides>[1]) => {
    setBusy(true)
    setError(null)
    try {
      onChange(await applicationsApi.setOverrides(application.id, changes))
      return true
    } catch (e) {
      setError(describeError(e))
      return false
    } finally {
      setBusy(false)
    }
  }

  const startEdit = () => {
    setDraft(toDraft(salary))
    setEditing(true)
  }
  const saveSalary = async () => {
    if (await save({ salary_override: fromDraft(draft) })) setEditing(false)
  }
  // Picking the parsed mode again drops the override instead of copying it.
  const pickMode = (key: WorkMode) => {
    if (key === mode) return
    void save({ work_mode_override: key === parsedMode ? null : key })
  }

  const min = Number(draft.min)
  const max = Number(draft.max)
  const draftError =
    (draft.min.trim() && !(min >= 0)) || (draft.max.trim() && !(max >= 0))
      ? 'Amounts must be positive numbers.'
      : draft.min.trim() && draft.max.trim() && min > max
        ? 'The minimum is above the maximum.'
        : null
  const field = (key: keyof Draft) => ({
    value: draft[key],
    onChange: (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [key]: e.target.value })),
    disabled: busy,
  })

  const reset = (label: string, onClick: () => void, original: string) => (
    <button
      type="button"
      className="app-icon-btn"
      onClick={onClick}
      disabled={busy}
      title={`Back to the parsed ${label}${original ? `: ${original}` : ' (none)'}`}
      aria-label={`Back to the parsed ${label}`}
    >
      <Undo2 size={14} aria-hidden="true" />
    </button>
  )

  return (
    <section className="app-section app-pay" aria-labelledby={`app-pay-${application.id}`}>
      <h3 id={`app-pay-${application.id}`}>Salary &amp; work mode</h3>

      {editing ? (
        <div className="app-salary-form">
          <div className="app-salary-amounts">
            <input type="number" min={0} placeholder="Min" aria-label="Minimum salary" {...field('min')} />
            <span aria-hidden="true">–</span>
            <input type="number" min={0} placeholder="Max" aria-label="Maximum salary" {...field('max')} />
          </div>
          <div className="app-salary-amounts">
            <input
              type="text"
              placeholder="PLN"
              aria-label="Currency"
              maxLength={8}
              className="app-salary-currency"
              {...field('currency')}
            />
            <select aria-label="Per" {...field('period')}>
              <option value="">per</option>
              {SALARY_PERIODS.map((p) => (
                <option key={p} value={p}>
                  / {p}
                </option>
              ))}
            </select>
            <select aria-label="Gross or net" {...field('gross')}>
              <option value="">gross/net</option>
              <option value="gross">gross</option>
              <option value="net">net</option>
            </select>
          </div>
          <div className="app-buttons">
            <button type="button" className="small" onClick={saveSalary} disabled={busy || !!draftError}>
              {busy ? 'Saving…' : 'Save'}
            </button>
            <button type="button" className="secondary small" onClick={() => setEditing(false)} disabled={busy}>
              Cancel
            </button>
          </div>
          {draftError && <p className="error">{draftError}</p>}
        </div>
      ) : (
        <div className="app-pay-row">
          <span
            className={salary && formatSalary(salary) ? 'app-salary' : 'app-salary muted'}
            title={parsedSalary?.raw && !salaryOverride ? `Parsed from: ${parsedSalary.raw}` : undefined}
          >
            {formatSalary(salary) || 'Salary not stated'}
          </span>
          {salaryOverride && <span className="app-edited">edited</span>}
          <span className="app-pay-actions">
            <button
              type="button"
              className="app-icon-btn"
              onClick={startEdit}
              disabled={busy}
              title="Edit the salary"
              aria-label="Edit the salary"
            >
              <Pencil size={14} aria-hidden="true" />
            </button>
            {salaryOverride &&
              reset('salary', () => void save({ salary_override: null }), formatSalary(parsedSalary))}
          </span>
        </div>
      )}

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
            {reset(
              'work mode',
              () => void save({ work_mode_override: null }),
              WORK_MODES.find((m) => m.key === parsedMode)?.label ?? '',
            )}
          </span>
        )}
      </div>
      {!mode && <p className="muted app-pay-hint">Work mode not stated.</p>}
      {error && <p className="error">{error}</p>}
    </section>
  )
}
