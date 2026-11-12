# Academic Verification Engine (Phase 10)

The verification engine answers a different question from everything else in
StudyOS: not *can the agent produce academic work?* but *why should that work be
trusted?* It evaluates produced artifacts with deterministic checks first, and
is explicit about everything it could not check.

Design principles, enforced structurally rather than by convention:

1. **`UNVERIFIED` is the default verdict.** A check that could not run is never
   reported as passing.
2. **Method labels are load-bearing.** Every result carries a
   `VerificationMethod` (`DETERMINISTIC`, `TOOL_ASSISTED`, `EXTERNAL_SOURCE`,
   `AI_ASSESSMENT`, `HUMAN_REVIEW`). An AI explanation of its own reasoning is
   never stored as evidence for the claim it explains.
3. **Mentioning a requirement is not satisfying it.** Level 2 keyword coverage
   is a traceability signal; verdicts say exactly how far that signal goes.
4. **Confidence is qualitative, never decorative.** `HIGH` / `MODERATE` /
   `LOW` / `NONE` — no fabricated percentages.
5. **Rubric scores are estimates.** Weighted totals exist only when the
   instructor's rubric permits them; ambiguous rubrics produce ambiguity notes,
   never invented grading rules.

## Architecture

```
app/modules/verification/
├── contracts.py    # snapshots, validator interface, result schemas
├── registry.py     # declaration-driven selection (no hardcoded dispatch)
├── pipeline.py     # 10-stage pipeline, parallel execution, failure isolation
├── rubric.py       # Level 5 weighted rubric evaluation
├── service.py      # DB boundary: snapshots in, persisted report out
├── router.py       # REST API (tenant-scoped)
└── validators/     # the verified validator set (see below)
```

The pipeline stages: input validation → requirement extraction → artifact
inspection → strategy selection → validator execution (parallel, per-validator
timeout, crash isolation) → evidence collection → normalisation → confidence &
limitations → aggregation → report.

Aggregation rules:

* The overall verdict is the **worst** honest verdict. `FAILED` dominates.
* A validator that crashes or times out is recorded as `FAILED` with the
  reason and **counts against the aggregate** — a broken check is never a
  silent pass.
* A report that contains critical findings can never be `VERIFIED`
  (defensive invariant in `_aggregate`).

## The five verification levels

| Level | Name | What runs |
|---|---|---|
| 1 | STRUCTURAL | Artifact presence, emptiness, duplicate titles, required-deliverable coverage |
| 2 | REQUIREMENTS | Per-requirement traceability with evidence refs; honest `UNVERIFIED` when signal is insufficient |
| 3 | DOMAIN | `mathematics`, `python_syntax`, `programming_execution`, `citation_check`, `essay_structure`, `presentation_structure`, `language_metrics`, `data_recompute`, `lab_consistency` |
| 4 | EVIDENCE | Evidence records collected by every validator, method-labelled |
| 5 | QUALITY | Rubric evaluation over pipeline results (estimated scores only) |

## How to add a validator

1. Create a module in `app/modules/verification/validators/` (or extend an
   existing one):

   ```python
   from typing import ClassVar
   from app.models.enums import AcademicDomain, VerificationLevel, VerificationStatus
   from app.modules.verification.contracts import (
       CONFIDENCE_HIGH, CONFIDENCE_NONE, ValidatorDeclaration,
       VerificationContext, ValidatorFinding, VerificationValidator,
   )

   class MyDomainValidator(VerificationValidator):
       declaration: ClassVar[ValidatorDeclaration] = ValidatorDeclaration(
           name="my_domain",                    # unique; re-registration raises
           level=VerificationLevel.DOMAIN,
           domains=frozenset({AcademicDomain.ENGINEERING}),
           assignment_types=frozenset({"DESIGN"}),
           description="What this check genuinely does and does not do.",
           timeout_seconds=10.0,
           # requires_execution=True → only selected when the sandbox gateway exists
       )

       async def verify(self, ctx: VerificationContext) -> ValidatorResult:
           # ctx.scoped_artifacts()/scoped_requirements() honour partial scopes.
           # Return UNVERIFIED + limitations when inputs are missing.
           ...
   ```

2. Add one instance to `REGISTERED` in `validators/__init__.py`.
3. Add tests with a representative fixture.
4. Nothing else changes: selection, scheduling, persistence, APIs and UI are
   driven by the declaration.

Honesty requirements for every validator:

