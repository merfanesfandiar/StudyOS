# Development setup

## API

```bash
cd apps/api
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install aiosqlite httpx mypy pytest pytest-asyncio ruff
python -m alembic upgrade head
```

## LLM settings (Phase 3)

All settings are in `app/core/config.py` and read from `.env`:

| Variable | Default | Description |
| --- | --- | --- |
| `ANALYSIS_ENABLED` | `True` | Whether analysis endpoints serve. |
| `LLM_PROVIDER` | `mock` | `mock` (deterministic heuristics, runs in CI) or `openai` (live LLM). |
| `LLM_MODEL` | `gpt-4o-mini` | The model name used by `OpenAIProvider`. |
| `LLM_API_KEY` | `(empty)` | Required when `LLM_PROVIDER=openai`. |
| `LLM_BASE_URL` | `(empty)` | Optional override for the OpenAI base URL. |
| `LLM_TIMEOUT_SECONDS` | `30` | Timeout for provider calls. |
| `LLM_MAX_OUTPUT_TOKENS` | `4096` | Max output tokens from the model. |
| `ANALYSIS_MAX_INPUT_CHARS` | `32000` | Max character limit for the analysis input. |
| `ANALYSIS_INCLUDE_DOCUMENT_TEXT` | `False` | Whether to include document text in the prompt. Default False is the privacy default. |
| `ANALYSIS_COST_PER_1K_TOKENS` | `0.02` | Cost rate for telemetry. |

### Mock provider (CI default)

When `LLM_PROVIDER=mock`, the full pipeline (parse → validate → persist) runs using the deterministic heuristics engine (`MockLLMProvider`). The mock provider runs without an API key and produces structured output that passes validation. The 12 golden dataset fixtures in `tests/test_golden_analysis.py` verify that all fixtures pass with `classification_accuracy 1.0`, `evidence_grounding 1.0`, `hallucination_rate 0.0`.

### OpenAI provider (live LLM)

When `LLM_PROVIDER=openai`, the provider uses the configured model and sends structured prompts through the `LLMProvider` abstraction. The prompts use an envelope (`system` + `developer` + `untrusted-data`) with explicit `{document_text}` injection only when `analysis_include_document_text` is `True`. Prompt version is fixed at `assignment_analyzer_v1`.

### Offline mode

No external services are required for the analysis pipeline beyond the database: `MockLLMProvider` needs no API key, and `analysis_enabled` can be set to `False` to disable the endpoints entirely. The full CI suite (`pytest -q`) passes without any LLM credentials.

## Migration

```bash
python -m alembic upgrade head
python -m alembic downgrade base   # to reset
```

The Phase 3 migrations create 4 tables (`assignment_analyses`, `analysis_runs`,
`analysis_questions`, `analysis_classifications`) plus indexes and foreign keys
(`0003_phase3_analysis.py`), then add a monotonic `revision` to each analysis so
"the latest analysis" is well defined after a re-analysis (`0004_analysis_revision.py`).

## Quality gates

Commands that must stay green. From `apps/api`:

```bash
python -m pytest -q                       # 135 passed
python -m ruff check app tests alembic    # clean
python -m mypy app                        # 95 source files
python -m app.ai.evaluation.report        # golden gate, exit 0
```

From `apps/web`:

```bash
npx tsc --noEmit
npm run lint
npm test                                 # 70 passed
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
