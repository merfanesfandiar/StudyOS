"""Error vocabulary for the execution module.

Two kinds of error live here and they are deliberately different types.

``ExecutionError`` is an API-facing ``AppError``: it is raised inside a request and
becomes a JSON problem response. ``SandboxError`` is internal: a backend raises it
to describe *why the environment could not run the work*, and the orchestrator
turns it into a recorded attempt failure rather than a 5xx. A sandbox that is
unavailable is a bounded outcome ("this job could not run here"), not a bug in the
request, so it must not surface as an unhandled exception.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import AppError
from app.models.enums import ExecutionFailureClass


class ExecutionError(AppError):
    """Base class for API-facing execution errors."""


class ExecutionDisabledError(ExecutionError):
    """No sandbox backend is configured, so the request cannot be served."""

    def __init__(self) -> None:
        super().__init__(
            503,
            "EXECUTION_DISABLED",
            "Code execution is not enabled in this deployment.",
        )


class ExecutionRejectedError(ExecutionError):
    """The request failed validation or policy and was refused before running."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__(
            422,
            "EXECUTION_REQUEST_REJECTED",
            "The execution request is not permitted.",
            {"reasons": reasons},
        )


class ExecutionNotFoundError(ExecutionError):
    def __init__(self, job_id: object) -> None:
        super().__init__(404, "EXECUTION_NOT_FOUND", f"Execution job {job_id} was not found.")


class ExecutionQuotaExceededError(ExecutionError):
    """The caller is within policy but has hit a usage ceiling.

    Surfaced as a 429: the request is well-formed and permitted, it is simply too
    early to make another. The details name the scope and the limit so a client can
    explain *which* quota and back off rather than retry blindly.
    """

    def __init__(self, scope: str, limit: int) -> None:
        messages = {
            "workspace_active_jobs": (
                "This workspace has reached its limit of active executions. "
                "Wait for one to finish before starting another."
            ),
            "user_daily_jobs": (
                "You have reached the daily limit for executions. Try again tomorrow."
            ),
        }
        super().__init__(
            429,
            "EXECUTION_QUOTA_EXCEEDED",
            messages.get(scope, "An execution quota has been reached."),
            {"scope": scope, "limit": limit},
        )


class ExecutionConflictError(ExecutionError):
    """The job is in a state that forbids the requested operation."""

    def __init__(self, message: str) -> None:
        super().__init__(409, "EXECUTION_CONFLICT", message)


@dataclass(slots=True)
class SandboxError(Exception):
    """A backend could not run the work in its environment.

    Carries a failure class so the orchestrator can classify the attempt without
    guessing, and an operator-readable message that is stored on the attempt.
    Never carries user source code or host paths.
    """

    failure_class: ExecutionFailureClass
    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message
