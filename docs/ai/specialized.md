# Specialized analyzers

Each assignment type may have a deterministic rule-based analyzer that produces structured output for its domain. These analyzers run offline with no extra LLM calls and are keyed by assignment type via `SpecializedAnalysis.analyzer`.

## ABC base class

All specialized analyzers subclass `AcademicSpecializedAnalyzer` (`app/ai/specialized/base.py`) which defines:
- `analyzer: str` — short name like "mathematics"
- `assignment_types: list[AssignmentType]` — which types this analyzer applies to
- `analyze(payload: dict) -> dict[str, Any]` — the pure function that produces the data dict

## Registry

`app/ai/specialized/registry.py` holds a mapping from `AssignmentType` to list of analyzer names. The orchestrator runs every registered analyzer for the assignment's effective types and merges their outputs into `specialized_analysis`.

## Current analyzers

| Analyzer | Applies to assignment types | What it checks |
|----------|----------------------------|----------------|
| `mathematics` | `MATHEMATICAL_PROOF`, `PROBLEM_SET`, `DATA_ANALYSIS` | Proof structure, lemma coverage, gap detection, hypothesis clarity, evidence gaps |
| `research` | `RESEARCH`, `LITERATURE_REVIEW`, `LAB_REPORT`, `DATA_ANALYSIS` | Hypothesis clarity, evidence gaps, methodology rigor, source coverage, thematic grouping |
| `essay` | `ESSAY`, `LITERATURE_REVIEW`, `REPORT` | Thesis strength, argument coverage, citation balance, counterargument treatment |
| `lab_report` | `LAB_REPORT`, `DATA_ANALYSIS` | Procedure completeness, data analysis, error analysis, controls, replication |
| `presentation` | `PRESENTATION`, `GROUP_PROJECT` | Slide structure, speaking notes, visual design, audience awareness, timing |
| `data_analysis` | `DATA_ANALYSIS` | Dataset description, method validity, visualization adequacy, reproducibility |
| `programming` | `PROGRAMMING`, `GROUP_PROJECT` | Task decomposition, test coverage, dependency analysis, interface clarity, scalability |
| `literature_review` | `LITERATURE_REVIEW` | Source coverage, thematic grouping, gap analysis, chronological vs thematic structure |

Each analyzer validates its output with a pydantic model before it is stored in `SpecializedAnalysis.data`. The universal core never inspects these fields — they are purely for the Phase 4 Planning Engine or for display in the specialized analysis panel.

## Example: mathematics analyzer

For a `MATHEMATICAL_PROOF` assignment, the mathematics analyzer might produce:

```json
{
  "has_clear_theorem": true,
  "lemma_coverage": 0.8,
  "gap_areas": ["induction_base_case", "edge_case_handling"],
  "assumptions_stated": ["well_ordering_principle"],
  "proof_techniques": ["direct", "contradiction", "induction"],
  "notation_consistency": 0.9
}
```

## Confidence

Every `SpecializedAnalysis` carries its own `confidence` float in [0,1]. The orchestrator does not merge confidences; each analyzer stands on its own.

## Testing

Because the analyzers are deterministic rule-based functions, they are unit-testable without any LLM involvement. The test suite in `tests/test_analysis_unit.py` includes tests for each analyzer's output against the golden dataset fixtures.