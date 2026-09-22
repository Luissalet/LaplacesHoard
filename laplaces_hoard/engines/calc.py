"""Exact numeric evaluation: arithmetic, percentages, number theory.

Every literal in the input is converted to an exact SymPy `Rational` /
`Integer` (never a lossy Python `float`), so `0.1 + 0.2` is exactly
`3/10`, not `0.30000000000000004`. Expressions never touch `eval` or
`sympify`; see `safe_ast.py` for the whitelisted parser.
"""
from __future__ import annotations

from typing import Any

import sympy

from .safe_ast import UnsafeExpressionError, parse_expression

__all__ = ["compute", "UnsafeExpressionError"]


def compute(expression: str, precision: int = 15) -> dict[str, Any]:
    precision = max(1, min(int(precision), 1000))
    raw: dict = {}
    result, symbols = parse_expression(expression, allow_symbols=False, raw_result=raw)
    if symbols:
        # allow_symbols=False guarantees this never happens; kept for safety.
        raise UnsafeExpressionError("calc does not accept variables; use the math engine")

    if raw:
        return _raw_result(expression, raw, precision)

    try:
        exact = sympy.nsimplify(result, rational=True) if result.is_number else result
    except Exception:  # noqa: BLE001 - nsimplify can throw on exotic input
        exact = result

    try:
        decimal_value = sympy.N(exact, precision)
    except Exception as exc:  # noqa: BLE001
        raise UnsafeExpressionError(f"could not evaluate expression: {exc}") from exc

    if decimal_value.has(sympy.zoo) or decimal_value == sympy.nan:
        raise UnsafeExpressionError("division by zero or undefined result")

    is_exact = bool(exact.is_rational) if exact.is_number else False
    try:
        decimal_out: Any = float(decimal_value) if decimal_value.is_real else str(decimal_value)
    except TypeError:
        decimal_out = str(decimal_value)

    return {
        "input": expression,
        "exact": sympy.sstr(exact),
        "decimal": decimal_out,
        "digits": precision,
        "is_exact": is_exact,
        "latex": sympy.latex(exact),
    }


def _raw_result(expression: str, raw: dict, precision: int) -> dict[str, Any]:
    kind = raw["kind"]
    args = raw["args"]
    if kind == "isprime":
        n = _require_int(args[0], "isprime")
        value = bool(sympy.isprime(n))
        return {
            "input": expression,
            "exact": str(value),
            "decimal": None,
            "digits": precision,
            "is_exact": True,
            "latex": None,
            "value": value,
        }
    if kind == "nextprime":
        n = _require_int(args[0], "nextprime")
        value = int(sympy.nextprime(n))
        return {
            "input": expression,
            "exact": str(value),
            "decimal": float(value),
            "digits": precision,
            "is_exact": True,
            "latex": sympy.latex(sympy.Integer(value)),
            "value": value,
        }
    if kind == "factorint":
        n = _require_int(args[0], "factorint")
        factors = sympy.factorint(n)
        factors_str = {str(k): int(v) for k, v in factors.items()}
        exact = " * ".join(
            f"{k}^{v}" if v > 1 else str(k) for k, v in factors_str.items()
        ) or "1"
        return {
            "input": expression,
            "exact": exact,
            "decimal": None,
            "digits": precision,
            "is_exact": True,
            "latex": None,
            "factors": factors_str,
        }
    raise UnsafeExpressionError(f"unknown raw function: {kind}")


def _require_int(value: sympy.Expr, fn: str) -> int:
    if not value.is_number or not sympy.Integer(value) == value:
        raise UnsafeExpressionError(f"{fn}() needs an integer argument")
    return int(value)
