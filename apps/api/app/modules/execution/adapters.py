"""Runtime adapters: a validated request becomes a fixed, versioned command.

An adapter is the only place that knows how to turn a runtime *name* into an
executable invocation. A client never supplies a host command; it supplies an
execution type, and the adapter owns the image, the compiler flags and the run
command. That indirection is the whole security argument: "run my Python" cannot
become "run this binary on the host" because there is no field a client could fill
with a binary.

Images are pinned by tag here for readability, and the operator may narrow the
allowlist through ``execution_allowed_images`` — never widen it. A production
deployment is expected to pin digests; the tag is the development default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.core.config import Settings
from app.models.enums import ExecutionType
from app.modules.execution.errors import ExecutionRejectedError

#: Directory the sandbox mounts the job's files into. The source tree lives here
#: and nowhere else; there is no host mount.
WORKDIR: str = "/workspace"

_PYTHON_IMAGE: str = "python:3.12-slim"
_JAVA_IMAGE: str = "eclipse-temurin:21-jdk"
_CPP_IMAGE: str = "gcc:14"

_CPP_STANDARDS: frozenset[str] = frozenset({"c++17", "c++20", "c++23"})


@dataclass(frozen=True, slots=True)
class CommandPlan:
    """The commands an adapter will run inside the sandbox.

    ``compile_argv`` is ``None`` for interpreted runtimes. When present the backend
    runs it first and treats a non-zero exit as a compile failure, distinct from a
    runtime failure.
    """

    image: str
    compile_argv: list[str] | None
    run_argv: list[str]
    working_dir: str = WORKDIR


class RuntimeAdapter:
    """Base adapter. Subclasses declare the image and the concrete commands."""

    execution_type: ExecutionType
    image: str

    def build_plan(
        self,
        *,
        entrypoint: str | None,
        options: Mapping[str, object],
        job_id: object,
    ) -> CommandPlan:
        raise NotImplementedError

    def _require_entrypoint(self, entrypoint: str | None) -> str:
        if not entrypoint:
            raise ExecutionRejectedError(
                [f"{self.execution_type.value} execution requires an entrypoint file."]
            )
        return entrypoint

    @staticmethod
    def _user_args(options: Mapping[str, object]) -> list[str]:
        raw = options.get("args", [])
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw]


class _PythonAdapter(RuntimeAdapter):
    """Runs a single Python entrypoint and its declared arguments.

    Used for ``PYTHON`` and the academic data/numerical/test types, which all run
    under the same interpreter. The entrypoint is passed as a path, not as ``-c``
    text, so the executed program is exactly the reviewed file in the workspace.
    """

    execution_type = ExecutionType.PYTHON
    image = _PYTHON_IMAGE

    def build_plan(
        self, *, entrypoint: str | None, options: Mapping[str, object], job_id: object
    ) -> CommandPlan:
        entry = self._require_entrypoint(entrypoint)
        return CommandPlan(
            image=self.image,
            compile_argv=None,
            run_argv=["python3", entry, *self._user_args(options)],
        )


class _JavaAdapter(RuntimeAdapter):
    execution_type = ExecutionType.JAVA
    image = _JAVA_IMAGE

    def build_plan(
        self, *, entrypoint: str | None, options: Mapping[str, object], job_id: object
    ) -> CommandPlan:
        entry = self._require_entrypoint(entrypoint)
        main_class = options.get("main_class")
        if not isinstance(main_class, str) or not main_class.strip():
            main_class = entry.rsplit("/", 1)[-1].removesuffix(".java")
        return CommandPlan(
            image=self.image,
            compile_argv=["javac", entry],
            run_argv=["java", "-cp", WORKDIR, main_class, *self._user_args(options)],
        )


class _CppAdapter(RuntimeAdapter):
    execution_type = ExecutionType.CPP
    image = _CPP_IMAGE

    def build_plan(
        self, *, entrypoint: str | None, options: Mapping[str, object], job_id: object
    ) -> CommandPlan:
        entry = self._require_entrypoint(entrypoint)
        standard = str(options.get("standard", "c++17"))
        if standard not in _CPP_STANDARDS:
            raise ExecutionRejectedError(
                [
                    f"Unsupported C++ standard {standard!r}; choose one of "
                    f"{', '.join(sorted(_CPP_STANDARDS))}."
                ]
            )
        return CommandPlan(
            image=self.image,
            compile_argv=["g++", f"-std={standard}", "-O2", entry, "-o", "/tmp/program"],
            run_argv=["/tmp/program", *self._user_args(options)],
        )


def _python_adapter(execution_type: ExecutionType) -> _PythonAdapter:
    """Build a Python adapter stamped with the requested execution type.

    The command is identical; the type is what the job records, so a
    ``DATA_ANALYSIS`` job is attributable as data analysis rather than collapsing
    to ``PYTHON`` in the history.
    """

    class _Typed(_PythonAdapter):
        pass

    adapter = _Typed()
    adapter.execution_type = execution_type
    return adapter


def build_adapters() -> dict[ExecutionType, RuntimeAdapter]:
    return {
        ExecutionType.PYTHON: _PythonAdapter(),
        ExecutionType.DATA_ANALYSIS: _python_adapter(ExecutionType.DATA_ANALYSIS),
        ExecutionType.NUMERICAL_COMPUTATION: _python_adapter(
            ExecutionType.NUMERICAL_COMPUTATION
        ),
        ExecutionType.TEST_EXECUTION: _python_adapter(ExecutionType.TEST_EXECUTION),
        ExecutionType.JAVA: _JavaAdapter(),
        ExecutionType.CPP: _CppAdapter(),
    }


class AdapterRegistry:
    """Resolve the adapter for an execution type, applying the image allowlist."""

    def __init__(
        self, adapters: Mapping[ExecutionType, RuntimeAdapter] | None = None
    ) -> None:
        self._adapters: dict[ExecutionType, RuntimeAdapter] = dict(
            adapters if adapters is not None else build_adapters()
        )

    def get(self, execution_type: ExecutionType) -> RuntimeAdapter:
        adapter = self._adapters.get(execution_type)
        if adapter is None:
            raise ExecutionRejectedError(
                [f"No runtime adapter is available for {execution_type.value}."]
            )
        return adapter

    def supports(self, execution_type: ExecutionType) -> bool:
        return execution_type in self._adapters

    def execution_types(self) -> tuple[str, ...]:
        return tuple(sorted(t.value for t in self._adapters))

    def images(self) -> frozenset[str]:
        return frozenset(adapter.image for adapter in self._adapters.values())


def build_adapter_registry(settings: Settings) -> AdapterRegistry:
    """Build the registry, narrowing images to the operator's allowlist if set.

    ``execution_allowed_images`` can only *remove* an image; an adapter whose image
    is not listed is dropped from the registry, so a job for that runtime is
    rejected rather than run on an unapproved image.
    """
    registry = AdapterRegistry()
    allowlist = {item.strip() for item in settings.execution_allowed_images.split(",") if item}
    if not allowlist:
        return registry
    filtered = {
        exec_type: adapter
        for exec_type, adapter in registry._adapters.items()
        if adapter.image in allowlist
    }
    return AdapterRegistry(filtered)


DEFAULT_ADAPTERS: AdapterRegistry = AdapterRegistry()
