"""The default backend: it refuses.

This exists so that "no sandbox configured" is a *working* state rather than an
error condition. A deployment with execution enabled but no backend selected
serves every request with an ``EXECUTION_REJECTED`` outcome and a reason, which is
the correct fail-closed behaviour: the alternative — falling back to running on the
host — is the exact failure mode the whole phase exists to prevent.
"""

from __future__ import annotations

from app.models.enums import (
    ExecutionAttemptStatus,
    ExecutionBackendKind,
    ExecutionFailureClass,
)
from app.modules.execution.backends.base import SandboxResult, SandboxSpec


class DisabledSandboxBackend:
    """Rejects every job with a bounded, recorded outcome."""

    kind = ExecutionBackendKind.DISABLED

    @property
    def available(self) -> bool:
        return False

    def run(self, spec: SandboxSpec) -> SandboxResult:
        return SandboxResult(
            status=ExecutionAttemptStatus.REJECTED,
            failure_class=ExecutionFailureClass.POLICY_REJECTED,
            error_code="EXECUTION_DISABLED",
            error_message="No sandbox backend is configured; the job was not run.",
        )

    def reap(self, sandbox_id: str) -> bool:
        # A disabled backend never created a sandbox, so there is nothing to reap
        # and reporting success is honest rather than optimistic.
        return True
