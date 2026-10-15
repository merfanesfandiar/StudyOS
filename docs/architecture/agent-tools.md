# Agent Tools and Capabilities

`app/modules/agent/tools.py` is the security boundary of the runtime, and its most important property
is what is *absent*. There is no host shell, no host subprocess, no host filesystem, no HTTP client
and no browser tool anywhere in the registry, and no configuration option that would add one.

Phase 6 widened the *academic* work the runtime can do without widening that boundary: **29 tools**,
five core and twenty-four deterministic academic tools, every one a pure-ish function over data the
runtime already holds. None of them reaches the database, the clock, the network or the filesystem.

Phase 7 adds exactly one new kind of capability — **submitting code to a sandbox** — and gives it its
own permission and risk level rather than smuggling it under an existing one. The three execution
tools are described in [The execution tools](#the-execution-tools) and their isolation in
[`execution-isolation.md`](./execution-isolation.md). The claim they change is narrow and explicit:
the runtime may *run code in an isolated backend*; it still may not run a command on the host.

## The core tools

| Tool | Permissions | What it does |
| --- | --- | --- |
| `read_context` | `READ_CONTEXT` | Reads a bounded slice of the context already assembled for this step. |
| `list_artifacts` | `READ_CONTEXT` | Lists the artifacts this run has produced. The only directory a tool can list. |
| `read_artifact` | `READ_CONTEXT` | Reads the bounded body of one of this run's artifacts by title. |
| `write_artifact` | `WRITE_ARTIFACT` | Drafts an artifact for the current task. Text only, persisted and attributed. |
| `request_checkpoint` | `ASK_USER`, `REQUEST_APPROVAL` | Asks the student a question and stops the run. |

`list_artifacts` and `read_artifact` are the read side of the artifact boundary. They are scoped to
`ToolContext.artifact_texts`, which the runtime fills only with the current run's own artifacts, each
capped before it arrives. There is no tool that opens a file, lists a directory or reaches a bucket:
the "filesystem" a tool can see is this run's output and nothing else.

`write_artifact` drafts text. It does not execute it. That distinction is the whole reason `CODE` is
an artifact *type* rather than a capability — the runtime may draft a function, and it may not run
one.

## The academic toolkit

The twenty-four academic tools are grouped by the category of work they serve. The category is a
grouping for the catalogue and the worker vocabulary, never a permission grant: whether a tool may
run is decided by `ToolPermission` and `AgentToolRisk`, not by its category.

| Category | Tools |
| --- | --- |
| `MATHEMATICS` | `calculate`, `solve_linear_system`, `prime_factorize`, `gcd_lcm` |
| `DATA` | `compute_statistics`, `detect_outliers`, `linear_regression`, `profile_dataset`, `detect_missing_values` |
| `WRITING` | `count_words`, `readability_score`, `top_keywords`, `assess_structure`, `suggest_outline` |
| `RESEARCH` | `extract_citations`, `format_citation` |
| `DOCUMENT` | `extract_document_metadata`, `segment_document`, `search_document`, `summarize_document` |
| `CODING` | `count_code_lines`, `extract_code_identifiers`, `check_syntax_balance` |
| `PRESENTATION` | `build_slide_outline` |

Every one of them is `LOW` risk and deterministic. `summarize_document` is *extractive* — it scores
and selects the document's own sentences. A generative abstract is a model's job, not a tool's, and
pretending otherwise would put an untraceable paraphrase behind a deterministic name.

## Permissions and risk are independent axes

`ToolPermission` names *what kind of work* a tool does. Phase 6 adds four read-only vocabulary
entries — `COMPUTE`, `ANALYZE_TEXT`, `ANALYZE_CODE`, `EXTRACT_REFERENCES` — none of which opens a
channel to anything outside the run. A tool in the `CODING` category still only reads text;
`ANALYZE_CODE` does not mean "run code".

`AgentToolRisk` names *how dangerous* a tool would be given hostile arguments. The runtime refuses to
dispatch anything above `MAX_TOOL_RISK`. Phase 6 held that ceiling at `MEDIUM`; Phase 7 raises it to
`HIGH` — exactly enough to dispatch the sandbox tools, and not a step further. This is a second,
independent gate: a tool can hold every permission it declares and still be refused for being too
dangerous (`AGENT_TOOL_RISK_EXCEEDED`), and `CRITICAL` (host filesystem) is still refused. Raising
the ceiling was a reviewed change in the phase that shipped the sandbox, not a permission a tool can
obtain by declaring it.

Phase 7 adds `EXECUTE_SANDBOXED`, which means "submit to the isolation plane". It is deliberately
distinct from `EXECUTE_UNTRUSTED`, which would mean "run this on the host".

`EXECUTE_UNTRUSTED` is declared in `ToolPermission` and granted to nothing. `ToolRegistry.register`
raises at startup if any tool declares it, so the forbidden capability has a name in review rather
than being discovered later behind an existing permission.

## Workers are the tool boundary

A `SpecializedAcademicWorker` (see `workers.py`) binds a set of task types to a bounded tool set.
Each of the eighteen `AcademicTaskType` values is bound to exactly one worker, and every worker's
`tool_ids` are validated against the registry — a worker cannot name a tool that does not exist. The
catalogue's reachability check, `ToolRegistry.validate(...)`, returns `[]` only when every registered
tool is reachable by some worker.

| Worker | Serves (task types) |
| --- | --- |
| `MATHEMATICS` | `SOLVE`, `PROVE` |
| `DATA` | `ANALYZE_DATA`, `EXPERIMENT`, `COLLECT_DATA` |
| `WRITING` | `WRITE`, `REVISE` |
| `RESEARCH` | `READ`, `RESEARCH` |
| `PRESENTATION` | `PRESENT` |
| `CODE` | `IMPLEMENT`, `VERIFY` |
| `REASONING` | `UNDERSTAND`, `ANALYZE`, `DESIGN`, `REVIEW`, `PRACTICE`, `SUBMIT`, `OTHER` |

`REASONING` is the fallback: a task type without a dedicated worker is still served by a worker that
is safe. The active worker's tool set narrows the prompt's tool catalogue, so a `MATHEMATICS` worker
never sees the code-analysis tools in its prompt.

Each worker also declares `capabilities` (the verbs it is trusted to perform, e.g. `solve`,
`prove`) and `supported_domains` (the subject areas it covers). Both are published through the
capabilities endpoint, so the boundary's own vocabulary — not just the tools it names — is
inspectable. The runtime emits a `WORKER_SELECTED` event naming the chosen worker, so which boundary
a step ran under is part of the run's audit trail.

## The registry refuses to grow by accident

`ToolRegistry` is a closed registry with no registration API beyond `register`, which refuses
forbidden permissions. Adding `EXECUTE_UNTRUSTED` to a tool raises at startup rather than at the
first time a model decides to use it.

`ToolRegistry.validate(...)` is the reachability guard: it returns a list of problems (unknown
worker tools, unreachable tools) and `[]` means the catalogue is sound. It is checked in tests so a
tool added in review cannot be silently unreachable.

## Tools are called, not merely described

The model reaches a tool through exactly one route: a `CALL_TOOL` decision naming one of the
registered tools. Layers gate it before anything is dispatched.

1. **Schema.** The decision must name a `tool`. A `CALL_TOOL` with no tool is rejected as incomplete
   before it is even compared to the world.
2. **Semantics.** The tool must be in the registry. `get` is the boundary here: a name the model
   invents is `AGENT_TOOL_NOT_REGISTERED`, recorded and refused, with nothing dispatched.
3. **Permissions.** Every declared permission must be in the run's granted set. The four read-only
   Phase 6 permissions are granted by default; `EXECUTE_UNTRUSTED` never is.
4. **Risk.** The tool's risk must be at or below `MAX_TOOL_RISK`.

`invoke_tool(...)` is the single function that resolves, authorises and calls a tool. Nothing else
calls `tool.invoke`.

## Results are structured, not boolean

A tool does not merely succeed or fail. `ToolResult` carries a `status` from `AgentToolStatus` —
`SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`, `BLOCKED`, `NEEDS_USER_INPUT`, `RATE_LIMITED`, `UNAVAILABLE`
— alongside `summary`, `payload`, `reason`, `warnings`, `artifacts` and `metadata`. `ok` is derived
from `status` (and vice versa) so the two can never disagree, and the constructors name the intent:
`ToolResult.success`, `.partial`, `.refusal`, `.failure`, `.needs_user_input`, `.rate_limited`,
`.unavailable`.

The status is not decoration. It decides three things downstream: whether the step advances
(`PARTIAL_SUCCESS` does, with its warning preserved), which `AgentToolInvocationStatus` is persisted,
and which `AgentFailureCategory` a hard failure is recorded as. A usable-but-imperfect result is
therefore never flattened into either "worked" or "crashed".

`invoke_tool` also runs the result through the boundary: arguments are validated against the tool's
`arguments_schema`, the returned payload is validated against its optional `output_schema`, and the
summary is sanitised and truncated with a visible marker. A tool that returns a shape it did not
declare is corrected at the boundary rather than trusted.

## Tools describe themselves and each other

Every tool has a name, description, `arguments_schema`, category, risk, permission set, and — where
declared — a `version`, an `availability` (`AgentToolAvailability`) and an `output_schema`. All of it
is published through `schema()`, so the catalogue the UI reads and the prompt the model reads are the
same data.

`ToolRegistry.find_tools(*, granted, max_risk, categories, tool_ids, available_only)` is the discovery
query behind both: it answers "which tools could this worker actually call right now" from the same
grant and risk rules the dispatcher enforces, rather than from a hand-maintained list. A tool that is
`REQUIRES_CONSENT` or `UNSUPPORTED` is filtered out before the model ever sees it.

## Bounded by structure, bounded by budget

Tool dispatch is bounded three ways, and none of them relies on the model behaving.

- **Per step.** `AgentLimits.max_tool_calls_per_step` (default 4,
  `agent_max_tool_calls_per_step`) caps how many `CALL_TOOL` decisions one step may spend. A model
  that reads context repeatedly instead of deciding is stopped with `AGENT_TOOL_CALL_LIMIT`.
2. **Per run.** `AgentLimits.max_tool_calls_per_run` (default 60, `agent_max_tool_calls_per_run`)
   caps the whole run. The per-step budget cannot see a run that behaves plausibly every step but
   never converges; this can. It is counted from the persisted invocation rows, so a resume cannot
   hand the run a fresh allowance. Breaching it fails the run with `AGENT_TOOL_RUN_LIMIT`.
3. **Idempotency.** Every tool in the registry is deterministic, so an identical call (same tool,
   same arguments) within one step is answered from the first result instead of being re-invoked.
   The repeat is still recorded — it cost a provider round-trip to decide — and the `TOOL_INVOKED`
   event is marked `cached: true` so the saving is visible rather than assumed.

Each successful call also occupies its own `slot` on the run's decision ledger, so the sequence stays
auditable decision by decision.

## The public tool catalogue

The boundary is published as data, so the UI and the security documentation share one shape:

- `GET /api/v1/tools` — the whole catalogue with categories, permissions, risk levels, determinism,
  side-effect flags, versions, availability and argument/output schemas.
- `GET /api/v1/tools/{tool_id}` — one entry, or `AGENT_TOOL_NOT_FOUND`.
- `GET /{assignment_id}/agent/runs/{run_id}/tool-invocations` — every call a run made, including the
  blocked ones, each with its structured status.
- `GET /{assignment_id}/agent/runs/{run_id}/tools` — per-tool usage counts for the run.

The two per-run reads are also addressed by run id alone, for a client that holds a run and not an
assignment: `GET /api/v1/agent/runs/{run_id}/tool-invocations` and
`GET /api/v1/agent/runs/{run_id}/tools`. It is the same read model behind the same ownership check,
reachable from the id the client actually has.

## Observability names every move

The run's event stream records the tool lifecycle rather than only its endpoints: `WORKER_SELECTED`,
`TOOL_SELECTED`, `TOOL_INVOCATION_STARTED`, `TOOL_INVOCATION_COMPLETED` (carrying the structured
status and any warnings) and `TOOL_INVOCATION_FAILED` (carrying the failure category). "The agent
used a tool" and "the agent tried to use a tool and was refused" are distinguishable after the fact,
which is the difference between a transcript and an audit.

## Artifact ownership

An artifact records who it belongs to: `USER_OWNED`, `AGENT_OWNED`, `SYSTEM_GENERATED` or `IMPORTED`.
The runtime may only ever persist `AGENT_OWNED` output — `_persist_artifact` raises
`AGENT_ARTIFACT_OWNERSHIP_INVALID` if asked to write anything else — so the runtime can never
overwrite or claim the student's own work. Revising a student's artifact produces a new revision
beside it, never a mutation in place.

## Context provenance

Each step records which sources its context drew from and how much of each survived, as a
`CONTEXT_BUILT` event carrying a per-section `provenance` list. The run detail exposes the flattened
record as `context_provenance`, so "why did the agent do that" is answerable after the fact without
re-running the step. The record is append-only: it is stored on the event as it happened, never
rewritten.

## What is absent, and how you can tell

The runtime publishes the negative list as data:

```python
ABSENT_CAPABILITIES = [
    "host_code_execution", "shell", "filesystem_write_outside_sandbox",
    "network_access", "browser", "outbound_web_search", "credential_access",
    "email_or_messaging", "arbitrary_http", "background_scheduler",
    "cross_assignment_data",
]
```

It is a module constant rather than something derived. A derived list ("everything not registered")
would shrink toward nothing as tools are added; a written list forces every addition to be considered
against it. It is served through the capabilities endpoint and rendered in the UI so a student can
read the boundary without opening documentation.

## What is absent is also unrepresentable

`MAX_TOOL_RISK` is a ceiling rather than a suggestion, so a `CRITICAL` tool cannot be reached by
declaring a permission. Removing a capability and removing the *vocabulary for requesting it* are
different defences; where a capability is removed (host execution, shell, network), the runtime has
both. Phase 7 is the deliberate exception to the first half: it *adds* the vocabulary for one
capability, `EXECUTE_SANDBOXED`, and immediately bounds it — a distinct permission from the forbidden
`EXECUTE_UNTRUSTED`, a `HIGH` rather than `CRITICAL` ceiling, and a gateway that fixes the command,
image and limits before the tool ever sees them. See
[`execution-isolation.md`](./execution-isolation.md).

## The execution tools

`app/modules/agent/execution_tools.py` adds three `HIGH`-risk tools, each bound to a fixed runtime:

| Tool | Category | Permissions | What it does |
| --- | --- | --- | --- |
| `execute_code` | `CODING` | `EXECUTE_SANDBOXED` | Submits source text for a named runtime and returns the outcome. |
| `run_tests` | `CODING` | `EXECUTE_SANDBOXED` | Runs the submitted source as a test module and reports the result. |
| `run_data_analysis` | `DATA` | `EXECUTE_SANDBOXED` | Runs a Python snippet over data the run already produced. |

They are the only tools that reach outside the process, and they reach only as far as the gateway.
A tool names a **runtime** (`python`, `java`, `cpp`) and supplies **text**; it cannot name a command,
an image, a working directory, an environment variable, a mount or a resource limit, because the
schema has none of those fields. When no gateway is present — execution disabled, or a worker whose
run was not given one — the tool answers `UNAVAILABLE` instead of reaching for a host shell.

A non-zero exit is the *program's* answer, not the tool's refusal: it is returned as
`PARTIAL_SUCCESS` carrying the exit code and bounded stderr, so the model reacts to the compiler or
runtime error instead of the runtime treating the step as a dead end. A genuine refusal — no
gateway, an unknown runtime — is `BLOCKED`/`UNAVAILABLE`.

## The honest failure

The runtime has no dangerous capabilities, so its failures are honest ones. When a provider is
unavailable it says so with `MARK_BLOCKED` rather than improvising; a task that seems to need a
shell is refused with an explanation rather than faked. An unauthorized-tool error produces confident
wrong work, and that is the failure this whole module exists to make impossible.
