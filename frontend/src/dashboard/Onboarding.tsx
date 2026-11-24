import { Check, ChevronRight } from 'lucide-react'
import { pageHref } from '../shell/nav.ts'
import type { Setup } from '../shell/useSetup.ts'

/** Shown on the dashboard instead of the widgets until the app is set up. */
export default function Onboarding({ setup }: { setup: Setup }) {
  const total = setup.steps.length
  // The first open step is the one to do next.
  const next = setup.steps.find((s) => !s.done)
  return (
    <section className="onboarding" aria-labelledby="onboarding-title">
      <header className="onboarding-head">
        <h2 id="onboarding-title">Let&rsquo;s get you set up</h2>
        <p>Finish these steps and your dashboard will appear here.</p>
        <div className="onboarding-progress">
          <progress className="setup-bar" value={setup.done} max={total} aria-label="Setup progress" />
          <span>
            {setup.done} of {total} done
          </span>
        </div>
      </header>
      <ol className="onboarding-steps">
        {setup.steps.map((step, i) => {
          const content = (
            <>
              <span className="onboarding-check" aria-hidden="true">
                {step.done ? <Check size={16} strokeWidth={2.6} /> : i + 1}
              </span>
              <span className="onboarding-text">
                <span className="onboarding-label">{step.label}</span>
                <span className="onboarding-desc">{step.description}</span>
              </span>
              {step.page && <ChevronRight className="onboarding-go" size={18} aria-hidden="true" />}
              <span className="sr-only">{step.done ? '(done)' : '(to do)'}</span>
            </>
          )
          const className = `onboarding-step${step.done ? ' done' : ''}${step === next ? ' next' : ''}`
          return (
            <li key={step.id}>
              {step.page ? (
                <a className={className} href={pageHref(step.page)}>
                  {content}
                </a>
              ) : (
                <div className={className}>{content}</div>
              )}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
