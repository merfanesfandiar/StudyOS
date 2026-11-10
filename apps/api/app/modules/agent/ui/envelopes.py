from __future__ import annotations

from typing import Any

AGENT_UI_VERSION = 1


def _envelope(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"version": AGENT_UI_VERSION, "blocks": blocks}


def build_checkpoint_ui(
    *,
    question: str,
    context: str | None = None,
    options: list[str] | None = None,
) -> dict[str, Any] | None:
    """Build a structured UI envelope for checkpoints when useful.

    Today most checkpoints are plain text; emit UI only when there is structure
    that benefits from a richer presentation (e.g. multiple options) without
    replacing the existing form.
    """
    blocks: list[dict[str, Any]] = []
    if question:
        blocks.append({"type": "text", "text": question})
    if context:
        blocks.append({"type": "callout", "tone": "info", "text": context})
    if options:
        choice_options = [
            {"value": option, "label": option} for option in options
        ]
        blocks.append(
            {
                "type": "choice",
                "id": "checkpoint-options",
                "prompt": "Choose an option",
                "options": choice_options,
            }
        )
    if not blocks:
        return None
    return _envelope(blocks)


def build_artifact_ui(*, title: str, artifact_type: str) -> dict[str, Any] | None:
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": title},
        {"type": "callout", "tone": "info", "text": f"Artifact type: {artifact_type}"},
    ]
    return _envelope(blocks)
