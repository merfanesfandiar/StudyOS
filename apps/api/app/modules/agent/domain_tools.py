"""Phase 6: the deterministic academic toolkit.

One committed belief holds this file together: a tool is a *pure function over
data the runtime already has*. Nothing here opens a file, makes an HTTP call,
spawns a process or executes code — not because it is hard to imagine, but
because the moment a tool can touch the outside world it stops being explainable,
testable and bounded. The Phase 5 boundary in :mod:`app.modules.agent.tools`
stands exactly where it did; this file only makes more of the *other* kind of
tool available.

Every tool in this module is:

* **deterministic** — the same arguments produce the same result, so a run's
  tool log is reproducible;
* **bounded** — every input is length- or size-limited, and every loop is over a
  bounded list, so a pathological model call cannot produce unbounded work;
* **stdlib only** — computation is done with :mod:`math`, :mod:`statistics` and
  :mod:`fractions`; there is no dependency a new tooling review would have to
  trust;
* **refusal-first** — invalid or over-budget arguments return
  :meth:`ToolResult.refusal` rather than raising, because a refusal is a
  user-safe explanation and an exception is a crash.

The categories map on to the specialised workers in
:mod:`app.modules.agent.workers`; a tool's category is what groups it in the
catalogue UI, and a tool's declared :class:`ToolPermission` is what gates it.

Security notes a reviewer should check on every read:

* :func:`CalculateTool` evaluates arithmetic with a hand-written AST walker, not
  :func:`eval`. Only numeric literals, a named allow-list of constants and
  functions, and ``+ - * / // % **`` unary minus/plus are accepted. Attribute
  access, subscripts, comprehensions, lambdas and unknown names are all rejected
  at parse time.
* No arguments schema here accepts a *path*, a *url*, a *command* or *script*
  key. The :func:`assert_static_boundary` test in the suite scans this module's
  schemas so that property never silently degrades.
"""

from __future__ import annotations

import ast
import csv
import io
import math
import re
import statistics
from collections import Counter
from collections.abc import Mapping
from fractions import Fraction
from typing import Any, Final

from app.models.enums import AgentToolCategory, AgentToolRisk
from app.modules.agent.tools import AgentTool, ToolContext, ToolPermission, ToolResult


def _refusal(reason: str) -> ToolResult:
    """A tool's way of saying "not like that, and here is why"."""
    return ToolResult.refusal(reason)


def _round(value: float, places: int = 10) -> float:
    """Deterministic rounding. Returns int for whole numbers to avoid ``1.0`` noise."""
    rounded = round(float(value), places)
    return int(rounded) if rounded == int(rounded) else rounded


