"""AI provider errors.

These are transport- and provider-level failures, kept separate from domain
errors so the application layer can map them to API responses without leaking
provider internals to the user.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for every provider failure."""

    code = "LLM_ERROR"

    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class LLMTimeoutError(LLMError):
    code = "LLM_TIMEOUT"


class LLMUnavailableError(LLMError):
    code = "LLM_UNAVAILABLE"


class LLMResponseFormatError(LLMError):
    """The provider returned something that is not a JSON object."""

    code = "LLM_RESPONSE_INVALID"


class AnalysisSchemaError(LLMError):
    """The JSON did not satisfy the structured output contract."""

    code = "ANALYSIS_SCHEMA_INVALID"


class AnalysisSemanticError(LLMError):
    """The JSON was well formed but internally inconsistent."""

    code = "ANALYSIS_SEMANTIC_INVALID"

    def __init__(self, message: str, violations: list[str]) -> None:
        super().__init__(message, {"violations": violations})
        self.violations = violations


class AnalysisInputError(LLMError):
    """The analyzer input itself is unusable (e.g. an empty specification)."""

    code = "ANALYSIS_INPUT_INVALID"
