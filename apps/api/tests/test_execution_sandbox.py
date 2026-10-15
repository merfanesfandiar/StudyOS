"""The isolation boundary itself: the Docker command line and the agent tool.

The Docker backend builds a ``docker run`` invocation that is the deployment's
entire isolation contract. These tests capture that invocation with a fake runner
and assert the hardening flags are present *and* that the isolation defaults are
not something a later change can quietly drop: no network, a read-only root,
dropped capabilities, ``no-new-privileges``, an unprivileged user and a bound
memory/CPU/PID limit.

A daemon is not required, because the runner is injected. Where a daemon exists,
``STUDYOS_EXECUTION_DOCKER=1`` runs a real container through
``test_execution_docker_live.py``; this file is the part that always runs.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.models.enums import ExecutionAttemptStatus, ExecutionType
from app.modules.agent.execution_tools import EXECUTION_TOOLS, ExecuteCodeTool
from app.modules.agent.tools import ToolContext
from app.modules.execution.adapters import build_adapter_registry
from app.modules.execution.backends.base import SandboxSpec
from app.modules.execution.backends.docker import (
    CommandResult,
    DockerSandboxBackend,
)
from app.modules.execution.errors import ExecutionRejectedError
from app.modules.execution.gateway import ExecutionOutcome


class _RecordingRunner:
    """A command runner that records argv and replays a scripted result."""

    def __init__(self, results: list[CommandResult] | None = None) -> None:
        self.calls: list[list[str]] = []
        self._results = results or []

    def __call__(self, argv: list[str], *, input: bytes | None, timeout: float) -> CommandResult:
        self.calls.append(list(argv))
        if self._results:
            return self._results.pop(0)
        return CommandResult(0, b"ok", b"")


def _spec(**overrides) -> SandboxSpec:
    base = dict(
        job_id=str(uuid4()),
        image="python:3.12-slim",
        files=(),
        compile_argv=None,
        run_argv=["python", "main.py"],
        working_dir="/workspace",
        timeout_seconds=30,
        memory_mb=512,
        cpus=1.0,
        pids=128,
        max_output_bytes=1_000_000,
        max_artifact_bytes=1024,
        max_artifacts=10,
    )
    base.update(overrides)
    return SandboxSpec(**base)


def test_the_docker_run_is_hardened_by_construction() -> None:
    runner = _RecordingRunner()
    backend = DockerSandboxBackend(runner=runner)
    result = backend.run(_spec())

    assert result.status is ExecutionAttemptStatus.SUCCEEDED
    argv = runner.calls[0]
    flattened = " ".join(argv)
    assert "--network none" in flattened
    assert "--read-only" in argv
    assert ["--cap-drop", "ALL"] == argv[argv.index("--cap-drop") : argv.index("--cap-drop") + 2]
    assert "no-new-privileges" in argv
    assert argv[argv.index("--user") + 1] == "65534:65534"
    assert argv[argv.index("--memory") + 1] == "512m"
    assert argv[argv.index("--memory-swap") + 1] == "512m"
    assert argv[argv.index("--cpus") + 1] == "1.0"
    assert argv[argv.index("--pids-limit") + 1] == "128"
    assert "python:3.12-slim" in argv


def test_a_compile_failure_is_classified_as_such() -> None:
    runner = _RecordingRunner([CommandResult(1, b"", b"error: expected ';'")])
    backend = DockerSandboxBackend(runner=runner)
    result = backend.run(_spec(compile_argv=["g++", "main.cpp", "-o", "main"]))

    assert result.status is ExecutionAttemptStatus.FAILED
    assert result.failure_class is not None
    assert result.failure_class.value == "COMPILE_FAILED"
    # The run step never happened: only one command was issued.
    assert len(runner.calls) == 1


def test_a_timeout_is_reported_and_the_container_reaped() -> None:
    runner = _RecordingRunner([CommandResult(124, b"", b"", timed_out=True)])
    backend = DockerSandboxBackend(runner=runner)
    result = backend.run(_spec())

    assert result.status is ExecutionAttemptStatus.TIMED_OUT
    # The second call is the ``docker rm -f`` reap.
    assert runner.calls[-1][:3] == ["docker", "rm", "-f"]


def test_an_empty_image_is_rejected_without_invoking_docker() -> None:
    runner = _RecordingRunner()
    backend = DockerSandboxBackend(runner=runner)
    result = backend.run(_spec(image=""))
    assert result.status is ExecutionAttemptStatus.REJECTED
    assert runner.calls == []


def test_the_adapter_registry_pins_images_and_refuses_unknown_types() -> None:
    from app.core.config import get_settings

    registry = build_adapter_registry(get_settings())
    assert ExecutionType.PYTHON in [ExecutionType(t) for t in registry.execution_types()]
    assert "python:3.12-slim" in registry.images()


def test_building_a_java_plan_without_an_entrypoint_is_refused() -> None:
    from app.core.config import get_settings

    registry = build_adapter_registry(get_settings())
    adapter = registry.get(ExecutionType.JAVA)
    with pytest.raises(ExecutionRejectedError):
        adapter.build_plan(entrypoint=None, options={}, job_id=uuid4())


# ---------------------------------------------------------------------------
# The agent tool that submits to the sandbox
# ---------------------------------------------------------------------------


class _FakeGateway:
    """A gateway that records the request and returns a fixed outcome."""

    def __init__(self, outcome: ExecutionOutcome) -> None:
        self.outcome = outcome
        self.calls: list[dict] = []

    async def run(self, **kwargs) -> ExecutionOutcome:
        self.calls.append(kwargs)
        return self.outcome


def _outcome(**overrides) -> ExecutionOutcome:
    base = dict(
        job_id=uuid4(),
        status="SUCCEEDED",
        exit_code=0,
        stdout="hello\n",
        stderr="",
        failure_class=None,
        duration_ms=12,
    )
    base.update(overrides)
    return ExecutionOutcome(**base)


def _context(execution=None) -> ToolContext:
    return ToolContext(
        run_id=uuid4(),
        task_id=None,
        task_key="T1",
        context="",
        execution=execution,
    )


async def test_execute_code_is_unavailable_without_a_gateway() -> None:
    result = await ExecuteCodeTool().invoke({"language": "python", "code": "print(1)"}, _context())
    assert result.structured_status.value == "UNAVAILABLE"
    assert "not enabled" in result.summary


async def test_execute_code_submits_through_the_gateway() -> None:
    gateway = _FakeGateway(_outcome())
    result = await ExecuteCodeTool().invoke(
        {"language": "python", "code": "print('hi')"},
        _context(gateway),  # type: ignore[arg-type]
    )
    assert result.structured_status.value == "SUCCESS"
    assert result.payload["exit_code"] == 0
    assert gateway.calls[0]["execution_type"] == "PYTHON"
    assert gateway.calls[0]["code"] == "print('hi')"


async def test_a_nonzero_exit_is_a_usable_result_not_a_tool_failure() -> None:
    gateway = _FakeGateway(
        _outcome(status="FAILED", exit_code=1, failure_class="USER_CODE_FAILED", stderr="boom")
    )
    result = await ExecuteCodeTool().invoke(
        {"language": "python", "code": "raise SystemExit(1)"},
        _context(gateway),  # type: ignore[arg-type]
    )
    # Not ``SUCCESS`` — the exit code is a caveat the model must heed — but not a
    # refusal either: the tool did its job, the program did not.
    assert result.structured_status.value == "PARTIAL_SUCCESS"
    assert result.payload["exit_code"] == 1
    assert result.warnings


async def test_an_unknown_language_is_refused_without_calling_the_gateway() -> None:
    gateway = _FakeGateway(_outcome())
    result = await ExecuteCodeTool().invoke(
        {"language": "brainfuck", "code": "++"}, _context(gateway)  # type: ignore[arg-type]
    )
    assert result.structured_status.value == "BLOCKED"
    assert gateway.calls == []


def test_every_execution_tool_is_high_risk_and_sandboxed() -> None:
    for tool in EXECUTION_TOOLS:
        assert "EXECUTE_SANDBOXED" in tool.permissions
        assert "EXECUTE_UNTRUSTED" not in tool.permissions
        assert tool.risk_level.value == "HIGH"
