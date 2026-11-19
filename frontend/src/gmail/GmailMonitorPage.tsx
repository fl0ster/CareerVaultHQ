import { useEffect, useState } from 'react'
import {
  type ConnectionTest,
  gmailMonitorApi,
  MIN_INTERVAL_SECONDS,
  type MonitorJob,
  type MonitorSettings,
  type MonitorSettingsUpdate,
  OUTCOME_LABEL,
  type ProcessedMail,
  LABEL_PATTERN,
  MAX_LOOKBACK_DAYS,
} from './api.ts'
import { isTerminal } from '../tools/api.ts'
import { notifyApplicationsChanged } from '../applications/api.ts'
import './gmail.css'

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

type FieldProps = {
  label: string
  value: string
  type?: 'text' | 'email' | 'url' | 'number'
  placeholder?: string
  hint?: string
  disabled?: boolean
  min?: number
  max?: number
  step?: number
  /** Turns the edited text into a settings patch; return an error message to reject it. */
  toPatch: (text: string) => MonitorSettingsUpdate | string
  onSave: (patch: MonitorSettingsUpdate) => Promise<boolean>
}

/** A settings input that saves on blur / Enter and resets when the server value changes. */
function Field({ label, value, type = 'text', placeholder, hint, disabled, min, max, step, toPatch, onSave }: FieldProps) {
  const [draft, setDraft] = useState(value)
  const [seen, setSeen] = useState(value)
  const [invalid, setInvalid] = useState<string | null>(null)
  if (seen !== value) {
    setSeen(value)
    setDraft(value)
  }

  const commit = async () => {
    if (draft === value) return
    const patch = toPatch(draft)
    if (typeof patch === 'string') {
      setInvalid(patch)
      return
    }
    setInvalid(null)
    if (!(await onSave(patch))) setDraft(value)
  }

  return (
    <label className="gmail-field">
      <span className="gmail-field-label">{label}</span>
      <input
        type={type}
        value={draft}
        placeholder={placeholder}
        disabled={disabled}
        min={min}
        max={max}
        step={step}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void commit()}
        onKeyDown={(e) => {
          if (e.key === 'Enter') void commit()
          if (e.key === 'Escape') setDraft(value)
        }}
      />
      {invalid ? <span className="error">{invalid}</span> : hint && <span className="muted">{hint}</span>}
    </label>
  )
}

