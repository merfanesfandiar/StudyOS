# How to add an academic tool (Phase 6)

The agent runtime's tool registry is closed on purpose. This guide is the reviewed path for widening
it by exactly one deterministic academic capability — and, just as importantly, for proving that the
boundary did not move.

The rule that governs everything below: **a tool is a pure function over data the runtime already
holds.** No shell, no subprocess, no filesystem, no HTTP, no code execution. If the tool you want
needs one of those, it is not a Phase 6 tool.

The one exception is Phase 7's sandboxed execution tools (`execute_code`, `run_tests`,
`run_data_analysis`). They hold `EXECUTE_SANDBOXED`, route through the isolation backend rather than
the host, and exist only because a sandbox was built to contain them. They are not a template for a
new tool and do not widen this rule — see
[../architecture/execution-isolation.md](../architecture/execution-isolation.md).

## 1. Write the tool in `domain_tools.py`

Add a class next to its siblings in `apps/api/app/modules/agent/domain_tools.py`. Copy the shape of an
existing deterministic tool, e.g. `ComputeStatisticsTool`.

```python
class SummarizeAbstractTool:
    name = "summarize_abstract"
    permissions = frozenset({ToolPermission.ANALYZE_TEXT})
    category = AgentToolCategory.WRITING
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "The source text."}},
        "required": ["text"],
    }
    description = "One sentence for a person, in the catalogue and the prompt."

    async def invoke(self, arguments, context) -> ToolResult:
        text = str(arguments.get("text", ""))
        if not text.strip():
            return ToolResult.refusal("text must not be empty.")
        if len(text) > MAX_TEXT_CHARS:
            return ToolResult.refusal(f"text is {len(text)} characters; the limit is {MAX_TEXT_CHARS}.")
        return ToolResult.success("...", {...})
```

A tool may also declare three optional descriptors, all read through the boundary:

- `version: str` — the tool's own contract version (default `"1.0.0"`), so a consumer can pin to it.
- `availability: AgentToolAvailability` — `AVAILABLE` by default; `REQUIRES_CONSENT`, `DISABLED` or
  `UNSUPPORTED` tools are filtered out of discovery before the model sees them.
- `output_schema: dict` — a JSON schema for `payload`; when present, the boundary validates the tool's
  own return value against it and corrects a mismatch rather than trusting it.

Return the right *status*, not just success or failure. `ToolResult.partial(...)` advances the step
and preserves a `warnings` tuple; `ToolResult.needs_user_input(...)`, `.rate_limited(...)`,
`.unavailable(...)` and `.failure(...)` each map to a distinct persisted invocation status and failure
category. A usable-but-imperfect answer must never be flattened into `SUCCESS` or `FAILED`.

Rules that are checked, not merely advised:

- Every tool declares `risk_level`, and in Phase 6 it must be `LOW`. `MEDIUM` is the ceiling for the
  runtime; anything above it is refused at dispatch (`AGENT_TOOL_RISK_EXCEEDED`).
- Every tool declares `deterministic = True` and `side_effect_free = True`. `write_artifact` is the
  only tool that is not side-effect free, because it persists a draft.
- Bad arguments return a `ToolResult.refusal(...)`. A tool must never raise for an expected refusal:
  a refusal is a user-safe explanation, a traceback is a crash.
- Bound every input. Truncate only with a visible marker, or refuse — never silently cut.

## 2. Register it in `ACADEMIC_TOOLS`

Append an instance to the `ACADEMIC_TOOLS` tuple at the bottom of the file. The tuple is the closed
set the registry is built from, so a tool that is not here does not exist.

## 3. Bind it to at least one worker

A tool no worker can reach is dead weight and fails the reachability check. Open
`apps/api/app/modules/agent/workers.py` and add your tool's name to the `tools` tuple of the worker
whose work it serves. `CORE_TOOLS` (the five core tools) is added automatically. See
[adding-agent-workers.md](./adding-agent-workers.md) for the worker side.

If you are serving a task type that has no worker yet, add a worker with `_worker(...)` covering its
`AcademicTaskType` values. Every one of the eighteen task types must be bound to exactly one worker.

## 4. Verify the boundary

From `apps/api`:

```bash
.venv/bin/ruff check app/ tests/
.venv/bin/mypy app/
.venv/bin/python -m pytest tests/test_agent_domain_tools.py -q
```

`tests/test_agent_domain_tools.py` enforces the shared safety shape on every tool, that the worker
registry binds every tool and every task (`DEFAULT_WORKER_REGISTRY.validate(DEFAULT_TOOLS) == []`),
and that no tool opens a channel out of the run. Add a behavioural test for your tool there: the
happy path, an empty input, and an oversized input.

Then run the full suite:

```bash
.venv/bin/python -m pytest -q
```

## 5. Check the published catalogue

The catalogue is generated from the registry, so it is correct the moment the tool is registered. To
inspect it:

```bash
curl -s localhost:8000/api/v1/tools | jq '.tools[] | {id, category, risk_level}'
curl -s localhost:8000/api/v1/tools/summarize_abstract | jq '{workers, arguments_schema}'
```

If `workers` is empty, you skipped step 3.

## Calling tools from the runtime (no action needed)

Once registered and bound, the tool is reachable through the one dispatch path:
`invoke_tool(name, arguments, context, registry=..., granted=DEFAULT_GRANTED_PERMISSIONS)`. It is
gated by permissions, the risk ceiling, the per-step tool budget, the per-run tool budget, and an
in-step idempotency cache. You do not add any of that to your tool.

## What not to do

- **Do not add a capability, only a function.** A new tool that reads a URL or runs code cannot be
  made safe by marking it `LOW`; the whole point is that the runtime cannot reach those things.
- **Do not add a new permission casually.** `ToolPermission` is a reviewed vocabulary change. The
  Phase 6 read-only entries (`COMPUTE`, `ANALYZE_TEXT`, `ANALYZE_CODE`, `EXTRACT_REFERENCES`) name
  kinds of analysis; none is a channel. `EXECUTE_UNTRUSTED` exists and is granted to nothing.
- **Do not raise the risk ceiling in a tool phase.** `MAX_TOOL_RISK` moves only when the phase that
  ships a sandbox ships it.
