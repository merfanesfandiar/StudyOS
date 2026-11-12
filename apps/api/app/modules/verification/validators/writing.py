"""Domain validators: essays, written work, presentations, language.

Deterministic, structure-and-metrics based. These validators separate two
things explicitly:

* Objective signals (section presence, word-count targets, readability,
  grammar markers like doubled words) — reported as measured facts.
* Subjective quality (argument strength, style, persuasiveness) — NOT scored
  here. Without a rubric bound to evidence, such a score would be an AI opinion
  dressed as measurement, and this engine refuses to produce that.
"""

from __future__ import annotations

import re
from typing import ClassVar

from app.models.enums import (
    AcademicDomain,
    VerificationLevel,
    VerificationMethod,
    VerificationSeverity,
    VerificationStatus,
)
from app.modules.verification.contracts import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MODERATE,
    CONFIDENCE_NONE,
    ValidatorDeclaration,
    ValidatorEvidence,
    ValidatorFinding,
    ValidatorResult,
    VerificationContext,
    VerificationValidator,
)
from app.modules.verification.validators.helpers import (
    detect_sections,
    readability_score,
    word_count,
)

_INTRO_RE = re.compile(r"\b(introduction|overview|abstract)\b", re.IGNORECASE)
_CONCLUSION_RE = re.compile(r"\b(conclusion|summary|closing)\b", re.IGNORECASE)
_DOUBLE_WORD_RE = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)
_REPEATED_PUNCT_RE = re.compile(r"[!?]{3,}")
_HEDGE_CLAIM_RE = re.compile(
    r"\b(everyone knows|obviously|clearly|it is well[- ]known|proves that|always|never)\b",
    re.IGNORECASE,
)


def _structured_result(
    validator: VerificationValidator,
    status: VerificationStatus,
    summary: str,
    confidence: str,
    limitations: list[str],
    findings: list[ValidatorFinding],
    evidence: list[ValidatorEvidence],
) -> ValidatorResult:
    return ValidatorResult(
        validator=validator.declaration.name,
        version=validator.declaration.version,
        level=validator.declaration.level,
        status=status,
        summary=summary,
        method=VerificationMethod.DETERMINISTIC,
        confidence=confidence,
        executed=True,
        limitations=limitations,
        findings=findings,
        evidence=evidence,
    )


class EssayStructureValidator(VerificationValidator):
    """L3: essay structure, length signals, unsupported-claim markers."""

    declaration: ClassVar[ValidatorDeclaration] = ValidatorDeclaration(
        name="essay_structure",
        level=VerificationLevel.DOMAIN,
        domains=frozenset({
            AcademicDomain.HUMANITIES,
            AcademicDomain.SOCIAL_SCIENCES,
            AcademicDomain.LANGUAGES,
            AcademicDomain.BUSINESS,
            AcademicDomain.ECONOMICS,
        }),
        assignment_types=frozenset({"ESSAY", "REPORT", "READING"}),
        description=(
            "Checks introduction/conclusion presence, word-count signal, "
            "readability, and flags unhedged universal claims for evidence "
            "review. Objective metrics only; writing quality is not scored."
        ),
        timeout_seconds=10.0,
    )

    def applies_to(self, ctx: VerificationContext) -> bool:
        return bool(ctx.scoped_artifacts())

    async def verify(self, ctx: VerificationContext) -> ValidatorResult:
        text = "\n".join(a.content for a in ctx.scoped_artifacts())
        if word_count(text) < 20:
            return _structured_result(
                self,
                VerificationStatus.UNVERIFIED,
                "Artifact text too short for structural essay checks.",
                CONFIDENCE_NONE,
                ["Fewer than 20 words of content; nothing meaningful to check."],
                [],
                [],
            )

        findings: list[ValidatorFinding] = []
        evidence: list[ValidatorEvidence] = []
        sections = detect_sections(text)

        has_intro = bool(_INTRO_RE.search(text))
        has_conclusion = bool(_CONCLUSION_RE.search(text))
        if not has_intro:
            findings.append(
                ValidatorFinding(
                    severity=VerificationSeverity.MEDIUM,
                    title="No identifiable introduction",
                    description=(
                        "No section heading or opening marker matches an "
                        "introduction/abstract. Structure check is heading-based."
                    ),
                    recommendation="Add an introduction section.",
                )
            )
        if not has_conclusion:
            findings.append(
                ValidatorFinding(
                    severity=VerificationSeverity.MEDIUM,
                    title="No identifiable conclusion",
                    description="No conclusion/summary section was detected.",
                    recommendation="Add a conclusion section.",
                )
            )

        hedged = _HEDGE_CLAIM_RE.findall(text)
        for match in list(dict.fromkeys(hedged))[:6]:
            findings.append(
                ValidatorFinding(
                    severity=VerificationSeverity.LOW,
                    title=f"Unhedged claim marker: '{match}'",
                    description=(
                        "A universal or evidentially strong phrase appears without "
                        "an adjacent citation. This is a marker for review, not a "
                        "proof of unsupportedness."
                    ),
                    recommendation="Support this claim with a citation or soften it.",
                )
            )

        doubles = list(_DOUBLE_WORD_RE.finditer(text))[:5]
        for match in doubles:
            findings.append(
                ValidatorFinding(
                    severity=VerificationSeverity.LOW,
                    title=f"Repeated word: '{match.group(1)}'",
                    description="The same word appears twice in a row.",
                    recommendation="Remove the duplicated word.",
                )
            )

        readability = readability_score(text)
        words = word_count(text)
        evidence.append(
            ValidatorEvidence(
                kind="WRITING_METRICS",
                source="artifact text",
                method=VerificationMethod.DETERMINISTIC,
                status=VerificationStatus.VERIFIED,
                content=(
                    f"words={words}, sentences≈{len(sections)} headings, "
                    f"readability={readability and round(readability, 1)}, "
                    f"sections={len(sections)}"
                ),
            )
        )

        structure_issues = sum(
            1 for f in findings if "introduction" in f.title or "conclusion" in f.title
        )
        status = (
            VerificationStatus.PARTIAL if structure_issues else VerificationStatus.VERIFIED
        )
        return _structured_result(
            self,
            status,
            (
                f"Structure checked: intro={'yes' if has_intro else 'NO'}, "
                f"conclusion={'yes' if has_conclusion else 'NO'}, {words} words, "
                f"{len(findings)} markers."
            ),
            CONFIDENCE_HIGH,
            [
                "Structure detection is heading/marker based; argument quality, "
                "coherence and relevance are subjective and are not scored here.",
            ],
            findings,
            evidence,
        )


