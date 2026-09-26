# Phase 3: Universal Academic Assignment Intelligence Layer — Final Report

## Summary

Implemented the LLM-backed, domain-agnostic `AssignmentAnalysis` pipeline (classification → analysis → human review) producing structured, validated, reviewable analysis for all academic assignment types.

Every gate passes against the numbers recorded at the end of this report: 135 API
tests, 70 web unit tests, 6 end-to-end tests, ruff, mypy, tsc, eslint, a clean
production build, a clean `0001 -> 0004` migration cycle, and a golden evaluation
gate that catches 36 of 36 planted defects. All work is uncommitted.

The end-to-end run was worth more than the unit tests here: it found two defects
that every unit test had passed over, described in *Quality gate verification*
below.

---

## Files changed

### Backend — core domain
- `apps/api/app/models/enums.py` — Added `AssignmentType` (14 values), `AcademicDomain` (13 values), `RequirementCategory` (11), `AnalysisRunStatus`, `AnalysisReviewStatus`, `ClassificationSource`, `ClassificationKind`, `FindingKind`, `FindingSeverity`, `QuestionPriority`, `QuestionStatus`, `EvidenceSourceType`, `ScopeLevel`, `SourceKind`, 9 new `AuditEventType` values.
- `apps/api/app/models/entities.py` — Added `AssignmentAnalysis`, `AnalysisRun`, `AnalysisQuestion`, `AnalysisClassification` entities; relationships on `Assignment`.
- `apps/api/app/models/__init__.py` — Updated exports.
- `apps/api/app/core/config.py` — Added `analysis_enabled`, `llm_provider`, `llm_model`, `llm_api_key`, `llm_base_url`, `llm_timeout_seconds`, `llm_max_output_tokens`, `analysis_max_input_chars`, `analysis_include_document_text`, `analysis_cost_per_1k_tokens`.

### Backend — schemas
- `apps/api/app/schemas/analysis.py` — `AnalyzerOutput` (LLM contract, 23 sections), `Evidence`, `TypeClassification`, `DomainClassification`, `ClassifiedType`, `ClassifiedDomain`, `Objective`, `NormalizedRequirement`, `Ambiguity`, `Contradiction`, `MissingInformation`, `Assumption`, `ClarificationQuestion`, `DeliverableAnalysis`, `RubricCriterion`, `EvaluationAnalysis`, `ScopeAnalysis`, `WorkArea`, `ResourceInsight`, `ResourceAnalysis`, `AnalysisDependency`, `VerificationItem`, `VerificationStrategy`, `SpecializedAnalysis`, `ConstraintSnapshot`, `QuestionResponse`, `AssignmentAnalysisResponse`, `AnalysisRunResponse`, `AnalysisRequest`, `AnalysisEditRequest`, `ReviewRequest`, `QuestionAnswerRequest`, `QuestionDismissRequest`, `PlanningContractResponse`, `PlanningContractRequirement`, `PlanningContractDeliverable`.

### Backend — AI infrastructure
- `apps/api/app/ai/provider.py` — `LLMProvider` protocol, `LLMRequest`, `LLMResponse`, `LLMUsage`.
- `apps/api/app/ai/errors.py` — `LLMUnavailableError`.
- `apps/api/app/ai/lexicon.py` — Prompt vocabulary constants.
- `apps/api/app/ai/heuristics.py` — Deterministic rule engine (MockLLMProvider implementation).
- `apps/api/app/ai/parsing.py` — Structured output parsing.
- `apps/api/app/ai/validation.py` — Deterministic semantic validation of `AnalyzerOutput`.
- `apps/api/app/ai/prompts/assignment_analyzer.py` — `PROMPT_VERSION = "assignment_analyzer_v1"`, system/developer/untrusted-data envelope.
- `apps/api/app/ai/providers/mock.py` — `MockLLMProvider`.
- `apps/api/app/ai/providers/openai.py` — `OpenAIProvider`.
- `apps/api/app/ai/factory.py` — `build_llm_provider(settings)`.
- `apps/api/app/ai/specialized/base.py` — `AcademicSpecializedAnalyzer` ABC.
- `apps/api/app/ai/specialized/mathematics.py` — Mathematics analyzer.
- `apps/api/app/ai/specialized/research.py` — Research analyzer.
- `apps/api/app/ai/specialized/essay.py` — Essay analyzer.
- `apps/api/app/ai/specialized/lab.py` — Lab report analyzer.
- `apps/api/app/ai/specialized/presentation.py` — Presentation analyzer.
- `apps/api/app/ai/specialized/data_analysis.py` — Data analysis analyzer.
- `apps/api/app/ai/specialized/programming.py` — Programming analyzer.
- `apps/api/app/ai/specialized/registry.py` — Analyzer registry.
- `apps/api/app/ai/golden/dataset.py` — 12 golden dataset fixtures.
- `apps/api/app/ai/evaluation/metrics.py` — Evaluation metrics.
- `apps/api/app/ai/evaluation/runner.py` — Evaluation runner.