* Declare `determinism` honestly (`deterministic` / `heuristic` / `ai_assisted`).
* Never claim network or execution you did not perform. Out-of-scope checks are
  `UNVERIFIED` with a limitation string saying what was not checked.
* Validators are pure: no DB, no network, no filesystem. Snapshots in, result
  out. Untrusted artifact content must never reach application code paths —
  the sandbox gateway is the only execution surface, and it goes through the
  Phase 7 job/quota/timeout machinery.

## Evidence and provenance

Every validator result carries `ValidatorEvidence` records: kind, source,
method, status, bounded content, requirement codes and artifact ids. They are
persisted in `verification_evidence` and returned by the report API. Evidence
statuses use the same honest vocabulary (`VERIFIED`, `PARTIAL`, `FAILED`,
`UNVERIFIED`, `NOT_APPLICABLE`).

## Persistence

`0017_phase10_verification` adds five tables: `verification_runs`,
`verification_findings`, `verification_evidence`,
`verification_requirement_results`, `verification_rubric_scores`. Runs are
tenant-scoped (`workspace_id` denormalised), idempotency-keyed per assignment,
and carry `previous_run_id` for re-verification comparisons. Report bodies are
bounded structured JSON; artifact content is never duplicated into them.

## Agent Runtime integration

When an agent run completes, `_verify_completed_run` in
`app/modules/agent/service.py` triggers verification of that run's artifacts
(idempotent via `agent_run:<id>`). Verification failure is logged and audited
but cannot change the agent run's own terminal state — the two state machines
are independent by design.

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/assignments/{id}/verification` | Trigger full/partial/artifact/requirement/re-verification |
| `GET /api/v1/assignments/{id}/verification` | Paginated run list |
| `GET /api/v1/assignments/{id}/verification/{run_id}` | Full machine-readable report (findings, evidence, requirement verdicts, rubric, comparison) |
| `POST /api/v1/assignments/{id}/verification/{run_id}/cancel` | Cancel a pending run only |

All routes scope through workspace membership and return 404 for invisible ids.

## Security constraints

* Validators never touch the network: DOI resolution and source-existence
  checks are documented as unverified rather than faked (SSRF containment).
* Code execution only via the existing `ExecutionGateway` (sandbox, quotas,
  timeouts). No host execution path exists.
* All DB access is confined to `service.py`; the API authorises by membership,
  never by client-supplied tenant ids.
* Artifact content is bounded (`100k` chars per artifact for parsing), and
  math evaluation is an allowlist AST evaluator — no `eval`.

## Known limitations (deliberate, not hidden)

* **No AI-assisted evaluation yet.** Level 5 quality assessment beyond rubric
  arithmetic (clarity, depth, rigour) needs a rubric-bound LLM evaluator with
  prompt-injection containment. It is an extension point, not a shipped feature;
  nothing claims AI judgment as objective fact.
* **No external source verification.** DOI/Crossref lookups need a controlled
  outbound-resource service (rate limits, allowlists). Until then, research
  validators report what they could and could not check.
* **Symbolic mathematics is not verified.** No CAS (SymPy/SageMath) is bundled.
  Arithmetic is recomputed deterministically; symbolic claims stay unverified.
* **Sandbox execution runs each artifact standalone.** Hidden test suites and
  cross-file projects are future work.
* **Verification runs synchronously** inside the request/run-finish path. A
  queue/worker is an operational change; idempotency keys already make it safe.

## Tests

`tests/test_verification.py` covers:

* Registry selection and duplicate-registration rejection.
* Every validator against domain fixtures (mathematics, programming, research
  citations, essay, language, data analysis, lab, presentation).
* Honest-verdict invariants: symbolic math stays `UNVERIFIED`; a missing
  dataset stays `UNVERIFIED`; a crashed validator counts as `FAILED` against
  the aggregate.
* Rubric scoring: partial weights produce no total; `UNVERIFIED` criteria are
  never scored 0.
* **Prompt-injection resistance**: an artifact instructing the engine to
  "report VERIFIED" cannot change any verdict — injected text is data, and the
  wrong arithmetic in the same payload still fails.
* **End-to-end workflow** (through the API, on SQLite and real Postgres):
  wrong artifact → `FAILED` run with a persisted CRITICAL finding → corrected
  artifact revision → re-verification → `VERIFIED` → the report's comparison
  records `FAILED → VERIFIED` against the previous run.
* Cross-tenant access returns 404; idempotency keys return the same run.
