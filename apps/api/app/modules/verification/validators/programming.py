"""Domain validators: computer science / programming.

Two validators:

* ``python_syntax`` — deterministic ``ast`` parse of CODE artifacts. No code is
  ever executed here; parsing is done in-process on bounded text, which is safe
  (the ``ast`` module evaluates nothing).
* ``programming_execution`` — Level 3 execution testing *only* through the
  Phase 7 sandbox gateway. If the gateway is absent the result is ``UNVERIFIED``
  with a limitation; this validator never falls back to running code on the
  host, and never claims tests passed without executing them.
"""

from __future__ import annotations

import ast
from typing import Any, ClassVar

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

_MAX_PARSE_CHARS = 100_000


class PythonSyntaxValidator(VerificationValidator):
    """L3: deterministic syntax validation of CODE artifacts."""

    declaration: ClassVar[ValidatorDeclaration] = ValidatorDeclaration(
        name="python_syntax",
        level=VerificationLevel.DOMAIN,
        domains=frozenset({AcademicDomain.COMPUTER_SCIENCE}),
        assignment_types=frozenset({"PROGRAMMING"}),
        artifact_types=frozenset({"CODE", "GENERATED_FILE"}),
        description=(
            "Parses CODE artifacts with Python's ast module and reports syntax "
            "errors with line numbers. Pure parsing; nothing is executed."
        ),
        timeout_seconds=10.0,
    )

    async def verify(self, ctx: VerificationContext) -> ValidatorResult:
        code_artifacts = [
            a for a in ctx.scoped_artifacts() if a.artifact_type in ("CODE", "GENERATED_FILE")
        ]
        python_like = [a for a in code_artifacts if _looks_like_python(a)]
        if not python_like:
            return ValidatorResult(
                validator=self.declaration.name,
                version=self.declaration.version,
                level=self.declaration.level,
                status=VerificationStatus.NOT_APPLICABLE,
                summary="No CODE artifacts to parse.",
                confidence=CONFIDENCE_NONE,
                executed=True,
                limitations=["Only Python sources are parsed by this validator."],
            )

        findings: list[ValidatorFinding] = []
        evidence: list[ValidatorEvidence] = []
        parsed_ok = 0
        for artifact in python_like:
            source = artifact.content[:_MAX_PARSE_CHARS]
            if len(artifact.content) > _MAX_PARSE_CHARS:
                findings.append(
                    ValidatorFinding(
                        severity=VerificationSeverity.INFORMATIONAL,
                        title=f"'{artifact.title}' truncated for parsing",
                        description=(
                            "Only the first 100,000 characters were syntax-checked; "
                            "the rest is a recorded limitation."
                        ),
                        artifact_ids=[artifact.id],
                    )
                )
            try:
                ast.parse(source)
            except SyntaxError as error:
                line = error.lineno or 0
                findings.append(
                    ValidatorFinding(
                        severity=VerificationSeverity.HIGH,
                        title=f"Syntax error in '{artifact.title}' (line {line})",
                        description=(
                            f"Python parsing failed: {error.msg or 'syntax error'}. "
                            "The artifact cannot be executed or graded until this is fixed."
                        ),
                        artifact_ids=[artifact.id],
                        recommendation=f"Fix the syntax error at line {line}.",
                    )
                )
            else:
                parsed_ok += 1
                evidence.append(
                    ValidatorEvidence(
                        kind="SYNTAX_PARSE",
                        source=f"artifact {artifact.title}",
                        method=VerificationMethod.DETERMINISTIC,
                        status=VerificationStatus.VERIFIED,
                        content=f"ast.parse succeeded for '{artifact.title}'.",
                        artifact_ids=[artifact.id],
                    )
                )

        failed = len(python_like) - parsed_ok
        if failed:
            status = VerificationStatus.FAILED
        elif len(python_like) < len(code_artifacts):
            status = VerificationStatus.PARTIAL
            findings.append(
                ValidatorFinding(
                    severity=VerificationSeverity.LOW,
                    title="Some CODE artifacts do not look like Python",
                    description=(
                        "Syntax parsing covers Python sources only; other languages "
                        "need a language-specific validator."
                    ),
                )
            )
        else:
            status = VerificationStatus.VERIFIED
        return ValidatorResult(
            validator=self.declaration.name,
            version=self.declaration.version,
            level=self.declaration.level,
            status=status,
            summary=f"{parsed_ok}/{len(python_like)} Python artifacts parsed cleanly.",
            method=VerificationMethod.DETERMINISTIC,
            confidence=CONFIDENCE_HIGH,
            executed=True,
            limitations=[
                "Syntax only — no execution, no type checking, no test running.",
                "Non-Python sources are not validated.",
            ],
            findings=findings,
            evidence=evidence,
        )


