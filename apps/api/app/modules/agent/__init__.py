"""Professional Agent Runtime.

Application-layer orchestration for long-running, multi-step academic work. The
runtime is domain-agnostic: it knows about plans, tasks, dependencies and
artifacts, and nothing about any particular subject. The Academic Planning
Engine (``app.modules.planning``) remains the authority on what work exists and
whether it is sound; this module only ever executes a plan a student has
already approved.

The division of responsibility inside the module:

* ``state_machine`` is the authority on which run transitions are legal.
  Deterministic, and it refuses transitions rather than repairing them.
* ``limits`` owns every budget. Effort is finite by construction rather than by
  convention, so a runaway loop runs out of permission instead of time.
* ``tools`` is the only way the runtime touches the world, and the registry
  contains no capability that could reach outside the database.
* ``decisions`` validates every model action against the task, the plan and the
  student's permissions before anything is written.
* ``context`` assembles bounded, provenance-tracked, explicitly-untrusted input.
* ``executors`` and ``workers`` turn a validated action into work. Workers are
  bounded contracts; the coding worker is a text-only draft writer.
* ``ml`` may reorder work that is already legal to run, and may not change what
  is legal. Advisory input can never authorise, skip or gate anything.
* ``service`` owns the run lifecycle, persistence and the audit trail.
* ``recovery`` reconciles runs that outlived the process that was executing them.

Nothing here executes model-authored code, spawns a process, opens a socket or
reads a file. The strongest guarantee the module offers is that the set of
things a run can do is finite, declared in code, and auditable after the fact.
"""