def _to_number(value: Any, name: str = "value") -> float | None:
    """Coerce a JSON number or numeric string to a finite float, else ``None``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


#: Shared length ceiling for tools that read free text. Mirrors what the context
#: builder already allows, so no tool can demand more than the runtime would send.
MAX_TEXT_CHARS: Final = 20_000
MAX_CODE_CHARS: Final = 40_000


# ---------------------------------------------------------------------------
# Maths
# ---------------------------------------------------------------------------


class CalculateTool:
    """Safe evaluation of a bounded arithmetic expression.

    The one tool here that looks like "run code" and emphatically is not. The
    expression is walked as an :mod:`ast` tree by :func:`_eval_expr`, which
    accepts only numeric constants, the named constants ``pi`` and ``e``, the
    functions ``sqrt``, ``abs``, ``round``, ``min``, ``max``, ``floor`` and
    ``ceil``, and the operators supported by the runtime. There is no attribute
    access, no subscripting and no arbitrary call.
    """

    name = "calculate"
    permissions = frozenset({ToolPermission.COMPUTE})
    category = AgentToolCategory.MATHEMATICS
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": (
                    "An arithmetic expression over numbers, constants pi/e and the "
                    "functions sqrt, abs, round, min, max, floor, ceil. Operators: "
                    "+ - * / // % ** and parentheses."
                ),
            },
        },
        "required": ["expression"],
    }
    description = "Evaluate a bounded, safe arithmetic expression exactly and return the value."

    _MAX_LENGTH: Final = 200
    _CONSTANTS: Final[dict[str, float]] = {"pi": math.pi, "e": math.e}
    _FUNCTIONS: Final[dict[str, Any]] = {
        "sqrt": math.sqrt,
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "floor": math.floor,
        "ceil": math.ceil,
    }

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        expression = str(arguments.get("expression", "")).strip()
        if not expression:
            return _refusal("An expression is required.")
        if len(expression) > self._MAX_LENGTH:
            return _refusal(
                f"That expression is {len(expression)} characters; the limit is {self._MAX_LENGTH}."
            )
        if "\n" in expression or "\r" in expression:
            return _refusal("Expressions must be a single line.")
        try:
            tree = ast.parse(expression, mode="eval")
        except (SyntaxError, ValueError):
            return _refusal("That could not be parsed as arithmetic.")
        try:
            value = self._eval(tree.body)
        except ArithmeticError:
            return _refusal("That expression is not a defined arithmetic value.")
        if not math.isfinite(value):
            return _refusal("That expression produces a non-finite value.")
        if abs(value) > 1e100:
            return _refusal("The result is too large to be useful.")
        return ToolResult(
            ok=True,
            summary=f"Evaluated {expression!r} to {_round(value)}.",
            payload={"expression": expression, "value": _round(value)},
        )

    def _eval(self, node: ast.AST) -> float:  # noqa: PLR0911 - one branch per allowed node
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in self._CONSTANTS:
                return self._CONSTANTS[node.id]
            raise ArithmeticError(f"unknown name {node.id!r}")
        if isinstance(node, ast.BinOp):
            left = self._eval(node.left)
            right = self._eval(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow):
                return float(left**right)
            raise ArithmeticError("unsupported operator")
        if isinstance(node, ast.UnaryOp):
            value = self._eval(node.operand)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return +value
            raise ArithmeticError("unsupported unary operator")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in self._FUNCTIONS:
                raise ArithmeticError("unsupported function")
            if len(node.args) < 1 or node.keywords:
                raise ArithmeticError("calls may not use keywords")
            func = self._FUNCTIONS[node.func.id]
            args = tuple(self._eval(arg) for arg in node.args)
            if func is round and len(args) not in (1, 2):
                raise ArithmeticError("round takes one or two arguments")
            return float(func(*args))
        raise ArithmeticError("unsupported syntax")


class SolveLinearSystemTool:
    """Solve a square system of linear equations exactly.

    Uses :class:`fractions.Fraction` for the elimination so a mathematics worker
    gets exact answers instead of float noise. Bounded to square systems of at
    most 20 unknowns.
    """

    name = "solve_linear_system"
    permissions = frozenset({ToolPermission.COMPUTE})
    category = AgentToolCategory.MATHEMATICS
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "matrix": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}},
                "description": "The square coefficient matrix, one row per equation.",
            },
            "constants": {
                "type": "array",
                "items": {"type": "number"},
                "description": "The right-hand side vector, one value per equation.",
            },
        },
        "required": ["matrix", "constants"],
    }
    description = "Solve a square system of linear equations exactly (Gaussian elimination)."

    _MAX_UNKNOWNS: Final = 20

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        matrix_raw = arguments.get("matrix")
        constants_raw = arguments.get("constants")
        if not isinstance(matrix_raw, list) or not isinstance(constants_raw, list):
            return _refusal("matrix and constants must be arrays of numbers.")
        if len(constants_raw) != len(matrix_raw):
            return _refusal("matrix and constants must have the same number of rows.")
        n = len(matrix_raw)
        if n < 2 or n > self._MAX_UNKNOWNS:
            return _refusal(f"Systems must have between 2 and {self._MAX_UNKNOWNS} unknowns.")
        matrix: list[list[Fraction]] = []
        constants: list[Fraction] = []
        for i, row in enumerate(matrix_raw):
            if not isinstance(row, list) or len(row) != n:
                return _refusal(f"Row {i} must be a list of exactly {n} coefficients.")
            converted: list[Fraction] = []
            for value in row:
                number = _to_number(value, "coefficient")
                if number is None:
                    return _refusal(f"Coefficient {value!r} on row {i} is not a finite number.")
                converted.append(Fraction(str(number)).limit_denominator(10**9))
            matrix.append(converted)
            number = _to_number(constants_raw[i], "constant")
            if number is None:
                return _refusal(f"Constant {constants_raw[i]!r} is not a finite number.")
            constants.append(Fraction(str(number)).limit_denominator(10**9))

        augmented = [row + [constants[i]] for i, row in enumerate(matrix)]

        def _reduce(rows: list[list[Fraction]]) -> list[list[Fraction]] | None:
            rows = [row[:] for row in rows]
            for col in range(n):
                pivot = next((r for r in range(col, n) if rows[r][col] != 0), None)
                if pivot is None:
                    return None
                rows[col], rows[pivot] = rows[pivot], rows[col]
                divisor = rows[col][col]
                rows[col] = [v / divisor for v in rows[col]]
                for r in range(n):
                    if r != col and rows[r][col] != 0:
                        factor = rows[r][col]
                        rows[r] = [
                            v - factor * pivot_v
                            for pivot_v, v in zip(rows[col], rows[r], strict=True)
                        ]
            return rows

        reduced = _reduce(augmented)
        if reduced is None:
            return ToolResult(
                ok=True,
                summary="The system has no unique set of solutions.",
                payload={
                    "unique": False,
                    "variables": [f"x{i + 1}" for i in range(n)],
                    "values": [],
                },
            )
        values = [_round(float(reduced[i][n])) for i in range(n)]
        return ToolResult(
            ok=True,
            summary=f"Solved a {n} x {n} linear system.",
            payload={
                "unique": True,
                "variables": [f"x{i + 1}" for i in range(n)],
                "values": values,
            },
        )


class PrimeFactorizeTool:
    """Prime factorisation of a bounded integer by trial division."""

    name = "prime_factorize"
    permissions = frozenset({ToolPermission.COMPUTE})
    category = AgentToolCategory.MATHEMATICS
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "number": {"type": "integer", "description": "An integer in [2, 10_000_000]."},
        },
        "required": ["number"],
    }
    description = "Return the prime factorisation of a bounded integer."

    _MAX: Final = 10_000_000

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        raw = arguments.get("number")
        if not isinstance(raw, int) or isinstance(raw, bool):
            return _refusal("number must be an integer.")
        if raw < 2 or raw > self._MAX:
            return _refusal(f"number must be in [2, {self._MAX}].")
        factors: dict[str, int] = {}
        remaining = raw
        for prime in (2, 3):
            while remaining % prime == 0:
                factors[str(prime)] = factors.get(str(prime), 0) + 1
                remaining //= prime
        divisor = 5
        while divisor * divisor <= remaining:
            for step in (2, 4):
                if divisor * divisor > remaining:
                    break
                while remaining % divisor == 0:
                    factors[str(divisor)] = factors.get(str(divisor), 0) + 1
                    remaining //= divisor
                divisor += step
        if remaining > 1:
            factors[str(remaining)] = factors.get(str(remaining), 0) + 1
        is_prime = raw > 1 and len(factors) == 1 and factors.get(str(raw), 0) == 1
        return ToolResult(
            ok=True,
            summary=f"Factorised {raw} into {len(factors)} prime"
            f"{'s' if len(factors) != 1 else ''}.",
            payload={
                "number": raw,
                "factors": factors,
                "distinct_primes": [int(p) for p in factors],
                "is_prime": is_prime,
                "total_divisors": math.prod((e + 1) for e in factors.values()),
            },
        )


class GcdLcmTool:
    """GCD and LCM of a list of bounded integers."""

    name = "gcd_lcm"
    permissions = frozenset({ToolPermission.COMPUTE})
    category = AgentToolCategory.MATHEMATICS
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Two to fifty integers, each with absolute value at most 10^18.",
            },
        },
        "required": ["values"],
    }
    description = (
        "Return the greatest common divisor and least common multiple of a list of integers."
    )

    _MAX_COUNT: Final = 50
    _DISPLAY_LIMIT: Final = 10**400

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        raw = arguments.get("values")
        if not isinstance(raw, list):
            return _refusal("values must be an array of integers.")
        if not (2 <= len(raw) <= self._MAX_COUNT):
            return _refusal(f"values must contain between 2 and {self._MAX_COUNT} integers.")
        numbers: list[int] = []
        for value in raw:
            if not isinstance(value, int) or isinstance(value, bool):
                return _refusal(f"{value!r} is not an integer.")
            if abs(value) > 10**18 or value == 0:
                return _refusal("Every value must be a non-zero integer with |v| <= 10^18.")
            numbers.append(value)

        gcd = numbers[0]
        for number in numbers[1:]:
            gcd = math.gcd(gcd, number)
        lcm = numbers[0]
        lcm_exceeds = False
        for number in numbers[1:]:
            lcm = abs(lcm * number) // math.gcd(lcm, number)
            if lcm > self._DISPLAY_LIMIT:
                lcm_exceeds = True
                lcm = self._DISPLAY_LIMIT
                break
        return ToolResult(
            ok=True,
            summary=(
                f"GCD {gcd} and LCM {lcm if not lcm_exceeds else '> 10^400'} "
                f"of {len(numbers)} integers."
            ),
            payload={
                "gcd": gcd,
                "lcm": None if lcm_exceeds else lcm,
                "lcm_exceeds_display_limit": lcm_exceeds,
                "values_count": len(numbers),
            },
        )


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


class ComputeStatisticsTool:
    """Summary statistics for a list of finite numbers."""

    name = "compute_statistics"
    permissions = frozenset({ToolPermission.COMPUTE})
    category = AgentToolCategory.DATA
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "number"},
                "description": "At least two finite numbers.",
            },
        },
        "required": ["values"],
    }
    description = "Return count, mean, median, variance, deviation, min, max and range of numbers."

    _MAX_VALUES: Final = 10_000

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        raw = arguments.get("values")
        if not isinstance(raw, list):
            return _refusal("values must be an array of numbers.")
        if not (2 <= len(raw) <= self._MAX_VALUES):
            return _refusal(f"values must contain between 2 and {self._MAX_VALUES} numbers.")
        numbers: list[float] = []
        for value in raw:
            number = _to_number(value, "value")
            if number is None:
                return _refusal(f"{value!r} is not a finite number.")
            numbers.append(number)
        return ToolResult(
            ok=True,
            summary=f"Computed summary statistics for {len(numbers)} values.",
            payload={
                "count": len(numbers),
                "min": _round(min(numbers)),
                "max": _round(max(numbers)),
                "mean": _round(statistics.mean(numbers)),
                "median": _round(statistics.median(numbers)),
                "variance": _round(statistics.variance(numbers)),
                "stdev": _round(statistics.stdev(numbers)),
                "range": _round(max(numbers) - min(numbers)),
            },
        )


class DetectOutliersTool:
    """Outliers by the interquartile-range rule."""

    name = "detect_outliers"
    permissions = frozenset({ToolPermission.COMPUTE})
    category = AgentToolCategory.DATA
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "number"},
                "description": "At least three finite numbers.",
            },
            "k": {
                "type": "number",
                "description": "Fence multiplier for the IQR rule (default 1.5).",
            },
        },
        "required": ["values"],
    }
    description = "Flag outliers using the Tukey IQR fence rule on a list of numbers."

    _MAX_VALUES: Final = 10_000

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        raw = arguments.get("values")
        if not isinstance(raw, list):
            return _refusal("values must be an array of numbers.")
        if not (3 <= len(raw) <= self._MAX_VALUES):
            return _refusal(f"values must contain between 3 and {self._MAX_VALUES} numbers.")
        numbers: list[float] = []
        for value in raw:
            number = _to_number(value, "value")
            if number is None:
                return _refusal(f"{value!r} is not a finite number.")
            numbers.append(number)
        raw_k = arguments.get("k", 1.5)
        k = _to_number(raw_k, "k")
        if k is None or k < 0:
            return _refusal("k must be a non-negative number.")
        if statistics.pstdev(numbers) == 0:
            return _refusal("All values are identical, so no outlier test is meaningful.")
        quartiles = statistics.quantiles(sorted(numbers), n=4)
        q1, q3 = quartiles[0], quartiles[2]
        iqr = q3 - q1
        lower, upper = q1 - k * iqr, q3 + k * iqr
        outliers = [_round(x) for x in numbers if x < lower or x > upper]
        return ToolResult(
            ok=True,
            summary=f"Found {len(outliers)} outlier{'s' if len(outliers) != 1 else ''}.",
            payload={
                "method": "iqr",
                "k": k,
                "lower_bound": _round(lower),
                "upper_bound": _round(upper),
                "outliers": outliers,
                "count": len(outliers),
            },
        )


class LinearRegressionTool:
    """Ordinary least squares fit for a list of (x, y) points."""

    name = "linear_regression"
    permissions = frozenset({ToolPermission.COMPUTE})
    category = AgentToolCategory.DATA
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "description": "At least two [x, y] point pairs.",
            },
        },
        "required": ["points"],
    }
    description = "Fit y = slope * x + intercept to a list of (x, y) points by least squares."

    _MAX_POINTS: Final = 500

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        raw = arguments.get("points")
        if not isinstance(raw, list):
            return _refusal("points must be an array of [x, y] pairs.")
        if not (2 <= len(raw) <= self._MAX_POINTS):
            return _refusal(f"points must contain between 2 and {self._MAX_POINTS} pairs.")
        points: list[tuple[float, float]] = []
        for i, point in enumerate(raw):
            if not isinstance(point, list) or len(point) != 2:
                return _refusal(f"Point {i} must be a [x, y] pair.")
            x, y = _to_number(point[0], "x"), _to_number(point[1], "y")
            if x is None or y is None:
                return _refusal(f"Point {i} must contain finite numbers.")
            points.append((x, y))
        n = len(points)
        sum_x = sum(x for x, _ in points)
        sum_y = sum(y for _, y in points)
        sum_xy = sum(x * y for x, y in points)
        sum_xx = sum(x * x for x, _ in points)
        denominator = n * sum_xx - sum_x * sum_x
        if denominator == 0:
            return _refusal("All x values are identical, so a slope is not defined.")
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n
        residuals = [(y - (slope * x + intercept)) for x, y in points]
        ss_res = sum(r * r for r in residuals)
        mean_y = sum_y / n
        ss_tot = sum((y - mean_y) ** 2 for _, y in points)
        r_squared = None if ss_tot == 0 else _round(1 - ss_res / ss_tot, 6)
        return ToolResult(
            ok=True,
            summary=f"Fitted y = {_round(slope, 6)}x + {_round(intercept, 6)} over {n} points.",
            payload={
                "n": n,
                "slope": _round(slope, 6),
                "intercept": _round(intercept, 6),
                "r_squared": r_squared,
                "x_mean": _round(sum_x / n),
                "y_mean": _round(mean_y),
            },
        )


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

_WORD_RE: Final = re.compile(r"\w+")
_SENTENCE_END_RE: Final = re.compile(r"[.!?](?=\s|$)")
_VOWEL_GROUP_RE: Final = re.compile(r"[aeiouy]+")
_HEADING_LINE_RE: Final = re.compile(r"^\s*(?:#{1,6}\s+)?[A-Z0-9][A-Za-z0-9 &:,\-()']{2,70}$")

#: A deliberately short list of high-frequency English words. Not a linguist's
#: stop-word set; it only needs to prevent "the"/"and"/"of" from dominating.
_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "the",
        "and",
        "for",
        "are",
        "but",
        "not",
        "you",
        "all",
        "any",
        "can",
        "her",
        "was",
        "one",
        "our",
        "out",
        "that",
        "this",
        "have",
        "with",
        "from",
        "they",
        "will",
        "would",
        "there",
        "their",
        "what",
        "when",
        "where",
        "which",
        "while",
        "whom",
        "who",
        "why",
        "how",
        "about",
        "into",
        "over",
        "than",
        "then",
        "these",
        "those",
        "your",
        "its",
        "his",
        "she",
        "them",
        "been",
        "being",
        "were",
        "does",
        "doing",
        "did",
        "has",
        "had",
        "more",
        "most",
        "other",
        "some",
        "such",
        "only",
        "own",
        "same",
        "very",
        "just",
        "also",
    }
)


class CountWordsTool:
    """Word, sentence and paragraph counts for a block of text."""

    name = "count_words"
    permissions = frozenset({ToolPermission.ANALYZE_TEXT})
    category = AgentToolCategory.WRITING
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to measure."},
        },
        "required": ["text"],
    }
    description = "Count words, sentences, paragraphs and average sentence length of a text."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        text = str(arguments.get("text", ""))
        if not text.strip():
            return _refusal("text must not be empty.")
        if len(text) > MAX_TEXT_CHARS:
            return _refusal(f"text is {len(text)} characters; the limit is {MAX_TEXT_CHARS}.")
        words = _WORD_RE.findall(text)
        sentences = len(_SENTENCE_END_RE.findall(text)) or 1
        paragraphs = max(1, len([p for p in text.splitlines() if p.strip()]))
        return ToolResult(
            ok=True,
            summary=f"Counted {len(words)} words across {sentences} sentences.",
            payload={
                "words": len(words),
                "sentences": sentences,
                "paragraphs": paragraphs,
                "avg_words_per_sentence": _round(len(words) / sentences),
                "characters": len(text),
            },
        )


def _estimate_syllables(word: str) -> int:
    """A deliberately crude syllable counter. Purpose-built, bounded, documented."""
    lowered = word.lower().strip("'\"")
    if not lowered:
        return 0
    groups = _VOWEL_GROUP_RE.findall(lowered)
    count = max(1, len(groups))
    if lowered.endswith("e") and not lowered.endswith(("le", "ee", "ae")):
        count -= 1
    return max(1, count)


class ReadabilityScoreTool:
    """Flesch reading-ease and grade-level estimates for a text."""

    name = "readability_score"
    permissions = frozenset({ToolPermission.ANALYZE_TEXT})
    category = AgentToolCategory.WRITING
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to score."},
        },
        "required": ["text"],
    }
    description = "Estimate the Flesch reading ease and grade level of a text."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        text = str(arguments.get("text", "")).strip()
        if not text:
            return _refusal("text must not be empty.")
        if len(text) > MAX_TEXT_CHARS:
            return _refusal(f"text is {len(text)} characters; the limit is {MAX_TEXT_CHARS}.")
        words = _WORD_RE.findall(text)
        if not words:
            return _refusal("text contains no words to score.")
        sentences = max(1, len(_SENTENCE_END_RE.findall(text)))
        syllables = sum(_estimate_syllables(w) for w in words)
        words_per_sentence = len(words) / sentences
        syllables_per_word = syllables / len(words)
        ease = 206.835 - 1.015 * words_per_sentence - 84.6 * syllables_per_word
        grade = 0.39 * words_per_sentence + 11.8 * syllables_per_word - 15.59
        return ToolResult(
            ok=True,
            summary=(
                f"Estimated readability {_round(max(0.0, ease))} "
                f"({_round(max(0.0, grade))} grade)."
            ),
            payload={
                "flesch_reading_ease": _round(max(0.0, ease)),
                "flesch_kincaid_grade": _round(max(0.0, grade)),
                "words": len(words),
                "sentences": sentences,
                "estimated_syllables": syllables,
            },
        )


class TopKeywordsTool:
    """Frequency-based keywords for a text, after stopping and short-word removal."""

    name = "top_keywords"
    permissions = frozenset({ToolPermission.ANALYZE_TEXT})
    category = AgentToolCategory.WRITING
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to summarise."},
            "limit": {"type": "integer", "description": "How many keywords to return (1-25)."},
        },
        "required": ["text"],
    }
    description = "List the most frequent meaningful words in a text."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        text = str(arguments.get("text", "")).strip()
        if not text:
            return _refusal("text must not be empty.")
        if len(text) > MAX_TEXT_CHARS:
            return _refusal(f"text is {len(text)} characters; the limit is {MAX_TEXT_CHARS}.")
        limit_raw = arguments.get("limit", 10)
        if (
            not isinstance(limit_raw, int)
            or isinstance(limit_raw, bool)
            or not (1 <= limit_raw <= 25)
        ):
            return _refusal("limit must be an integer in [1, 25].")
        words = [w.lower() for w in _WORD_RE.findall(text)]
        meaningful = [w for w in words if len(w) >= 3 and not w.isdigit() and w not in _STOPWORDS]
        counts = Counter(meaningful)
        keywords = [{"word": word, "count": count} for word, count in counts.most_common(limit_raw)]
        return ToolResult(
            ok=True,
            summary=f"Extracted {len(keywords)} keywords.",
            payload={
                "total_words": len(words),
                "distinct_words": len(counts),
                "keywords": keywords,
            },
        )


class AssessStructureTool:
    """Check a text for the presence of required academic sections."""

    name = "assess_structure"
    permissions = frozenset({ToolPermission.ANALYZE_TEXT})
    category = AgentToolCategory.WRITING
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to check."},
            "required_sections": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Section names to look for (default introduction, conclusion, "
                    "references)."
                ),
            },
        },
        "required": ["text"],
    }
    description = "Report which required academic sections appear in a text."

    _DEFAULT_SECTIONS: Final = ("introduction", "conclusion", "references")

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        text = str(arguments.get("text", "")).strip()
        if not text:
            return _refusal("text must not be empty.")
        if len(text) > MAX_TEXT_CHARS:
            return _refusal(f"text is {len(text)} characters; the limit is {MAX_TEXT_CHARS}.")
        raw_sections = arguments.get("required_sections", list(self._DEFAULT_SECTIONS))
        if not isinstance(raw_sections, list) or not raw_sections:
            return _refusal("required_sections must be a non-empty array of names.")
        sections = [str(s).strip() for s in raw_sections]
        if len(sections) > 20 or any(not s or len(s) > 60 for s in sections):
            return _refusal("Each section name must be 1-60 characters, at most 20 names.")
        flattened = text.lower()
        present = [s for s in sections if re.search(rf"\b{re.escape(s.lower())}\b", flattened)]
        missing = [s for s in sections if s not in present]
        headings: list[str] = []
        for line in text.splitlines():
            match = _HEADING_LINE_RE.match(line)
            if match:
                headings.append(match.group(0))
        return ToolResult(
            ok=True,
            summary=f"Found {len(present)} of {len(sections)} required sections.",
            payload={
                "present": present,
                "missing": missing,
                "structure_score": _round(len(present) / len(sections), 2),
                "required_count": len(sections),
                "detected_headings": headings[:30],
            },
        )


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------


class ExtractCitationsTool:
    """Pattern-match likely citations in a text."""

    name = "extract_citations"
    permissions = frozenset({ToolPermission.EXTRACT_REFERENCES})
    category = AgentToolCategory.RESEARCH
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to scan."},
            "limit": {"type": "integer", "description": "Maximum citations to return (1-50)."},
        },
        "required": ["text"],
    }
    description = (
        "Extract likely citations (parenthetical, narrative, numeric, DOI, URL) from text."
    )

    _PATTERNS: Final = (
        ("APA_PARENTHETICAL", re.compile(r"\(([^()]{0,80}?\d{4}(?:[,;][^()]{0,60}?)?)\)")),
        (
            "APA_NARRATIVE",
            re.compile(
                r"\b([A-Z][^\W\d_'-]+(?:\s+(?:and|&|et al\.?)\s+[A-Z][^\W\d_'-]+)?,\s+\d{4})"
            ),
        ),
        ("NUMERIC", re.compile(r"\[(\d+(?:[,\-–]\d+){0,10})\]$")),
        ("DOI", re.compile(r"\b(10\.\d{4,9}/[^\s)\]}\.,;]+)")),
        ("URL", re.compile(r"\b(https?://[^\s)\]}\.,;]+)")),
    )

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        text = str(arguments.get("text", "")).strip()
        if not text:
            return _refusal("text must not be empty.")
        if len(text) > MAX_TEXT_CHARS:
            return _refusal(f"text is {len(text)} characters; the limit is {MAX_TEXT_CHARS}.")
        limit_raw = arguments.get("limit", 20)
        if (
            not isinstance(limit_raw, int)
            or isinstance(limit_raw, bool)
            or not (1 <= limit_raw <= 50)
        ):
            return _refusal("limit must be an integer in [1, 50].")
        seen: list[tuple[str, str]] = []
        seen_keys: set[str] = set()
        for kind, pattern in self._PATTERNS:
            for match in pattern.finditer(text):
                candidate = match.group(1).strip()
                if not candidate or len(candidate) > 120:
                    continue
                key = f"{kind}:{candidate.lower()}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                seen.append((kind, candidate))
                if len(seen) >= limit_raw:
                    break
            if len(seen) >= limit_raw:
                break
        return ToolResult(
            ok=True,
            summary=f"Found {len(seen)} likely citation{'s' if len(seen) != 1 else ''}.",
            payload={
                "citations": [{"kind": kind, "snippet": candidate} for kind, candidate in seen],
                "count": len(seen),
            },
        )


# ---------------------------------------------------------------------------
# Code (static only)
# ---------------------------------------------------------------------------


def _dedup_names(items: list[tuple[str, str]]) -> list[str]:
    """Distinct names in first-seen order, capped at 50 per kind."""
    ordered: list[str] = []
    for _label, hit in items:
        if hit and hit not in ordered:
            ordered.append(hit)
    return ordered[:50]


class CountCodeLinesTool:
    """Line counts with a simple, documented comment heuristic. Never runs code."""

    name = "count_code_lines"
    permissions = frozenset({ToolPermission.ANALYZE_CODE})
    category = AgentToolCategory.CODING
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Source code as text."},
        },
        "required": ["code"],
    }
    description = "Count total, non-blank, comment and code lines of source text."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        code = str(arguments.get("code", ""))
        if not code.strip():
            return _refusal("code must not be empty.")
        if len(code) > MAX_CODE_CHARS:
            return _refusal(f"code is {len(code)} characters; the limit is {MAX_CODE_CHARS}.")
        lines = code.splitlines()
        non_blank = [line for line in lines if line.strip()]
        in_block = False
        comment_lines = 0
        for line in non_blank:
            stripped = line.strip()
            if '"""' in stripped or "'''" in stripped:
                in_block = not in_block
                comment_lines += 1
            elif in_block or stripped.startswith(("#", "//", "*", "--")):
                comment_lines += 1
        code_lines = len(non_blank) - comment_lines
        return ToolResult(
            ok=True,
            summary=f"Counted {len(lines)} lines ({code_lines} code, {comment_lines} comment).",
            payload={
                "lines": len(lines),
                "non_blank": len(non_blank),
                "comment_lines": comment_lines,
                "code_lines": code_lines,
                "comment_ratio": _round(comment_lines / len(non_blank), 4) if non_blank else 0,
            },
        )


