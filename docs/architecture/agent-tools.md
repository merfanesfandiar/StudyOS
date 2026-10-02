# Agent Tools and Capabilities

`app/modules/agent/tools.py` is the shortest file in the phase and the most important one. It has
three tools in it. That is not an unfinished roadmap — it is the boundary.

## The three tools

| Tool | Permissions | What it does |
| --- | --- | --- |
| `read_context` | `READ_CONTEXT` | Reads a bounded slice of the context already assembled for this step. |
| `write_artifact` | `WRITE_ARTIFACT` | Drafts an artifact for the current task. Text only, persisted and attributed. |
| `request_checkpoint` | `ASK_USER`, `REQUEST_APPROVAL` | Asks the student a question and stops the run. |

`write_artifact` drafts text. It does not execute it. That distinction is the whole reason `CODE` is
an artifact *type* rather than a capability — the runtime may draft a function, and it may not run
one.

## The registry refuses to grow by accident

`ToolRegistry.register` rejects any tool declaring a permission in `FORBIDDEN_PERMISSIONS`. Adding
`EXECUTE_UNTRUSTED` to a tool raises at startup rather than at the first time a model decides to use
it.

`EXECUTE_UNTRUSTED` is declared in `ToolPermission` and never granted to anything. It exists so that
a future tool needing it has to be *named* in a code review rather than discovering that some
existing permission quietly covered it. The cost is one unused constant; the benefit is that the
dangerous capability has a name in review.

`ToolRegistry.assert_permitted(name, required)` is checked before every invocation, so a tool cannot
be called for a permission it did not declare.

## What is absent, and how you can tell

The runtime publishes the negative list as data:

```python
ABSENT_CAPABILITIES = [
    "execute_code", "shell", "filesystem_write", "network_access", "browser",
    "outbound_web_search", "credential_access", "email_or_messaging",
    "arbitrary_http", "background_scheduler", "cross_assignment_data",
]
```

It is a module constant rather than something derived, deliberately. Deriving it — "whatever is not
registered" — would produce a list that silently grows less alarming-looking every time a tool is
added. This list only changes when someone edits it, which means a new capability forces a
conscious decision about the sentence above it.

It is served by `GET /assignments/{id}/agent/capabilities` and rendered in the UI's "What this agent
cannot do" section. A student can read the boundary without opening documentation.

## Executors are the other half of the registry

`AgentExecutorKind` names how a task kind is actually performed: `REASONING`, `WRITING`, `ANALYSIS`,
`RESEARCH`, `CALCULATION`, `PLANNING`, `ARTIFACT`, `MOCK_TOOL`.

The mapping from a plan task's type to an executor lives in `executors.py` and is finite and
declared. A task type with no executor does not get one invented at runtime — it routes to the
deterministic path and says so. There is no dynamic dispatch that could resolve a task type to
something a caller supplied.

## Why this is closed

An open tool registry is the usual way agent systems acquire shell access, and it usually arrives as a
feature request: "let the agent run the tests", "let it look up the paper". Each one is individually
reasonable and collectively a system that runs code it read from the internet.

The alternative used here is that anything requiring a capability outside these three has to be
argued for as a change to this file, in a review, where the whole list is visible. The friction is
the feature.

## The honest failure mode

When a provider is unavailable, the run does not fail at the first step and it does not reach for a
tool it does not have. It degrades to the deterministic executors, and the run says so — the
`routing_reason` and the `AgentExecution.executor` both record it.

A fallback presented silently as a model result is the failure this design is most careful about,
because it is the one that produces confident wrong work.