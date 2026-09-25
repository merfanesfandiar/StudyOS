# Future AI layer

This document describes how the AI platform described in the product context attaches to the
codebase. **Nothing in this document exists yet.** The product ships no LLM calls, no agents, no
tooling, and no vector storage. The purpose is to record the intended shape so the AI phase extends
the domain instead of rewriting it.

The structured specification phase landed first and is what makes this seam possible: an assignment is
now a validated artifact with requirements, dependencies, weighted criteria, and resources, and
`READY_FOR_ANALYSIS` is only reachable once that artifact is complete.

## The rule

Domain modules stay the only place where domain state changes. An AI run may *request* a change; it
never writes domain tables directly. Every future code path ends in the same service call the HTTP
handler uses, so business rules such as criteria validation and tenancy checks cannot be bypassed by
a background job.

```text
HTTP handler ──> module service ──> SQLAlchemy
AI tool      ──> module service ──> SQLAlchemy
```

## Target layout

```text
apps/api/app/modules/ai/
  orchestrator/   run lifecycle, approval gates, checkpoint resume
  agents/         one module per agent role (analyzer, planner, executor, reviewer)
  tools/          typed, allow-listed capabilities an agent may call
  memory/         conversation and artifact history for a run
  evaluation/     verification of produced artifacts against evaluation criteria
```

Supporting pieces live outside `modules/ai/`, because they are not AI-specific:

- Run state is persisted in new tables (`ai_runs`, `ai_run_steps`) that reference `assignments.id`
  with a foreign key, so a run cannot outlive the assignment it was created for.
- Human approval is an explicit state on `ai_runs`, not an implicit timeout.
- Agent output is written through `StorageService`, so artifacts are subject to the same validation
  and naming rules as user uploads.

## What already exists to build on

| Existing seam | How the AI layer uses it |
| --- | --- |
| `Assignment` + structured requirements, constraints, criteria | The analyzer agent reads a complete, already validated specification instead of parsing free text |
| `EvaluationCriterion.weight` | The evaluation module scores artifacts against the same criteria the student's grade will use |
| `services/audit.py` and `AuditEventType` | Agent actions become audit events with the same vocabulary as user actions |
| `Notification` / `NotificationType` | Approval requests, run failures, and deadline reminders extend the existing in-app channel |
| `StorageService` | Artifacts, patches, and generated reports are stored without new filesystem code |
| Module-level ownership helpers | Every tool call reuses the assignment ownership check, so tenant isolation is inherited |
| `AuditEventType` | The same event names the future engine will emit are already recorded, so the vocabulary exists before any producer does |
| `AssignmentSpecificationResponse` and the readiness gate | The engine receives a specification that has already passed every blocking check, instead of re-validating free text |
| `AssignmentVersion` | An immutable, ordered snapshot exists, so a run can pin the exact specification it planned against |

## Domain events

Domain state changes are recorded as audit rows through `services/events.py`, using the names
`ASSIGNMENT_CREATED`, `REQUIREMENT_CREATED`, `DOCUMENT_UPLOADED`, and so on. That is deliberately the
only event surface: an append-only record that already names every state change, without an invented
bus or subscriber framework. Every specification change, including a document upload or delete, goes
through the single `record_specification_change` choke point, which is what keeps the readiness score,
the audit row, and the version snapshot in step.

The AI phase introduces a typed in-process hook and maps the same names onto it, so an event can fan
out to notifications and to agent runs without touching the write paths. The rule is that a handler
calling the domain's record function remains the single way domain changes are announced.

## Deliberately deferred to later phases

- LLM provider client and model routing
- Prompt templates, retrieval, embeddings, and vector storage
- Code execution sandboxes
- Any UI for agent activity, checkpoints, verification, or mastery

The assignment detail page shows no placeholder slots for these sections. They will appear when the
feature exists, rather than shipping empty navigation that implies a capability the backend cannot
serve.

## The AI phase

The AI phase adds the analyzer and planner as the first real consumers of the domain model: read a
`READY_FOR_ANALYSIS` assignment, produce a plan, and stop for human approval. It introduces `ai_runs`
and the orchestrator state machine, wires the first tools to existing assignment services, and extends
`NotificationType` for approval requests.

Two states are already reserved for it: `ANALYSIS_IN_PROGRESS` and `ANALYZED` are part of the status
enum but are not client-settable, so a run can own the transition and a client cannot fake it. Nothing
shipped so far needs to be modified to make this possible beyond additive changes.
