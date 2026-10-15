"""Backend selection.

The mapping from configuration to backend is deliberately total and closed. A
deployment names one of three kinds; there is no plugin discovery and no way for
a value in an environment variable to select a code path that is not in this file.
The default is :class:`DisabledSandboxBackend`, so an unconfigured deployment
rejects execution rather than running it.
"""

from __future__ import annotations

from app.core.config import Settings
from app.modules.execution.backends.base import SandboxBackend
from app.modules.execution.backends.disabled import DisabledSandboxBackend
from app.modules.execution.backends.docker import CommandRunner, DockerSandboxBackend
from app.modules.execution.backends.mock import MockSandboxBackend


def build_backend(
    settings: Settings,
    *,
    runner: CommandRunner | None = None,
) -> SandboxBackend:
    """Resolve the configured backend.

    ``runner`` is only honoured for the Docker backend and exists so tests can
    assert the generated command line without a daemon; production never passes it.
    """
    kind = settings.execution_backend
    if kind == "docker":
        return DockerSandboxBackend(runner=runner)
    if kind == "mock":
        return MockSandboxBackend()
    return DisabledSandboxBackend()
