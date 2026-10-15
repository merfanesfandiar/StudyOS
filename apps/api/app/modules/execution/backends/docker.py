"""The hardened Docker backend.

The container is defined entirely here, and every flag is a deliberate refusal of
a capability: no network, a read-only root filesystem, all Linux capabilities
dropped, no-new-privileges, a non-root user, bounded memory/CPU/processes, and a
single bind mount for the workspace. The Docker socket is never mounted into a
container, so a job cannot ask Docker to run something for it.

The backend is written against a small runner protocol rather than shelling out
directly, so the test suite can drive the whole pipeline without a Docker daemon
and so the exact command line is asserted in a unit test rather than trusted.

A note on the writable ``/tmp``: it is a size-bounded tmpfs that permits
execution, because compiled output must live somewhere the program can run. The
workspace mount is already executable and the sandbox is disposable, so the
tmpfs exec flag adds nothing an attacker could not already do inside the boundary
— while ``noexec`` there would break C++ and Java compilation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Protocol

from app.models.enums import (
    ExecutionAttemptStatus,
    ExecutionBackendKind,
    ExecutionFailureClass,
)
from app.modules.execution.backends.base import SandboxArtifact, SandboxResult, SandboxSpec

#: User the workload runs as inside the container (``nobody``).
_CONTAINER_USER: str = "65534:65534"


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The outcome of one host command invocation."""

    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False


class CommandRunner(Protocol):
    """A callable that runs one command and reports its result."""

    def __call__(
        self, argv: list[str], *, input: bytes | None, timeout: float
    ) -> CommandResult: ...


