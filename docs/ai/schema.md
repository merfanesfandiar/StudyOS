# Schema & type architecture

## AnalyzerOutput — the universal LLM contract

`app/schemas/analysis.py` defines `AnalyzerOutput` as the single contract every provider must satisfy. It is domain-agnostic: nothing here assumes an assignment is a programming project. Unknown extra fields are ignored (non-fatal), but missing fields, invalid enums, out-of-range confidence, and inconsistent references are all enforced.

### 23 sections

| # | Field | Type | Description |
|---|-------|------|-------------|
| 1 | `assignment_types` | `list[TypeClassification]` | What kind of work is requested |
| 2 | `academic_domains` | `list[DomainClassification]` | The discipline |
| 3 | `summary` | `str` | One-paragraph overview (max 2000 chars) |
| 4 | `objectives` | `list[Objective]` | Stated goals |
| 5 | `normalized_requirements` | `list[NormalizedRequirement]` | Requirements grouped by key |
| 6 | `ambiguities` | `list[Ambiguity]` | Underspecified areas |
| 7 | `contradictions` | `list[Contradiction]` | Conflicting signals |
| 8 | `missing_information` | `list[MissingInformation]` | Gaps |
| 9 | `assumptions` | `list[Assumption]` | Labeled guesses, never authoritative |
| 10 | `clarification_questions` | `list[ClarificationQuestion]` | What the student should answer |
| 11 | `deliverables` | `list[DeliverableAnalysis]` | Expected outputs |
| 12 | `evaluation` | `EvaluationAnalysis` | Rubric availability and quality expectations |
| 13 | `scope` | `ScopeAnalysis` | Breadth/depth/research intensity estimates |
| 14 | `work_areas` | `list[WorkArea]` | High-level areas (not executable tasks) |
| 15 | `resources` | `ResourceAnalysis` | Document insights and roles |
| 16 | `dependencies` | `list[AnalysisDependency]` | "needs first" edges |
| 17 | `verification` | `VerificationStrategy` | How completion could later be verified |
| 18 | `risks` | `list[Risk]` | Mitigation hints |
| 19 | `confidence` | `float` | Model confidence in [0,1], never certainty |
| 20 | `specialized_analysis` | `list[SpecializedAnalysis]` | Domain-specific structured data |
| 21 | `evidence` | `list[Evidence]` | Flattened provenance across all findings |
| 22 | `status` | `AnalysisReviewStatus` | PENDING / ACCEPTED / REJECTED |
| 23 | `is_stale` | `bool` | Specification hash changed since analysis was computed |

### Provenance: SourceKind

Every conclusion carries `source: SourceKind`:
- **EXPLICIT** — stated in the brief (authoritative)
- **AI_INFERENCE** — inferred by the model
- **UNCERTAIN** — low confidence or ambiguous
- **MISSING** — not stated in the brief

The UI must never render AI inference as if the brief stated it. The only provenance that is safe to plan against is EXPLICIT.

### Specialization isolation

`SpecializedAnalysis.data` is a `dict[str, Any]` validated by the producing analyzer's own model. The universal core never knows the field names, and the specialized analyzer is keyed by `AssignmentType` (e.g. `mathematics`, `programming`, `research`). This means a mathematical proof in a CS course carries the universal core (`objectives`, `requirements`, etc.) plus the `mathematics` analyzer's `data` — programming-specific fields live only in the specialized layer, never in the universal core.