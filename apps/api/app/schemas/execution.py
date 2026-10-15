"""Phase 7 DTOs: the secure execution environment.

Two conventions matter here. First, a request carries *text source and a runtime
name*, never a host command, an image or a path outside the workspace — the
schema itself is part of the boundary, because a field that does not exist cannot
be set. Second, responses expose outcomes and metadata, never a sandbox id that a
client could use, and never raw environment internals.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.models.enums import (
    ExecutionArtifactKind,
    ExecutionAttemptStatus,
    ExecutionBackendKind,
    ExecutionCleanupStatus,
    ExecutionEventType,
    ExecutionFailureClass,
    ExecutionJobStatus,
    ExecutionResourceProfile,
    ExecutionType,
)
from app.schemas.common import APIModel

# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class ExecutionCreateRequest(APIModel):
    """Submit one execution for an assignment the caller owns."""

    model_config = APIModel.model_config | {"extra": "forbid"}

    execution_type: ExecutionType
    #: Relative path of the file to run. Defaults to the runtime's conventional
    #: entrypoint when omitted.
    entrypoint: str | None = Field(default=None, max_length=255)
    #: Source files keyed by workspace-relative path. Text only.
    files: dict[str, str] = Field(default_factory=dict)
    #: Runtime options. Only keys allowed for the execution type are accepted.
    options: dict[str, Any] = Field(default_factory=dict)
    #: Optional standard input.
    stdin: str | None = Field(default=None, max_length=65_536)
    #: Resource profile. Omitted means the runtime's default for its type.
    resource_profile: ExecutionResourceProfile | None = None
    #: A shorter wall-clock limit than the profile allows. A longer one is clamped.
    timeout_seconds: int | None = Field(default=None, ge=1, le=3600)
    #: ``sync`` runs the job inside this request; ``queue`` hands it to a worker.
    mode: Literal["sync", "queue"] = "sync"
    #: Deduplication key. Two requests with the same key return one job.
    idempotency_key: str | None = Field(default=None, max_length=64)


class ExecutionCancelRequest(APIModel):
    model_config = APIModel.model_config | {"extra": "forbid"}

    reason: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class ExecutionAttemptResponse(APIModel):
    id: UUID
    attempt: int
    status: ExecutionAttemptStatus
    backend: str | None
    exit_code: int | None
    failure_class: ExecutionFailureClass | None
    error_code: str | None
    error_message: str | None
    duration_ms: int | None
    stdout_excerpt: str | None
    stderr_excerpt: str | None
    started_at: datetime
    completed_at: datetime | None


class ExecutionArtifactResponse(APIModel):
    id: UUID
    filename: str
    size_bytes: int
    mime_type: str | None
    kind: ExecutionArtifactKind
    created_at: datetime


class ExecutionEventResponse(APIModel):
    id: UUID
    sequence: int
    event_type: ExecutionEventType
    summary: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ExecutionJobResponse(APIModel):
    id: UUID
    workspace_id: UUID
    assignment_id: UUID | None
    agent_run_id: UUID | None
    task_id: UUID | None
    execution_type: ExecutionType
    backend: ExecutionBackendKind | None
    status: ExecutionJobStatus
    resource_profile: ExecutionResourceProfile
    entrypoint: str | None
    attempt_count: int
    max_attempts: int
    exit_code: int | None
    duration_ms: int | None
    failure_class: ExecutionFailureClass | None
    error_code: str | None
    error_message: str | None
    result_excerpt: str | None
    cleanup_status: ExecutionCleanupStatus
    created_at: datetime
    queued_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    cancelled_at: datetime | None


class ExecutionJobDetailResponse(APIModel):
    job: ExecutionJobResponse
    attempts: list[ExecutionAttemptResponse]
    artifacts: list[ExecutionArtifactResponse]
    events: list[ExecutionEventResponse]


class ExternalAgentCapability(APIModel):
    """Whether a delegation target is configured, and why not when it is not.

    Reported rather than omitted, exactly like the sandbox backend: the UI can then
    say "not configured" instead of offering an action that would fail.
    """

    kind: str
    available: bool
    reason: str | None = None


class ExecutionCapabilitiesResponse(APIModel):
    """What this deployment can run, and the boundary it runs it behind."""

    enabled: bool
    backend: ExecutionBackendKind
    available: bool
    execution_types: list[ExecutionType]
    resource_profiles: dict[str, dict[str, int | float]]
    default_profile: dict[str, ExecutionResourceProfile]
    limits: dict[str, Any]
    external_agent: ExternalAgentCapability
    absent_capabilities: list[str]