def _subprocess_runner(argv: list[str], *, input: bytes | None, timeout: float) -> CommandResult:
    try:
        completed = subprocess.run(
            argv,
            input=input,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(124, exc.stdout or b"", exc.stderr or b"", timed_out=True)
    except FileNotFoundError:
        return CommandResult(127, b"", b"docker binary not found")
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


class DockerSandboxBackend:
    """Run one workload in a hardened, disposable container."""

    kind = ExecutionBackendKind.DOCKER

    def __init__(
        self,
        *,
        docker_binary: str = "docker",
        runner: CommandRunner | None = None,
        available_check: bool = True,
    ) -> None:
        self._docker = docker_binary
        self._run: CommandRunner = runner if runner is not None else _subprocess_runner
        self._available: bool | None = None
        self._available_check = available_check

    # -- capability probe ---------------------------------------------------

    @property
    def available(self) -> bool:
        if not self._available_check:
            return True
        if self._available is None:
            probe = self._run(
                [self._docker, "version", "--format", "{{.Server.Version}}"],
                input=None,
                timeout=10.0,
            )
            self._available = probe.returncode == 0
        return self._available

    # -- execution ----------------------------------------------------------

    def run(self, spec: SandboxSpec) -> SandboxResult:
        if not spec.image:
            return SandboxResult(
                status=ExecutionAttemptStatus.REJECTED,
                failure_class=ExecutionFailureClass.STARTUP_FAILED,
                error_code="EXECUTION_NO_IMAGE",
                error_message="No container image was resolved for this execution.",
            )

        workdir = tempfile.mkdtemp(prefix=f"studyos-exec-{spec.job_id}-")
        container = f"studyos-exec-{spec.job_id}"[:63]
        started = time.monotonic()
        try:
            input_paths = self._materialise(workdir, spec)
            base = self._base_argv(spec, container, workdir)

            if spec.compile_argv is not None:
                compiled = self._run(
                    [*base, *spec.compile_argv], input=None, timeout=float(spec.timeout_seconds)
                )
                if compiled.timed_out:
                    return self._timeout_result(spec, container, started)
                if compiled.returncode != 0:
                    return self._compile_failure(spec, container, started, compiled)

            ran = self._run(
                [*base, *spec.run_argv], input=spec.stdin, timeout=float(spec.timeout_seconds)
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            if ran.timed_out:
                return self._timeout_result(spec, container, started)

            artifacts = self._capture(workdir, input_paths, spec)
            if ran.returncode == 137:
                return SandboxResult(
                    status=ExecutionAttemptStatus.RESOURCE_LIMIT_EXCEEDED,
                    exit_code=137,
                    stdout=ran.stdout[: spec.max_output_bytes],
                    stderr=ran.stderr[: spec.max_output_bytes],
                    duration_ms=duration_ms,
                    sandbox_id=container,
                    failure_class=ExecutionFailureClass.RESOURCE_EXHAUSTED,
                    error_code="EXECUTION_KILLED",
                    error_message="The sandbox killed the process (memory or CPU limit).",
                    artifacts=artifacts,
                )
            succeeded = ran.returncode == 0
            return SandboxResult(
                status=(
                    ExecutionAttemptStatus.SUCCEEDED
                    if succeeded
                    else ExecutionAttemptStatus.FAILED
                ),
                exit_code=ran.returncode,
                stdout=ran.stdout[: spec.max_output_bytes],
                stderr=ran.stderr[: spec.max_output_bytes],
                duration_ms=duration_ms,
                sandbox_id=container,
                failure_class=None if succeeded else ExecutionFailureClass.USER_CODE_FAILED,
                error_code=None if succeeded else "EXECUTION_NONZERO_EXIT",
                error_message=(
                    None if succeeded else f"Process exited with code {ran.returncode}."
                ),
                artifacts=artifacts,
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def reap(self, sandbox_id: str) -> bool:
        result = self._run([self._docker, "rm", "-f", sandbox_id], input=None, timeout=15.0)
        return result.returncode == 0 or b"No such container" in result.stderr

    # -- helpers ------------------------------------------------------------

    def _base_argv(self, spec: SandboxSpec, container: str, workdir: str) -> list[str]:
        argv = [
            self._docker,
            "run",
            "--rm",
            "--name",
            container,
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,exec,size=256m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            _CONTAINER_USER,
            "--memory",
            f"{spec.memory_mb}m",
            "--memory-swap",
            f"{spec.memory_mb}m",
            "--cpus",
            str(spec.cpus),
            "--pids-limit",
            str(spec.pids),
            "--workdir",
            spec.working_dir,
            "-v",
            f"{workdir}:{spec.working_dir}:rw",
        ]
        for key, value in spec.environment.items():
            argv += ["-e", f"{key}={value}"]
        if spec.image is not None:
            argv.append(spec.image)
        return argv

    def _materialise(self, workdir: str, spec: SandboxSpec) -> set[str]:
        materialised: set[str] = set()
        for file in spec.files:
            target = os.path.join(workdir, file.path)
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(file.content)
            materialised.add(os.path.normpath(file.path))
        return materialised

    def _capture(
        self, workdir: str, input_paths: set[str], spec: SandboxSpec
    ) -> tuple[SandboxArtifact, ...]:
        artifacts: list[SandboxArtifact] = []
        for root, _dirs, files in os.walk(workdir):
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.normpath(os.path.relpath(full, workdir))
                if rel in input_paths:
                    continue
                if len(artifacts) >= spec.max_artifacts:
                    return tuple(artifacts)
                if os.path.getsize(full) > spec.max_artifact_bytes:
                    continue
                with open(full, "rb") as handle:
                    artifacts.append(SandboxArtifact(filename=rel, content=handle.read()))
        return tuple(artifacts)

    def _timeout_result(
        self, spec: SandboxSpec, container: str, started: float
    ) -> SandboxResult:
        self.reap(container)
        return SandboxResult(
            status=ExecutionAttemptStatus.TIMED_OUT,
            exit_code=None,
            duration_ms=int((time.monotonic() - started) * 1000),
            sandbox_id=container,
            failure_class=ExecutionFailureClass.TIMEOUT,
            error_code="EXECUTION_TIMEOUT",
            error_message=f"Execution exceeded its {spec.timeout_seconds}s limit.",
        )

    def _compile_failure(
        self, spec: SandboxSpec, container: str, started: float, result: CommandResult
    ) -> SandboxResult:
        return SandboxResult(
            status=ExecutionAttemptStatus.FAILED,
            exit_code=result.returncode,
            stdout=result.stdout[: spec.max_output_bytes],
            stderr=result.stderr[: spec.max_output_bytes],
            duration_ms=int((time.monotonic() - started) * 1000),
            sandbox_id=container,
            failure_class=ExecutionFailureClass.COMPILE_FAILED,
            error_code="EXECUTION_COMPILE_FAILED",
            error_message="Compilation failed.",
        )
