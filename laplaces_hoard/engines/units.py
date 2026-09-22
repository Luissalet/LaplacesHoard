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

_CURRENCY_CODES = {
    "usd", "eur", "gbp", "jpy", "cad", "aud", "chf", "cny", "mxn", "brl",
    "dollar", "dollars", "euro", "euros", "pound", "pounds", "yen",
}

_COMPOUND_TOKEN = re.compile(r"(-?\d+(?:\.\d+)?)\s*([A-Za-zµ°]+)")


class UnitsError(ValueError):
    pass


def _reject_currency(text: str) -> None:
    words = re.findall(r"[A-Za-z]+", text.lower())
    if any(w in _CURRENCY_CODES for w in words):
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
    return {
        "input": quantity,
        "to": to,
        "from_magnitude": float(q.magnitude),
        "from_unit": str(q.units),
        "to_magnitude": float(result.magnitude),
        "to_unit": str(result.units),
        "formatted": f"{result.magnitude:g} {result.units:~P}",
    }


def check(expression: str) -> dict[str, Any]:
    """Check dimensional consistency, e.g. `"3 m/s * 2 s" -> length` OK, wrong units flagged."""
    try:
        q = _ureg.parse_expression(expression)
    except Exception as exc:  # noqa: BLE001
        raise UnitsError(f"could not parse expression: {expression!r} ({exc})") from exc
    dim = q.dimensionality if hasattr(q, "dimensionality") else pint.util.UnitsContainer()
    return {
        "input": expression,
        "dimensionality": str(dim),
        "magnitude": float(q.magnitude) if hasattr(q, "magnitude") else float(q),
        "units": str(q.units) if hasattr(q, "units") else "dimensionless",
    }


def compatible(unit: str) -> dict[str, Any]:
    try:
        u = _ureg.Unit(unit)
    except Exception as exc:  # noqa: BLE001
        raise UnitsError(f"unknown unit: {unit!r} ({exc})") from exc
    names = sorted(str(x) for x in _ureg.get_compatible_units(u))
    return {"unit": unit, "dimensionality": str(u.dimensionality), "compatible": names[:50], "count": len(names)}