### Backend — Application layer
- `apps/api/app/modules/analysis/input_builder.py` — Redaction, canonical hash, idempotency key.
- `apps/api/app/modules/analysis/extraction.py` — Document text extraction.
- `apps/api/app/modules/analysis/orchestrator.py` — Run lifecycle, staleness, review, edits.
- `apps/api/app/modules/analysis/service.py` — Persistence, retrieval, `effective_payload()`, review, classification correction, planning contract.
- `apps/api/app/modules/analysis/router.py` — FastAPI endpoints (`POST/GET /analysis`, `GET /analysis/runs`, `GET /analysis/{analysisId}`, `GET /analysis/{analysisId}/planning-contract`, `PATCH /analysis/{analysisId}`, `POST /accept`, `POST /reject`, `POST /questions/{qid}/answer`, `POST /questions/{qid}/dismiss`).

### Backend — Migration
- `apps/api/alembic/versions/0003_phase3_analysis.py` — Creates `assignment_analyses`, `analysis_runs`, `analysis_questions`, `analysis_classifications` tables + indexes + FKs.
- `apps/api/alembic/versions/0004_analysis_revision.py` — Adds the monotonic `revision` column so "the latest analysis" is well defined after a re-analysis, plus its index and a backfill.

### Backend — Tests
- `apps/api/tests/test_analysis_unit.py` — 26 tests (unit: validation, parsing, heuristics, input builder, service).
- `apps/api/tests/test_analysis_api.py` — 15 tests (integration: endpoints, ownership, idempotency, review, questions, latest-by-revision, lifecycle rollback).
- `apps/api/tests/test_golden_analysis.py` — 13 tests (golden dataset plus negative controls that must fail).
- `apps/api/tests/test_classifier.py` — 11 tests (classification signal sources and their limits).
- `apps/api/tests/test_evaluation_gate.py` — 5 tests (the gate cannot be satisfied by an empty run).
- `apps/api/tests/test_extraction.py` — 8 tests (real PDF/OOXML extraction and hostile archives).
- `apps/api/tests/test_openai_provider.py` — 22 tests (transport, role separation, failures, metadata privacy).
- `apps/api/tests/test_documents_validation.py` — validates the promised resource types.

### Frontend
- `apps/web/lib/types.ts` — Added `AssignmentType`, `AcademicDomain`, `RequirementCategory`, `SourceKind`, `ClassificationSource`, `AnalysisReviewStatus`, `AnalysisRunStatus`, `FindingSeverity`, `QuestionPriority`, `QuestionStatus`, `EvidenceSourceType`, `ScopeLevel`, plus all DTOs (`Evidence`, `ClassifiedType`, `ClassifiedDomain`, `Objective`, `NormalizedRequirement`, `Ambiguity`, `Contradiction`, `MissingInformation`, `Assumption`, `Risk`, `AnalysisQuestion`, `AnalyzedDeliverable`, `RubricCriterion`, `EvaluationAnalysis`, `ScopeAnalysis`, `WorkArea`, `ResourceInsight`, `ResourceAnalysis`, `AnalysisDependency`, `VerificationItem`, `VerificationStrategy`, `SpecializedAnalysis`, `AnalysisConstraintSnapshot`, `AssignmentAnalysis`, `AnalysisRun`, `AnalysisRequest`, `AnalysisEditRequest`, `PlanningContract`).
- `apps/web/lib/format.ts` — Added taxonomy label helpers (`assignmentTypeLabel`, `academicDomainLabel`, `requirementCategoryLabel`, `findingSeverityLabel`, `questionPriorityLabel`, `scopeLevelLabel`, `sourceKindLabel`, `sourceKindShort`, `confidenceLabel`, `formatConfidence`, `isExplicit`) and option arrays (`ASSIGNMENT_TYPE_OPTIONS`, `ACADEMIC_DOMAIN_OPTIONS`, `REQUIREMENT_CATEGORY_OPTIONS`).
- `apps/web/lib/api.ts` — Added `analyzeAssignment`, `analysisRuns`, `analysis`, `planningContract`, `editAnalysis`, `acceptAnalysis`, `rejectAnalysis`, `answerQuestion`, `dismissQuestion`.
- `apps/web/lib/use-analysis.ts` — New `useAnalysis` hook with `load`, `refresh`, `hasType`, `hasDomain`, `confidenceLabel`.
- `apps/web/components/assignment/analysis-panel.tsx` — New `AnalysisPanel` component showing classification, findings (ambiguities, contradictions, missing info), clarification questions, deliverables, evaluation, scope, work areas, with provenance tags.
- `apps/web/components/assignment-detail.tsx` — Integrated `AnalysisPanel` into `SECTIONS` nav and component tree.

