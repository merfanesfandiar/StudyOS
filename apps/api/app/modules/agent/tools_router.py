"""The public tool catalogue.

These endpoints are read-only and describe the runtime's tools rather than
running them. That split is deliberate: the catalogue is static code, so it can
be served without an assignment, a plan or a run, and it cannot be used to
*push* the runtime toward a capability. Everything here is derived from
:data:`~app.modules.agent.tools.DEFAULT_TOOLS` and the worker registry, so the
API and the code cannot disagree about what exists.

A tool the runtime deliberately does not have (a shell, a network client) has no
row here at all. The absence is the answer.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.errors import AppError
from app.db.session import get_db
from app.models import User
from app.modules.agent import service
from app.modules.agent.tools import DEFAULT_TOOLS
from app.modules.agent.workers import DEFAULT_WORKER_REGISTRY
from app.schemas.agent import (
    AgentToolCatalogueResponse,
    AgentToolDetailResponse,
    AgentToolInvocationResponse,
    AgentToolUsageResponse,
)

CurrentUser = Annotated[User, Depends(get_current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])

#: The documented run-scoped shape, ``/api/v1/agent/runs/{runId}/...``. It is the
#: same read model as the assignment-scoped endpoints on the agent router, offered
#: where a client holds a run id and not an assignment id. Ownership is checked
#: through the run's assignment either way.
run_router = APIRouter(prefix="/api/v1/agent/runs", tags=["agent"])


def _workers_for(tool_name: str) -> list[str]:
    """Worker ids that may call this tool, newest-safe ordering by worker id."""
    return sorted(
        worker.kind.value
        for worker in DEFAULT_WORKER_REGISTRY.all()
        if tool_name in worker.tool_ids
    )


def _tool_detail(tool_id: str) -> dict[str, Any]:
    schema = DEFAULT_TOOLS.schema(tool_id)
    return {**schema, "workers": _workers_for(tool_id)}


@router.get(
    "",
    response_model=AgentToolCatalogueResponse,
    summary="The complete, closed set of agent tools",
    description=(
        "Every tool the runtime has, with its category, permissions, risk level "
        "and argument schema.\n\n"
        "The list is closed: there is no registration endpoint and no setting "
        "that adds a tool. A capability the runtime deliberately lacks — a shell, "
        "a socket, a filesystem — is absent here rather than disabled."
    ),
)
async def list_tools(user: CurrentUser) -> AgentToolCatalogueResponse:
    return AgentToolCatalogueResponse(
        tools=[_tool_detail(name) for name in DEFAULT_TOOLS.names()]
    )


@router.get(
    "/{tool_id}",
    response_model=AgentToolDetailResponse,
    summary="One tool in full",
    description="The metadata and argument schema for a single registered tool.",
)
async def get_tool(tool_id: str, user: CurrentUser) -> AgentToolDetailResponse:
    if tool_id not in DEFAULT_TOOLS.names():
        raise AppError(404, "AGENT_TOOL_NOT_FOUND", f"No agent tool named {tool_id!r}.")
    return AgentToolDetailResponse.model_validate(_tool_detail(tool_id))


@run_router.get(
    "/{run_id}/tool-invocations",
    summary="Every tool call a run made or had blocked",
    description=(
        "The run's tool audit trail, oldest first, addressed by run id.\n\n"
        "Includes ``BLOCKED`` calls: a tool the model asked for but its worker did "
        "not authorise is exactly the event a review wants to see."
    ),
)
async def list_run_tool_invocations(
    run_id: UUID,
    user: CurrentUser,
    db: Db,
) -> dict[str, list[AgentToolInvocationResponse]]:
    run = await service.load_owned_run_by_id(run_id, user.id, db)
    return {"items": await service.run_tool_invocations(run, db)}


@run_router.get(
    "/{run_id}/tools",
    summary="Which tools carried a run, and how they went",
    description=(
        "Per-tool totals for the run: calls, successes, failures and blocked "
        "attempts, addressed by run id."
    ),
)
async def list_run_tools(
    run_id: UUID,
    user: CurrentUser,
    db: Db,
) -> dict[str, list[AgentToolUsageResponse]]:
    run = await service.load_owned_run_by_id(run_id, user.id, db)
    usage = await service.run_tool_usage(run, db)
    return {"items": [AgentToolUsageResponse.model_validate(item) for item in usage]}
