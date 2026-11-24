# CareerVaultHQ backend

FastAPI REST API that also serves the built React/Vite frontend.

## Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## Development

Run the API with auto-reload:

```bash
uvicorn app.main:app --reload
```

Run the Vite dev server separately (`npm run dev` in `frontend/`). CORS is
preconfigured for `http://localhost:5173`. In the frontend, call the API at
`/api/...`; add a Vite proxy to `http://localhost:8000` if you want to avoid
hard-coding the host.

## Production-style run (API + frontend from one server)

```bash
cd frontend && npm run build && cd ../backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The server mounts `frontend/dist`:

- `/assets/*` are served as static files.
- `/api/*` routes go to FastAPI (docs at `/api/docs`).
- Every other path returns `index.html` so client-side routing works.

If `frontend/dist` does not exist the SPA mount is skipped and only the API runs.

## Tests

```bash
pytest
```

## Layout

```
app/
  main.py          app factory, middleware, router wiring
  config.py        settings loaded from env / .env
  spa.py           static + SPA fallback for the Vite build
  queue.py         Redis connection + RQ queue (API side)
  workers/         Background worker entrypoint
    worker.py      RQ worker for the single job queue (LaTeX + scraping): python -m app.workers.worker
  tasks/latex.py   pdflatex compile step executed by the worker
  tasks/scrape/    worker job scrape(): runs the scraper plugins and stores new listings in jobs
    sources/       one plugin module per job board (drop a <key>.py file to add a source; see the
                   package docstring for the contract). Mirrored into the scrape_sources table
                   (enabled, scrape interval, health, relevance) by services/sources.py
  tasks/parse/     worker job parse_job(): extracts title/company/description with the source's
                   parse_* hooks
  tasks/cv/        CV tailored to one parsed job (worker job generate_cv): history.py builds the
                   coherent timeline from relevance-scored roles, render.py fills cv_template.tex,
                   generate.py orchestrates the OpenRouter calls and the pdflatex compile
  tasks/cv_import/ CV PDF import preview (worker job import_cv, POST /api/cv-import): pypdf text +
                   link annotations -> one structured chat extraction -> validated candidate
                   details + work history in the shapes PUT /api/candidate-details and
                   POST /api/work-history/json accept; nothing is saved
  tasks/gmail/     Gmail rejection monitor (worker job check_rejection_mails, scheduled by
                   scheduler/gmail.py): Jev is_rejection -> chat extraction of company/role ->
                   unique match against open applications -> REJECTED event (source "gmail")
  integrations/gmail/  Apps Script web app (apps_script.gs, pasted into the monitored Google
                   account) and its HTTP client; setup instructions live in Settings > Gmail monitor
  services/
    openrouter.py  LLM client (chat completions + Jev decisions); logs every call to the
                   openrouter_calls table. Routes/tasks use OpenRouterService directly, naming
                   an llm.toml task; /api/openrouter/* exposes it over HTTP
    llm/           pluggable providers (OpenRouter, any OpenAI-compatible server for chat) and
                   the loader of app/llm.toml, the one file setting the provider, model and
                   parameters of every LLM task (see docs/llm.md)
    companies.py   resolves the scraped company name to a canonical companies row
                   (normalise -> alias lookup -> canonical lookup -> fuzzy match -> create)
    sources.py     syncs scrape_sources rows with the plugin modules, records per-source run
                   health and aggregates relevance per source (/api/sources)
  api/
    __init__.py    aggregates routers under /api
    routes/        one module per resource (health.py, latex.py, jobs.py, companies.py, ...)
tests/
```

## Docker (Raspberry Pi 2 / ARMv7)

The `Dockerfile` at the repo root builds the frontend in a Node stage (natively on
your workstation) and packages it with the API in a `python:3.12-slim` image for
`linux/arm/v7`. See the comments in `Dockerfile`, `docker-compose.yml` and
`build-pi.sh` at the repo root.

```bash
# on your workstation (Docker Desktop with buildx)
./build-pi.sh                       # -> careervaulthq-latest.tar.gz
scp careervaulthq-latest.tar.gz pi@raspberrypi:~
# on the Pi
gunzip -c careervaulthq-latest.tar.gz | docker load
docker compose up -d                # copy docker-compose.yml to the Pi first
```

The SQLite database lives in the `/data` volume. `uvicorn[standard]` extras
(uvloop, httptools, watchfiles) are dev-only because they have no ARMv7 wheels.