function SetupInstructions({ settings, onRotate }: { settings: MonitorSettings; onRotate: () => void }) {
  const [script, setScript] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    try {
      const text = await gmailMonitorApi.script()
      setScript(text)
      return text
    } catch (e) {
      setError(`Could not load the script: ${message(e)}`)
      return null
    }
  }

  const copy = async () => {
    const text = await load()
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard needs a secure context (https / localhost); the text area below works anywhere.
      setError('Copying is not available here; select the script below and copy it by hand.')
    }
  }

  return (
    <details className="gmail-setup" open={!settings.configured}>
      <summary>How to set it up</summary>
      <p>
        The app never gets your Google password or tokens. Instead you deploy a small Google Apps Script in the
        Gmail account to monitor; the app calls it (outbound only) to read unread inbox mails and to mark the
        handled ones. Requests are protected by a secret embedded in the script (ending in{' '}
        <code>{settings.secret_hint}</code>). The script itself limits what can be read: only unread inbox mails
        of the last {MAX_LOOKBACK_DAYS} days that look like job application mails, never password resets or
        sign-in codes, so even a leaked secret cannot be used to search the rest of the mailbox.
      </p>
      <ol>
        <li>
          Sign in to the Gmail account you want to monitor and open{' '}
          <a href="https://script.google.com/home/projects/create" target="_blank" rel="noreferrer">
            script.google.com → New project
          </a>
          .
        </li>
        <li>
          Replace the contents of <code>Code.gs</code> with the script (it already contains your secret) and save.{' '}
          <span className="gmail-inline-buttons">
            <button type="button" className="small" onClick={() => void copy()}>
              {copied ? 'Copied ✓' : 'Copy script'}
            </button>
            <button type="button" className="secondary small" onClick={() => (script ? setScript(null) : void load())}>
              {script ? 'Hide script' : 'Show script'}
            </button>
          </span>
        </li>
        <li>
          <strong>Deploy → New deployment</strong>, type <strong>Web app</strong>. Set <em>Execute as</em>:{' '}
          <strong>Me</strong> and <em>Who has access</em>: <strong>Anyone</strong>, then <strong>Deploy</strong>.
        </li>
        <li>Authorize the requested Gmail access when Google asks (Advanced → Go to project, for an unverified script).</li>
        <li>
          Copy the <strong>Web app URL</strong> (ending in <code>/exec</code>) into the field above, enter the
          account's address, and press <strong>Test connection</strong>.
        </li>
        <li>Turn the monitor on, or use <strong>Run now</strong> to check once.</li>
      </ol>
      <p className="muted">
        When you change the script later, use <strong>Deploy → Manage deployments → Edit → New version</strong> so the
        URL stays the same. After rotating the secret the script must be pasted and redeployed again.{' '}
        <button
          type="button"
          className="secondary small"
          onClick={() => {
            if (window.confirm('Generate a new secret? The deployed script stops working until you paste the new one.')) {
              setScript(null)
              onRotate()
            }
          }}
        >
          Rotate secret
        </button>
      </p>
      {error && <p className="error">{error}</p>}
      {script && (
        <textarea
          className="gmail-script"
          readOnly
          value={script}
          rows={16}
          onFocus={(e) => e.currentTarget.select()}
          aria-label="Apps Script source"
        />
      )}
    </details>
  )
}

