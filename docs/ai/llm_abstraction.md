# LLM provider abstraction

The analyzer layer depends on an `LLMProvider` protocol (`app/ai/provider.py`), not on OpenAI or LangChain directly. The core domain never imports either.

## Protocol

```python
class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(self, request: LLMRequest) -> LLMResponse: ...
```

`LLMRequest` carries:
- `messages: list[dict]` — system + developer + untrusted-data envelope
- `temperature: float` — defaults to 0.0 for determinism
- `max_output_tokens: int`
- `response_format: dict` — structured output schema (Pydantic `model_json_schema()`)
- `extra: dict` — provider-specific knobs

`LLMResponse` returns:
- `content: str` — raw text (usually JSON)
- `usage: LLMUsage` — prompt/completion/total tokens
- `raw: Any` — provider-specific metadata

## Providers

### MockLLMProvider (default)

Runs the deterministic heuristics engine (`app/ai/heuristics.py`). No API key required. Returns structured JSON that validates against `AnalyzerOutput`. Used by default in CI and local dev.

### OpenAIProvider

Wraps the OpenAI client with structured output (`response_format={"type": "json_schema", "json_schema": ...}`). Reads `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS` from config.

### Factory

`app/ai/factory.py:build_llm_provider(settings)` returns the appropriate provider based on `LLM_PROVIDER`. Throws `LLMUnavailableError` if OpenAI is selected but credentials are missing.

## Prompt envelope

Prompts (`app/ai/prompts/assignment_analyzer.py`) use an envelope:
- `system` — fixed instructions about the analyzer's role
- `developer` — the structured task description and output schema
- `untrusted-data` — document text, user notes, specification (only when `analysis_include_document_text=True`)

Prompt version is `assignment_analyzer_v1` and is part of the idempotency key. Changing the prompt schema or instructions requires a new version string.

## Structured output

The provider is asked to produce JSON matching the `AnalyzerOutput` JSON schema. The response is parsed and validated with `AnalyzerOutput.model_validate()`. Missing fields, invalid enums, out-of-range confidence, and inconsistent references (e.g., an evidence `source_id` that doesn't exist in the normalized requirements) all cause validation failure — the run is marked `FAILED` and the analysis is not persisted.

## Determinism

`temperature=0.0` and `max_output_tokens` are set in config. The idempotency key includes `provider.name`, `provider.model`, and `prompt_version`. Any change to the model config creates a new idempotency key, forcing a fresh run.

## Testing without credentials

`MockLLMProvider` exercises the full parse → validate → persist pipeline in CI. All 12 golden dataset fixtures pass with `classification_accuracy 1.0`, `evidence_grounding 1.0`, `hallucination_rate 0.0`.