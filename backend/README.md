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
  api/
    __init__.py    aggregates routers under /api
    routes/        one module per resource (health.py as example)
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