class ExtractCodeIdentifiersTool:
    """Extract function, class, import and constant names from source text."""

    name = "extract_code_identifiers"
    permissions = frozenset({ToolPermission.ANALYZE_CODE})
    category = AgentToolCategory.CODING
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Source code as text."},
        },
        "required": ["code"],
    }
    description = "Extract the function, class, import and constant names declared in source text."

    _DEF_RE: Final = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")
    _CLASS_RE: Final = re.compile(r"^\s*class\s+([A-Za-z_]\w*)\b")
    _IMPORT_RE: Final = re.compile(r"^\s*import\s+([\w.]+)")
    _FROM_IMPORT_RE: Final = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+(.+)")
    _CONSTANT_RE: Final = re.compile(r"^\s*([A-Z][A-Z0-9_]{1,30})\s*=\s*\S+")

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        code = str(arguments.get("code", ""))
        if not code.strip():
            return _refusal("code must not be empty.")
        if len(code) > MAX_CODE_CHARS:
            return _refusal(f"code is {len(code)} characters; the limit is {MAX_CODE_CHARS}.")

        functions: list[tuple[str, str]] = []
        classes: list[tuple[str, str]] = []
        imports: list[tuple[str, str]] = []
        constants: list[tuple[str, str]] = []
        for line in code.splitlines():
            match = self._DEF_RE.match(line)
            if match:
                functions.append(("def", match.group(1)))
            match = self._CLASS_RE.match(line)
            if match:
                classes.append(("class", match.group(1)))
            match = self._FROM_IMPORT_RE.match(line)
            if match:
                imports.append(("from", match.group(1)))
                imports.append(("import", re.sub(r"\s+", ", ", match.group(2)).strip()))
                continue
            match = self._IMPORT_RE.match(line)
            if match:
                imports.append(("import", match.group(1)))
            match = self._CONSTANT_RE.match(line)
            if match:
                constants.append(("constant", match.group(1)))
        return ToolResult(
            ok=True,
            summary=(
                f"Found {len(_dedup_names(functions))} functions and "
                f"{len(_dedup_names(classes))} classes."
            ),
            payload={
                "functions": _dedup_names(functions),
                "classes": _dedup_names(classes),
                "imports": _dedup_names(imports),
                "constants": _dedup_names(constants),
            },
        )


