# Human review workflow

Review actions never mutate the authoritative specification. They layer only writes to analysis tables.

## Review lifecycle

An analysis starts with `status = PENDING`. The student can:
1. **Accept** → `status = ACCEPTED` (analysis is considered correct)
2. **Reject** → `status = REJECTED` (analysis is considered incorrect)
3. **Answer questions** → clarification questions move from OPEN to ANSWERED
4. **Dismiss questions** → clarification questions move from OPEN to DISMISSED
5. **Correct classification** → user corrections override AI classifications
6. **Edit findings** → shallow overlay on the AI payload (e.g. replace ambiguities list)
7. **Add review note** → free-form text attached to the analysis

All of these actions leave the authoritative specification untouched.

## Invariant: AI never mutates authoritative data

When a human corrects a classification or edits a finding, the change lives in:
- `AssignmentAnalysis.edited_payload` (validated against `AnalyzerOutput`) or
- `AnalysisClassification` rows with `source = USER` (for type/domain corrections)

The original AI rows remain in the database with `source = AI`, preserving the audit trail.

The `effective_payload()` function merges the AI payload with any human edits
(the edits win on key collisions) and returns the combined object for serialization.

## What can be corrected

### Classification
- Assignment types (`AssignmentAnalysis.assignment_types`)
- Academic domains (`AssignmentAnalysis.academic_domains`)

Client sends `AnalysisEditRequest.types` or `.domains`; the service deletes existing
USER classifications of that kind and inserts the new ones.

### Findings overlay
Client sends `AnalysisEditRequest.edits` — a dict that gets merged into the AI
payload. The service validates the merged result against `AnalyzerOutput` before
accepting it.

### Questions
- Answer a clarification question (`POST /questions/{id}/answer`)
- Dismiss a clarification question (`POST /questions/{id}/dismiss`)

Both update the `AnalysisQuestion` row in place; the analysis response reflects
the new state.

### Review state
- Accept analysis (`POST /analysis/{id}/accept`)
- Reject analysis (`POST /analysis/{id}/reject`)

These set `AssignmentAnalysis.status` and fill in `reviewed_by_id`,
`reviewed_at`, and `review_note`.

## What cannot be changed

The following are **authoritative specification data** and are never touched by
review endpoints:
- Requirements (title, description, priority, type, required flag)
- Constraints (title, description, type, severity)
- Criteria (title, description, weight)
- Deliverables (title, description, type, required flag)
- Deadline
- Description
- Technologies
- Tags
- Documents

These can only be changed through the specification endpoints (`/assignments/{id}`).

## Example flow

1. Student submits a brief with ambiguous requirements.
2. AI produces an analysis with two `ambiguities` and three `clarification_questions`.
3. Student answers two questions and dismisses one.
4. Student corrects the assignment type from `ESSAY` to `RESEARCH`.
5. Student accepts the analysis.
6. The assignment can now proceed to Phase 4 planning (if not stale).

At no point did the AI change the brief's requirements, constraints, or deadline.