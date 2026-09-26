"""Print the golden analysis report and fail when it regresses.

Run as ``python -m app.ai.evaluation.report``. Used by CI as a gate and useful
locally:

    python -m app.ai.evaluation.report            # report, non-zero exit on failure
    python -m app.ai.evaluation.report --report   # report only, always exit 0

The thresholds are deliberately modest. A pass means "no fixture regressed and the
evaluation can still detect a broken analysis", not "the analyzer is perfect".
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.ai.evaluation.runner import run_evaluation

#: Floors below which the analyzer has regressed on the golden dataset.
THRESHOLDS: dict[str, float] = {
    "classification_accuracy": 0.9,
    "requirement_coverage": 0.9,
    "deliverable_recall": 0.9,
    "schema_validity": 1.0,
    "evidence_grounding": 1.0,
    "ambiguity_detection": 1.0,
    "contradiction_detection": 1.0,
    "dependency_recall": 1.0,
    "rubric_recall": 1.0,
}

#: Ceilings above which the analyzer has started inventing content.
CEILINGS: dict[str, float] = {"hallucination_rate": 0.0}

#: The evaluation must reject every mutation it plants, or it measures nothing.
REQUIRED_MUTATION_DETECTION = 1.0


async def build_report() -> tuple[dict[str, float | int], list[str]]:
    report = await run_evaluation()
    summary = report.summary()
    problems: list[str] = []

    failing = [result.name for result in report.results if not result.passed]
    if failing:
        problems.append(f"fixtures regressed: {', '.join(failing)}")

    for metric, floor in THRESHOLDS.items():
        value = float(summary[metric])
        if value < floor:
            problems.append(f"{metric} {value} < {floor}")
    for metric, ceiling in CEILINGS.items():
        value = float(summary[metric])
        if value > ceiling:
            problems.append(f"{metric} {value} > {ceiling}")

    detection = float(summary["mutation_detection_rate"])
    if detection < REQUIRED_MUTATION_DETECTION:
        blind = [item.name for item in report.mutations if not item.caught]
        problems.append(f"evaluation is blind to: {', '.join(blind) or 'unknown'}")
    return summary, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        action="store_true",
        help="always exit 0, even when the evaluation regressed",
    )
    arguments = parser.parse_args(argv)

    summary, problems = asyncio.run(build_report())

    print("Golden analysis evaluation (mock provider, no network)")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if problems:
        print("\nFAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 0 if arguments.report else 1
    print("\nOK: every fixture passed and every planted defect was detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
