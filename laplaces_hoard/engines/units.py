"""Unit conversion and dimensional checking, backed by Pint.

No currencies: exchange rates change over time and need network access,
which this local-only tool does not make on its own — `convert()` raises a
clear error if the target/source look like a currency code.
"""
from __future__ import annotations

import re
from typing import Any

import pint

__all__ = ["convert", "check", "compatible", "UnitsError"]

_ureg = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
_ureg.formatter.default_format = "~P"

# "pound"/"pounds" are deliberately absent: in Pint they are the mass unit (lb).
_CURRENCY_CODES = {
    "usd", "eur", "gbp", "jpy", "cad", "aud", "chf", "cny", "mxn", "brl",
    "dollar", "dollars", "euro", "euros", "yen", "sterling",
}
_CURRENCY_SYMBOLS = ("$", "€", "£", "¥")


def _sig(x: float, digits: int = 12) -> float:
    """Round to `digits` significant digits: hides float noise like -40.000000000000064."""
    if x == 0 or x != x or x in (float("inf"), float("-inf")):
        return x
    return float(f"{x:.{digits}g}")


def _fmt(x: float) -> str:
    return f"{x:.12g}"

_COMPOUND_TOKEN = re.compile(r"(-?\d+(?:\.\d+)?)\s*([A-Za-zµ°]+)")


class UnitsError(ValueError):
    pass


def _reject_currency(text: str) -> None:
    words = re.findall(r"[A-Za-z]+", text.lower())
    if any(w in _CURRENCY_CODES for w in words) or any(sym in text for sym in _CURRENCY_SYMBOLS):
        raise UnitsError(
            "currency conversion is not supported: exchange rates change and "
            "need network access, which this local tool does not perform on its own"
        )


def _parse_quantity(text: str) -> "pint.Quantity":
    _reject_currency(text)
    text = text.strip()
    matches = _COMPOUND_TOKEN.findall(text)
    reconstructed = " ".join(f"{n} {u}".strip() for n, u in matches)
    if matches and len(matches) > 1 and reconstructed.replace("  ", " ") == text.replace("  ", " "):
        total = None
        for n, u in matches:
            q = _ureg.Quantity(float(n), u)
            total = q if total is None else total + q
        return total
    try:
        return _ureg.Quantity(text)
    except Exception as exc:  # noqa: BLE001
        raise UnitsError(f"could not parse quantity: {text!r} ({exc})") from exc


def convert(quantity: str, to: str) -> dict[str, Any]:
    q = _parse_quantity(quantity)
    _reject_currency(to)
    try:
        target = _ureg.Unit(to)
    except Exception as exc:  # noqa: BLE001
        raise UnitsError(f"unknown target unit: {to!r} ({exc})") from exc
    try:
        result = q.to(target)
    except pint.DimensionalityError as exc:
        raise UnitsError(
            f"cannot convert {q.units} to {target}: dimensions differ ({exc})"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - e.g. offset-unit arithmetic
        raise UnitsError(f"cannot convert {quantity!r} to {to!r}: {exc}") from exc
    try:
        from_mag = float(q.magnitude)
        to_mag = float(result.magnitude)
    except (TypeError, ValueError) as exc:
        raise UnitsError("only single numeric quantities can be converted (no arrays)") from exc
    return {
        "input": quantity,
        "to": to,
        "from_magnitude": _sig(from_mag),
        "from_unit": str(q.units),
        "to_magnitude": _sig(to_mag),
        "to_unit": str(result.units),
        "formatted": f"{_fmt(to_mag)} {result.units:~P}",
        "precision_note": "floating-point conversion, rounded to 12 significant digits",
    }


def check(expression: str) -> dict[str, Any]:
    """Check dimensional consistency, e.g. `"3 m/s * 2 s" -> length` OK, wrong units flagged."""
    try:
        q = _ureg.parse_expression(expression)
    except pint.DimensionalityError as exc:
        raise UnitsError(f"dimensionally inconsistent: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise UnitsError(f"could not parse expression: {expression!r} ({exc})") from exc
    dim = q.dimensionality if hasattr(q, "dimensionality") else pint.util.UnitsContainer()
    try:
        magnitude = float(q.magnitude) if hasattr(q, "magnitude") else float(q)
    except (TypeError, ValueError) as exc:
        raise UnitsError(f"could not evaluate {expression!r} to a single quantity") from exc
    return {
        "input": expression,
        "dimensionality": str(dim) if str(dim) else "dimensionless",
        "magnitude": _sig(magnitude),
        "units": str(q.units) if hasattr(q, "units") else "dimensionless",
    }


def compatible(unit: str) -> dict[str, Any]:
    try:
        u = _ureg.Unit(unit)
    except Exception as exc:  # noqa: BLE001
        raise UnitsError(f"unknown unit: {unit!r} ({exc})") from exc
    names = sorted(str(x) for x in _ureg.get_compatible_units(u))
    return {"unit": unit, "dimensionality": str(u.dimensionality), "compatible": names[:50], "count": len(names)}
