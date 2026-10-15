# How to add a runtime adapter (Phase 7)

A runtime adapter is the only place in StudyOS that turns a *runtime name* into a *command*. It is
where the security argument for code execution actually lives: a client submits an `execution_type`
and source files, and the adapter — trusted, static, versioned code — decides the image, the compile
step and the argv. There is no request field for a binary, a flag or a path, so "run untrusted code"
can never become "run this thing on the host".

Everything below keeps that property. If a step would let a client choose the executable, the flags or
the image, the adapter is wrong.

## The pieces

| Concern | File |
| --- | --- |
| The adapter and its `CommandPlan` | `apps/api/app/modules/execution/adapters.py` |
| Options allowlist, default entrypoint, default profile, compiled set | `apps/api/app/modules/execution/policies.py` |
| The `ExecutionType` vocabulary | `apps/api/app/models/enums.py` |
| Backend contract the plan is handed to | `apps/api/app/modules/execution/backends/base.py` |
| Web vocabulary and starters | `apps/web/lib/execution-types.ts` |
| Web labels | `apps/web/lib/i18n/messages.ts` |

`RuntimeAdapter.build_plan(...)` returns a `CommandPlan(image, compile_argv, run_argv, working_dir)`:

- `compile_argv` is `None` for an interpreted runtime. When present the backend runs it first and a
  non-zero exit is classified as `COMPILE_FAILED`, distinct from a user-code failure.
- `run_argv` runs after a successful compile, or immediately for an interpreted runtime.

## 1. Add the execution type

Add the value to `ExecutionType` in `apps/api/app/models/enums.py`. `execution_jobs.execution_type` is
a plain string column with no check constraint, so a new value needs no migration — but the frontend
union in `execution-types.ts` must gain the same value in the same change.

## 2. Write the adapter

Add a subclass in `adapters.py` next to its siblings. Pin the image at the top of the file rather than
inlining a tag.

```python
class _RubyAdapter(RuntimeAdapter):
    execution_type = ExecutionType.RUBY
    image = _RUBY_IMAGE

    def build_plan(self, *, entrypoint, options, job_id) -> CommandPlan:
        entry = self._require_entrypoint(entrypoint)
        return CommandPlan(
            image=self.image,
            compile_argv=None,
            run_argv=["ruby", entry, *self._user_args(options)],
        )
```

Rules the adapter must keep:

- **The binary and flags are literals here**, never taken from `options`. `options` carries *data* the
  program reads (declared arguments, stdin), not the command line's structure.
- **`_require_entrypoint` for anything that runs a file.** A runtime with no entrypoint is a rejection,
  not a guess.
- **Reject an unsupported option value** the way `_CppAdapter` rejects an unknown C++ standard, rather
  than passing it through.

## 3. Register it

Add it to `build_adapters()`. To run the same interpreter under a different academic label, reuse
`_python_adapter(ExecutionType.X)` — that is how `DATA_ANALYSIS`, `NUMERICAL_COMPUTATION` and
`TEST_EXECUTION` share the Python path while staying distinguishable in the job record.

Then update `policies.py`:

- `ALLOWED_OPTIONS[ExecutionType.X]` — the exact option keys the adapter reads. Anything else is a 422.
- `DEFAULT_ENTRYPOINT[ExecutionType.X]` — the filename assumed when the client sends none.
- `DEFAULT_PROFILE[ExecutionType.X]` — the resource profile a job gets when none is requested.
- `COMPILED_TYPES` — add it **only** if `compile_argv` is set.

## 4. Pin and bound the image

A production deployment pins digests; the tag in `adapters.py` is the development default.
`execution_allowed_images` may only *narrow* the set of images the registry serves — an operator can
remove an image, never add one that is not in this file. Do not add a package-install step to a job to
make a runtime work; bake the dependencies into the image (see the dependency section of
[`../architecture/execution-isolation.md`](../architecture/execution-isolation.md)).

## 5. Register the runtime on the web surface

- Add the value to the `ExecutionType` union and to `EXECUTION_ENTRYPOINT` / `STARTERS` in
  `apps/web/lib/execution-types.ts`.
- Add `execution.type.<lowercase>` to **both** `en` and `fa` in `apps/web/lib/i18n/messages.ts`. The
  catalogue is typed, so a missing key is a compile error rather than a silent English fallback.
- If you introduced a new resource profile, add `execution.profile.<lowercase>` and a `keys()` entry;
  otherwise reuse an existing one.

## 6. Test it

- **Unit (always):** assert the exact argv the adapter builds, and that an unknown type or a missing
  entrypoint is refused. Follow `tests/test_execution_sandbox.py::test_the_adapter_registry_pins_images_and_refuses_unknown_types`.
- **Live (opt-in):** add a representative run to `tests/test_execution_docker_live.py`, gated on
  `STUDYOS_EXECUTION_DOCKER=1`. A runtime is not "supported" until a real container has run it; say so
  in the phase report until then.

## Checklist

- [ ] `ExecutionType` value added (API enum + web union).
- [ ] Adapter subclass with a pinned image and literal argv.
- [ ] Registered in `build_adapters()`.
- [ ] `ALLOWED_OPTIONS`, `DEFAULT_ENTRYPOINT`, `DEFAULT_PROFILE` updated; `COMPILED_TYPES` if compiled.
- [ ] Web starters and `en`/`fa` labels added.
- [ ] Unit argv test added; live test added or explicitly deferred.
- [ ] No client-reachable path selects a binary, a flag or an image.