class CheckSyntaxBalanceTool:
    """Delimiter/quote balancing plus TODO/FIXME detection. Never parses or runs."""

    name = "check_syntax_balance"
    permissions = frozenset({ToolPermission.ANALYZE_CODE})
    category = AgentToolCategory.CODING
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Source code as text."},
        },
        "required": ["code"],
    }
    description = "Check delimiter and quote balance and flag TODO/FIXME markers in source text."

    _OPEN: Final = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
    _PAIRS: Final = {")": "(", "]": "[", "}": "{", '"': '"', "'": "'"}

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        code = str(arguments.get("code", ""))
        if not code.strip():
            return _refusal("code must not be empty.")
        if len(code) > MAX_CODE_CHARS:
            return _refusal(f"code is {len(code)} characters; the limit is {MAX_CODE_CHARS}.")
        stack: list[str] = []
        issues: list[str] = []
        for column, char in enumerate(code):
            if char in self._OPEN:
                stack.append(char)
            elif char in self._PAIRS:
                if not stack or stack[-1] != char:
                    issues.append(f"column {column}: unmatched closing {char!r}")
                    break
                stack.pop()
        if not issues and stack:
            issues.append(f"unclosed delimiters: {''.join(stack)}")
        todo_lines = [
            i + 1
            for i, line in enumerate(code.splitlines())
            if re.search(r"\b(TODO|FIXME|HACK)\b", line, flags=re.IGNORECASE)
        ]
        balanced = not issues
        return ToolResult(
            ok=True,
            summary=("Delimiters are balanced." if balanced else "Delimiters are not balanced."),
            payload={
                "balanced": balanced,
                "issues": issues,
                "open_delimiters": list(stack),
                "has_todo": len(todo_lines) > 0,
                "todo_lines": todo_lines,
            },
        )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