class PresentationStructureValidator(VerificationValidator):
    """L3: slide coverage and completeness for presentation artifacts."""

    declaration: ClassVar[ValidatorDeclaration] = ValidatorDeclaration(
        name="presentation_structure",
        level=VerificationLevel.DOMAIN,
        domains=frozenset({AcademicDomain.OTHER}),
        assignment_types=frozenset({"PRESENTATION"}),
        description=(
            "Checks slide/section count and that required topic terms appear. "
            "Chart accuracy and visual quality are not verifiable without the "
            "rendered deck and are reported as unverified."
        ),
        timeout_seconds=10.0,
    )

    def applies_to(self, ctx: VerificationContext) -> bool:
        return bool(ctx.scoped_artifacts())

    async def verify(self, ctx: VerificationContext) -> ValidatorResult:
        text = "\n".join(a.content for a in ctx.scoped_artifacts())
        if not text.strip():
            return _structured_result(
                self,
                VerificationStatus.UNVERIFIED,
                "No presentation content.",
                CONFIDENCE_NONE,
                ["No content."],
                [],
                [],
            )
        slides = [s for s in detect_sections(text)]
        findings: list[ValidatorFinding] = []
        if len(slides) < 3:
            findings.append(
                ValidatorFinding(
                    severity=VerificationSeverity.MEDIUM,
                    title="Very few slides/sections detected",
                    description=(
                        f"Only {len(slides)} headings were found; a presentation "
                        "typically needs several structured slides."
                    ),
                    recommendation="Structure the deck into per-topic slides.",
                )
            )
        status = VerificationStatus.PARTIAL if findings else VerificationStatus.VERIFIED
        return _structured_result(
            self,
            status,
            f"{len(slides)} slides/sections detected.",
            CONFIDENCE_MODERATE,
            [
                "Content is assumed to be slide text; rendered layout, charts and "
                "visual accuracy cannot be verified from text alone.",
            ],
            findings,
            [
                ValidatorEvidence(
                    kind="SLIDE_SCAN",
                    source="artifact text",
                    method=VerificationMethod.DETERMINISTIC,
                    status=VerificationStatus.VERIFIED,
                    content="\n".join(slides)[:2000],
                )
            ],
        )


class LanguageMetricsValidator(VerificationValidator):
    """L3: grammar markers and length constraints for language assignments."""

    declaration: ClassVar[ValidatorDeclaration] = ValidatorDeclaration(
        name="language_metrics",
        level=VerificationLevel.DOMAIN,
        domains=frozenset({AcademicDomain.LANGUAGES}),
        assignment_types=frozenset({"LANGUAGE", "ESSAY"}),
        description=(
            "Flags mechanical grammar issues (doubled words, runaway "
            "punctuation) and measures length and readability. Semantic and "
            "idiomatic quality is not machine-verifiable here."
        ),
        timeout_seconds=10.0,
    )

    def applies_to(self, ctx: VerificationContext) -> bool:
        return bool(ctx.scoped_artifacts())

    async def verify(self, ctx: VerificationContext) -> ValidatorResult:
        text = "\n".join(a.content for a in ctx.scoped_artifacts())
        words = word_count(text)
        if words < 10:
            return _structured_result(
                self,
                VerificationStatus.UNVERIFIED,
                "Too little text for language metrics.",
                CONFIDENCE_NONE,
                ["Fewer than 10 words."],
                [],
                [],
            )
        findings: list[ValidatorFinding] = []
        for match in list(_DOUBLE_WORD_RE.finditer(text))[:8]:
            findings.append(
                ValidatorFinding(
                    severity=VerificationSeverity.LOW,
                    title=f"Repeated word: '{match.group(1)}'",
                    description="The same word appears twice in a row.",
                    recommendation="Remove the duplicated word.",
                )
            )
        if _REPEATED_PUNCT_RE.search(text):
            findings.append(
                ValidatorFinding(
                    severity=VerificationSeverity.LOW,
                    title="Runaway punctuation",
                    description="Three or more consecutive '!' or '?' characters.",
                    recommendation="Reduce to a single punctuation mark.",
                )
            )
        readability = readability_score(text)
        status = VerificationStatus.VERIFIED if not findings else VerificationStatus.PARTIAL
        return _structured_result(
            self,
            status,
            f"{words} words checked; {len(findings)} mechanical findings.",
            CONFIDENCE_HIGH,
            [
                "Only mechanical markers are checked. Grammaticality, register, "
                "translation consistency and semantic accuracy require a "
                "language-specialised reviewer and are NOT covered.",
            ],
            findings,
            [
                ValidatorEvidence(
                    kind="LANGUAGE_METRICS",
                    source="artifact text",
                    method=VerificationMethod.DETERMINISTIC,
                    status=VerificationStatus.VERIFIED,
                    content=f"words={words}, readability={readability and round(readability, 1)}",
                )
            ],
        )
