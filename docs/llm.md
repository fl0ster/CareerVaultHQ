# LLMs in CareerVaultHQ: providers and per-task configuration

This document covers three things:

1. How the app uses LLMs.
2. How viable it is to swap OpenRouter for your own model.
3. How the pluggable-provider design and the single `llm.toml` config work.

## 1. How LLMs are used

Every LLM call goes through one client, `OpenRouterService` (`backend/app/services/openrouter.py`). Each call, failed ones included, is recorded in the `openrouter_calls` table, along with its cost when the API reports one. The Cost page reads from that table. There are two kinds of call:

| Kind | Method | What it returns | Endpoint |
|---|---|---|---|
| **chat** | `service.chat(...)` | free text or JSON | OpenAI-style `POST /chat/completions` |
| **decision** | `service.decide(...)` | calibrated probabilities for typed questions (`noul` = P(yes), `choice`, `score`) about a `state` | OpenRouter **Jev Decisions API** `POST /api/alpha/decisions` (`typesafe/jev-1.14`) |

### Call inventory

| Task key (`llm.toml`) | Kind | Where | What for | Volume |
|---|---|---|---|---|
| `evaluate.match` | decision | `tasks/evaluate/evaluate.py` | P(job matches the candidate profile) → `job_evaluations.match_probability` | every scraped job (highest) |
| `candidate_profile.create` | chat | `services/candidate_profile.py` | candidate profile text from the work history | once per work-history change |
| `job.score_explanation` | chat | `services/score_explanation.py` | 2-3 sentence explanation of a score | on click |
| `parse.technologies` | chat | `tasks/parse/parse.py` | technologies + evidence quotes from a job description | per shortlisted job |
| `interview_steps.presence` | decision | `tasks/parse/parse.py` | does the text describe the interview process? | per shortlisted job / recruiter mail |
| `interview_steps.extract` | chat | `tasks/parse/parse.py` | ordered interview stages as JSON | same, when present |
| `interview_steps.faithful` | decision | `tasks/parse/parse.py` | are the extracted stages faithful to the text? | same |
| `gmail.rejection` | decision | `tasks/gmail/rejections.py` | is this e-mail a rejection? | every monitored mail |
| `gmail.company_role` | chat | `tasks/gmail/rejections.py` | company + role named in the mail (JSON) | per rejection / interview mail |
| `work_history.prefill` | chat | `tasks/work_history/prefill.py` | fills a work-history entry from an accepted offer | per accepted offer |
| `cv_import.extract` | chat | `tasks/cv_import/extract.py` | CV PDF text → structured data (strict `json_schema`) | per CV upload |
| `cv.relevance` | decision | `tasks/cv/generate.py` | P(past role is relevant to the target job) | per role, per CV |
| `cv.context` / `cv.tech` / `cv.early` | chat | `tasks/cv/generate.py` | rewrite / filter / condense each role | per role, per CV |
| `cv.categories` / `cv.summary` / `cv.role` / `cv.core_tech` | chat | `tasks/cv/generate.py` | CV headline sections | 4 per CV |
| `api.chat` / `api.decide` | chat / decision | `api/routes/openrouter.py` | ad-hoc `POST /api/openrouter/{chat,decide}` | manual |

In total there are 15 chat tasks and 6 decision tasks.

### What was tied to OpenRouter (before this change)

- **Chat request body:** `usage: {"include": true}` asks OpenRouter to report the cost. Strict OpenAI-compatible servers can reject unknown fields like this.
- **Chat headers:** `HTTP-Referer` and `X-Title` are OpenRouter attribution headers.
- **Decision calls:** the Jev Decisions API exists only on OpenRouter. No other provider (OpenAI, Ollama, LM Studio, vLLM…) offers an equivalent "probabilities for typed questions" endpoint.
- **Settings:** models and parameters were spread across env settings (`OPENROUTER_CHAT_MODEL`, `OPENROUTER_DECISION_MODEL`, `CV_CHAT_MODEL`, `CV_IMPORT_MODEL`) and literals at about 20 call sites (`temperature=0/0.2/0.3`, `max_tokens=200`).