#: Sentence-ish split: a boundary is terminal punctuation followed by space.
_SENTENCE_SPLIT: Final = re.compile(r"(?<=[.!?])\s+")
#: Markdown or plain-text heading: ``# Title``, ``## Subtitle``.
_HEADING: Final = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>\S.*)$")
#: Column type sniffers, applied to every non-missing value in a column.
_INT_RE: Final = re.compile(r"^[+-]?\d+$")
_NUMBER_RE: Final = re.compile(r"^[+-]?(\d+(\.\d+)?|\.\d+)([eE][+-]?\d+)?$")
_DATE_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}([ T].*)?$")

_TABLE_MAX_ROWS: Final = 5_000
_TABLE_MAX_COLUMNS: Final = 60
_DELIMITERS: Final[tuple[str, ...]] = (",", ";", "\t", "|")


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z][A-Za-z'-]+", text.lower()) if w]


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text.strip()) if part.strip()]


def _headings(text: str) -> list[str]:
    found = []
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            found.append(match.group("title").strip())
    return found


class ExtractDocumentMetadataTool:
    """Read structural metadata out of document *text* the runtime already holds.

    Text-only on purpose: this tool never opens a file and never parses a binary
    format. A future PDF text-extraction tool belongs behind the same boundary
    and would feed its text here.
    """

    name = "extract_document_metadata"
    permissions = frozenset({ToolPermission.ANALYZE_TEXT})
    category = AgentToolCategory.DOCUMENT
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "The document text."}},
        "required": ["text"],
    }
    description = "Extract title, headings and size statistics from document text."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        text = str(arguments.get("text", ""))
        if not text.strip():
            return _refusal("text must not be empty.")
        if len(text) > MAX_TEXT_CHARS:
            return _refusal(f"text is {len(text)} characters; the limit is {MAX_TEXT_CHARS}.")
        headings = _headings(text)
        non_empty = [line.strip() for line in text.splitlines() if line.strip()]
        title = headings[0] if headings else (non_empty[0][:200] if non_empty else "")
        paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        return ToolResult(
            ok=True,
            summary=f"Read metadata: {len(headings)} heading(s), {len(paragraphs)} paragraph(s).",
            payload={
                "title": title,
                "headings": headings[:100],
                "heading_count": len(headings),
                "paragraph_count": len(paragraphs),
                "word_count": len(_words(text)),
                "char_count": len(text),
            },
        )


