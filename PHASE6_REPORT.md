# Phase 6: Professional Agent Tool System & Specialized Academic Workers — Final Report

## Summary

Phase 5 gave the agent runtime three tools and one loop. Phase 6 grows the *academic* work it can do
without widening the security boundary by a single inch. The registry now holds **29 deterministic
tools**: five core tools and twenty-four academic tools spanning mathematics, data, writing,
research, documents, code, and presentations. Eighteen task types are bound to seven specialized
academic workers, each of which sees only its own tool set.

The premise is unchanged from Phase 5 and is what the whole phase is built around: the model is not
trusted, and it cannot reach anything the code did not put in front of it. Every academic tool is a
pure function over text the runtime already holds — no shell, no subprocess, no filesystem, no HTTP,
no browser, no code execution, and no configuration option that would add one. The twenty-four new
tools are more capable, not more powerful: they compute exactly, read text, and draft, and none of
them opens a channel out of the run.

Phase 6 also publishes the boundary as data. The full tool catalogue, each tool's risk level and
argument schema, the worker that may call it, and the list of capabilities the runtime *lacks* are
all served by the API and rendered in the UI, so a student can read what the agent can do and cannot
do without opening a single document.

## What was built

### The academic toolkit — 24 tools

`apps/api/app/modules/agent/domain_tools.py` (1,922 lines) is a closed catalogue, grouped by the
category of work each tool serves:

| Category | Tools |
| --- | --- |
| `MATHEMATICS` | `calculate`, `solve_linear_system`, `prime_factorize`, `gcd_lcm` |
| `DATA` | `compute_statistics`, `detect_outliers`, `linear_regression`, `profile_dataset`, `detect_missing_values` |
| `WRITING` | `count_words`, `readability_score`, `top_keywords`, `assess_structure`, `suggest_outline` |
| `RESEARCH` | `extract_citations`, `format_citation` |
| `DOCUMENT` | `extract_document_metadata`, `segment_document`, `search_document`, `summarize_document` |
| `CODING` | `count_code_lines`, `extract_code_identifiers`, `check_syntax_balance` |
| `PRESENTATION` | `build_slide_outline` |

Every one is `LOW` risk, deterministic, and side-effect free. Two properties were enforced on purpose:

- **Exactness where exactness is possible.** `solve_linear_system` uses `Fraction` elimination, not
  floats, so a mathematics worker gets an answer rather than float noise. `calculate` walks an
  allow-list AST — constants, arithmetic, and eight named functions — and never `eval`s.
- **Honesty where honesty is required.** `summarize_document` is extractive: it selects the
  document's own sentences. A generative abstract is a model's job, not a tool's. `format_citation`
  refuses when a required field is missing rather than filling the gap with a plausible guess,
  because a fabricated citation is worse than a missing one.

### Risk levels and the dispatch ceiling

`AgentToolRisk` (`LOW`/`MEDIUM`/`HIGH`/`CRITICAL`) is a second, independent axis from
`ToolPermission`. A tool can hold every permission it declares and still be refused for being too
dangerous. `MAX_TOOL_RISK` is `MEDIUM` for the whole phase, so a future `HIGH` (code execution) or
`CRITICAL` (host filesystem) tool cannot be reached by declaring a permission — raising the ceiling
is a reviewed change in the phase that ships a sandbox. `ToolRegistry.require_granted` enforces both
axes, and `invoke_tool` is the only path to a tool's `invoke`.

### Specialized academic workers

`workers.py` binds the planner's domain-agnostic task vocabulary to bounded tool sets. Each of the
eighteen `AcademicTaskType` values is served by exactly one worker:

| Worker | Serves |
| --- | --- |
| `MATHEMATICS` | `SOLVE`, `PROVE` |
| `DATA` | `ANALYZE_DATA`, `EXPERIMENT`, `COLLECT_DATA` |
| `WRITING` | `WRITE`, `REVISE` |
| `RESEARCH` | `READ`, `RESEARCH` |
| `PRESENTATION` | `PRESENT` |
| `CODE` | `IMPLEMENT`, `VERIFY` |
| `REASONING` | `UNDERSTAND`, `ANALYZE`, `DESIGN`, `REVIEW`, `PRACTICE`, `SUBMIT`, `OTHER` |

