"""Sandbox backends.

``disabled`` rejects every job and is the default; ``mock`` is a deterministic
in-process fake for the test suite; ``docker`` runs a hardened, network-less
container. There is deliberately no host-exec backend, and adding one would be a
change to this package that renames the safety story of the whole product.
"""

from app.modules.execution.backends.base import (
    SandboxArtifact,
    SandboxBackend,
    SandboxFile,
    SandboxResult,
    SandboxSpec,
)

__all__ = [
    "SandboxArtifact",
    "SandboxBackend",
    "SandboxFile",
    "SandboxResult",
    "SandboxSpec",
]