class SegmentDocumentTool:
    """Split document text into bounded sections for downstream analysis."""

    name = "segment_document"
    permissions = frozenset({ToolPermission.ANALYZE_TEXT})
    category = AgentToolCategory.DOCUMENT
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The document text."},
            "max_sections": {
                "type": "integer",
                "description": "Maximum sections to return (default 40, cap 100).",
            },
        },
        "required": ["text"],
    }
    description = "Split document text into headed or paragraph-delimited sections."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        text = str(arguments.get("text", ""))
        if not text.strip():
            return _refusal("text must not be empty.")
        if len(text) > MAX_TEXT_CHARS:
            return _refusal(f"text is {len(text)} characters; the limit is {MAX_TEXT_CHARS}.")
        default_cap = 40
        raw_cap = arguments.get("max_sections", default_cap)
        cap = raw_cap if isinstance(raw_cap, int) and raw_cap > 0 else default_cap
        cap = min(cap, 100)

        sections: list[dict[str, Any]] = []
        current_title = "(intro)"
        buffer: list[str] = []
        for line in text.splitlines():
            match = _HEADING.match(line)
            if match:
                if buffer or sections:
                    sections.append(_section(current_title, buffer))
                current_title = match.group("title").strip()
                buffer = []
            else:
                buffer.append(line)
        sections.append(_section(current_title, buffer))
        non_empty = [s for s in sections if s["chars"] > 0]
        truncated = len(non_empty) > cap
        return ToolResult(
            ok=True,
            summary=f"Split into {min(len(non_empty), cap)} section(s).",
            payload={"sections": non_empty[:cap], "truncated": truncated},
        )


def _section(title: str, lines: list[str]) -> dict[str, Any]:
    body = "\n".join(lines).strip()
    return {"title": title, "chars": len(body), "preview": body[:200]}


class SearchDocumentTool:
    """Find a literal query in document text, with line context."""

    name = "search_document"
    permissions = frozenset({ToolPermission.ANALYZE_TEXT})
    category = AgentToolCategory.DOCUMENT
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The document text."},
            "query": {"type": "string", "description": "The text to search for."},
            "max_hits": {
                "type": "integer",
                "description": "Maximum matches to return (default 20, cap 100).",
            },
        },
        "required": ["text", "query"],
    }
    description = "Search document text for a query and return matching lines."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        text = str(arguments.get("text", ""))
        query = str(arguments.get("query", "")).strip()
        if not text.strip():
            return _refusal("text must not be empty.")
        if not query:
            return _refusal("query must not be empty.")
        if len(text) > MAX_TEXT_CHARS:
            return _refusal(f"text is {len(text)} characters; the limit is {MAX_TEXT_CHARS}.")
        raw_cap = arguments.get("max_hits", 20)
        cap = raw_cap if isinstance(raw_cap, int) and raw_cap > 0 else 20
        cap = min(cap, 100)

        needle = query.lower()
        hits: list[dict[str, Any]] = []
        total = 0
        for number, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                total += 1
                if len(hits) < cap:
                    hits.append({"line": number, "text": line.strip()[:300]})
        return ToolResult(
            ok=True,
            summary=f"Found {total} matching line(s) for {query!r}.",
            payload={"query": query, "match_count": total, "hits": hits, "truncated": total > cap},
        )


