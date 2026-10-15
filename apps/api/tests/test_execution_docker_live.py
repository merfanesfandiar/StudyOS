"""The one test that runs a real container, skipped unless a daemon is present.

Set ``STUDYOS_EXECUTION_DOCKER=1`` to run it. It is kept out of the default suite
because a build machine without a Docker daemon (and without the pinned image
cached) should not fail a pull request. When it does run, it proves the isolation
is not only in the command line: a program with no network and a read-only root
still runs and returns its output.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from app.modules.execution.backends.base import SandboxFile, SandboxSpec
from app.modules.execution.backends.docker import DockerSandboxBackend

pytestmark = pytest.mark.skipif(
    os.environ.get("STUDYOS_EXECUTION_DOCKER") != "1",
    reason="Set STUDYOS_EXECUTION_DOCKER=1 with a running daemon to run live sandbox tests.",
)


def test_a_python_program_runs_in_a_real_container() -> None:
    backend = DockerSandboxBackend()
    assert backend.available, "the pinned image is required for this test"

    spec = SandboxSpec(
        job_id=str(uuid4()),
        image="python:3.12-slim",
        files=(SandboxFile(path="main.py", content=b"print('live sandbox ok')\n"),),
        compile_argv=None,
        run_argv=["python", "main.py"],
        working_dir="/workspace",
        timeout_seconds=30,
        memory_mb=256,
        cpus=1.0,
        pids=64,
        max_output_bytes=100_000,
        max_artifact_bytes=1_000_000,
        max_artifacts=10,
    )
    result = backend.run(spec)
    assert result.exit_code == 0, result.stderr
    assert b"live sandbox ok" in result.stdout
    if result.sandbox_id:
        backend.reap(result.sandbox_id)
