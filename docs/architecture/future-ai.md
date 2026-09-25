# Future AI layer

This document describes how the AI platform described in the product context attaches to the Phase 1
codebase. **Nothing in this document exists yet.** Phase 1 ships no LLM calls, no agents, no
tooling, and no vector storage. The purpose is to record the intended shape so that Phase 2 and later
phases extend the domain instead of rewriting it.

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
| `AuditEventType` | Phase 1 already records the same event names the future engine will emit, so the vocabulary exists before any producer does |

## Domain events

Phase 1 records domain state changes as audit rows through `services/events.py`, using the names
`ASSIGNMENT_CREATED`, `ASSIGNMENT_UPDATED`, `DOCUMENT_UPLOADED`, and so on. That is deliberately the
only event surface in Phase 1: an append-only record that already names every state change, without
an invented bus or subscriber framework.

Phase 2 introduces a typed in-process hook and maps the same names onto it, so an event can fan out
to notifications today and to agent runs later without touching the write paths. The rule is that a
handler calling `record_audit` remains the single way domain changes are announced.

## Deliberately deferred to later phases

- LLM provider client and model routing
- Prompt templates, retrieval, embeddings, and vector storage
- Code execution sandboxes
- Any UI for agent activity, checkpoints, verification, or mastery

The assignment detail page reserves the navigation slots for these sections so the information
architecture is reviewable now, but the slots render an explicit "not available in Phase 1" state
rather than placeholder data.

## Phase 2 shape

Phase 2 adds the analyzer and planner as the first real consumers of the domain model: read an
assignment, produce a plan, and stop for human approval. It introduces `ai_runs` and the orchestrator
state machine, wires the first tools to existing assignment services, and extends
`NotificationType` for approval requests. Nothing in Phase 1 needs to be modified to make this
possible beyond additive changes.
