# Phase 4 contract: PlanningContract

The frozen, structured input the future Planning Engine consumes. Everything the
planner needs, already validated and with no raw LLM text to parse.

## Endpoint

`GET /api/v1/assignments/{id}/analysis/{analysisId}/planning-contract`

Returns `PlanningContractResponse` with `is_stale` — a hard signal: a stale
contract must not be planned against silently.

## Contents

| Field | Source | Notes |
|-------|--------|-------|
| `analysis_id` | analysis | |
| `assignment_id` | analysis | |
| `analysis_version` | analysis | |
| `specification_version` | analysis | |
| `specification_hash` | analysis | |
| `prompt_version` | analysis | `assignment_analyzer_v1` |
| `provider` | analysis | `mock` or `openai` |
| `model` | analysis | e.g. `gpt-4o-mini` |
| `is_stale` | `service.is_analysis_stale()` | Hard signal |
| `assignment_types` | analysis | With provenance |
| `academic_domains` | analysis | With provenance |
| `objectives` | analysis | |
| `requirements` | `normalized_requirements` | `PlanningContractRequirement` |
| `constraints` | `constraints_snapshot` | Frozen copy, never AI-invented |
| `deliverables` | analysis | `PlanningContractDeliverable` |
| `dependencies` | analysis | |
| `work_areas` | analysis | Not executable tasks |
| `risks` | analysis | |
| `verification_strategy` | analysis | How completion could be verified |
| `clarification_questions` | analysis | With answers/dismissals |
| `specialized_analysis` | analysis | Domain-specific structured data |
| `evaluation` | analysis | Rubric + quality expectations |
| `scope` | analysis | Breadth/depth/research/technical estimates |

## Key invariants

1. **Provenance everywhere**: every requirement/deliverable carries
   `source_kind` (`EXPLICIT`, `AI_INFERENCE`, `UNCERTAIN`, `MISSING`) and
   `source_reference` (authoritative REQ code when `EXPLICIT`). The planner
   knows what came from the brief vs. AI inference.

2. **No invented constraints**: `constraints` is a frozen copy of authoritative
   constraints (`constraints_snapshot`). The analyzer never invents constraints;
   it only mirrors what the student entered.

3. **Staleness is explicit**: `is_stale` is computed at response time. A stale
   contract must not be used without human acknowledgment.

4. **Work areas are not tasks**: `WorkArea` is a high-level area of work.
   Phase 4 plans executable tasks from work areas — the analyzer does not do this.

5. **Specialized analysis is untyped**: `SpecializedAnalysis.data` is a
   `Record<string, unknown>` validated by the producing analyzer's own model.
   The universal core never knows the field names; the planner may introspect
   specific analyzers (e.g. `analyzer: "mathematics"`) if it knows their schema.

## Example consumption (pseudocode)

```python
contract = get_planning_contract(assignment_id, analysis_id)
if contract.is_stale:
    raise Exception("Analysis is stale — must re-run analysis first")

# Only plan against EXPLICIT requirements and constraints
explicit_requirements = [r for r in contract.requirements if r.source_kind == "EXPLICIT"]
all_constraints = contract.constraints  # These are always authoritative

# Work areas guide task decomposition
for area in contract.work_areas:
    if area.origin == "EXPLICIT":
        create_tasks_from(area)
    else:
        # AI-inferred area — present as suggestion
        suggest_tasks_from(area)

# Specialized data available by analyzer
math_data = next((s.data for s in contract.specialized_analysis if s.analyzer == "mathematics"), None)
```

## Backward compatibility

- The contract is versioned by `analysis_version` + `specification_version` +
  `prompt_version` + `provider` + `model`.
- Adding a new field to `PlanningContractResponse` is additive — the planner
  ignores unknown fields.
- Changing the shape of a field (e.g. `requirements` item) requires a new
  prompt version and new analysis run.