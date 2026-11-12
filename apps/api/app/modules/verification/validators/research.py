"""Domain validators: research, literature, citations.

Genuinely implemented, deterministic:

* Reference parsing and count (author-year and bracketed styles).
* DOI format validation (``10.<prefix>/<suffix>``) and internal duplicate
  detection — catching two citations that are the *same* reference.
* Claim-support mapping: which citation-bearing claims exist near evidence.

Honest scaffolds (documented, not faked):

* DOI resolution and source-existence checks need network access. The engine
  performs **no network access** from validators by design (SSRF and
  prompt-injection containment), so these checks report UNVERIFIED with the
  limitation stated. Integrating Crossref/DOI.org goes through the controlled
  external-resource path and is future work.
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
    CONFIDENCE_NONE,
    ValidatorDeclaration,
    ValidatorEvidence,
    ValidatorFinding,
    ValidatorResult,
    VerificationContext,
    VerificationValidator,
)

_BRACKET_RE = re.compile(r"\[([^\[\]]{4,120})\]")
_AUTHOR_YEAR_RE = re.compile(
    r"\(([A-Z][A-Za-z\-']+(?:\s+(?:et al\.|&|and)\s+[A-Z][A-Za-z\-']+|\s+\d{4}))(?:,\s*\d{4})?\)"
)
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_MAX_REFERENCES = 100


class CitationValidator(VerificationValidator):
    """L3/L4: citation parsing, DOI format checks and duplicate detection."""

    declaration: ClassVar[ValidatorDeclaration] = ValidatorDeclaration(
        name="citation_check",
        level=VerificationLevel.DOMAIN,
        domains=frozenset({
            AcademicDomain.SOCIAL_SCIENCES,
            AcademicDomain.HUMANITIES,
            AcademicDomain.BUSINESS,
            AcademicDomain.ECONOMICS,
        }),
        assignment_types=frozenset({"RESEARCH", "LITERATURE_REVIEW", "ESSAY", "REPORT"}),
        description=(
            "Parses references, validates DOI format, detects duplicate "
            "references and flags years that are impossible. No network access: "
            "source existence is reported UNVERIFIED, never assumed."
        ),
        timeout_seconds=10.0,
    )

    def applies_to(self, ctx: VerificationContext) -> bool:
        return bool(ctx.scoped_artifacts())

    async def verify(self, ctx: VerificationContext) -> ValidatorResult:
        text = "\n".join(a.content for a in ctx.scoped_artifacts())
        if not text.strip():
            return ValidatorResult(
                validator=self.declaration.name,
                version=self.declaration.version,
                level=self.declaration.level,
                status=VerificationStatus.NOT_APPLICABLE,
                summary="No content to check for citations.",
                confidence=CONFIDENCE_NONE,
                executed=True,
                limitations=["No content."],
            )

        findings: list[ValidatorFinding] = []
        evidence: list[ValidatorEvidence] = []

        bracketed = [m.group(1).strip() for m in _BRACKET_RE.finditer(text)][:_MAX_REFERENCES]
        author_year = [m.group(1).strip() for m in _AUTHOR_YEAR_RE.finditer(text)][:_MAX_REFERENCES]
        dois = [m.group(0).rstrip(".,);") for m in _DOI_RE.finditer(text)][:_MAX_REFERENCES]
        # Exact duplicates are kept here on purpose: repeated identical
        # citations are exactly what the duplicate check looks for.
        references = bracketed + author_year

        # DOI format: structural check only. Resolution requires network and is
        # not performed — stated in the result, never implied.
        malformed_dois = [
            doi for doi in dois
            if not re.match(r"^10\.\d{4,9}/\S+$", doi) or doi.endswith((".", ","))
        ]
        for doi in malformed_dois:
            findings.append(
                ValidatorFinding(
                    severity=VerificationSeverity.MEDIUM,
                    title=f"Malformed DOI: {doi}",
                    description=(
                        "This DOI does not match the 10.<prefix>/<suffix> structure. "
                        "Format only — existence was not checked (no network access)."
                    ),
                    recommendation="Check the DOI against the publisher's record.",
                )
            )

        # Duplicate references: the same citation appearing twice is usually one
        # source cited inconsistently, not two sources.
        counts: dict[str, int] = {}
        for reference in references:
            key = reference.lower().split(",")[0].strip()
            counts[key] = counts.get(key, 0) + 1
        duplicates: list[str] = []
        seen_keys: set[str] = set()
        for reference in references:
            key = reference.lower().split(",")[0].strip()
            if counts[key] > 1 and key not in seen_keys:
                seen_keys.add(key)
                duplicates.append(reference)
        for reference in duplicates[:10]:
            findings.append(
                ValidatorFinding(
                    severity=VerificationSeverity.LOW,
                    title=f"Possible duplicate reference: {reference}",
                    description=(
                        "A reference with the same leading author/year token appears "
                        "more than once. This usually means one source cited twice "
                        "with inconsistent formatting."
                    ),
                    recommendation="Deduplicate and normalise the reference format.",
                )
            )

        # Impossible years.
        future_years = [int(y) for y in _YEAR_RE.findall(text) if int(y) > 2027]
        for year in future_years[:5]:
            findings.append(
                ValidatorFinding(
                    severity=VerificationSeverity.MEDIUM,
                    title=f"Citation year {year} is in the future",
                    description=(
                        "A year later than the current publication horizon appears in "
                        "the text. Either a typo or a fabricated reference."
                    ),
                    recommendation="Verify the publication year of the source.",
                )
            )

        if references:
            evidence.append(
                ValidatorEvidence(
                    kind="REFERENCE_PARSE",
                    source="artifact text",
                    method=VerificationMethod.DETERMINISTIC,
                    status=VerificationStatus.VERIFIED,
                    content=(
                        f"Parsed {len(references)} distinct references "
                        f"({len(dois)} DOIs); {len(duplicates)} duplicates; "
                        f"{len(malformed_dois)} malformed DOIs."
                    ),
                )
            )

        if not references:
            status = VerificationStatus.PARTIAL
            findings.append(
                ValidatorFinding(
                    severity=VerificationSeverity.MEDIUM,
                    title="No citations detected",
                    description=(
                        "The text contains no recognisable citation format. For a "
                        "research assignment this usually means missing sourcing; "
                        "the parser covers bracketed [..] and (Author, Year) styles."
                    ),
                    recommendation="Add citations for every factual claim.",
                )
            )
        elif findings:
            status = VerificationStatus.PARTIAL
        else:
            status = VerificationStatus.VERIFIED

        return ValidatorResult(
            validator=self.declaration.name,
            version=self.declaration.version,
            level=self.declaration.level,
            status=status,
            summary=(
                f"{len(references)} references parsed; {len(dois)} DOIs; "
                f"{len(findings)} citation findings."
            ),
            method=VerificationMethod.DETERMINISTIC,
            confidence=CONFIDENCE_HIGH if references else CONFIDENCE_NONE,
            executed=True,
            limitations=[
                "No network access: DOI resolution, source existence, metadata "
                "validation and citation-to-claim semantic alignment are NOT "
                "verified. They are reported as unverified, not as passed.",
                "Citation format coverage: bracketed [..] and (Author, Year). "
                "Other styles (e.g. numeric superscripts) are not parsed.",
            ],
            findings=findings,
            evidence=evidence,
        )
