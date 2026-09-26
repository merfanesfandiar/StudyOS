# Assignment Analyzer

The universal academic assignment analyzer is the core of Phase 3. It produces a structured,
reviewable analysis for any assignment type — programming, essay, lab report, mathematical proof,
literature review, data analysis, presentation, reading, language work, design, group project, etc.

## Core contract: `AnalyzerOutput`

Every LLM call returns an `AnalyzerOutput` instance (see `app/schemas/analysis.py`). It is
domain-newsletter-agnostic: no field assumes a programming project. The model has 23 sections:

1. **assignment_types** (`list[TypeClassification]`) — what kind of work is requested
2. **academic_domains** (`list[DomainClassification]`) — the discipline
3. **summary** (`str`) — one-paragraph overview
4. **objectives** (`list[Objective]`) — stated goals
5. **normalized_requirements** (`list[NormalizedRequirement]`) — requirements grouped by key
6. **ambiguities** (`list[Ambiguity]`) — underspecified areas
7. **contradictions** (`list[Contradiction]`) — conflicting signals
8. **missing_information** (`list[MissingInformation]`) — gaps
9. **assumptions** (`list[Assumption]`) — labeled guesses, never authoritative
10. **clarification_questions** (`list[ClarificationQuestion]`) — what a student should answer
11. **deliverables** (`list[DeliverableAnalysis]`) — expected outputs
12. **evaluation** (`EvaluationAnalysis`) — rubric availability and quality expectations
13. **scope** (`ScopeAnalysis`) — breadth/depth/research intensity etc. estimates
14. **work_areas** (`list[WorkArea]`) — high-level areas (not executable tasks)
15. **resources** (`ResourceAnalysis`) — document insights and roles
16. **dependencies** (`list[AnalysisDependency]`) — "needs first" edges
17. **verification** (`VerificationStrategy`) — how completion could later be verified
18. **risks** (`list[Risk]`) — mitiation hints
19. **confidence
idence** (`float`) — model confidence in [0,1], never certainty
20. **specialized_analysis** (`list[SpecializedAnalysis]`) — domain-specific structured data
21. **evidence** — flattened provenance across all findings
22. **status** (`AnalysisReviewStatus`) — PENDING / ACCEPTED / REJECTED
23. **is_stale** (`bool`) — specification hash changed since the analysis was computed

## Provenance: SourceKind everywhere

Every conclusion carries `source: SourceKind` — EXPLICIT (in the brief), AI_INFERENCE,
UNCERTAIN, or MISSING. The UI must never render AI inference as if the brief stated it.

## Specialized analyzers

Deterministic rule-based `AcademicSpecializedAnalyzer` ABC subclasses keyed by assignment type.
They operate offline/testable with no extra LLM calls. Examples:

- `mathematics` — proof structure, lemma coverage, gap detection
- `research` — hypothesis clarity, evidence gaps, methodology rigor
- `essay` — thesis strengthScore, argument coverage, citation balance
- `lab_report` — procedure completeness, data analysis, error analysis
- `presentation` — slide structure, speaking notes, visual design
- `data_analysis` — dataset description, method validity, visualization adequacy
- `programming` — task decomposition, test coverage, dependency analysis
- `literature_review` — source coverage, thematic grouping, gap analysis

The `SpecializedAnalysis` DTO carries `analyzer: str`, `assignment_types: list[AssignmentType]`,
`data: Record<string, unknown>` (untyped — the universal core never interprets these fields),
`summary`, and `confidence`.

## Idempotency and staleness

- Every analysis run has an `idempotency_key` = `sha256(assignment_id + spec_version + prompt_version + model_config)`.
- `UNIQUE(assignment_id, idempotency_key)` prevents duplicate runs.
- `specification_hash` (SHA-256 of the canonical specification) enables stale detection: if(item1. `mark_stale_analyses()` compares the current hash against stored ones.
2. `is_analysis_stale()` returns True when hashes differ or the analysis is already marked stale.
3. Clients may pass `force: true` to get a distinct key (`sha256(base:uuid4)`) and force a re-run.

## Human review invariant

- Review actions (`accept`, `reject`, `correct classification`, `answer question`, `dismiss question`)
  **never** mutate authoritative requirements, deadline, rubric, constraints, or deliverables.
- Corrections go into `edited_payload` (validated against `AnalyzerOutput`) or `AnalysisClassification`
  rows with `source: USER`.
- The assignment status `ANALYZED` is only set when `ALLOWED_TRANSITIONS` permits it (from
  `READY_FOR_ANALYSIS`), owned by the analysis layer, never by a client.

## Security and privacy

- **Auth**: JWT in session cookie; every handler resolves the caller's workspace from membership.
- **Authz**: ownership helpers (`load_owned_assignment`) filter by `workspace_id`; IDs from other
  workspaces return 404.
- **Prompt-injection defense**: untrusted data is never interpolated into prompts; prompts use an
  envelope (`system` + `developer` + `untrusted-data`) with explicit `{document_text}` injection only
  when `analysis_include_document_text` is True (defaults to `False`).
- **No tool execution**: the analyzer never executes code, makes HTTP calls, or opens browsers.
- **No PII to providers**: document text sent to LLMs is redacted; only metadata (filename, size, mime_type)
  is forwarded.
- **Observability**: `ASSIGNMENT_ANALYSIS_REQUESTED/STARTED/COMPLETED/FAILED/REVIEWED/REJECTSJECTED/MARKED_STALE`
  events; no document contents or full prompts in logs.

## CI without LLM credentials

- `MockLLMProvider` runs the deterministic heuristics engine so the full parse→validate→persist pipeline
  is exercised in CI.
- All 12 golden dataset fixtures pass with `classification_accuracy 1.0`, `evidence_grounding 1.0`,
  `hallucination_rate 0.0`.
- `force: true` re-runs derive a distinct idempotency key to satisfy the `UNIQUE` constraint.

## Files

- `app/schemas/analysis.py` — AnalyzerOutput, all section DTOs, response shapes
- `app/models/enums.py` — AssignmentType, AcademicDomain, RequirementCategory, all run/review/finding enums
- `app/models/entities.py` — AssignmentAnalysis, AnalysisRun, AnalysisQuestion, AnalysisClassification
- `app/ai/provider.py` — LLMProvider protocol, LLMRequest/Response/Usage, OpenAIProvider, MockLLMProvider
- `app/ai/heuristics.py` — deterministic rule engine, the MockLLMProvider implementation
- `app/ai/prompts/assignment_analyzer.py` — PROMPT_VERSION "assignment_analyzer_v1", system/developer/envelope
- `app/ai/specialized/` — base ABC + per-type analyzers + registry
- `app/ai/golden/dataset.py` — 12 fixtures
- `app/ai/evaluation/` — metrics.py, runner.py
- `app/modules/analysis/input_builder.py` — redaction, canonical hash, idempotency key
- `app/modules/analysis/orchestrator.py` — run lifecycle, staleness, review, edits
- `app/modules/analysis/service.py` — persistence, retrieval, effective payload, review, classification correction
- `app/modules/analysis/router.py` — FastAPI endpoints (POST/GET /analysis, accept/reject, questions, planning contract)
- `app/core/config.py` — `analysis_enabled`, `llm_provider` (mock default), all LLM/analysis settings