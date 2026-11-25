# CareerVaultHQ — PR Review Guidelines

## System Context & Hardware Constraints

- **Target Hardware:** Raspberry Pi 2 (`armv7`) running via Docker Compose.
- **Dependency Check:** Flag any new runtime dependencies in `pyproject.toml` that lack `armv7` wheels, require heavy C/Rust compilation, or are high-memory packages (e.g., `torch`, `scipy`, `playwright`, `pandas`). Heavy packages belong in `dev` extras or must be avoided.
- **Database:** SQLite (`/data/careervault.db`). Watch out for SQLite-specific concurrency locks (e.g., long-running write transactions across the API and RQ worker) and unsupported SQLite DDL/types.
- **Background Processing:** Single RQ worker (`app/workers/worker.py`) processing one queue, fed by a scheduler (`app/scheduler/scheduler.py`). Flag blocking I/O or long synchronous loops in FastAPI routes that should be offloaded to RQ tasks, as well as non-idempotent scheduled tasks.

## Architecture & Code Organization

- **Thin Routers (`backend/app/api/routes/`):** Routes should only handle HTTP parsing, validation (Pydantic v2), dependency injection, and response serialization. Flag business logic or direct complex ORM queries placed inside route handlers instead of `services/` or `tasks/`.
- **LLM Integration:** All LLM calls **must** go through `OpenRouterService` (which logs usage/costs to `openrouter_calls`). Flag any direct calls to OpenAI, Anthropic, `httpx`/`requests` to LLM endpoints, or bypassing of `OpenRouterService`.
- **Centralised LLM Call Config (`backend/app/llm_calls.py`):** Every OpenRouter call **must** be registered there as a `ChatCall` (for `OpenRouterService.chat`) or `DecisionCall` (for `OpenRouterService.decide`) with a unique `key`, `source` label, default `model`, `purpose` and `used_in`, listed in `ALL_CALLS`, and passed as `call=`. The class fixes the kind of call; only the model is configurable — flag any attempt to make the kind configurable or to pass the base `LlmCall`. Each new call must also be added (commented out) to `backend/llm_models.example.toml`, the per-deployment override file (`OPENROUTER_MODELS_FILE`). Flag hardcoded model ids, ad-hoc `source` strings, or new per-feature model settings in `config.py` outside that registry.
- **Scrape Sources (`backend/app/tasks/scrape/sources/`):** New job board plugins (`<key>.py`) must adhere to the contract defined in the package docstring and properly sync/mirror into the `scrape_sources` table.
- **Frontend Structure (`frontend/src/<feature>/`):** Code should be organized by feature folder (containing its own `api.ts`, components, and CSS) using React 19 and strict TypeScript.

## Backend Performance & Database Efficiency

- **SQL & ORM Query Optimization:**
  - **N+1 Queries & Eager Loading:** Flag lazy-loaded relationships accessed inside loops or serialization layers. Require `selectinload` or `joinedload` where appropriate.
  - **Unbounded Queries & In-Memory Filtering:** Flag `SELECT` queries lacking `.limit()`/pagination on growing tables (e.g., jobs, logs, openrouter calls), or fetching entire tables into Python lists just to filter, sort, or count them instead of using SQL `WHERE`, `ORDER BY`, or `func.count()`.
  - **Over-fetching & Missing Indexes:** Flag fetching full ORM models with large text/JSON columns when only a few scalar columns are needed. Flag new queries filtering or sorting by unindexed columns on large tables.
  - **Bulk Operations:** Flag row-by-row `.add()` / `.commit()` loops for batch inserts or updates instead of bulk operations or batched commits.
- **Memory & CPU Footprints (Raspberry Pi 2 Limits):**
  - **Unbounded Memory Growth:** Flag loading large files, HTTP payloads, or full query result sets into memory at once instead of streaming, chunking, or using generators (`yield_per`).
  - **Concurrency & Event Loop Starvation:** Flag synchronous CPU-bound operations (e.g., heavy regex, HTML parsing, JSON serialization of massive payloads) or synchronous I/O inside `async def` FastAPI routes that block the event loop.
- **Problematic Backend Anti-Patterns:**
  - **Unclosed Resources & Leaks:** Flag HTTP clients (`httpx.AsyncClient`), file handles, or DB sessions created without context managers (`with` / `async with`) or shared singleton pooling.
  - **Missing Timeouts & Retries:** Flag outbound HTTP requests (`httpx`/`requests`) lacking explicit timeouts, or unbounded retry loops that can stall the single RQ worker indefinitely.
  - **Swallowed Exceptions:** Flag bare `except:` or `except Exception:` blocks that silently pass or swallow errors without proper logging, rollback, or re-raising.

## Code Design & Maintainability

- **Encapsulation & Modularity:** Code should be well-encapsulated into focused, cohesive modules, classes, or functions with clear boundaries and single responsibilities. Flag monolithic functions, leaky abstractions, or tightly coupled components that cross domain/feature boundaries unnecessarily.
- **DRY & No Redundant Work:** Flag duplicated logic across routes, services, tasks, or frontend components that should be extracted into shared helpers/services. Also flag redundant computation or duplicate API calls doing the same work.
- **Dead & No-Op Code:** Flag unused imports, variables, functions, unreachable branches, commented-out code blocks, and no-op logic that serves no purpose.
- **Readability & Maintainability:** Code must be straightforward and easy to follow. Flag overly clever/obscure one-liners, deeply nested conditionals, magic numbers/strings, unclear naming, or complex logic lacking clear structure that will be hard to maintain.

## Database & Schema Rules

- **No Alembic Migrations:** The project is in active development and recreates schemas via `init_db()` (`Base.metadata.create_all`).
  - Do **not** flag missing Alembic migration files for model changes in `models.py`.
  - Flag unnecessary Alembic migration scripts or unrequested entries added to `ADDED_COLUMNS` in `db.py`.

## Code Quality, Testing & Security Checklist

- **Test Coverage:** Changes to `backend/app/api/routes/` or `backend/app/tasks/` must include corresponding unit/integration tests in `backend/tests/` (using `fakeredis` rather than live Redis).
- **Formatting & Linting Standards:**
  - **Backend:** Must adhere to `ruff` rules (`E`, `F`, `I`, `B`, `UP`) with a max line length of `125`, Python 3.12 typing syntax (`X | Y` instead of `Optional`/`Union`), and Pydantic v2 / SQLAlchemy 2.0 idioms (flag legacy SQLAlchemy 1.x `.query()` or Pydantic v1 `@validator`).
  - **Frontend:** Must pass ESLint (`npm run lint`) and strict TypeScript checks (`tsc -b --noEmit`). Flag `any` types or broken type definitions.
- **Secrets & Hygiene:** Flag any committed `.env` files, hardcoded API keys (OpenRouter, Gmail credentials), or accidental build artifacts (`frontend/dist/`, `.db` files).
- **PR Target:** Verify the PR targets `dev` (not `main` or `master`).