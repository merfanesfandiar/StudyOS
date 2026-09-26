# API Reference — Assignment Analysis

All endpoints are under `/api/v1/assignments` and enforce workspace ownership.

## Analysis lifecycle

### POST `/assignments/{id}/analysis`

Run the universal academic analyzer.

**Request body** (`AnalysisRequest`):

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `force` | `bool` | `false` | Re-run even when an identical, non-stale analysis exists. |
| `user_notes` | `str \| null` | `null` | Context the student wants the analyzer to use. |
| `include_questions` | `bool` | `true` | Whether to generate clarification questions. |

**Responses**:

- `200` — `AssignmentAnalysisResponse` with the analysis payload.
- `200` (idempotent reuse) — returns the existing analysis; `is_stale` is `true` if the specification hash changed.
- `409` — `ANALYSIS_ALREADY_RUNNING` if another analysis is in progress.
- `503` — `ANALYSIS_DISABLED` if analysis is not enabled in config.

After a successful run the assignment status transitions to `ANALYZED` if and only if the state
machine permits it (`ALLOWED_TRANSITIONS` owns the gate).

---

### GET `/assignments/{id}/analysis`

Return the most recent analysis for the assignment (404 if none exists). Never triggers a run.

---

### GET `/assignments/{id}/analysis/runs`

List all analysis runs for the assignment, newest first. Paginated response (`PageResponse[AnalysisRunResponse]`).

---

### GET `/assignments/{id}/analysis/{analysisId}`

Return one full analysis with review state. `is_stale` reflects whether the spec hash has changed.

---

### GET `/assignments/{id}/analysis/{analysisId}/planning-contract`

Return a `PlanningContract` DTO frozen from the analysis. `is_stale` is a hard signal: a stale
contract must not be planned against silently. Contains:

- `assignment_types` / `academic_domains` — classifications with provenance
- `objectives` / `normalized_requirements` — requirements with `source_kind` / `source_reference`
- `requirements` / `deliverables` / `constraints` / `dependencies` / `work_areas` / `risks`
- `verification_strategy` / `clarification_questions`
- `specialized_analysis` / `evaluation` / `scope`

---

### PATCH `/assignments/{id}/analysis/{analysisId}`

Human corrections layered on the AI payload.

**Request body** (`AnalysisEditRequest`):

| Field | Type | Description |
| --- | --- | --- |
| `types` | `list[AssignmentType] \| null` | Replace user classifications (TYPE kind). |
| `domains` | `list[AcademicDomain] \| null` | Replace user classifications (DOMAIN kind). |
| `edits` | `dict[str, Any] \| null` | Shallow overlay on the AI payload (e.g. replace `ambiguities`). |
| `note` | `str \| null` | Free-text review note. |

**Important**: Authoritative assignment data (requirements, constraints, deadline, rubric,
deliverables) is **never** modified. Corrections live in `edited_payload` or `AnalysisClassification`
rows with `source: USER`.

---

### POST `/assignments/{id}/analysis/{analysisId}/accept`

Mark the analysis as ACCEPTED. Moves the analysis review state; does not change the assignment status
beyond what the review gate allows.

---

### POST `/assignments/{id}/analysis/{analysisId}/reject`

Mark the analysis as REJECTED. Same invariant as accept.

---

### POST `/assignments/{id}/analysis/{analysisId}/questions/{questionId}/answer`

Answer a clarification question. Updates `question.answer`, `question.status = ANSWERED`,
`question.answered_by_id`, `question.answered_at`.

---

### POST `/assignments/{id}/analysis/{analysisId}/questions/{questionId}/dismiss`

Dismiss a clarification question. Updates `question.status = DISMISSED` and appends the reason to
`question.rationale`.

---

## Enums (Phase 3)

### `AssignmentType` (14 values)

PROGRAMMING, PROBLEM_SET, MATHEMATICAL_PROOF, ESSAY, RESEARCH, LITERATURE_REVIEW, LAB_REPORT,
DATA_ANALYSIS, PRESENTATION, READING, LANGUAGE, DESIGN, GROUP_PROJECT, REPORT, OTHER

### `AcademicDomain` (13 values)

MATHEMATICS, COMPUTER_SCIENCE, PHYSICS, CHEMISTRY, BIOLOGY, ENGINEERING, ECONOMICS,
BUSINESS, SOCIAL_SCIENCES, HUMANITIES, LANGUAGES, ART_AND_DESIGN, OTHER

### `RequirementCategory` (13 values)

CONTENT, PROCESS, DELIVERABLE, QUALITY, FORMAT, ACADEMIC, METHODOLOGY, EVALUATION,
PRESENTATION, TECHNICAL, OTHER

### `AnalysisRunStatus` / `AnalysisReviewStatus` / `ClassificationSource` / `FindingSeverity`
### `QuestionPriority` / `QuestionStatus` / `EvidenceSourceType` / `ScopeLevel` / `SourceKind`

See `app/models/enums.py` for the full enum catalog.

## Security

- All endpoints require a valid JWT session cookie.
- Ownership is enforced through `load_owned_assignment` — an ID from another workspace returns 404.
- Prompt-injection defense: untrusted data is never interpolated into prompts.
- No tool execution, no PII in provider calls, document text sent to LLMs is redacted.
- `analysis_include_document_text` defaults to `False` (privacy default).