# Security considerations

## Authentication and authorization

- All endpoints require a valid JWT session cookie.
- The dependency layer resolves the caller's workspace from their memberships.
- Every handler filters queries by `workspace_id`; IDs from other workspaces return 404.
- Multi-workspace selection is out of scope, but the dependency is the single seam where it would be introduced.

## Prompt-injection defense

- Prompts use an envelope (`system` + `developer` + `untrusted-data`) with explicit
  `{document_text}` injection only when `analysis_include_document_text` is `True`.
- The system prompt forbids any reference to external tools or code execution.
- The developer prompt specifies that the model must produce JSON matching the
  `AnalyzerOutput` schema — no free text is allowed.

## Data privacy

- **No PII to providers**: document text sent to LLMs is redacted; only metadata
  (filename, size, mime_type) is forwarded.
- **Redaction**: before sending to the provider, the prompt builder removes all
  personally identifiable information from document content.
- **No tool execution**: the analyzer never executes code, makes HTTP calls, or opens
  browsers.
- **No raw prompt logging**: request IDs are logged, but full prompts and document
  contents are never included in logs.
- **Offline mode**: `MockLLMProvider` runs the deterministic heuristics engine
  without any external call, so CI passes without LLM credentials.

## Security boundaries

| Boundary | Who controls it | What is allowed |
|----------|----------------|---------------|
| **Auth** | Backend JWT validation | Authenticated users only |
| **Authz** | Workspace ownership checks | Only assignments in the caller's workspace are accessible |
| **Prompt** | Backend prompt builder | Structured output only, no code execution |
| **LLM call** | Provider implementation | Only JSON response matching schema |
| **Analysis output** | Backend validation | Must conform to `AnalyzerOutput` schema |
- **No tool execution**: The analyzer layer is completely sandboxed — no network calls, no process spawning.
- **No PII leakage**: document text is redacted before sending to the provider; only metadata is sent.
- **Prompt integrity**: prompts are built from a fixed template with explicit document text injection only when allowed.
- **No silent failures**: any validation error (missing fields, invalid enums, out-of-range confidence) results in a clear error response.

## Observability

- Every request receives a request ID (returned in `X-Request-ID` header).
- Structured JSON logs include method, path, status, duration, and request ID.
- Domain errors are raised as `AppError` and rendered as a consistent envelope.
- Validation failures use `VALIDATION_ERROR`; uniqueness violations surface as 409 `CONFLICT`; unexpected database problems return 503 `DATABASE_UNAVAILABLE`.

## Rate limiting

Not implemented at this time; the service is stateless and can be scaled horizontally.