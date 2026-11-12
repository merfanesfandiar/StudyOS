"""Shared, pure helpers for validators.

Everything here is deterministic and side-effect free: it operates on artifact
text that is already in memory and returns plain data. No validator reaches the
database, the network or the filesystem, so untrusted artifact content can never
pull verification into an unsafe code path.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from app.modules.verification.contracts import ArtifactSnapshot

_WORD_RE = re.compile(r"\b[\w'-]+\b", re.UNICODE)


def artifact_text(artifacts: Iterable[ArtifactSnapshot]) -> str:
    """All artifact content joined with title headers, for text-based checks."""
    parts: list[str] = []
    for artifact in artifacts:
        parts.append(f"# {artifact.title}\n{artifact.content}")
    return "\n\n".join(parts)


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def sentence_count(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, len(re.findall(r"[.!?]+(?:\s|$)", stripped)))


def normalise(text: str) -> str:
    return text.lower()


def keyword_coverage(
    text: str, keywords: Iterable[str]
) -> tuple[list[str], list[str]]:
    """Which of the keywords appear in ``text`` and which do not.

    Matching is case-insensitive whole-word-ish substring matching. It is a
    *traceability* signal, not proof of compliance: coverage answers "is there
    relevant material?" and the explanation must say exactly that.
    """
    lowered = normalise(text)
    present: list[str] = []
    missing: list[str] = []
    for keyword in keywords:
        needle = normalise(keyword.strip())
        if not needle:
            continue
        if needle in lowered:
            present.append(keyword)
        else:
            missing.append(keyword)
    return present, missing


def detect_sections(text: str) -> list[str]:
    """Markdown-style headings and short title-ish lines."""
    sections: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            sections.append(stripped.lstrip("#").strip())
        elif (
            0 < len(stripped) <= 80
            and stripped.endswith(":")
            and not stripped.startswith(("-", "*", ">", "|"))
        ):
            sections.append(stripped.rstrip(":").strip())
    return sections


def duplicated_titles(artifacts: Iterable[ArtifactSnapshot]) -> list[str]:
    """Titles that appear more than once across artifacts."""
    counts = Counter(a.title.strip().lower() for a in artifacts)
    return [title for title, count in counts.items() if count > 1]


def empty_artifacts(artifacts: Iterable[ArtifactSnapshot]) -> list[ArtifactSnapshot]:
    return [a for a in artifacts if not a.content.strip()]


def readability_score(text: str) -> float | None:
    """Flesch reading ease, pure Python. ``None`` when text is too short.

    Deliberately the same idea as the runtime's readability tool so verification
    and generation agree on what "readable" means.
    """
    words = _WORD_RE.findall(text)
    if len(words) < 20:
        return None
    sentences = max(1, sentence_count(text))
    syllables = sum(_estimate_syllables(word) for word in words)
    return 206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syllables / len(words))


def _estimate_syllables(word: str) -> int:
    lowered = word.lower().strip("'")
    if not lowered:
        return 0
    groups = re.findall(r"[aeiouy]+", lowered)
    count = len(groups)
    if lowered.endswith("e") and count > 1:
        count -= 1
    return max(1, count)
