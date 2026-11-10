"""Centralised approval policy for the runtime's tool dispatch.

The engine runs against the vocabulary the tool registry actually uses —
:class:`AgentToolRisk` levels and the named :class:`ToolPermission` set. It is
consulted by the runtime's single dispatch point (``invoke_tool``'s caller);
the model cannot override it, because the model never names its own risk level
or permission grant — those come from the registration.

Applied rule, in one sentence: a *grant* means the tool may run in general, an
*approval* means this particular invocation runs now, and the two are distinct
for anything at HIGH risk — sandbox execution and external delegation change
what exists outside the run, so a person decides, every time a new binding
appears.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.enums import AgentToolRisk
from app.modules.agent.tools import ToolPermission


def binding_key(tool_name: str, args: dict[str, Any] | None) -> str:
    """A stable identity for one gated invocation.

    Approval is operation-bound: approving "run tests" must not authorize
    "execute code" or even the same tool with different arguments. The key goes
    onto the PERMISSION checkpoint record so a resolved approval can be found
    again when the step replays after the resume.
    """
    import hashlib
    import json

    payload = json.dumps(
        {"tool": tool_name, "args": args or {}}, sort_keys=True, separators=(",", ":")
    )
    return f"TOOL_PERMISSION:{hashlib.sha256(payload.encode()).hexdigest()[:32]}"


@dataclass(frozen=True)
class PolicyDecision:
    requires_approval: bool
    binding: str | None = None
    reason: str = ""
    approvable: bool = field(default=True)


class ApprovalPolicy:
    """Risk-based approval policy. Never overridden by the model."""

    def evaluate_tool(
        self,
        *,
        tool_name: str,
        risk_level: str,
        permissions: set[str] | list[str],
        args: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        perms = set(permissions or [])
        external = ToolPermission.DELEGATE_EXTERNAL_AGENT in perms
        executing = ToolPermission.EXECUTE_SANDBOXED in perms
        high = risk_level == AgentToolRisk.HIGH.value

        if high and (executing or external):
            return PolicyDecision(
                requires_approval=True,
                binding=binding_key(tool_name, args),
                reason=(
                    f"Running '{tool_name}' executes outside this run's own process, "
                    "so it needs your approval."
                ),
            )
        return PolicyDecision(
            requires_approval=False,
            binding=binding_key(tool_name, args),
            reason="Allowed by policy",
        )


DEFAULT_POLICY = ApprovalPolicy()
