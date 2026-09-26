# Evidence model

Evidence is embedded per finding/requirement inside the analysis payload, validated
to reference real sources, rather than in a separate table — this avoids duplication.

## Where evidence lives

Evidence appears on these analysis sections:
- `Objective.evidence`
- `NormalizedRequirement.evidence`
- `Ambiguity.evidence`
- `Contradiction.evidence`
- `MissingInformation.evidence`
- `Assumption.evidence`
- `DeliverableAnalysis.evidence`
- `Risk.evidence`
- `WorkArea.evidence`

## Evidence structure

| Field | Type | Description |
|-------|------|-------------|
| `source_type` | `EvidenceSourceType` | Where the evidence points to |
| `source_id` | `str \| null` | Requirement/criterion/deliverable/document id or code |
| `location` | `str \| null` | e.g. `REQ-003` or `description` |
| `excerpt_reference` | `str \| null` | Short paraphrase, not a long quote (max 500 chars) |
| `supports` | `str` | The claim this evidence supports (max 500 chars) |
| `confidence` | `float` | In [0,1] |

## Provenance values

| Value | Meaning |
|-------|---------|
| `TITLE` | Evidence from the assignment title |
| `DESCRIPTION` | Evidence from the assignment description |
| `COURSE` | Evidence from the course context |
| `REQUIREMENT` | Evidence from an explicit requirement |
| `CONSTRAINT` | Evidence from an explicit constraint |
| `CRITERION` | Evidence from an evaluation criterion |
| `DELIVERABLE` | Evidence from a deliverable |
| `RESOURCE` | Evidence from a resource/document |
| `USER_NOTE` | Evidence from student-provided notes |
| `INFERENCE` | No source — the honest escape hatch |

## Validation

The `AnalyzerOutput` validator checks that `evidence.source_id` references a real
requirement/criterion/deliverable/document code from the specification. Stale or
nonexistent references cause validation failure and the run is marked `FAILED`.

## UI display

The response flattens evidence across all findings into `evidence: list[Evidence]`
for the UI. The frontend shows the provenance tag (e.g. "Stated in the brief" vs
"Inferred by AI") next to each finding so the student can distinguish explicit
requirements from model interpretation.

## Design rationale

Evidence is embedded rather than in a separate table because:
1. Avoids duplication — the same evidence may support multiple conclusions.
2. Keeps the analysis self-contained — a single analysis row is sufficient for review.
3. The UI can show per-finding provenance without joining tables.
4. Validation is simpler — evidence references are checked against the specification at analysis time.