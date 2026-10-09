# Development setup

## API

```bash
cd apps/api
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install aiosqlite httpx mypy pytest pytest-asyncio ruff
python -m alembic upgrade head
```

## LLM settings

All settings are in `app/core/config.py` and read from `.env`:

| Variable | Default | Description |
| --- | --- | --- |
| `ANALYSIS_ENABLED` | `True` | Whether analysis endpoints serve. |
| `LLM_PROVIDER` | `mock` | `mock` (deterministic heuristics, runs in CI) or `openai` (live LLM). |
| `LLM_MODEL` | `mock-academic-analyzer-v1` | The model used when `LLM_PROVIDER=openai`. |
| `LLM_API_KEY` | `(empty)` | Required when `LLM_PROVIDER=openai`. |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Optional override for the OpenAI base URL. |
| `LLM_TIMEOUT_SECONDS` | `60` | Timeout for provider calls. |
| `LLM_MAX_OUTPUT_TOKENS` | `4000` | Max output tokens from the model. |
| `ANALYSIS_MAX_INPUT_CHARS` | `60000` | Max character limit for the analysis input. |
| `ANALYSIS_INCLUDE_DOCUMENT_TEXT` | `False` | Whether to include document text in the prompt. Default False is the privacy default. |
| `ANALYSIS_COST_PER_1K_TOKENS` | `0.0` | Cost rate for telemetry. |

The planner and agent runtime carry their own settings (gates, model tiers, step and
token budgets) in the same file; look for the `planning_` and `agent_` prefixes.

## Auth security defaults

Passwords are hashed with Argon2 off the event loop (`hash_password` and
`verify_password` run in a worker thread so a login does not stall the request
queue), and validation error responses never echo request bodies back.

| Variable | Default | Description |
| --- | --- | --- |
| `RATE_LIMIT_ENABLED` | `True` | Whether the application rate limiter answers. |
| `AUTH_RATE_LIMIT_MAX` | `10` | Register/login requests per client address within one window. |
| `AUTH_RATE_LIMIT_WINDOW_SECONDS` | `60` | Sliding window length. |

The limiter is in-process and keyed by client address, which is correct for a
single-node deployment. Behind a load balancer, move the same policy to the edge
instead of trusting per-process counters.

## Web security defaults

`next.config.ts` ships security headers on every response:

- A Content Security Policy — `default-src 'self'`, `base-uri 'self'`,
  `form-action 'self'`, `object-src 'none'`, `frame-ancestors 'none'` — with
  `connect-src 'self'` plus the build-time API origin. Script and style sources
  are `'unsafe-inline'` on purpose: the theme/locale bootstrap runs as an inline
  blocking script and Tailwind injects styles inline in development. A
  nonce-based policy would be stricter but requires dynamic rendering for every
  page; the trade-off is documented next to the constant. `'unsafe-eval'` is
  added only when `NODE_ENV=development`.
- `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
  `X-Frame-Options: SAMEORIGIN`, a `Permissions-Policy` that disables
  camera/microphone/geolocation, and HSTS (ignored over HTTP, active once served
  over HTTPS). `upgrade-insecure-requests` is deliberately omitted so plain-HTTP
  local builds keep working.

The workspace also re-reads a live agent run on a 4s timer while it is running,
so progress moves without a click, and both `(app)/error.tsx` and
`global-error.tsx` turn a crash into a recoverable, translated screen instead of
a blank one.

### Mock provider (CI default)

When `LLM_PROVIDER=mock`, the full pipeline (parse → validate → persist) runs using the deterministic heuristics engine (`MockLLMProvider`). The mock provider runs without an API key and produces structured output that passes validation.

The golden evaluation gate does **not** use the mock provider. `python -m app.ai.evaluation.report` replays twelve hand-written transcripts through `RecordedTranscriptProvider`, so the gate scores the pipeline against output the heuristic engine did not produce. `tests/test_evaluation_independence.py` asserts that separation by parsing the evaluation modules' AST and by checking every recorded transcript parses, validates and stays grounded. All 12 fixtures pass with `classification_accuracy 1.0`, `evidence_grounding 1.0`, `hallucination_rate 0.0`, and all 36 planted defects are caught.

The one thing this does not measure is how a real model answers the analyzer prompt; that needs an API key and is deliberately not in CI.

### OpenAI provider (live LLM)

When `LLM_PROVIDER=openai`, the provider uses the configured model and sends structured prompts through the `LLMProvider` abstraction. The prompts use an envelope (`system` + `developer` + `untrusted-data`) with explicit `{document_text}` injection only when `analysis_include_document_text` is `True`. Prompt version is fixed at `assignment_analyzer_v1`.

### Offline mode

No external services are required for the AI pipeline beyond the database: `MockLLMProvider`
needs no API key, and `analysis_enabled` can be set to `False` to disable the analysis endpoints
entirely. The planner and agent runtime share the same provider switch, so the full loop
(analysis → planning → execution) is testable offline. The CI suite (`pytest -q`) passes without
any LLM credentials.

## Migration

```bash
python -m alembic upgrade head
python -m alembic downgrade base   # to reset
```

Migrations run once at deploy time, not on API boot: the compose `migrate` job
applies them and the API service waits for it to complete successfully.
`alembic current` then prints the applied head revision so the operator sees what
ran. Table-by-table history — the Phase 3 analysis tables, the Phase 4 planning
tables, and the Phase 5 agent/run tables and tool audit — is recorded in the
`apps/api/alembic/versions` files.

## Quality gates

Commands that must stay green. From `apps/api`:

```bash
python -m pytest -q                       # 372 passed
python -m ruff check app tests alembic    # clean
python -m mypy app                        # 123 source files
python -m app.ai.evaluation.report        # golden gate, exit 0
```

From `apps/web`:

```bash
npx tsc --noEmit
npm run lint
npm test                                 # 157 passed
npm run build
```

The `MockLLMProvider` exercises the full parse -> validate -> persist pipeline in CI so that no live LLM call is required. The `force` parameter derives a distinct idempotency key (`sha256(base:uuid4)`) to satisfy the `UNIQUE(assignment_id, idempotency_key)` constraint.

## End-to-end tests

The Playwright suite needs a running API on port 8000 and a **production build
of the web app that was built with the same API URL**:

```bash
# apps/api
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# apps/web
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/api/v1 npm run build
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/api/v1 npm run start

# apps/web, once both are up
E2E_BASE_URL=http://127.0.0.1:3000 npx playwright test
```

Two traps cost real time here, so they are worth stating:

- `NEXT_PUBLIC_API_URL` is **baked in at build time**, not read at runtime.
  Rebuilding without it silently points the app at `http://localhost:8000`, and
  because the browser is on `127.0.0.1` the auth cookie is then never sent
  back. Every test fails at the login redirect with no obvious cause.
- `next start` warns that it "does not work with `output: standalone`". It does
  serve the app here, but the standalone bundle in `.next/standalone` is *not*
  usable directly: its static chunks are not copied, so the page renders
  without hydrating. Use `npm run start`.