## 2. Viability of "bring your own LLM"

| Area | Verdict | Notes |
|---|---|---|
| Chat tasks | **High** | Every call site already sends OpenAI-format messages. Any `/chat/completions` server works: OpenAI, Ollama, LM Studio, vLLM, llama.cpp server, Together, Groq… |
| `cv_import.extract` | **Medium** | Sends a strict `response_format: json_schema`. Supported by OpenAI, Ollama ≥ 0.5, LM Studio, vLLM and llama.cpp. Needs a large context window, because the input can be up to `CV_IMPORT_MAX_CHARS` = 60k characters. Small local models may return invalid JSON; the import then fails with a clear error. |
| JSON-in-text chat tasks | **Medium-high** | `parse.technologies`, `interview_steps.extract`, `gmail.company_role` and `work_history.prefill` parse JSON out of free text and tolerate failures: a bad reply means "nothing extracted". Weaker models extract less, but nothing breaks. |
| Decision tasks | **Low, so they stay on OpenRouter** | Downstream logic depends on *calibrated* probabilities: `RELEVANT_JOB_THRESHOLD`, `INTERVIEW_STEPS_THRESHOLD` and the CV relevance thresholds. A plain chat model has no endpoint that gives equivalent numbers. They go through a `DecisionProvider` interface so another backend can be added later (see §5). |
| Cost tracking | OK | Local servers report no `usage.cost`, so `openrouter_calls.cost` is `NULL`. The Cost page already handles nulls, and token counts are still recorded. |
| Hardware | OK | The Pi 2 cannot run a model itself. "Your own LLM" means a server elsewhere on the network, or a hosted API. The config loader uses only the standard library (`tomllib`), so no new dependency was added. |

**Conclusion:** make providers pluggable per task. Chat tasks can move to your own model all together or one at a time. Decision tasks stay on OpenRouter's Jev behind an interface.

## 3. Design

```
call site ──task="cv.summary", source="tasks.cv.summary"──▶ OpenRouterService
                                                            │ 1. llm.toml: resolve(task) → provider, model, params
                                                            │ 2. build provider (ChatProvider | DecisionProvider)
                                                            │ 3. provider builds HttpRequest(url, body, headers, timeout)
                                                            │ 4. POST + record in openrouter_calls
                                                            └ 5. provider parses the response (text | answers)
```

- **`backend/app/llm.toml`** is the only place that sets models and parameters.
- **`app/services/llm/config.py`**:
  - Pydantic models validate the file when it loads: unknown provider, a decision task on a provider without decision support, misspelt keys, out-of-range temperature.
  - `LlmConfig.resolve(task, kind)` merges the task entry over the kind's defaults.
  - The file is re-read when its mtime changes, so edits apply without restarting the worker.
- **`app/services/llm/providers.py`**:
  - `ChatProvider` protocol, with two implementations:
    - `OpenAICompatibleChat`: plain OpenAI body. It sends `Authorization` only when a key is configured.
    - `OpenRouterChat`: also adds `usage.include` and the attribution headers.
  - `DecisionProvider` protocol, with one implementation: `JevDecisions`.
  - Providers only translate requests and responses. HTTP, logging and error handling stay in the service.
- **`OpenRouterService`** keeps its name, its errors (`OpenRouterError`, `OpenRouterNotConfigured`) and the `openrouter_calls` table. This avoids churning every caller and the frontend. `chat()` and `decide()` now require a `task`. Explicit `model`, `temperature`, `max_tokens` and `extra` arguments still override the config; the HTTP API relies on this.
- **`task` vs `source`:**
  - `task` is the tuning key in `llm.toml`.
  - `source` is the audit label shown on the Cost page. It is unchanged.
  - One task can have several sources. For example, `interview_steps.*` serves both job parsing and the Gmail interview mails.
- **Secrets stay in the environment.** A provider names its key's env var with `api_key_env`. `OPENROUTER_API_KEY` and `LOCAL_LLM_API_KEY` are also read from `backend/.env`, because they are `Settings` fields. Any other name is read from the process environment.

## 4. How to use your own model

