# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
The main user is the owner, a developer who runs the job search on their own hardware. There is one person per install and no accounts. They use it between job searches as well as during them: they log their career as it happens, then come back when they need to apply, track and interview.

The design should also work for other developers who later self-host the same open-source (GPL-3.0) app with their own career data. Copy and flows must not assume they belong to one particular person.

## Product Purpose
Pica is a self-hosted vault for a whole career, plus the job-search pipeline that draws on it. The user keeps a complete, unfiltered record of their work history (positions, achievements, journal entries). When a job search starts, the app scrapes job boards, scores how relevant each listing is, generates a tailored LaTeX CV for each application from the full record, tracks applications through interview stages to offers, and watches Gmail for rejection emails.

Success looks like this: the user gets a focused CV in place of a generic one, and the search mostly runs itself because the career record is already there.

## Positioning
**Career memory first, job tracker second.** A spreadsheet or a SaaS tracker (Huntr, Teal, LinkedIn) only exists while someone is applying. Pica keeps everything, unfiltered, long after a search ends, then trims it down to a clean, focused CV for each job. Three things back this up: the user owns the data on their own machine ("Your job search organised. Fully Yours."), the UI is bespoke, and there is a magpie mascot. The magpie fits because it is a bird that collects things worth keeping and also finds and collects shiny objects (new jobs)

## Operating Context
- Self-hosted with Docker Compose on a Raspberry Pi 2 (armv7). The SPA is served by FastAPI and opened in a browser on the local network.
- Background work runs on a single RQ worker: scrapes, parsing, relevance evaluation, the CV pipeline, LaTeX compiles and Gmail checks. Many actions are therefore asynchronous, and the UI reports queue and worker state. The magpie in `WorkerMascot` does this.
- LLM work goes through OpenRouter and costs real money. Every call is logged and shown on the Cost settings page.
- Main areas: Dashboard (with first-run onboarding), Jobs inbox, Applications, Interviews, Offers, My profile (work history, journal, current employment) and Settings (personal details, scrape sources, Gmail monitor, cost, import/export).
- Light, dark and system themes are supported.

## Capabilities and Constraints
- Scrape sources are plug-in modules.
- Do not overflow users with choice - Applications, Interviews and Offers only show up in the menu once they have entries. Employment only shows while the user holds a position.
- Runtime dependencies must run on armv7 (pure Python or armv7 wheels). That applies to the frontend bundle as well: keep it light for a low-power server.
- Not decided: target market and language beyond what the code implies today (one Polish board, PLN salary placeholder, English UI), and whether the app is desktop-first or must work fully on mobile.

## Brand Commitments
- Name: Pica. Tagline: "Your job search organised. Fully Yours."
- **The magpie mascot is binding.** It's a round, flat-coloured bird (`frontend/src/mascot/Magpie.tsx`), used as the brand mark (head only) and as the animated worker-status character with moods: idle, working, queued, error, loading.
- The UI is meant to be bespoke, not a generic admin template.

## Evidence on Hand
- The real product: the full working app in `frontend/src` and `backend/app`.
- Exploratory brand imagery in `_ref/_website_ideas/` (AI-generated forest, owl and magpie concepts). These are reference only, not committed assets.
- There are no testimonials, users, metrics or press. Don't invent any.

## Product Principles
1. **Keep everything, then filter at the point of use.** Capturing career history should be easy and complete. Curating it happens later, per application.
2. **The vault outlives the search.** Design for long-term, calm use between searches as well as busy periods of applying.
3. **Automation stays visible.** Background jobs, LLM spend and automatic state changes (such as Gmail rejections) are always shown, never hidden.
4. **Yours, on your hardware.** No accounts, no outside service the user didn't choose, and a low resource footprint.
5. **Character in the details.** The magpie and the bespoke touches give the app its personality. They must never get in the way of the work.
