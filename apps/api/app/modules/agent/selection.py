"""Choosing which task the runtime works on next.

This is a deterministic function of the plan and the run's progress, not a model
decision. Two reasons:

* **Ordering is a graph property, not a judgement.** Executing a task before its
  predecessors is the failure that makes a plan worthless, so it must not depend
  on a model choosing correctly.
* **It has to survive a restart.** After a crash the runtime must be able to
  answer "what was I about to do" from the database alone. A selection rule that
  needed live reasoning would not be reproducible.

The ordering itself is: ready tasks first, then by priority, then by the plan's
stored ``position``. Priority is only a tiebreak among tasks that are *already*
executable, so a CRITICAL task that is not ready never jumps its dependencies.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.models.enums import AcademicTaskPriority, AcademicTaskStatus, AcademicTaskType

#: Priority ordering, best first. Numeric rather than enum comparison because
#: ``StrEnum`` members do not order, which is a trap this codebase has already
#: had to work around in the model router.
PRIORITY_RANK: dict[str, int] = {
    AcademicTaskPriority.CRITICAL.value: 0,
    AcademicTaskPriority.HIGH.value: 1,
    AcademicTaskPriority.MEDIUM.value: 2,
    AcademicTaskPriority.LOW.value: 3,
}

#: Task types whose result needs a human to confirm before the runtime may treat
#: it as complete. Submission is the obvious one: deciding that work is finished
#: and ready to hand in is the student's call, not the agent's.
HUMAN_JUDGEMENT_TYPES: frozenset[str] = frozenset({AcademicTaskType.SUBMIT.value})


@dataclass(frozen=True, slots=True)
class TaskNode:
    """The minimum a task needs to be schedulable.

    A projection rather than the ORM entity so selection is a pure function and
    can be tested exhaustively without a database.
    """

    key: str
    status: str
    priority: str
    position: int
    type: str = AcademicTaskType.OTHER.value
    depends_on: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Selection:
    """The chosen task, plus why it was chosen and what else was runnable.

    ``runnable_keys`` is retained even when a choice was made: when the student
    asks "why that one?", the answer is the ordering of the list, not a
    reconstructed guess.
    """

    task: TaskNode | None
    runnable_keys: tuple[str, ...]
    #: Why no task was runnable. Empty when ``task`` is set.
    blocked_reason: str | None = None

    @property
    def has_work(self) -> bool:
        return self.task is not None


def is_terminal(status: str) -> bool:
    return status in {
        AcademicTaskStatus.COMPLETED.value,
        AcademicTaskStatus.SKIPPED.value,
    }


def executable_keys(tasks: Sequence[TaskNode]) -> tuple[str, ...]:
    """Keys of tasks whose every predecessor is finished.

    A predecessor that is ``BLOCKED`` is not finished, so its successors stay
    blocked too. That is intentional: a blocked task is a wall, not a pause, and
    letting the graph flow around it would let the plan silently skip work.
    """
    done = {t.key for t in tasks if is_terminal(t.status)}
    ready = [
        t
        for t in tasks
        if t.status in {AcademicTaskStatus.PENDING.value, AcademicTaskStatus.IN_PROGRESS.value}
        and t.depends_on <= done
    ]
    ready.sort(key=lambda t: (PRIORITY_RANK.get(t.priority, 2), t.position, t.key))
    return tuple(t.key for t in ready)


def select_next_task(tasks: Sequence[TaskNode]) -> Selection:
    """Pick the next task, or explain why there is none."""
    runnable = executable_keys(tasks)
    if runnable:
        by_key = {t.key: t for t in tasks}
        return Selection(task=by_key[runnable[0]], runnable_keys=runnable)

    unfinished = [t for t in tasks if not is_terminal(t.status)]
    if not unfinished:
        return Selection(
            task=None,
            runnable_keys=(),
            blocked_reason="Every task in the plan is finished.",
        )
    # Distinguish "waiting on a predecessor" from "genuinely blocked", because
    # they need different remedies: one is automatic once the predecessor
    # finishes, the other needs a person to intervene.
    waiting = [
        t
        for t in unfinished
        if any(
            p.status in {AcademicTaskStatus.PENDING.value, AcademicTaskStatus.IN_PROGRESS.value}
            for p in tasks
            if p.key in t.depends_on
        )
    ]
    if waiting:
        keys = ", ".join(sorted(t.key for t in waiting))
        return Selection(
            task=None,
            runnable_keys=(),
            blocked_reason=f"Waiting on unfinished earlier tasks: {keys}.",
        )
    blocked = [t for t in unfinished if t.status == AcademicTaskStatus.BLOCKED.value]
    keys = ", ".join(sorted(t.key for t in blocked))
    return Selection(
        task=None,
        runnable_keys=(),
        blocked_reason=f"Blocked tasks need attention: {keys}."
        if keys
        else "No task is executable.",
    )


def approval_required_keys(tasks: Iterable[TaskNode]) -> frozenset[str]:
    """Tasks a human must confirm before the runtime may mark them complete.

    Derived from the task type rather than stored, so a plan regenerated with a
    new task type immediately gets the right constraint.
    """
    return frozenset(t.key for t in tasks if t.type in HUMAN_JUDGEMENT_TYPES)


def progress(tasks: Sequence[TaskNode]) -> dict[str, int]:
    """Counts for the UI. ``percent`` counts only tasks the plan actually has."""
    total = len(tasks)
    completed = sum(1 for t in tasks if t.status == AcademicTaskStatus.COMPLETED.value)
    skipped = sum(1 for t in tasks if t.status == AcademicTaskStatus.SKIPPED.value)
    in_progress = sum(1 for t in tasks if t.status == AcademicTaskStatus.IN_PROGRESS.value)
    blocked = sum(1 for t in tasks if t.status == AcademicTaskStatus.BLOCKED.value)
    return {
        "total": total,
        "completed": completed,
        "skipped": skipped,
        "in_progress": in_progress,
        "blocked": blocked,
        "remaining": total - completed - skipped,
        # Rounded down: a progress bar that shows 100% with a task outstanding is
        # a lie the student notices immediately.
        "percent": round(100 * (completed + skipped) / total) if total else 0,
    }


def build_nodes(
    tasks: Sequence[TaskNode],
    *,
    predecessors: Mapping[str, Sequence[str]] | None = None,
) -> tuple[TaskNode, ...]:
    """Attach dependency edges from a plan-local key map."""
    edges = predecessors or {}
    return tuple(
        TaskNode(
            key=t.key,
            status=t.status,
            priority=t.priority,
            position=t.position,
            type=t.type,
            depends_on=frozenset(edges.get(t.key, ())),
        )
        for t in tasks
    )