class SummarizeDocumentTool:
    """Extractive summary: the highest-scoring sentences, in original order.

    Extractive, not abstractive. It selects sentences the text already contains;
    it never writes new prose, so it cannot invent a claim the source does not
    make. A generative summary is a model's job, not a deterministic tool's.
    """

    name = "summarize_document"
    permissions = frozenset({ToolPermission.ANALYZE_TEXT})
    category = AgentToolCategory.DOCUMENT
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The document text."},
            "max_sentences": {
                "type": "integer",
                "description": "Maximum sentences in the summary (default 5, cap 20).",
            },
        },
        "required": ["text"],
    }
    description = "Produce an extractive summary by scoring the document's own sentences."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        text = str(arguments.get("text", ""))
        if not text.strip():
            return _refusal("text must not be empty.")
        if len(text) > MAX_TEXT_CHARS:
            return _refusal(f"text is {len(text)} characters; the limit is {MAX_TEXT_CHARS}.")
        raw_cap = arguments.get("max_sentences", 5)
        cap = raw_cap if isinstance(raw_cap, int) and raw_cap > 0 else 5
        cap = min(cap, 20)

        sentences = _sentences(text)
        if len(sentences) <= cap:
            chosen = sentences
        else:
            freq = Counter(w for w in _words(text) if w not in _STOPWORDS)
            scored = []
            for index, sentence in enumerate(sentences):
                words = [w for w in _words(sentence) if w not in _STOPWORDS]
                score = sum(freq[w] for w in words) / (len(words) or 1)
                scored.append((score, index, sentence))
            top = sorted(scored, key=lambda item: (-item[0], item[1]))[:cap]
            chosen = [sentence for _, _, sentence in sorted(top, key=lambda item: item[1])]
        return ToolResult(
            ok=True,
            summary=f"Selected {len(chosen)} of {len(sentences)} sentence(s).",
            payload={
                "summary": " ".join(chosen),
                "sentences": chosen,
                "sentence_count": len(sentences),
            },
        )


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def _bounded_int(value: Any, default: int, cap: int) -> int:
    """Coerce an argument to a positive int, capped. Non-numbers use the default."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return default
    return min(value, cap)


def _detect_delimiter(data: str) -> str:
    """Pick the delimiter that appears most in the first line, defaulting to a comma."""
    lines = data.splitlines()
    first_line = lines[0] if lines else ""
    counts = {delimiter: first_line.count(delimiter) for delimiter in _DELIMITERS}
    best = max(counts, key=lambda delimiter: counts[delimiter])
    return best if counts[best] else ","


def _parse_table(data: str, delimiter: str) -> tuple[list[str], list[list[str]], bool]:
    """Parse CSV-ish text into a header and bounded data rows.

    Returns ``(header, rows, truncated)``. A ragged row is tolerated by absence
    rather than rejected: one short line in a student's export should not make the
    whole dataset unreadable.
    """
    reader = csv.reader(io.StringIO(data), delimiter=delimiter)
    header: list[str] = []
    rows: list[list[str]] = []
    truncated = False
    for index, raw_row in enumerate(reader):
        cells = [cell.strip() for cell in raw_row[:_TABLE_MAX_COLUMNS]]
        if len(raw_row) > _TABLE_MAX_COLUMNS:
            truncated = True
        if index == 0:
            header = cells
            continue
        if index > _TABLE_MAX_ROWS:
            truncated = True
            break
        if not any(cells):
            continue
        rows.append(cells)
    if not header:
        width = max((len(row) for row in rows), default=0)
        header = [f"column_{i + 1}" for i in range(width)]
    return header, rows, truncated


def _column_values(rows: list[list[str]], index: int) -> list[str]:
    return [row[index] if index < len(row) else "" for row in rows]


def _infer_column(values: list[str]) -> tuple[str, list[str]]:
    """Infer a column's type and return its non-missing values.

    Empty is a real type: a column of blanks is not "text", it is a column with
    no data, and calling it text would let a later stage pretend it has content.
    """
    present = [value for value in values if value.strip()]
    if not present:
        return "empty", present
    if all(_NUMBER_RE.match(value) for value in present):
        return ("integer" if all(_INT_RE.match(value) for value in present) else "number"), present
    if all(_DATE_RE.match(value) for value in present):
        return "date", present
    return "text", present


class ProfileDatasetTool:
    """Profile a CSV-style dataset: shape, column types, missingness and stats.

    The dataset arrives as text the runtime already holds; nothing is read from
    disk and no code is executed. That keeps "analyse my CSV" a deterministic,
    bounded operation rather than a step toward running arbitrary Python.
    """

    name = "profile_dataset"
    permissions = frozenset({ToolPermission.COMPUTE})
    category = AgentToolCategory.DATA
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "data": {"type": "string", "description": "The dataset as CSV/semicolon/TAB text."},
            "delimiter": {
                "type": "string",
                "description": "Column delimiter. Detected from the first line when omitted.",
            },
        },
        "required": ["data"],
    }
    description = "Profile a dataset: row and column counts, column types, missingness and stats."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        data = str(arguments.get("data", ""))
        if not data.strip():
            return _refusal("data must not be empty.")
        if len(data) > MAX_CODE_CHARS:
            return _refusal(f"data is {len(data)} characters; the limit is {MAX_CODE_CHARS}.")
        raw_delimiter = str(arguments.get("delimiter", "")).strip()
        delimiter = raw_delimiter if raw_delimiter in _DELIMITERS else _detect_delimiter(data)
        header, rows, truncated = _parse_table(data, delimiter)
        if not rows:
            return _refusal("The dataset has a header but no data rows.")

        columns: list[dict[str, Any]] = []
        missing_total = 0
        for index, name in enumerate(header):
            values = _column_values(rows, index)
            missing = sum(1 for value in values if not value.strip())
            missing_total += missing
            column_type, present = _infer_column(values)
            entry: dict[str, Any] = {
                "name": name,
                "type": column_type,
                "missing": missing,
                "missing_percent": _round(100 * missing / len(values)) if values else 0,
                "distinct": len(set(present)),
            }
            if column_type in {"integer", "number"}:
                finite = [number for number in map(_to_number, present) if number is not None]
                if finite:
                    entry["min"] = _round(min(finite))
                    entry["max"] = _round(max(finite))
                    entry["mean"] = _round(sum(finite) / len(finite))
            columns.append(entry)
        return ToolResult(
            ok=True,
            summary=f"Profiled {len(rows)} row(s) across {len(header)} column(s).",
            payload={
                "delimiter": delimiter,
                "row_count": len(rows),
                "column_count": len(header),
                "missing_total": missing_total,
                "truncated": truncated,
                "columns": columns,
            },
        )


class DetectMissingValuesTool:
    """Report which cells are missing, per column and per row."""

    name = "detect_missing_values"
    permissions = frozenset({ToolPermission.COMPUTE})
    category = AgentToolCategory.DATA
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "data": {"type": "string", "description": "The dataset as CSV/semicolon/TAB text."},
            "delimiter": {
                "type": "string",
                "description": "Column delimiter. Detected from the first line when omitted.",
            },
        },
        "required": ["data"],
    }
    description = "Find missing values in a dataset, by column and by row."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        data = str(arguments.get("data", ""))
        if not data.strip():
            return _refusal("data must not be empty.")
        if len(data) > MAX_CODE_CHARS:
            return _refusal(f"data is {len(data)} characters; the limit is {MAX_CODE_CHARS}.")
        raw_delimiter = str(arguments.get("delimiter", "")).strip()
        delimiter = raw_delimiter if raw_delimiter in _DELIMITERS else _detect_delimiter(data)
        header, rows, truncated = _parse_table(data, delimiter)
        if not rows:
            return _refusal("The dataset has a header but no data rows.")

        by_column = [
            {
                "name": name,
                "missing": sum(1 for value in _column_values(rows, index) if not value.strip()),
            }
            for index, name in enumerate(header)
        ]
        incomplete_rows = []
        for number, row in enumerate(rows, start=1):
            missing_columns = [
                header[i] for i, cell in enumerate(row) if i < len(header) and not cell.strip()
            ]
            if missing_columns:
                incomplete_rows.append({"row": number, "missing_columns": missing_columns})
        return ToolResult(
            ok=True,
            summary=f"{len(incomplete_rows)} of {len(rows)} row(s) have missing values.",
            payload={
                "delimiter": delimiter,
                "row_count": len(rows),
                "incomplete_row_count": len(incomplete_rows),
                "by_column": by_column,
                "rows": incomplete_rows[:20],
                "truncated": truncated or len(incomplete_rows) > 20,
            },
        )


# ---------------------------------------------------------------------------
# Writing, presentation and research
# ---------------------------------------------------------------------------


def _outline(text: str, max_sections: int, bullets: int) -> list[dict[str, Any]]:
    """Heading/bullet outline. Uses headings when present, else paragraph openers."""
    if _headings(text):
        return _outline_from_headings(text, max_sections, bullets)
    sections: list[dict[str, Any]] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        sentences = _sentences(paragraph)
        if not sentences:
            continue
        sections.append({"title": sentences[0][:120], "bullets": sentences[1 : bullets + 1]})
        if len(sections) >= max_sections:
            break
    return sections


def _outline_from_headings(text: str, max_sections: int, bullets: int) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    title: str | None = None
    lines: list[str] = []

    def flush() -> None:
        if title is not None:
            sections.append(
                {
                    "title": title,
                    "bullets": [line.strip() for line in lines if line.strip()][:bullets],
                }
            )

    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            flush()
            title = match.group("title").strip()
            lines = []
        elif title is not None:
            lines.append(line)
    flush()
    return sections[:max_sections]


class SuggestOutlineTool:
    """Turn prose into a heading/bullet outline without inventing content."""

    name = "suggest_outline"
    permissions = frozenset({ToolPermission.ANALYZE_TEXT})
    category = AgentToolCategory.WRITING
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The draft or source text."},
            "max_sections": {
                "type": "integer",
                "description": "Maximum outline sections (default 12, cap 40).",
            },
        },
        "required": ["text"],
    }
    description = "Produce a heading and bullet outline from existing text."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        text = str(arguments.get("text", ""))
        if not text.strip():
            return _refusal("text must not be empty.")
        if len(text) > MAX_TEXT_CHARS:
            return _refusal(f"text is {len(text)} characters; the limit is {MAX_TEXT_CHARS}.")
        cap = _bounded_int(arguments.get("max_sections"), 12, 40)
        sections = _outline(text, cap, 5)
        return ToolResult(
            ok=True,
            summary=f"Produced a {len(sections)}-section outline.",
            payload={"sections": sections},
        )


class BuildSlideOutlineTool:
    """Shape existing text into a slide deck outline: titles and bullets."""

    name = "build_slide_outline"
    permissions = frozenset({ToolPermission.ANALYZE_TEXT})
    category = AgentToolCategory.PRESENTATION
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The source text."},
            "max_slides": {
                "type": "integer",
                "description": "Maximum slides (default 12, cap 30).",
            },
            "bullets_per_slide": {
                "type": "integer",
                "description": "Maximum bullets per slide (default 4, cap 8).",
            },
        },
        "required": ["text"],
    }
    description = "Build a slide outline with titles and bullets from existing text."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        text = str(arguments.get("text", ""))
        if not text.strip():
            return _refusal("text must not be empty.")
        if len(text) > MAX_TEXT_CHARS:
            return _refusal(f"text is {len(text)} characters; the limit is {MAX_TEXT_CHARS}.")
        max_slides = _bounded_int(arguments.get("max_slides"), 12, 30)
        bullets = _bounded_int(arguments.get("bullets_per_slide"), 4, 8)
        slides = _outline(text, max_slides, bullets)
        return ToolResult(
            ok=True,
            summary=f"Outlined {len(slides)} slide(s).",
            payload={"slides": slides},
        )


#: Citation styles this tool can format. Adding one is a formatting change, not a
#: research change; the tool never looks a source up and never invents a field.
_CITATION_STYLES: Final[tuple[str, ...]] = ("APA", "MLA", "BIBTEX")


def _join_authors(authors: list[str], style: str) -> str:
    if len(authors) == 1:
        return authors[0]
    if style == "APA":
        return ", ".join(authors[:-1]) + ", & " + authors[-1]
    return ", ".join(authors[:-1]) + ", and " + authors[-1]


class FormatCitationTool:
    """Format a citation from metadata the caller already has.

    The honesty rule is structural: the tool refuses when a required field is
    absent rather than filling the gap with a plausible guess. A fabricated
    citation is worse than a missing one, so an incomplete record produces a
    refusal that names exactly what is needed.
    """

    name = "format_citation"
    permissions = frozenset({ToolPermission.EXTRACT_REFERENCES})
    category = AgentToolCategory.RESEARCH
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "The source title."},
            "authors": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Author names, in order.",
            },
            "year": {"type": "integer", "description": "Publication year."},
            "publication": {"type": "string", "description": "Journal, publisher or venue."},
            "url": {"type": "string", "description": "URL or DOI locator."},
            "style": {
                "type": "string",
                "description": "One of APA, MLA, BIBTEX (default APA).",
            },
        },
        "required": ["title"],
    }
    description = "Format a citation in APA, MLA or BibTeX from metadata you provide."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        title = str(arguments.get("title", "")).strip()
        if not title:
            return _refusal("title is required.")
        style = str(arguments.get("style", "APA")).strip().upper()
        if style not in _CITATION_STYLES:
            return _refusal(f"style must be one of {', '.join(_CITATION_STYLES)}.")

        raw_authors = arguments.get("authors")
        if isinstance(raw_authors, list):
            authors = [str(author).strip() for author in raw_authors if str(author).strip()]
        elif isinstance(raw_authors, str) and raw_authors.strip():
            authors = [part.strip() for part in raw_authors.split(";") if part.strip()]
        else:
            authors = []

        year = arguments.get("year")
        year_text = str(year).strip() if isinstance(year, int) else ""
        publication = str(arguments.get("publication", "")).strip()
        url = str(arguments.get("url", "")).strip()

        if style in {"APA", "MLA"}:
            provided = (("authors", authors), ("year", year_text))
            needed = [name for name, value in provided if not value]
            if needed:
                return _refusal(
                    f"A {style} citation needs {', '.join(needed)}; supply them rather than invent."
                )

        if style == "APA":
            author_text = _join_authors(authors, "APA")
            parts = [f"{author_text} ({year_text}).", f"{title}."]
            if publication:
                parts.append(f"{publication}.")
            if url:
                parts.append(url)
            citation = " ".join(parts)
        elif style == "MLA":
            author_text = _join_authors(authors, "MLA")
            parts = [f"{author_text}.", f'"{title}."']
            if publication:
                parts.append(f"{publication},")
            if year_text:
                parts.append(f"{year_text}.")
            if url:
                parts.append(url)
            citation = " ".join(parts)
        else:
            surname = authors[0].split()[-1] if authors else "source"
            key = re.sub(r"[^A-Za-z]", "", surname) + year_text
            entries = [f"  title = {{{title}}}"]
            if authors:
                entries.append(f"  author = {{{' and '.join(authors)}}}")
            if year_text:
                entries.append(f"  year = {{{year_text}}}")
            if publication:
                entries.append(f"  journal = {{{publication}}}")
            if url:
                entries.append(f"  url = {{{url}}}")
            citation = "@article{" + key + ",\n" + ",\n".join(entries) + "\n}"

        return ToolResult(
            ok=True,
            summary=f"Formatted a {style} citation for {title!r}.",
            payload={"style": style, "citation": citation},
        )




#: The complete Phase 6 academic toolkit, in one place for a security review.
ACADEMIC_TOOLS: Final[tuple[AgentTool, ...]] = (
    CalculateTool(),
    SolveLinearSystemTool(),
    PrimeFactorizeTool(),
    GcdLcmTool(),
    ComputeStatisticsTool(),
    DetectOutliersTool(),
    LinearRegressionTool(),
    CountWordsTool(),
    ReadabilityScoreTool(),
    TopKeywordsTool(),
    AssessStructureTool(),
    ExtractCitationsTool(),
    CountCodeLinesTool(),
    ExtractCodeIdentifiersTool(),
    CheckSyntaxBalanceTool(),
    ExtractDocumentMetadataTool(),
    SegmentDocumentTool(),
    SearchDocumentTool(),
    SummarizeDocumentTool(),
    ProfileDatasetTool(),
    DetectMissingValuesTool(),
    SuggestOutlineTool(),
    BuildSlideOutlineTool(),
    FormatCitationTool(),
)