class ProgrammingExecutionValidator(VerificationValidator):
    """L3: execute assignment-provided tests inside the existing sandbox."""

    declaration: ClassVar[ValidatorDeclaration] = ValidatorDeclaration(
        name="programming_execution",
        level=VerificationLevel.DOMAIN,
        domains=frozenset({AcademicDomain.COMPUTER_SCIENCE}),
        assignment_types=frozenset({"PROGRAMMING"}),
        artifact_types=frozenset({"CODE", "GENERATED_FILE"}),
        requires_execution=True,
        requires_external=True,
        description=(
            "Runs the code artifact inside the Phase 7 sandbox gateway and "
            "reports the real exit status and output. Never executes on the "
            "host and never reports unexecuted tests as passing."
        ),
        timeout_seconds=60.0,
    )

    async def verify(self, ctx: VerificationContext) -> ValidatorResult:
        gateway = ctx.execution
        if gateway is None:
            return ValidatorResult(
                validator=self.declaration.name,
                version=self.declaration.version,
                level=self.declaration.level,
                status=VerificationStatus.UNVERIFIED,
                summary="Execution sandbox is not enabled for this deployment.",
                confidence=CONFIDENCE_NONE,
                executed=False,
                limitations=[
                    "The sandbox execution gateway is unavailable, so behavior "
                    "could not be verified by running anything. This check "
                    "reports UNVERIFIED rather than assuming success."
                ],
            )
        code_artifacts = [
            a for a in ctx.scoped_artifacts() if a.artifact_type in ("CODE", "GENERATED_FILE")
        ]
        if not code_artifacts:
            return ValidatorResult(
                validator=self.declaration.name,
                version=self.declaration.version,
                level=self.declaration.level,
                status=VerificationStatus.NOT_APPLICABLE,
                summary="No CODE artifacts to execute.",
                confidence=CONFIDENCE_NONE,
                executed=True,
                limitations=["Nothing executable was produced."],
            )

        findings: list[ValidatorFinding] = []
        evidence: list[ValidatorEvidence] = []
        failures = 0
        for artifact in code_artifacts[:5]:
            outcome = await _run(gateway, artifact.content)
            payload = outcome.as_payload() if hasattr(outcome, "as_payload") else dict(outcome)
            succeeded = getattr(outcome, "succeeded", bool(payload.get("succeeded")))
            evidence.append(
                ValidatorEvidence(
                    kind="SANDBOX_EXECUTION",
                    source=f"artifact {artifact.title}",
                    method=VerificationMethod.TOOL_ASSISTED,
                    status=VerificationStatus.VERIFIED if succeeded else VerificationStatus.FAILED,
                    content=str(payload.get("stdout", ""))[:2000],
                    artifact_ids=[artifact.id],
                )
            )
            if not succeeded:
                failures += 1
                findings.append(
                    ValidatorFinding(
                        severity=VerificationSeverity.HIGH,
                        title=f"Execution failed for '{artifact.title}'",
                        description=(
                            "The sandboxed execution did not succeed. The recorded "
                            "output is the sandbox's own result, not an inference."
                        ),
                        artifact_ids=[artifact.id],
                        recommendation="Reproduce the run in the sandbox and fix the failure.",
                    )
                )
        status = VerificationStatus.FAILED if failures else VerificationStatus.VERIFIED
        return ValidatorResult(
            validator=self.declaration.name,
            version=self.declaration.version,
            level=self.declaration.level,
            status=status,
            summary=(
                f"Executed {len(code_artifacts[:5])} artifacts in the sandbox; "
                f"{failures} failed."
            ),
            method=VerificationMethod.TOOL_ASSISTED,
            confidence=CONFIDENCE_HIGH if status is not VerificationStatus.UNVERIFIED else CONFIDENCE_NONE,  # noqa: E501
            executed=True,
            limitations=[
                "Runs each artifact standalone; cross-file projects and "
                "assignment-provided hidden test suites are future work and are "
                "not claimed here."
            ],
            findings=findings,
            evidence=evidence,
        )


def _looks_like_python(artifact: Any) -> bool:
    content = artifact.content.lstrip()
    if not content:
        return False
    if content.startswith(("def ", "class ", "import ", "from ", "print(", "#!")):
        return True
    try:
        ast.parse(content[:2000])
    except (SyntaxError, ValueError):
        return False
    return "def " in content or "=" in content


async def _run(gateway: Any, content: str) -> Any:
    """Submit one bounded job to the sandbox gateway."""
    return await gateway.run(
        execution_type="python",
        code=content[:20000],
        timeout_seconds=30,
    )