Each worker also declares `capabilities` (the verbs it serves, independent of tool names) and
`supported_domains` (its academic domains). These are descriptive, not authorisation — a router or the
UI may match on them, but only `tool_ids` decides what a worker can call. Both are published through
the capabilities endpoint.

`REASONING` holds only the core tools and is the fallback for any unfamiliar task type. The active
worker's `tool_ids` narrow the prompt's catalogue, so a `MATHEMATICS` worker is never told the
code-analysis tools exist. The runtime emits a `WORKER_SELECTED` event when it resolves the worker for
a task, so which boundary a step ran under is in the event trail. `DEFAULT_WORKER_REGISTRY.validate`
(DEFAULT_TOOLS)` returns `[]` — every tool is reachable and every bound tool exists — and a test pins
it.

### Structured tool results

A tool no longer merely succeeds or fails. `ToolResult` carries an `AgentToolStatus` — `SUCCESS`,
`PARTIAL_SUCCESS`, `FAILED`, `BLOCKED`, `NEEDS_USER_INPUT`, `RATE_LIMITED`, `UNAVAILABLE` — plus
`summary`, `payload`, `reason`, `warnings`, `artifacts` and `metadata`, with `ok` derived from the
status so the two cannot disagree. Named constructors (`.success`, `.partial`, `.refusal`,
`.failure`, `.needs_user_input`, `.rate_limited`, `.unavailable`) make the intent explicit.

The status is load-bearing. `PARTIAL_SUCCESS` advances the step with its warning preserved rather
than being flattened into `SUCCESS` or `FAILED`; every other status maps to a persisted
`AgentToolInvocationStatus` and, on failure, to an `AgentFailureCategory`. The dispatcher records
`TOOL_INVOCATION_STARTED`, `TOOL_SELECTED`, `TOOL_INVOCATION_COMPLETED` (with status and warnings) or
`TOOL_INVOCATION_FAILED`, so the observability stream carries the structured outcome rather than a
boolean.

### Discovery and self-description

Every tool exposes a `version`, an `availability` (`AgentToolAvailability`), and an optional
`output_schema` alongside its argument schema; `find_tools(...)` answers "what could this worker call
right now" from the same grant and risk rules the dispatcher enforces. `invoke_tool` validates
arguments against the declared schema, validates the returned payload against `output_schema` when
present, and sanitises and truncates the summary at the boundary — so a tool that returns a shape it
did not declare is corrected, not trusted.

### The artifact read side

`list_artifacts` and `read_artifact` join the core tools, so a run can read back its own output. They
are scoped to `ToolContext.artifact_texts`, which the runtime fills only with the current run's own
artifacts, each capped before it arrives. The "filesystem" a tool can see is this run's output and
nothing else; there is still no tool that opens a file, lists a directory, or reaches a bucket.

### Public tool APIs (§38)

Two new endpoints publish the catalogue, and two more expose a run's own tool use:

- `GET /api/v1/tools` — the closed catalogue with category, permissions, risk, determinism,
  side-effect flag, version, availability, argument and output schema, and which workers may call
  each tool.
- `GET /api/v1/tools/{tool_id}` — one entry, or `AGENT_TOOL_NOT_FOUND`.
- `GET /{assignment_id}/agent/runs/{run_id}/tool-invocations` — every call the run made, blocked
  ones included, each with its structured status.
- `GET /{assignment_id}/agent/runs/{run_id}/tools` — per-tool usage counts for the run.

The two run read models are also addressed by run id alone
(`GET /api/v1/agent/runs/{run_id}/tool-invocations` and `.../tools`) for a client that holds a run id
and not an assignment id — the same data, the same ownership check, addressed differently.

### Budgets, rate limits, and idempotency (§24–27)

- **Per-step tool budget** (Phase 5, unchanged): `agent_max_tool_calls_per_step`, default 4.
- **Per-run tool budget** (new): `agent_max_tool_calls_per_run`, default 60. The per-step budget
  cannot see a run that looks reasonable every step but never converges; the run-scoped ceiling is
  counted from persisted invocation rows, so a resume cannot hand the run a fresh allowance. A breach
  fails the run with `AGENT_TOOL_RUN_LIMIT` (`VALIDATION_ERROR`).
- **In-step idempotency** (new): every tool is deterministic, so an identical call — same tool, same
  canonical JSON arguments — within one step is answered from the first result instead of being
  re-invoked. The repeat still counts against both budgets because it cost a provider round-trip to
  decide, and the `TOOL_INVOKED` event is marked `cached: true` so the saving is visible rather than
  assumed.

### Context provenance (§24)

Each step's `CONTEXT_BUILT` event now carries a per-section `provenance` list (which sources fed the
step, how many characters of each survived, which were truncated or dropped). The run detail exposes
the flattened, task-keyed record as `context_provenance`. It is stored on the append-only event as it
happened — never rewritten — so "why did the agent do that" is answerable after the fact.

### Artifact ownership (§security core)

`AgentArtifact.ownership` distinguishes `USER_OWNED`, `AGENT_OWNED`, `SYSTEM_GENERATED` and
`IMPORTED`. `_persist_artifact` may only ever write `AGENT_OWNED` output and raises
`AGENT_ARTIFACT_OWNERSHIP_INVALID` otherwise, so the runtime can never overwrite or claim the
student's work; revising a student artifact produces a new revision beside it. Added by migration
`0011_artifact_ownership`, with the historic rows defaulting to `AGENT_OWNED` because every artifact
that predates the column was runtime-produced.

## Defects the completion work found and fixed

**`domain_tools.py` was internally corrupted.** The file carried a duplicated `_STOPWORDS`
definition and a broken shared helper (`_parse_table`/`_detect_delimiter`) that the data tools depend
on. Repaired in place, with the data tools now exercised by behavioural tests.

**A duplicated worker-registry comment.** Two identical copies of the "closed set of workers"
docstring preceded `DEFAULT_WORKERS`, a residue of an earlier edit. Removed.

**The artifact-ownership column had no migration.** The model declared `ownership` but no Alembic
revision added it, so a migrated database and the ORM disagreed. Caught by the metadata drift guard
in `tests/test_migrations.py`; fixed with `0011_artifact_ownership`.

**`context_provenance` was a hardcoded `[]`.** The context builder had computed provenance since
Phase 5, and the run detail returned an empty list. The record now survives into the API response.

**The per-run tool ceiling did not exist.** A run could call up to `max_tool_calls_per_step` on every
step, forever. The new run-scoped budget, checked from persisted rows, closes it.

**`_builtin_tools` had dropped the academic catalogue.** Composing the core tools during the registry
work left the `*ACADEMIC_TOOLS` unpack out of the core-tuple build, silently shrinking the catalogue.
Restoring it surfaced a circular import (`domain_tools` imports `tools`, so eagerly building
`DEFAULT_TOOLS` at import time broke when `domain_tools` was imported first); `DEFAULT_TOOLS` is now
built lazily through `default_tools()` with a module-level `__getattr__`, so import order no longer
matters.

## Quality gate verification

| Gate | Command | Result |
| --- | --- | --- |
| API lint | `ruff check app/ tests/ alembic/` | all checks passed |
| API types | `mypy app/` | clean, 126 source files |
| API tests | `pytest -q` | 429 passed |
| API migration | `tests/test_migrations.py` | 10 passed |
| Web types | `tsc --noEmit` | clean |
| Web lint | `eslint .` | clean |
| Web unit | `vitest run` | 159 passed, 11 files |

The API suite grew by 34 domain-tool tests (`tests/test_agent_domain_tools.py`), which assert the
shared safety shape of every tool, the structured result statuses and their factories, argument and
output-schema validation, discovery via `find_tools`, the artifact read tools, worker capabilities,
the worker/tool reachability invariant, the risk ceiling, the in-step idempotency, the run tool
budget, hostile-input refusals, and a composed multi-domain workflow. `test_agent_runtime.py` gains a
parametrized run per academic domain asserting the run reached its own domain's tool and emitted the
worker/selection/completion event trail; `test_agent_api.py` covers the catalogue detail fields, the
capabilities surface, and the run-id-addressed read models.

## What was not verified

- **No real model was ever called.** Every provider is the deterministic mock. Token accounting,
  latency, and provider-side rate limiting remain unmeasured.
- **PostgreSQL was not available.** All 429 backend tests ran on SQLite. The row-locking path and the
  new migration's batch-alter are correct in the schema but unexercised against a real engine.
- **The migration was verified by test, not by an upgrade path.** `tests/test_migrations.py` applies
  it to a clean database; no upgrade from a populated Phase 6 database was performed.
- **The web catalogue UI was not exercised against a live API.** It is verified by types and unit
  tests, not end to end.
- **Persian and English copy for the new surface was extended only where types required it.** The
  catalogue endpoints are typed, but the browser flow was not re-run against a live stack.

## Known limitations

- **Delimited untrusted context is a mitigation, not a guarantee.** A payload in a student's document
  can still influence what text is written into a draft. It cannot change what runs, what is called,
  or what is reachable — and that structural limit is the one that holds.
- **Idempotency is per-step.** The same call in a later step re-invokes the tool. This is deliberate:
  the context may have changed between steps, so a run-wide cache could serve a stale result.
- **`summarize_document` is extractive**, so it will not read as a fluent abstract. That is the
  honest trade: a deterministic tool must not pretend to be a model.
- **No PDF or spreadsheet ingestion.** Tools operate on text the runtime already holds; there is no
  parser for binary documents, because adding one would mean a dependency the phase did not review.

## Files changed

### Backend

- `app/modules/agent/domain_tools.py` — 24-tool academic catalogue (repaired and extended)
- `app/modules/agent/workers.py` — seven workers covering all eighteen task types, each with
  `capabilities` and `supported_domains`
- `app/modules/agent/tools.py` — `AgentToolRisk`, `MAX_TOOL_RISK`, risk enforcement;
  `AgentToolAvailability`/`AgentToolStatus`, structured `ToolResult`, discovery (`find_tools`),
  schema/output validation and sanitisation, `list_artifacts`/`read_artifact`, lazy `DEFAULT_TOOLS`
- `app/modules/agent/decisions.py` — `tool_purpose` on `CALL_TOOL`
- `app/modules/agent/tools_router.py` — public catalogue endpoints and the run-id-scoped read model
- `app/modules/agent/router.py` — run tool-invocation and usage endpoints
- `app/modules/agent/service.py` — per-run tool budget, in-step idempotency, context provenance,
  artifact-ownership guard, `WORKER_SELECTED`/`TOOL_SELECTED`/`TOOL_INVOCATION_*` events, status→
  failure-category mapping, `artifact_texts`, `load_owned_run_by_id`
- `app/modules/agent/limits.py` — `max_tool_calls_per_run`, `assert_tool_run_budget`
- `app/models/enums.py` — `AgentToolCategory`, `AgentToolRisk`, `AgentArtifactOwnership`,
  `AgentToolAvailability`, `AgentToolStatus`; extended `AgentFailureCategory` and `AgentEventType`
- `app/models/entities.py` — `AgentArtifact.ownership`
- `app/schemas/agent.py` — catalogue schemas, `AgentArtifactResponse.ownership`,
  `AgentWorkerResponse.capabilities`/`supported_domains`, `AgentToolDetailResponse.version`/
  `availability`/`output_schema`
- `app/core/config.py` — `agent_max_tool_calls_per_run`
- `app/main.py` — catalogue and run-tools router registration
- `alembic/versions/0010_phase6_tool_system.py`, `0011_artifact_ownership.py`

### Web

- `lib/agent-types.ts` — `AgentArtifactOwnership`, `AgentArtifact.ownership`
- `tests/unit/agent-panel.test.tsx` — fixtures carry ownership

### Docs

- `docs/architecture/agent-tools.md` — 29-tool catalogue, structured results, discovery, workers
- `docs/development/adding-agent-tools.md` — the reviewed path for one new tool
- `docs/development/adding-agent-workers.md` — the reviewed path for one new worker
- `PHASE6_REPORT.md` — this report
