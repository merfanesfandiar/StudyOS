"""A provider that replays recorded transcripts instead of computing them.

The evaluation needs an answer whose provenance is independent of the code it is
scoring. ``MockLLMProvider`` cannot provide that, because it runs the heuristic
engine, so the golden dataset ended up grading the engine with metrics derived
from the engine. This provider replays fixed, hand-written answers instead.

It deliberately holds no reference to ``app.ai.heuristics``. A test asserts that,
because the whole point is that the two cannot drift back together.
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.evaluation.transcripts import transcript_for
from app.ai.provider import LLMProvider, LLMRequest, LLMResponse, LLMUsage


class TranscriptNotRecorded(LookupError):
    """Raised when a fixture has no recorded transcript.

    This is an error rather than a fallback. Silently falling back to the
    heuristic engine would restore exactly the circularity this provider
    exists to remove, and it would do so invisibly.
    """


class RecordedTranscriptProvider(LLMProvider):
    """Replays the transcript recorded for the fixture in the request metadata."""

    name = "recorded"

    def __init__(self, model: str = "recorded-academic-analyzer-v1") -> None:
        self.model = model

    async def complete(self, request: LLMRequest) -> LLMResponse:
        fixture_name = str(request.metadata.get("fixture_name") or "")
        transcript = transcript_for(fixture_name)
        if transcript is None:
            raise TranscriptNotRecorded(
                f"No recorded transcript for fixture {fixture_name!r}. The golden "
                "dataset and app.ai.evaluation.transcripts have drifted apart."
            )

        content = json.dumps(transcript, ensure_ascii=False, default=str)
        payload = request.metadata.get("analyzer_input") or {}
        prompt_tokens = max(1, len(json.dumps(payload, default=str)) // 4)
        completion_tokens = max(1, len(content) // 4)
        return LLMResponse(
            content=content,
            provider=self.name,
            model=self.model,
            usage=LLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )


def recorded_payload(name: str) -> dict[str, Any]:
    """Public accessor used by tests that need the stored answer directly."""
    transcript = transcript_for(name)
    if transcript is None:
        raise TranscriptNotRecorded(f"No recorded transcript for fixture {name!r}.")
    return transcript