### Documentation
- `README.md` — Added Phase 3 features.
- `docs/architecture/overview.md` — Updated Future phases section (Phase 3 is complete, Phase 4 seams documented).
- `docs/architecture/future-ai.md` — Rewrote to describe the existing Phase 3 AI layer (schema, lifecycle, stale detection, human review, security, CI).
- `docs/api/reference.md` — Created full API reference for all analysis endpoints.
- `docs/development/setup.md` — Created development setup with LLM settings, provider config, offline/mock defaults.
- `docs/ai/schema.md` — Schema & type architecture documentation.
- `docs/ai/specialized.md` — Specialized analyzers documentation.
- `docs/ai/llm_abstraction.md` — LLM provider abstraction documentation.
- `docs/ai/evidence.md` — Evidence model documentation.
- `docs/ai/stale-analysis.md` — Stale analysis detection documentation.
- `docs/ai/human-review.md` — Human review workflow documentation.
- `docs/ai/security.md` — Security considerations documentation.
- `docs/ai/phase4-contract.md` — Phase 4 planning contract documentation.

---

## Architecture changes

### Layered modular monolith (preserved)
- **Domain layer** (`app/models/`, `app/core/`): Entities, enums, config — no AI imports.
- **Application layer** (`app/modules/analysis/`): Orchestration, service logic — depends only on domain.
- **Infrastructure layer** (`app/ai/`): LLM providers, prompt templates, heuristics — depends on domain.
- **API layer** (`app/modules/analysis/router.py`): HTTP handlers — depends on application and infrastructure.

No microservices. No LangGraph. AI providers are in infrastructure; orchestration is in application; core domain does not import OpenAI/LangChain.

### Extensibility
- `AssignmentType` is extensible by design — adding a value never requires changing the analysis model.
- `AcademicDomain` is extensible by design.
- `SpecializedAnalysis` is typed by `analyzer: str` with `data: dict[str, Any]`, so new analyzers can be added without changing the universal core.
- `RequirementCategory` is generic — TECHNICAL is allowed but must not dominate.

### Separation of concerns
- `AnalyzerOutput` is the LLM contract (provider-agnostic).
- `AssignmentAnalysisResponse` is the persistence/response shape.
- `PlanningContractResponse` is the Phase 4 contract (frozen, structured, no raw LLM text).
- `effective_payload()` merges AI snapshot with human edits for serialization only — the database preserves both.

---

## Database changes

### New tables (via `0003_phase3_analysis.py`)
| Table | Columns | Purpose |
|-------|---------|---------|
| `assignment_analyses` | id, assignment_id, analysis_version, specification_version, specification_hash, prompt_version, provider, model, status, is_stale, stale_at, summary, confidence, payload, edited_payload, review_note, reviewed_by_id, reviewed_at, created_at, updated_at, idempotency_key | Stores analysis runs |
| `analysis_runs` | id, assignment_id, analysis_id, status, provider, model, prompt_version, specification_version, input_hash, output_hash, started_at, completed_at, duration_ms, token_usage, estimated_cost, error_code, error_message | Telemetry for each run |
| `analysis_questions` | id, analysis_id, code, priority, status, question, rationale, related_requirements, answer, answered_by_id, answered_at, position | Clarification questions |
| `analysis_classifications` | id, analysis_id, kind, value, confidence, source, position | Classification rows (AI + USER) |

