# Agent Workspace

The Agent Workspace is the student-facing surface of the agent runtime: one screen where a
conversation, the agent's live work, and the assignment's real context sit side by side. It is
Phase 11 of the agent arc — the runtime itself (Phase 5) does the work; the workspace is how a
student briefs it, watches it, and answers it.

It is a workspace, not a chatbot. The conversation thread is the briefing and record-keeping
layer; every agent behaviour still comes from the runtime's persisted state. Nothing in the UI
invents an agent reply, a decision, or a progress bar.

## The three regions

```
┌──────────────┬──────────────────────────────┬──────────────────┐
│ Conversations│  Thread                      │ Context          │
│ (sidebar)    │  messages · activity · HITL  │ (assignment)     │
│              │  composer                    │ run · artifacts  │
│              │                              │ verification     │
└──────────────┴──────────────────────────────┴──────────────────┘
```

- **Sidebar** (`conversation-sidebar.tsx`) — the user's conversations, with search, archive
  (explicit `status=ARCHIVED` listing), and soft delete behind a confirmation.
- **Thread** (`workspace.tsx`, `message-item.tsx`, `composer.tsx`) — the conversation's messages,
  the agent's live activity rail, any pending human-in-the-loop card, and the composer with
  attachment upload.
- **Context panel** (`context-panel.tsx`) — the bound assignment's real data: record, newest run
  status with controls, artifacts (preview + download), and the verification panel. The run is the
  workspace's own state, passed down as a prop and refreshed by the workspace's polling and
  `refreshAll`; the panel never fetches a private copy, so a run that completes while the student
  watches shows the same state everywhere.

Each region is persistent on wide screens and a drawer on small ones; the layout is tested in both
in `tests/e2e/agent-workspace.spec.ts`.

## Conversations module (backend)

New module `app/modules/conversations/`, migration `0018_workspace_conversations` (followed by
`0019_migrated_timestamp_defaults`, which restores timestamp defaults the 0017/0018 migrations
omitted — see the defect note under Tests):

- `conversations` — tenant-scoped, user-owned; `status` is `ACTIVE` / `ARCHIVED` / `DELETED`
  (`DELETED` is soft and never listed); `assignment_id` is the binding to a real assignment.