function Activity({ mails }: { mails: ProcessedMail[] }) {
  if (mails.length === 0) return <p className="muted">No mails checked yet.</p>
  return (
    <table className="gmail-mails">
      <thead>
        <tr>
          <th>Received</th>
          <th>Mail</th>
          <th>Outcome</th>
          <th>Rejection</th>
          <th>Company / role</th>
        </tr>
      </thead>
      <tbody>
        {mails.map((m) => (
          <tr key={m.id}>
            <td className="nowrap">{when(m.received_at ?? m.created_at)}</td>
            <td>
              <div className="gmail-subject">{m.subject || '(no subject)'}</div>
              <div className="muted">{m.sender}</div>
            </td>
            <td>
              <span className={`badge gmail-outcome ${m.outcome}`} title={m.error ?? undefined}>
                {m.outcome === 'applied' && '⚡ '}
                {OUTCOME_LABEL[m.outcome] ?? m.outcome}
              </span>
              {m.application_title && <div className="muted">→ {m.application_title}</div>}
              {m.error && m.outcome !== 'applied' && <div className="muted gmail-error">{m.error}</div>}
            </td>
            <td>{m.probability == null ? '—' : `${Math.round(m.probability * 100)}%`}</td>
            <td>
              {m.company ?? '—'}
              {m.role && <div className="muted">{m.role}</div>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Follows a check job (polling once a second) until it reaches a terminal state. */
function useMonitorJob(onFinished: () => void) {
  const [job, setJob] = useState<MonitorJob | null>(null)
  const jobId = job?.job_id
  const done = job ? isTerminal(job.status) : false

  useEffect(() => {
    if (!jobId || done) return
    let cancelled = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const info = await gmailMonitorApi.job(jobId)
        if (cancelled) return
        setJob(info)
        if (isTerminal(info.status)) onFinished()
        else timer = window.setTimeout(poll, 1000)
      } catch {
        if (!cancelled) timer = window.setTimeout(poll, 2000)
      }
    }
    timer = window.setTimeout(poll, 500)
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [jobId, done, onFinished])

  return { job, setJob, running: !!job && !done }
}

export default function GmailMonitorPage() {
  const [settings, setSettings] = useState<MonitorSettings | null>(null)
  const [mails, setMails] = useState<ProcessedMail[]>([])
  const [error, setError] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [test, setTest] = useState<ConnectionTest | null>(null)
  const [testing, setTesting] = useState(false)
  const [onFinished] = useState(() => () => {
    setRefresh((n) => n + 1)
    notifyApplicationsChanged()
  })
  const { job, setJob, running } = useMonitorJob(onFinished)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([gmailMonitorApi.settings(controller.signal), gmailMonitorApi.mails(controller.signal)])
      .then(([s, m]) => {
        setSettings(s)
        setMails(m)
        setError(null)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(`Could not load the Gmail monitor: ${message(e)}`)
      })
    return () => controller.abort()
  }, [refresh])

  const save = async (patch: MonitorSettingsUpdate): Promise<boolean> => {
    try {
      setSettings(await gmailMonitorApi.update(patch))
      setError(null)
      return true
    } catch (e) {
      setError(`Could not save: ${message(e)}`)
      return false
    }
  }

  const runTest = async () => {
    setTesting(true)
    setTest(null)
    try {
      setTest(await gmailMonitorApi.test())
    } catch (e) {
      setTest({ ok: false, email: null, matches_configured: false, error: message(e) })
    } finally {
      setTesting(false)
    }
  }

  const runNow = async () => {
    setError(null)
    try {
      setJob(await gmailMonitorApi.run())
    } catch (e) {
      setError(`Could not start the check: ${message(e)}`)
    }
  }

  const rotate = async () => {
    try {
      setSettings(await gmailMonitorApi.rotateSecret())
      setTest(null)
    } catch (e) {
      setError(`Could not rotate the secret: ${message(e)}`)
    }
  }

  if (!settings) {
    return (
      <>
        <h1 className="title">Gmail rejection monitor</h1>
        {error ? <p className="error">{error}</p> : <span className="spinner" aria-hidden="true" />}
      </>
    )
  }

  const summary = settings.last_summary
  const finished = job && !running ? job : null

  return (
    <>
      <h1 className="title">Gmail rejection monitor</h1>
      <p>
        Watches the unread inbox of a Gmail account for rejection mails. A mail is acted on only when the model is
        confident it is a rejection and it matches exactly one open application (applied, not yet rejected or offered)
        by company, and by role when there are several at that company. That application gets the{' '}
        <span className="badge app-status rejected">⚡ Rejected</span> state, and the mail is marked as read and labelled.
        Anything else stays unread in your inbox.
      </p>

      <section className="gmail-section">
        <h2>Connection</h2>
        <div className="gmail-grid">
          <Field
            label="Monitored Gmail address"
            type="email"
            value={settings.email}
            placeholder="you@gmail.com"
            toPatch={(t) => (t.trim() && !t.includes('@') ? 'Enter an e-mail address' : { email: t.trim() })}
            onSave={save}
          />
          <Field
            label="Apps Script web app URL"
            type="url"
            value={settings.script_url}
            placeholder="https://script.google.com/macros/s/…/exec"
            toPatch={(t) =>
              t.trim() && !t.trim().startsWith('https://') ? 'The URL must start with https://' : { script_url: t.trim() }
            }
            onSave={save}
          />
        </div>
        <div className="gmail-toolbar">
          <button type="button" className="secondary" disabled={!settings.configured || testing} onClick={() => void runTest()}>
            {testing ? 'Testing…' : 'Test connection'}
          </button>
          {test &&
            (test.ok ? (
              <span className="gmail-ok">✓ Connected as {test.email}</span>
            ) : (
              <span className="error">{test.error ?? 'Connection failed'}</span>
            ))}
        </div>
        <SetupInstructions settings={settings} onRotate={() => void rotate()} />
      </section>

      <section className="gmail-section">
        <h2>Automation</h2>
        <label className="gmail-toggle">
          <input
            type="checkbox"
            checked={settings.enabled}
            disabled={!settings.configured && !settings.enabled}
            onChange={(e) => void save({ enabled: e.target.checked })}
          />
          <span>
            Check automatically every {Math.round(settings.interval_seconds / 60)} min
            {!settings.configured && <span className="muted"> (set the address and URL first)</span>}
          </span>
        </label>
        <div className="gmail-grid">
          <Field
            label="Gmail label for registered rejections"
            value={settings.label}
            toPatch={(t) =>
              LABEL_PATTERN.test(t.trim()) ? { label: t.trim() } : 'Letters, digits, spaces and _ . / - only'
            }
            onSave={save}
            hint="Created in Gmail when missing."
          />
          <Field
            label="Check every (minutes)"
            type="number"
            min={MIN_INTERVAL_SECONDS / 60}
            value={String(Math.round(settings.interval_seconds / 60))}
            toPatch={(t) => {
              const minutes = Number(t)
              if (!Number.isFinite(minutes) || minutes * 60 < MIN_INTERVAL_SECONDS) return 'At least 1 minute'
              return { interval_seconds: Math.round(minutes * 60) }
            }}
            onSave={save}
          />
          <Field
            label="Look back (days)"
            type="number"
            min={1}
            max={MAX_LOOKBACK_DAYS}
            value={String(settings.lookback_days)}
            toPatch={(t) => {
              const days = Number(t)
              return Number.isInteger(days) && days >= 1 && days <= MAX_LOOKBACK_DAYS
                ? { lookback_days: days }
                : `1 to ${MAX_LOOKBACK_DAYS} days`
            }}
            onSave={save}
            hint="Only unread mails this recent are checked."
          />
          <Field
            label="Minimum confidence (%)"
            type="number"
            min={50}
            max={100}
            step={1}
            value={String(Math.round(settings.threshold * 100))}
            toPatch={(t) => {
              const pct = Number(t)
              return pct >= 50 && pct <= 100 ? { threshold: pct / 100 } : '50 to 100'
            }}
            onSave={save}
            hint="Probability that a mail is a rejection before it is acted on."
          />
        </div>
      </section>

      <section className="gmail-section">
        <h2>Runs</h2>
        <div className="gmail-toolbar">
          <button type="button" disabled={!settings.configured || running} onClick={() => void runNow()}>
            {running ? 'Checking…' : 'Run now'}
          </button>
          <button type="button" className="secondary" onClick={() => setRefresh((n) => n + 1)}>
            Refresh
          </button>
          {job && (
            <span className="muted">
              <span className={`badge ${job.status}`}>{job.status}</span>
              {running && <span className="spinner" aria-hidden="true" />}
              {finished?.status === 'finished' && finished.result &&
                ` ${finished.result.fetched} mail(s) fetched, ${finished.result.outcomes.applied ?? 0} rejection(s) registered`}
            </span>
          )}
        </div>
        {finished?.status === 'failed' && finished.error && <p className="error">{finished.error}</p>}
        <dl className="gmail-status">
          <dt>Last run</dt>
          <dd>
            {when(settings.last_run_at)}
            {settings.last_status && (
              <span className={`badge ${settings.last_status === 'ok' ? 'finished' : 'failed'}`}>{settings.last_status}</span>
            )}
            {summary && settings.last_status === 'ok' && (
              <span className="muted">
                {' '}
                {summary.fetched} fetched · {summary.outcomes.applied ?? 0} registered · {summary.skipped} already seen
                {summary.failed > 0 && ` · ${summary.failed} to retry`}
              </span>
            )}
          </dd>
          <dt>Next run</dt>
          <dd>{settings.enabled ? (settings.next_run_at ? when(settings.next_run_at) : 'at the next scheduler tick') : 'off'}</dd>
        </dl>
        {settings.last_status === 'failed' && settings.last_error && <p className="error">{settings.last_error}</p>}
      </section>

      {error && <p className="error">{error}</p>}

      <section className="gmail-section">
        <h2>Recent mails</h2>
        <Activity mails={mails} />
      </section>
    </>
  )
}
