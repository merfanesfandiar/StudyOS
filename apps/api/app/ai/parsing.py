"""Parse raw provider text into the structured analysis contract.

The model's output is never trusted: it must be a single JSON object that
validates against ``AnalyzerOutput``. Anything else is a hard failure with a
stable error code, so a bad model response can never be mistaken for a valid
analysis.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.ai.errors import AnalysisSchemaError, LLMResponseFormatError
from app.schemas.analysis import AnalyzerOutput

#: Bound the size of the text we are willing to parse, so a runaway model cannot
#: exhaust memory.
MAX_RESPONSE_CHARS = 400_000


def parse_analyzer_output(content: str) -> AnalyzerOutput:
    if len(content) > MAX_RESPONSE_CHARS:
        raise LLMResponseFormatError("The model response was unexpectedly large.")
    text = content.strip()
    if text.startswith("```"):
        # Tolerate a fenced block, but do not attempt broader repair.
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMResponseFormatError(
            "The model response was not valid JSON.", {"reason": str(exc)[:200]}
        ) from exc
    if not isinstance(data, dict):
        raise LLMResponseFormatError("The model response was not a JSON object.")
    try:
        return AnalyzerOutput.model_validate(data)
    except ValidationError as exc:
        raise AnalysisSchemaError(
            "The model response did not match the analysis schema.",
            {"errors": _summarize(exc)},
        ) from exc


def _summarize(exc: ValidationError) -> list[str]:
    summary: list[str] = []
    for error in exc.errors()[:20]:
        location = ".".join(str(part) for part in error.get("loc", ()))
        summary.append(f"{location}: {error.get('msg', 'invalid')}")
    return summary
