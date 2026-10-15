# How to add a Specialized Academic Worker (Phase 6)

A `SpecializedAcademicWorker` is the **tool boundary** a task runs under. The planner's task
vocabulary is domain-agnostic (`PROVE`, `WRITE`, `ANALYZE_DATA` are plain strings), so the runtime
needs a layer that says "a proof task may use the mathematics toolset and nothing else". That layer is
`apps/api/app/modules/agent/workers.py`.

Workers are static code, like tools. There is no configuration option that creates a worker and none
that widens one; the closed set is `DEFAULT_WORKERS`.

## What a worker decides

A worker answers three questions and nothing else:

- **Which tools may run?** `tool_ids` is the whole boundary. The decision layer narrows the model's
  `available_tools` to these names and the prompt only describes them — a `MATHEMATICS` worker is
  never told `count_code_lines` exists.
- **Which task types does it serve?** `academic_task_types` maps plan task vocabulary onto the
  worker. Anything unmapped falls through to `REASONING`, so an unknown task is served safely.
- **What may it produce?** `output_artifact_types` constrains the drafts its tasks may claim.

It does *not* decide strategy. Executors decide *how* work is carried out; workers decide *which
boundary* it runs under. Keep those two registries separate.

## 1. Add the worker to `DEFAULT_WORKERS`

Construct it with `_worker(...)`, which prepends `CORE_TOOLS` (read context, list/read artifacts,
write artifact, request checkpoint) for you:

```python
_worker(
    AgentWorkerKind.YOUR_KIND,          # add the member to AgentWorkerKind first
    "One sentence describing the boundary.",
    (AcademicTaskType.SOME_TASK.value,),  # the task types it serves
    ("your_tool", "another_tool"),        # specialised tools, beyond CORE_TOOLS
    (AgentArtifactType.ESSAY,),           # artifact types its tasks may draft
    capabilities=("draft", "outline"),    # verbs, independent of tool names
    domains=("writing",),                 # academic domains, a routing hint only
)
```

A new `AgentWorkerKind` member is required — `DEFAULT_WORKERS` is keyed by it. `capabilities` and
`supported_domains` are descriptive, not authorisation: they survive a tool being renamed and are
what the capabilities endpoint and the UI match on. Authorisation is always `tool_ids`.

## 2. Bind every task type exactly once

Every `AcademicTaskType` must be served by **exactly one** worker. If your worker is serving a task
type currently falling through to `REASONING`, remove it from the `REASONING` worker's tuple as you
add it here. `DEFAULT_WORKER_REGISTRY.validate(DEFAULT_TOOLS)` reports a task type bound to two
workers, and that check runs in tests, so a duplicate is a red build rather than a runtime
coin-flip. (`WorkerRegistry.register` itself refuses a duplicate *kind*.)

## 3. Name only tools that exist

`tool_ids` is validated against the live registry. A worker that names an unknown tool fails
validation; a tool no worker can reach fails the catalogue's reachability check
(`ToolRegistry.validate(...) != []`). If you need a new tool, add it first — see
[adding-agent-tools.md](./adding-agent-tools.md).

## 4. Verify the boundary

From `apps/api`:

```bash
.venv/bin/ruff check app/ tests/
.venv/bin/mypy app/
.venv/bin/python -m pytest tests/test_agent_domain_tools.py tests/test_agent_runtime.py -q
```

`test_agent_domain_tools.py` asserts that every worker's `tool_ids` resolve, that `capabilities` and
`supported_domains` are non-empty, and that every tool and task is bound
(`DEFAULT_WORKER_REGISTRY.validate(DEFAULT_TOOLS) == []`). `test_agent_runtime.py` drives a run per
academic domain and asserts the run reached *that domain's own tool* — so a mis-bound worker is
caught by behaviour, not just by set membership.

Then run the full suite:

```bash
.venv/bin/python -m pytest -q
```

## 5. Check the published boundary

```bash
curl -s localhost:8000/api/v1/assignments/{assignment_id}/agent/capabilities \
  | jq '.workers[] | {id, tools, capabilities, supported_domains}'
```

If `tools` is missing your tool, step 3 is wrong. If `WORKER_SELECTED` events name the old worker in
a run, the task type is still bound to the previous owner.

## What the runtime does with a worker (no action needed)

Once bound, the runtime emits `WORKER_SELECTED` when it resolves the worker for a task, narrows the
prompt's tool catalogue to `tool_ids`, and restricts `available_tools` in the decision context to the
same set. You do not wire any of that: resolution, eventing and narrowing all read from
`DEFAULT_WORKER_REGISTRY`.

## The rule that governs all of the above

A worker can only ever *narrow*, never widen. It cannot grant a permission the run was not given, it
cannot name a tool that is not registered, and it cannot lift a task above the risk ceiling. Adding a
worker is how you give a task type a safer, smaller toolset than `REASONING` — never how you give it
a bigger one.
