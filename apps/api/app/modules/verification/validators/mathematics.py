"""Domain validator: mathematics and proofs.

What this validator genuinely does (deterministic, no AI):

* Re-verifies arithmetic: every claim of the form ``<numeric expression> = <number>``
  is recomputed with a safe expression evaluator and compared. A wrong numeric
  equality is a CRITICAL finding backed by the recomputation as evidence.
* Tracks stated assumptions and definitions so a proof's premises are visible.

What it deliberately does NOT do (recorded as limitations, never claimed):

* Symbolic algebra, inequality chains, inference-step checking and formal proof
  verification are out of scope without a computer algebra system / proof
  assistant, which this deployment does not bundle. Claims that cannot be
  checked numerically are reported UNVERIFIED — never "reviewed and correct".
"""

from __future__ import annotations

import ast
import operator as op
import re
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
    CONFIDENCE_MODERATE,
    CONFIDENCE_NONE,
    ValidatorDeclaration,
    ValidatorEvidence,
    ValidatorFinding,
    ValidatorResult,
    VerificationContext,
    VerificationValidator,
)

_ASSIGNMENT_RE = re.compile(r"^([^=\n]{1,80}?)\s*=\s*([^=\n]{1,80})$", re.MULTILINE)
_ALLOWED_UNARY: dict[type[ast.unaryop], Any] = {ast.USub: op.neg, ast.UAdd: op.pos}
_ALLOWED_BINOPS: dict[type[ast.operator], Any] = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.Mod: op.mod,
    ast.FloorDiv: op.floordiv,
}
_ASSUMPTION_RE = re.compile(
    r"^\s*(?:assume|given|let|suppose|by definition|where)\b", re.IGNORECASE
)
_MAX_CHECKED = 60


