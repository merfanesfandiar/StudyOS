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


def build_verification_ui(
    *,
    verdict: str,
    completion_percentage: int,
    critical: list[str],
    warnings: list[str],
    unverified: list[str],
    requirements: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """A validated UI envelope summarising one verification run.

    Uses only block types the client already validates and renders (``callout``,
    ``table``, ``task_list``, ``progress``): no new frontend protocol, and no
    model-generated frontend code — these blocks are built server-side from
    persisted verification rows.
    """
    tone = {
        "VERIFIED": "success",
        "PARTIAL": "warning",
        "FAILED": "critical",
    }.get(verdict, "info")
    blocks: list[dict[str, Any]] = [
        {
            "type": "callout",
            "tone": tone,
            "title": f"Verification: {verdict}",
            "text": (
                f"{completion_percentage}% of applicable checks verified. "
                "This is StudyOS's own verification, not an instructor grade."
            ),
        },
        {"type": "progress", "label": "Checks verified", "value": completion_percentage},
    ]
    if requirements:
        blocks.append(
            {
                "type": "task_list",
                "title": "Requirement compliance",
                "items": [
                    {
                        "label": f"{row.get('code', '?')}: {row.get('status', 'UNVERIFIED')}",
                        "done": row.get("status") == "VERIFIED",
                    }
                    for row in requirements[:20]
                ],
            }
        )
    if critical:
        blocks.append(
            {
                "type": "callout",
                "tone": "critical",
                "title": "Critical failures",
                "text": "\n".join(f"• {item}" for item in critical[:5]),
            }
        )
    if unverified:
        blocks.append(
            {
                "type": "callout",
                "tone": "info",
                "title": "Could not be verified",
                "text": "\n".join(f"• {item}" for item in unverified[:5]),
            }
        )
    return _envelope(blocks)