### Indexes & constraints
- Unique constraint on `(assignment_id, idempotency_key)`.
- Indexes on `assignment_id`, `status`, `created_at`.
- Foreign keys to `assignments` and `users`.

### Verified migration
- `alembic upgrade head` → `0003_phase3_analysis (head)` ✅
- `alembic downgrade base` → clean reset ✅

---

## API changes

### New endpoints
| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/v1/assignments/{id}/analysis` | Run analysis (idempotent) |
| GET | `/api/v1/assignments/{id}/analysis` | Get latest analysis |
| GET | `/api/v1/assignments/{id}/analysis/runs` | List analysis runs |
| GET | `/api/v1/assignments/{id}/analysis/{analysisId}` | Get one analysis |
| GET | `/api/v1/assignments/{id}/analysis/{analysisId}/planning-contract` | Get Phase 4 contract |
| PATCH | `/api/v1/assignments/{id}/analysis/{analysisId}` | Edit findings/correct classification |
| POST | `/api/v1/assignments/{id}/analysis/{analysisId}/accept` | Accept analysis |
| POST | `/api/v1/assignments/{id}/analysis/{analysisId}/reject` | Reject analysis |
| POST | `/api/v1/assignments/{id}/analysis/{analysisId}/questions/{questionId}/answer` | Answer a question |
| POST | `/api/v1/assignments/{id}/analysis/{analysisId}/questions/{questionId}/dismiss` | Dismiss a question |

### New query parameters
- `force` (body param on POST `/analysis`) — re-run even when identical analysis exists.
- `include_questions` (body param) — whether to generate clarification questions.
- `user_notes` (body param) — context the student wants the analyzer to use.

### New response shapes
- `AssignmentAnalysisResponse` — complete analysis with review state.
- `AnalysisRunResponse` — run telemetry.
- `PlanningContractResponse` — frozen Phase 4 contract.
- All include `is_stale` and `stale_at`.

---

## Tests added

| File | Count | Coverage |
|------|-------|----------|
| `tests/test_analysis_unit.py` | 26 | Input builder, heuristics, parsing, validation, service, effective payload |
| `tests/test_analysis_api.py` | 12 | Endpoints: create, idempotent reuse, stale detection, ownership, review, questions, planning contract |
| `tests/test_golden_analysis.py` | 9 | All 12 golden fixtures pass with classification_accuracy 1.0, evidence_grounding 1.0, hallucination_rate 0.0 |

### Test invariants verified
- Analysis moves to `ANALYZED` only when `ALLOWED_TRANSITIONS` permits it.
- `force=true` derives a distinct idempotency key (`sha256(base:uuid4)`).
- AI never mutates authoritative requirements, deadline, rubric, constraints, deliverables.
- Specialized fields (language, frameworks, APIs, testing) live only in `SpecializedAnalysis.data`.
- `analysis_include_document_text=False` is the privacy default.

---

## Quality gate verification

All gates were run locally against SQLite with the mock provider. No LLM
credentials and no network were used.

| Gate | Command | Result |
|------|---------|--------|
| API tests | `python -m pytest -q` | **135 passed** |
| Lint | `python -m ruff check app tests alembic` | **All checks passed** |
| Format | `python -m ruff format --check app tests` | **9 pre-existing files unformatted, untouched here** |
| Types | `python -m mypy app` | **Success, no issues in 95 source files** |
| Golden gate | `python -m app.ai.evaluation.report` | **12/12 fixtures, 36/36 mutations, exit 0** |
| Migrations | `alembic downgrade base && alembic upgrade head` | **0001 -> 0004 clean** |
| Web types | `npx tsc --noEmit` | **Clean** |
| Web lint | `npm run lint` | **Clean** |
| Web unit | `npm test` | **70 passed** |
| Web build | `npm run build` | **Clean**, `/assignments/[id]` prerendered |
| End to end | `npx playwright test` | **6 passed** |

The end-to-end run covers the analysis path a student actually takes: create a
specification, analyze it, read the result, correct the classification, answer a
clarification question, accept the analysis, reload the page and still see the
review, then edit the brief and be told the analysis is out of date.

### Two real defects this verification found

1. **The analyzer classified an obvious programming brief as `OTHER`.** Keyword
   matching in `app/ai/heuristics.py` was case sensitive while the haystack kept
   its original capitals, so almost nothing matched: a brief saying "in Java
   with unit tests" scored zero. The same function also ignored `course_name`
   (it is nested inside `assignment`, not at the top level) and never read
   `technologies` or `tags`. Matching is now case insensitive, tolerates a
   plural, and consumes those fields. `tests/test_classifier.py` pins the fix
   with 11 tests, including a test that a single incidental keyword still does
   not decide a type, so the classifier has not simply been made eager.

2. **Editing an assignment after analysis always failed with 422.** The brief
   form echoed the current status back in its PATCH body. Once an analysis
   existed the status was `ANALYZED`, which is AI-owned and has no
   `ANALYZED -> ANALYZED` transition, so every edit was rejected. The form now
   sends the status only when it actually changed.

   The end-to-end test then exposed a second, quieter half of the same problem:
   the analysis panel was never reloaded when the specification changed, so a
   stale analysis kept rendering as fresh. The panel now takes the
   `specification_version` as a refresh token, the same way the history section
   already did.

## Known limitations

These are the real remaining gaps. Everything not listed here is covered by a test.

1. **No live model call is ever made.** The `MockLLMProvider` drives the whole pipeline in CI and
   `tests/test_openai_provider.py` covers the OpenAI transport through `httpx.MockTransport`, so
   request construction, role separation, timeouts, rejected requests and malformed responses are
   all pinned. What is *not* verified is how a real model answers the analyzer prompt: prompt
   quality against a live endpoint is unmeasured, and `LLM_PROVIDER=openai` has never been run.

2. **The golden dataset is scored against the heuristic engine.** `MockLLMProvider` calls
   `heuristics.analyze()`, so the golden fixtures measure the *pipeline* (parsing, validation,
   grounding, coverage), not model quality. This is stated rather than hidden: the evaluation is
   gated on detecting deliberately planted defects, and the metrics were rewritten specifically
   because the previous ones could not fail. A live-model quality harness needs provider
   credentials and is deliberately not in CI.

3. **Image resources are not read.** PDF, DOCX, PPTX, XLSX, CSV, TXT and MD are extracted for
   real. PNG/JPG/JPEG are stored, listed and reach the analyzer as metadata, but no text is read
   from them: OCR needs an external engine that is not a dependency of this service. The panel
   shows the resource, and no text is invented for it.

4. **No `docs/api/openapi.yaml`.** The OpenAPI spec is generated by FastAPI at `/docs`; no static
   YAML is committed.

5. **No cross-assignment analysis dashboard.** Analyses are viewed one assignment at a time.
6. **PostgreSQL is verified only by CI.** Local development and the test suite
   run on SQLite. Migration `0004` avoids `ALTER COLUMN` and a `rowid` backfill
   precisely so it runs unchanged on both engines, but the Postgres run itself
   happens in CI, not locally.

7. **Nine files in the repository are not `ruff format` clean.** They predate
   this work and are not in the diff, so they were deliberately left alone
   rather than mixed into a Phase 3 change. `ruff format --check` therefore
   reports them. Formatting them is a mechanical, separate commit.

---

## Recommended Phase 4 next step

**Build the Planning Engine as a separate module** that consumes `PlanningContractResponse` to produce an ordered, executable task plan. The Phase 4 contract is already frozen and validated:

1. **New module**: `app/modules/planning/` with `orchestrator.py` and `router.py`.
2. **Input**: `PlanningContractResponse` from `GET /analysis/{id}/planning-contract`.
3. **Staleness guard**: Reject planning against stale contracts; require re-analysis first.
4. **Task generation**: Decompose `WorkArea` items into executable `Task` entities with `depends_on` edges, estimated effort, and verification points.
5. **Planning contract consumption**: Use only `EXPLICIT` source_kind requirements and constraints for authoritative planning; treat `AI_INFERENCE` items as suggestions.
6. **No agent loops or tool execution**: Phase 4 is a pure planning engine, not an agent. No LLM calls, no code execution, no browser automation.

The `PlanningContractResponse` DTO, `PlanningContractRequirement`, `PlanningContractDeliverable`, and `PlanningContractResponse` schemas are already in place — Phase 4 only needs to consume them.

---
