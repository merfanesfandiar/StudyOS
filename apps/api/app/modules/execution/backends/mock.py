"""A deterministic, in-process backend for the test suite.

It runs nothing. It reads *markers* from the job's files and returns the outcome
those markers ask for. That is the opposite of a security hazard — there is no
execution at all — and it is what lets the rest of the pipeline (queue, attempts,
artifacts, cleanup, failure classification, events) be tested end to end without a
Docker daemon, deterministically and instantly.

The markers are a test protocol, not a product feature:

``@mock:exit=<n>``       exit with code ``n``
``@mock:stdout=<text>``  emit ``<text>`` on stdout
``@mock:stderr=<text>``  emit ``text`` on stderr
``@mock:compile_fail``   fail the compile step (only for compiled runtimes)
``@mock:timeout``        report a timeout
``@mock:oom``            report resource exhaustion
``@mock:artifact=<name>`` produce an output artifact named ``name``

With no marker the job succeeds with exit 0. A marker line is
``# @mock:key=value`` (or ``//`` for compiled sources); the backend does not care
which comment syntax, it scans line by line.
"""

from __future__ import annotations

from app.models.enums import (
    ExecutionAttemptStatus,
    ExecutionBackendKind,
    ExecutionFailureClass,
)
from app.modules.execution.backends.base import SandboxArtifact, SandboxResult, SandboxSpec

_MARKER = "@mock:"


def _markers(spec: SandboxSpec) -> dict[str, str]:
    """Collect markers from every file, last definition winning."""
    found: dict[str, str] = {}
    for file in spec.files:
        try:
            text = file.content.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - decode never raises with replace
            continue
        for line in text.splitlines():
            index = line.find(_MARKER)
            if index == -1:
                continue
            body = line[index + len(_MARKER) :].strip().rstrip("*/").strip()
            if "=" in body:
                key, _, value = body.partition("=")
                found[key.strip()] = value.strip()
            else:
                found[body.strip()] = ""
    return found


class MockSandboxBackend:
    """A backend that reports a scripted outcome instead of running anything."""

    kind = ExecutionBackendKind.MOCK

    @property
    def available(self) -> bool:
        return True

    def run(self, spec: SandboxSpec) -> SandboxResult:
        markers = _markers(spec)
        stdout = markers.get("stdout", "").encode()
        stderr = markers.get("stderr", "").encode()
        sandbox_id = f"mock-{spec.job_id}"

        if "compile_fail" in markers and spec.compile_argv is not None:
            return SandboxResult(
                status=ExecutionAttemptStatus.FAILED,
                exit_code=1,
                stdout=b"",
                stderr=b"mock compile failure",
                duration_ms=5,
                sandbox_id=sandbox_id,
                failure_class=ExecutionFailureClass.COMPILE_FAILED,
                error_code="MOCK_COMPILE_FAILED",
                error_message="The mock backend reported a compile failure.",
            )

        if "oom" in markers:
            return SandboxResult(
                status=ExecutionAttemptStatus.RESOURCE_LIMIT_EXCEEDED,
                exit_code=137,
                stdout=stdout,
                stderr=stderr,
                duration_ms=10,
                sandbox_id=sandbox_id,
                failure_class=ExecutionFailureClass.RESOURCE_EXHAUSTED,
                error_code="MOCK_OOM",
                error_message="The mock backend reported memory exhaustion.",
                resource_usage={"memory_mb": spec.memory_mb, "cpus": spec.cpus},
            )

        if "timeout" in markers:
            return SandboxResult(
                status=ExecutionAttemptStatus.TIMED_OUT,
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                duration_ms=spec.timeout_seconds * 1000,
                sandbox_id=sandbox_id,
                failure_class=ExecutionFailureClass.TIMEOUT,
                error_code="MOCK_TIMEOUT",
                error_message="The mock backend reported a timeout.",
            )

        exit_code = 0
        if "exit" in markers:
            try:
                exit_code = int(markers["exit"])
            except ValueError:
                exit_code = 1

        artifacts: list[SandboxArtifact] = []
        for key, value in markers.items():
            if key.startswith("artifact"):
                name = value or f"artifact-{len(artifacts)}.txt"
                artifacts.append(
                    SandboxArtifact(
                        filename=name,
                        content=b"mock artifact",
                        mime_type="text/plain",
                    )
                )

        status = (
            ExecutionAttemptStatus.SUCCEEDED if exit_code == 0 else ExecutionAttemptStatus.FAILED
        )
        failure = (
            None if exit_code == 0 else ExecutionFailureClass.USER_CODE_FAILED
        )
        return SandboxResult(
            status=status,
            exit_code=exit_code,
            stdout=stdout or b"mock stdout\n",
            stderr=stderr,
            duration_ms=5,
            sandbox_id=sandbox_id,
            failure_class=failure,
            error_code=None if exit_code == 0 else "MOCK_NONZERO_EXIT",
            error_message=None if exit_code == 0 else f"Process exited with code {exit_code}.",
            resource_usage={"memory_mb": 16, "cpus": 0.01},
            artifacts=tuple(artifacts),
        )

    def reap(self, sandbox_id: str) -> bool:
        # Nothing was created; pretending to have cleaned up keeps the pipeline
        # exerciseable without a container runtime.
        return True
