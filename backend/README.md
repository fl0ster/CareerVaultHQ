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