class MathematicsValidator(VerificationValidator):
    """L3: deterministic arithmetic re-verification and assumption tracking."""

    declaration: ClassVar[ValidatorDeclaration] = ValidatorDeclaration(
        name="mathematics",
        level=VerificationLevel.DOMAIN,
        domains=frozenset({AcademicDomain.MATHEMATICS}),
        assignment_types=frozenset({"MATHEMATICAL_PROOF", "PROBLEM_SET", "DATA_ANALYSIS"}),
        artifact_types=frozenset(
            {"CALCULATION", "PROOF_DRAFT", "SOLUTION", "MARKDOWN", "TEXT", "REPORT"}
        ),
        description=(
            "Recomputes numeric equalities claimed in the artifacts and lists "
            "stated assumptions. Symbolic reasoning is NOT verified; such claims "
            "are reported as unverified with an explicit limitation."
        ),
        timeout_seconds=15.0,
    )

    def applies_to(self, ctx: VerificationContext) -> bool:
        return bool(ctx.scoped_artifacts())

    async def verify(self, ctx: VerificationContext) -> ValidatorResult:
        artifacts = ctx.scoped_artifacts()
        text = "\n".join(a.content for a in artifacts)
        if not text.strip():
            return ValidatorResult(
                validator=self.declaration.name,
                version=self.declaration.version,
                level=self.declaration.level,
                status=VerificationStatus.NOT_APPLICABLE,
                summary="No artifact content to check.",
                confidence=CONFIDENCE_NONE,
                executed=True,
                limitations=["No content."],
            )

        findings: list[ValidatorFinding] = []
        evidence: list[ValidatorEvidence] = []
        checked = 0
        wrong = 0
        unparsable = 0
        symbolic = 0
        checked_claims: list[str] = []

        for match in _ASSIGNMENT_RE.finditer(text):
            if checked >= _MAX_CHECKED:
                break
            lhs_raw, rhs_raw = match.group(1).strip(), match.group(2).strip()
            if not _is_pure_arithmetic(lhs_raw) or not _is_number(rhs_raw):
                symbolic += 1
                continue
            checked += 1
            try:
                computed = _safe_eval(lhs_raw)
            except (ArithmeticError, ValueError, SyntaxError):
                unparsable += 1
                continue
            claimed = float(rhs_raw)
            if abs(computed - claimed) <= 1e-6 * max(1.0, abs(computed)):
                checked_claims.append(f"{lhs_raw} = {claimed} (correct)")
            else:
                wrong += 1
                checked_claims.append(f"{lhs_raw} = {claimed} (WRONG: recomputed {computed})")
                findings.append(
                    ValidatorFinding(
                        severity=VerificationSeverity.CRITICAL,
                        title=f"Incorrect arithmetic: {lhs_raw} = {claimed}",
                        description=(
                            f"The artifact claims {lhs_raw} = {claimed}, but direct "
                            f"computation gives {computed}. This was recomputed "
                            "independently by the verification engine, not judged by "
                            "an AI reading the text."
                        ),
                        recommendation=f"Correct the computation to {computed}.",
                    )
                )

        assumptions = [
            line.strip() for line in text.splitlines() if _ASSUMPTION_RE.match(line)
        ][:20]

        numeric_present = checked > 0
        if wrong:
            status = VerificationStatus.FAILED
        elif numeric_present:
            status = VerificationStatus.VERIFIED
        else:
            status = VerificationStatus.UNVERIFIED

        if numeric_present:
            evidence.append(
                ValidatorEvidence(
                    kind="ARITHMETIC_RECOMPUTATION",
                    source=f"{checked} numeric claims in artifacts",
                    method=VerificationMethod.DETERMINISTIC,
                    status=VerificationStatus.FAILED if wrong else VerificationStatus.VERIFIED,
                    content="\n".join(checked_claims)[:4000],
                )
            )

        limitations = [
            "Only plain-numeric equalities are recomputed. Symbolic algebra, "
            "limits, inequalities and inference steps are NOT verified by this "
            "engine and would require a computer algebra system or proof assistant.",
        ]
        if unparsable:
            limitations.append(f"{unparsable} numeric expressions could not be parsed safely.")
        if not numeric_present:
            limitations.append("No checkable numeric equalities were found in the artifacts.")
        if symbolic:
            limitations.append(
                f"{symbolic} equality-looking lines were skipped as non-numeric/symbolic."
            )

        return ValidatorResult(
            validator=self.declaration.name,
            version=self.declaration.version,
            level=self.declaration.level,
            status=status,
            summary=(
                f"Recomputed {checked} arithmetic claims: {wrong} wrong; "
                f"{len(assumptions)} assumptions recorded."
                if numeric_present
                else "No numeric claims found to recompute; proof content is unverified."
            ),
            method=VerificationMethod.DETERMINISTIC,
            confidence=CONFIDENCE_HIGH if numeric_present else CONFIDENCE_MODERATE,
            executed=True,
            limitations=limitations,
            findings=findings,
            evidence=evidence,
        )


def _safe_eval(expression: str) -> float:
    """Evaluate an arithmetic expression composed of numbers and operators only.

    Mirrors the runtime calculator's allowlist: parsing accepts only numeric
    literals, the four basic operations with power/mod, and parentheses. Any
    name, call or attribute node raises, so artifact text can never execute
    anything.
    """
    tree = ast.parse(expression, mode="eval")

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return float(node.value)
            raise ValueError("non-numeric literal")
        if isinstance(node, ast.BinOp):
            handler = _ALLOWED_BINOPS.get(type(node.op))
            if handler is None:
                raise ValueError("operator not allowed")
            return float(handler(visit(node.left), visit(node.right)))
        if isinstance(node, ast.UnaryOp):
            handler = _ALLOWED_UNARY.get(type(node.op))
            if handler is None:
                raise ValueError("unary operator not allowed")
            return float(handler(visit(node.operand)))
        raise ValueError("expression element not allowed")

    return visit(tree)


def _is_pure_arithmetic(expression: str) -> bool:
    cleaned = expression.strip().rstrip("=").strip()
    return bool(re.fullmatch(r"[\d\s+\-*/().%^]+", cleaned)) and any(c.isdigit() for c in cleaned)


def _is_number(text: str) -> bool:
    try:
        float(text.strip().rstrip("."))
    except ValueError:
        return False
    return True
