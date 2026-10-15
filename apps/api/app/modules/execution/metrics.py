"""Named, in-process counters for the execution plane.

The event stream (``execution_events``) records what happened to *one* job. It is
the wrong shape for "how many jobs failed in the last hour", which is a question
asked of the whole deployment and not of a row. This module is that second shape,
and it is deliberately tiny: a process-local registry of monotonically increasing
counters, keyed by name and label set, with no dependency and no background
exporter.

Two honest limitations are documented rather than hidden:

* **It is per process.** An API replica and a worker each keep their own counters;
  the number is a rollout's worth of truth only once scraped from every process.
  That is how every Prometheus instrumented service works, and it is why the
  endpoint speaks the Prometheus text format rather than inventing a JSON shape a
  dashboard would have to special-case.
* **It resets on restart.** Counters are not persisted. They are for rates and
  alerting, not for audit; the event stream is the durable record.

Counters carry aggregate counts and enum labels only. Nothing here can hold source
code, an error message or a secret, because the call sites pass labels, not text.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Final

#: Metric name -> label-set -> accumulated value. A label set is a sorted tuple of
#: ``(name, value)`` pairs so two logically-equal labelings share one series.
_counters: Final[dict[str, dict[tuple[tuple[str, str], ...], float]]] = {}
_lock: Final = threading.Lock()


def _label_key(labels: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, str(value)) for key, value in labels.items()))


def incr(name: str, amount: float = 1.0, **labels: object) -> None:
    """Add ``amount`` to the counter ``name`` for this label set."""
    key = _label_key(labels)
    with _lock:
        series = _counters.setdefault(name, {})
        series[key] = series.get(key, 0.0) + amount


def observe(name: str, value: float, **labels: object) -> None:
    """Record one observation of a summary-shaped metric.

    Exposed as the conventional ``<name>_sum`` and ``<name>_count`` series, so a
    consumer can compute an average and a rate without a histogram bucket layout
    the workload does not justify.
    """
    key = _label_key(labels)
    with _lock:
        for suffix, delta in (("_sum", value), ("_count", 1.0)):
            series = _counters.setdefault(f"{name}{suffix}", {})
            series[key] = series.get(key, 0.0) + delta


def snapshot() -> dict[str, list[dict[str, object]]]:
    """A JSON-serializable view of every series, for tests and diagnostics."""
    with _lock:
        return {
            name: [
                {"labels": dict(key), "value": value}
                for key, value in sorted(series.items())
            ]
            for name, series in sorted(_counters.items())
        }


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render() -> str:
    """Render every series in the Prometheus text exposition format."""
    lines: list[str] = []
    with _lock:
        items = sorted(_counters.items())
        series_by_name = {name: sorted(series.items()) for name, series in items}
    for name, series in series_by_name.items():
        lines.append(f"# TYPE {name} counter")
        for key, value in series:
            if key:
                labels = ",".join(f'{k}="{_escape(v)}"' for k, v in key)
                lines.append(f"{name}{{{labels}}} {value:g}")
            else:
                lines.append(f"{name} {value:g}")
    return "\n".join(lines) + ("\n" if lines else "")


def reset() -> None:
    """Drop all counters. For tests that assert exact values, and nothing else."""
    with _lock:
        _counters.clear()
