"""The validator registry: declaration-driven selection, no hardcoded dispatch.

Validators register themselves here with a :class:`ValidatorDeclaration`. The
pipeline asks the registry which validators apply to a given verification level,
academic domain, assignment types and artifact types — selection is data, not a
chain of ``if domain == ...`` statements.

To add a validator (full guide in ``docs/architecture/verification.md``):

1. Subclass :class:`~app.modules.verification.contracts.VerificationValidator`
   with an honest declaration.
2. Append an instance to ``app.modules.validation.validators.REGISTERED`` (see
   ``validators/__init__.py``).
3. Add tests. Nothing else — no pipeline change, no UI change, no migration.
"""

from __future__ import annotations

from app.models.enums import AcademicDomain, VerificationLevel
from app.modules.verification.contracts import (
    VerificationContext,
    VerificationValidator,
)


class ValidatorRegistry:
    """A closed, explicit set of validators.

    Deliberately mirrors :class:`~app.modules.agent.tools.ToolRegistry`: there
    is no dynamic plugin loading, no remote registration and no silent override.
    Re-registering the same name raises, so two validators can never collide
    invisibly.
    """

    def __init__(self, validators: tuple[VerificationValidator, ...] = ()) -> None:
        self._validators: dict[str, VerificationValidator] = {}
        for validator in validators:
            self.register(validator)

    def register(self, validator: VerificationValidator) -> None:
        name = validator.declaration.name
        if name in self._validators:
            raise ValueError(f"Validator {name!r} is already registered")
        self._validators[name] = validator

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._validators))

    def get(self, name: str) -> VerificationValidator:
        validator = self._validators.get(name)
        if validator is None:
            raise KeyError(f"Validator {name!r} is not registered")
        return validator

    def all_validators(self) -> tuple[VerificationValidator, ...]:
        return tuple(self._validators[name] for name in sorted(self._validators))

    def select(
        self,
        *,
        level: VerificationLevel,
        domain: AcademicDomain | None = None,
        assignment_types: frozenset[str] | None = None,
        artifact_types: frozenset[str] | None = None,
        execution_available: bool = False,
    ) -> tuple[VerificationValidator, ...]:
        """The validators whose declaration matches this verification shape.

        A validator declared with ``requires_execution=True`` is selected only
        when the sandbox gateway is actually available — and if it still runs
        into a missing gateway it must answer ``UNVERIFIED`` with a limitation,
        never a pass.
        """
        types = assignment_types or frozenset()
        selected: list[tuple[int, str, VerificationValidator]] = []
        for validator in self._validators.values():
            d = validator.declaration
            if d.level is not level:
                continue
            # A declared domain list is an inclusion filter for that validator:
            # it runs when the assignment's domain is inside its set. When no
            # domain is known, domain-scoped validators still run — their
            # assignment-type filter governs, and "domain unknown" must not
            # silently disable domain checking.
            if d.domains is not None and domain is not None and domain not in d.domains:
                continue
            if d.assignment_types is not None and not (types & d.assignment_types):
                continue
            if d.requires_execution and not execution_available:
                continue
            selected.append((d.version, d.name, validator))
        selected.sort(key=lambda item: (item[0], item[1]))
        return tuple(v for _, _, v in selected)

    def applicable(
        self, validators: tuple[VerificationValidator, ...], ctx: VerificationContext
    ) -> tuple[VerificationValidator, ...]:
        """Second-stage filter: per-request applicability (scope, content)."""
        return tuple(v for v in validators if v.applies_to(ctx))
