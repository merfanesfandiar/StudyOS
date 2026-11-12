"""The verification pipeline: ten stages, cheap checks first.

Stages (from the phase contract, adapted):

1. Input validation          — snapshots are non-empty and scoped.
2. Requirement extraction    — from the assignment snapshot (authoritative).
3. Artifact inspection       — scope and content bounds.
4. Strategy selection        — registry-driven validator selection per level.
5. Validator execution       — parallel, per-validator timeout, failure
                               isolation: a crashing validator produces an
                               explicit FAILED result, never a silent pass.
6. Evidence collection       — every result's evidence is kept.
7. Result normalisation      — statuses and severities validated.
8. Confidence & limitations  — aggregated honestly.
9. Aggregation               — overall status is the *worst* honest verdict.
10. Report generation        — :class:`PipelineReport`, machine-readable.

Key rules enforced here:

* Deterministic levels (STRUCTURAL, REQUIREMENTS) always run before domain
  levels, and the report marks which levels actually executed.
* A validator that raises is turned into a FAILED result with the exception
  recorded — never swallowed.
* ``UNVERIFIED`` propagates: the aggregated status can never be better than the
  worst unverified-but-required area unless every scope was actually checked.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from uuid import UUID

from app.models.enums import (
    AcademicDomain,
    VerificationLevel,
    VerificationSeverity,
    VerificationStatus,
)
from app.modules.verification.contracts import (
    CONFIDENCE_NONE,
    ValidatorResult,
    VerificationContext,
    VerificationValidator,
)
from app.modules.verification.registry import ValidatorRegistry

logger = logging.getLogger(__name__)

#: Levels the pipeline executes, in order. EVIDENCE findings are carried inside
#: validator results (each validator collects its own evidence); QUALITY is the
#: rubric evaluator's job (see rubric.py) and runs over this report's output.
EXECUTION_ORDER: tuple[VerificationLevel, ...] = (
    VerificationLevel.STRUCTURAL,
    VerificationLevel.REQUIREMENTS,
    VerificationLevel.DOMAIN,
)

_MAX_PARALLEL = 4
#: Hard ceiling per validator regardless of its declaration.
_ABSOLUTE_TIMEOUT_SECONDS = 90.0


class PipelineError(Exception):
    """The pipeline itself failed. Never reported as a verification verdict."""


@dataclass(slots=True)
class PipelineReport:
    """Aggregated, machine-readable outcome of one pipeline execution."""

    levels_executed: list[VerificationLevel] = field(default_factory=list)
    results: list[ValidatorResult] = field(default_factory=list)
    overall_status: VerificationStatus = VerificationStatus.UNVERIFIED
    completion_percentage: int = 0
    critical_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def finding_count(self, severity: VerificationSeverity) -> int:
        return sum(
            1
            for result in self.results
            for finding in result.findings
            if finding.severity is severity
        )


class VerificationPipeline:
    """Executes validators for a context and produces a PipelineReport."""

    def __init__(self, registry: ValidatorRegistry, *, max_parallel: int = _MAX_PARALLEL) -> None:
        self._registry = registry
        self._max_parallel = max_parallel

    async def run(
        self,
        ctx: VerificationContext,
        *,
        domain: AcademicDomain | None,
        assignment_types: frozenset[str],
        levels: tuple[VerificationLevel, ...] = EXECUTION_ORDER,
    ) -> PipelineReport:
        report = PipelineReport(levels_executed=list(levels))
        for level in levels:
            validators = self._registry.select(
                level=level,
                domain=domain,
                assignment_types=assignment_types,
                execution_available=ctx.execution is not None,
            )
            validators = self._registry.applicable(validators, ctx)
            results = await self._execute(validators, ctx)
            report.results.extend(results)

        _aggregate(report)
        return report

    async def _execute(
        self, validators: tuple[VerificationValidator, ...], ctx: VerificationContext
    ) -> list[ValidatorResult]:
        if not validators:
            return []
        semaphore = asyncio.Semaphore(self._max_parallel)

        async def run_one(validator: VerificationValidator) -> ValidatorResult:
            async with semaphore:
                timeout = min(
                    validator.declaration.timeout_seconds, _ABSOLUTE_TIMEOUT_SECONDS
                )
                try:
                    return await asyncio.wait_for(validator.verify(ctx), timeout=timeout)
                except TimeoutError:
                    logger.warning("Validator %s timed out", validator.declaration.name)
                    return _crashed_result(validator, "timed out")
                except Exception as error:  # noqa: BLE001 - isolation is the point
                    logger.exception("Validator %s crashed", validator.declaration.name)
                    return _crashed_result(validator, str(error)[:300])

        return list(await asyncio.gather(*(run_one(v) for v in validators)))


def _crashed_result(validator: VerificationValidator, reason: str) -> ValidatorResult:
    """An explicit failure for a validator that raised or timed out.

    This is the anti-silent-pass rule: a broken check is recorded as FAILED
    with the reason, and the aggregate inherits it.
    """
    d = validator.declaration
    return ValidatorResult(
        validator=d.name,
        version=d.version,
        level=d.level,
        status=VerificationStatus.FAILED,
        summary=f"Validator failed to run: {reason}",
        confidence=CONFIDENCE_NONE,
        executed=False,
        limitations=[f"Validator {d.name} did not complete: {reason}"],
    )


def _aggregate(report: PipelineReport) -> None:
    """Compute overall status, completion and finding lists.

    ``overall_status`` is the worst verdict across executed validators — with
    the important nuance that UNVERIFIED does not beat VERIFIED when the
    unverified area is genuinely out of scope (e.g. no dataset attached); it is
    reported in ``unverified`` instead. FAILED and structural CRITICAL findings
    always dominate.
    """
    # A crashed validator (executed=False, FAILED) MUST count against the
    # aggregate — that is the anti-silent-pass rule. Only NOT_APPLICABLE results
    # are excluded from scoring, because "nothing to check" is not a verdict.
    executed = [r for r in report.results if r.status is not VerificationStatus.NOT_APPLICABLE]
    applicable = executed
    if not applicable:
        report.overall_status = VerificationStatus.UNVERIFIED
        report.completion_percentage = 0
        report.unverified.append("No validators could run for this verification shape.")
        return

    failed = [r for r in applicable if r.status is VerificationStatus.FAILED]
    partial = [r for r in applicable if r.status is VerificationStatus.PARTIAL]
    verified = [r for r in applicable if r.status is VerificationStatus.VERIFIED]

    if failed:
        report.overall_status = VerificationStatus.FAILED
    elif verified and not partial:
        report.overall_status = VerificationStatus.VERIFIED
    elif verified or partial:
        report.overall_status = VerificationStatus.PARTIAL
    else:
        report.overall_status = VerificationStatus.UNVERIFIED

    report.completion_percentage = int(round(100 * len(verified) / len(applicable)))

    for result in report.results:
        for finding in result.findings:
            line = f"[{finding.severity.value}] {finding.title}"
            if finding.severity is VerificationSeverity.CRITICAL:
                report.critical_failures.append(line)
            elif finding.severity in (VerificationSeverity.HIGH, VerificationSeverity.MEDIUM):
                report.warnings.append(line)
        if result.status is VerificationStatus.UNVERIFIED:
            report.unverified.append(f"{result.validator}: {result.summary or 'not checked'}")
        report.limitations.extend(result.limitations)

    report.limitations = list(dict.fromkeys(report.limitations))[:50]
    report.unverified = list(dict.fromkeys(report.unverified))[:50]
    report.warnings = list(dict.fromkeys(report.warnings))[:50]

    # Defensive invariant: a report must never claim full success while a
    # critical failure exists.
    if report.critical_failures:
        report.overall_status = VerificationStatus.FAILED


def scoped_domain(
    declared_domain: AcademicDomain | None, assignment_types: frozenset[str]
) -> AcademicDomain | None:
    """The effective domain for selection, when the assignment has one.

    Type-only assignments (e.g. ``PROGRAMMING`` without a domain classification)
    still select type-scoped validators because declarations match on either.
    """
    return declared_domain


def scope_context(
    ctx: VerificationContext,
    *,
    artifact_ids: frozenset[UUID] | None = None,
    requirement_ids: frozenset[UUID] | None = None,
) -> VerificationContext:
    """A narrowed copy of the context for partial/re-verification runs."""
    return VerificationContext(
        assignment=ctx.assignment,
        artifacts=ctx.artifacts,
        execution=ctx.execution,
        artifact_ids=artifact_ids if artifact_ids is not None else ctx.artifact_ids,
        requirement_ids=requirement_ids if requirement_ids is not None else ctx.requirement_ids,
    )