- `conversation_messages` — time-ordered, user-owned; `role` is `USER` / `AGENT` / `SYSTEM`,
  `kind` is `TEXT` / `ARTIFACT` / `VERIFICATION` / `RUN_SUMMARY` / `SYSTEM_NOTICE` (reference kinds
  carry the source record's id in `metadata_json`); `edit_history_json` keeps every prior revision
  of an edited message.

Endpoints live under `/api/v1/conversations`. Rules the module enforces:

- **Editing never rewrites.** Editing the last user message stores the new content as a new
  revision and appends the old one to `edit_history_json`; the edited marker shows the revision
  count. History is readable, never destroyed.
- **Deletion is soft.** `DELETE` marks the row `DELETED`; it disappears from every list but stays
  on the server. Restoring a conversation is possible; restoring a deleted one is a data-level
  operation, not a UI one.
- **Tenants and ownership everywhere.** Every query joins `WorkspaceMember`; an id the caller
  cannot see is a 404, not a 403 — invisible means nonexistent.
- **List semantics.** Default listing is `ACTIVE` only; archived conversations require the explicit
  `status=ARCHIVED` query.

## How the agent speaks

There is no free-form LLM chat responder in the workspace thread. Agent messages appear only when
the runtime produces a real outcome: the bridge in `agent/service.py::_set_status` calls
`conversations_service.record_run_outcome(db, run)` on every terminal run status (deduplicated per
run + status; bridge failures are logged and swallowed so they can never break a run). Those
messages are `kind=REFERENCE` rows that point at the run — `run_id`, and where applicable
`artifact_id` / `verification_run_id` — rather than duplicating the runtime's data.

Free-form chat (answering "what does this mean?" in prose) is **not implemented**: the runtime has
no conversational responder, and the workspace deliberately refuses to fake one.

## Live activity

`GET /api/v1/assignments/{assignment_id}/agent/runs/{run_id}/events/stream` (SSE, in
`observability/streaming.py`) streams the run's persisted `agent_events` with:

- `Last-Event-ID` / `last_event_id` resume from the client's last sequence,
- heartbeats, a terminal `run-status` event, and a terminal `event: done`.

The client (`useAgentActivity` in `lib/use-workspace.ts`) prefers the stream and falls back to
cursor polling of the same event log when SSE is unavailable. Both paths read the same persisted
log, so a reconnect after a reload shows exactly what happened — no more, no less. A terminal
run's static log is read page by page and then shown as `Idle`; reading only its first page would
have shown the oldest events of a long run instead of the tail. A run that is `WAITING_FOR_USER` is
not settled — its stream stays open, so answering a checkpoint resumes the rail. An empty log
renders "Nothing has happened yet." rather than invented progress.

## Human-in-the-loop

Pending checkpoints (`data-testid="checkpoint-card"`) and interactions
(`data-testid="interaction-card"`) are rendered only when the backend reports them. A card that is
resolved or expired refuses input and says so; approving, rejecting, or answering always goes to
the backend endpoint that owns the state
(`.../checkpoints/{id}/resolve`, `.../interactions/{id}/approve|reject`). A card is a client for
the decision, never the authorisation itself.

## Artifacts and verification

The run detail already carries every artifact with its full text content, so the context panel:

- previews the body as text (or a validated dynamic UI block through
  `lib/agent-ui/validate.ts` + `AgentUiView` when the artifact carries one),
- downloads the exact content the API returned as a Blob (`.md` for markdown artifacts, `.txt`
  otherwise) — nothing is synthesised client-side.

The verification section embeds the assignment's `VerificationPanel`; every completed run triggers
the real verification pipeline (`_verify_completed_run`), so the verdict shown is the pipeline's
own.

## Known limits (stated, not hidden)

- **No free-form chat.** As above; blocked on a conversational responder in the runtime.
- **No LaTeX rendering** in the markdown renderer: the CSP restricts `font-src 'self'`, so KaTeX
  web fonts are not loadable. Markdown + GFM (tables, code) render; math notation does not.
- **No artifact download endpoint.** Downloads are client-side Blobs of content the API already
  returned; a server-side `.../artifacts/{id}/download` route (mirroring documents) would be the
  next integration point if binary/large artifacts arrive.
- **Interaction creation is an API-only integration point.** `POST .../runs/{id}/interactions`
  exists, but no runtime component creates interactions yet; checkpoints (including the runtime's
  own revision-limit REVIEW) are the HITL path the runtime drives, and the workspace resolves them
  end to end.
- **A failed run has no retry button.** Failure is terminal by design; retry means a new run.

## Tests

- Backend: `apps/api/tests/test_conversations.py` plus the full suite (SQLite and the Postgres
  subset) — conversations CRUD, edit history, soft delete, tenant isolation, and the run-outcome
  bridge.
- Web unit: `tests/unit/workspace-*.test.tsx` — markdown safety, message edit/history, composer
  key handling and uploads, sidebar lifecycle, HITL card states, activity rail honesty.
- E2E: `tests/e2e/agent-workspace.spec.ts` — ten scenarios over the real API: conversation
  lifecycle, binding, uploads (accepted and rejected), run reconnect from persisted state, the
  runtime's revision-limit decision answered in the workspace, artifact preview/download,
  verification, the Persian right-to-left layout, and the mobile layout. Real defects this suite found and drove fixes for: the
  conversations router never committed its writes; a REVIEW checkpoint could not be resolved from
  the workspace (option-only answers were rejected); post-run verification failed with a lazy-load
  error because the snapshot depended on the caller's eager loading; binding an assignment never
  refreshed the sidebar; the context panel rendered its own stale copy of the run instead of the
  workspace's live one; and a completed run's activity rail loaded only the first page of its
  static log, showing the oldest events and hiding the run's actual ending — after first treating
  `WAITING_FOR_USER` as terminal, which froze the rail at the first checkpoint.

One defect was found by CI rather than by this suite, because this suite's API ran on a database
built by `create_all` while the deployed stack is built by migrations: `0017` and `0018` declared
`created_at`/`updated_at` `NOT NULL` without the `now()` server default that `TimestampMixin`
promises, so every insert into a verification or conversation table violated a not-null constraint
on a migrated database, and the API surfaced it as a generic 409. "New conversation" therefore did
nothing in CI's fresh PostgreSQL while all ten scenarios passed locally. `0019` adds the missing
defaults, and `test_migrations.py::test_server_defaults_survive_migration` now fails if a model's
server default is absent from the migrated schema.