1. Run an OpenAI-compatible server on a machine that can host a model. For example, Ollama: `ollama serve` and `ollama pull llama3.1:8b`, which serves `http://<host>:11434/v1`.
2. In `llm.toml`, uncomment `[providers.local]` and set its `base_url`. If the server needs a key, set `LOCAL_LLM_API_KEY`.
3. Choose how much to move:

   ```toml
   # (a) every chat task on your own model; decisions stay on OpenRouter
   [defaults.chat]
   provider = "local"
   model = "llama3.1:8b"

   # (b) or just one task: keep the defaults and override it
   [tasks."cv.summary"]
   kind = "chat"
   description = "..."
   temperature = 0.2
   provider = "local"
   model = "qwen2.5:14b-instruct"
   ```
4. Lower `CV_MAX_WORKERS`, often to 1, if your server handles one request at a time. Consider raising the provider's `timeout`.
5. Decision tasks still need `OPENROUTER_API_KEY`. Without it, evaluations, rejection detection, interview-step checks and CV relevance fail with "not configured", exactly as they did before this change.

**In Docker:** copy `app/llm.toml` to the data volume, edit it, and set `LLM_CONFIG_PATH=/data/llm.toml` on both the `careervaulthq` and `worker` services. `docker-compose.yml` already has this line, commented out.

### Config reference

| Section | Keys |
|---|---|
| `[providers.<name>]` | `type` (`openrouter` \| `openai_compatible`), `base_url`, `decisions_url` (openrouter), `api_key_env`, `timeout`, `site_url` / `site_name` (openrouter) |
| `[defaults.chat]`, `[defaults.decision]` | `provider`, `model` (required); `temperature`, `max_tokens`, `extra` (optional) |
| `[tasks."<key>"]` | `kind` (`chat` \| `decision`), `description`; optional `provider`, `model`, `temperature` (0-2), `max_tokens`, `extra` (a table merged into the request body, e.g. `top_p`, `seed`, OpenRouter `provider` routing) |

**Precedence:**
- `model`, `temperature`, `max_tokens`: call argument, then task, then kind default.
- `extra`: the default's table, overlaid by the task's, overlaid by the call's.

**Removed env vars:** `OPENROUTER_CHAT_MODEL`, `OPENROUTER_DECISION_MODEL`, `OPENROUTER_BASE_URL`, `OPENROUTER_TIMEOUT`, `OPENROUTER_SITE_URL`, `OPENROUTER_SITE_NAME`, `CV_CHAT_MODEL` and `CV_IMPORT_MODEL`. Set these in `llm.toml` instead.

## 5. Extending

- **Another chat API style.** Implement `ChatProvider`: `chat_request` builds the HTTP request and `chat_text` reads the text. Add a `type` literal in `config.py` and a branch in `build_chat_provider`.
- **Another probability model.** Implement `DecisionProvider` (`decision_request` and `decision_answers`), returning answers in the Jev shape `{"<question>": {"type": "noul", "noul": p}}`. Add its type to `DECISION_PROVIDER_TYPES` and to `build_decision_provider`. A natural candidate is a **logprob-based provider**:
  - Ask a chat model the question with "answer yes or no".
  - Request `logprobs` / `top_logprobs`, and read P(yes) = softmax over the "yes"/"no" tokens.
  - OpenAI, vLLM and llama.cpp return logprobs; Ollama only in recent versions.
  - If no logprobs are available, ask for structured `{"probability": x}` JSON. This is less calibrated, so the thresholds would need re-tuning.

  Such a provider wraps a chat endpoint, so it needs the chat-style `base_url` plus a model that follows instructions.

## 6. Follow-ups (not in this change)

- Rename `OpenRouterService`, its errors, `openrouter_calls` and `/api/openrouter` to provider-neutral names in one dedicated PR. This was deliberately kept out of this change to avoid conflicts with in-flight branches.
- Optional per-model pricing in `llm.toml`, so local or self-hosted calls show an estimated cost.
- The logprob `DecisionProvider` described in §5, behind an opt-in provider type, with thresholds re-tuned against Jev on a sample of past evaluations.
- Show the resolved task configuration, read-only, on the Settings page.
