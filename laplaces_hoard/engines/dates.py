"""Date arithmetic: differences, business days, time zones, ages.

Business-day counting excludes weekends and public holidays via the
`holidays` package (default country Spain, subdivision Madrid, both
overridable per call) — a sensible default for a Spanish user, made configurable
because the app is meant to travel.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import holidays as holidays_pkg
from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta

__all__ = ["diff", "add", "business_days", "weekday", "iso_week", "age", "convert_tz", "parse", "DateError"]

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class DateError(ValueError):
    pass


def parse(text: str) -> dict[str, Any]:
    try:
        dt = dateutil_parser.parse(text)
    except (ValueError, OverflowError) as exc:
        raise DateError(f"could not parse date: {text!r} ({exc})") from exc
    return {"input": text, "iso": dt.isoformat(), "date": dt.date().isoformat(), "has_time": _has_time(text)}


def _has_time(text: str) -> bool:
    return ":" in text


def _to_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return dateutil_parser.parse(value).date()
        except (ValueError, OverflowError) as exc:
            raise DateError(f"could not parse date: {value!r} ({exc})") from exc
    raise DateError(f"unsupported date value: {value!r}")


def diff(start: str, end: str, unit: str = "days") -> dict[str, Any]:
    d1, d2 = _to_date(start), _to_date(end)
    delta_days = (d2 - d1).days
    rd = relativedelta(d2, d1)
    result: dict[str, Any] = {
        "start": d1.isoformat(),
        "end": d2.isoformat(),
        "days": delta_days,
        "weeks": delta_days / 7,
        "calendar": {"years": rd.years, "months": rd.months, "days": rd.days},
    }
    if unit == "days":
        result["result"] = delta_days
    elif unit == "weeks":
        result["result"] = delta_days / 7
    elif unit in ("months", "years"):
        result["result"] = rd.years * 12 + rd.months if unit == "months" else rd.years + rd.months / 12
    else:
        raise DateError(f"unknown unit: {unit}; use days, weeks, months or years")
    return result


def add(start: str, *, days: int = 0, weeks: int = 0, months: int = 0, years: int = 0) -> dict[str, Any]:
    d = _to_date(start)
    result = d + relativedelta(years=years, months=months, weeks=weeks, days=days)
    return {"start": d.isoformat(), "result": result.isoformat(), "weekday": _WEEKDAYS[result.weekday()]}


def weekday(value: str) -> dict[str, Any]:
    d = _to_date(value)
    return {"date": d.isoformat(), "weekday": _WEEKDAYS[d.weekday()], "iso_weekday": d.isoweekday(), "is_weekend": d.weekday() >= 5}


def iso_week(value: str) -> dict[str, Any]:
    d = _to_date(value)
    iso = d.isocalendar()
    return {"date": d.isoformat(), "iso_year": iso[0], "iso_week": iso[1], "iso_weekday": iso[2]}


def business_days(
    start: str,
    end: str,
    *,
    country: str = "ES",
    subdivision: Optional[str] = "MD",
) -> dict[str, Any]:
    d1, d2 = _to_date(start), _to_date(end)
    if d2 < d1:
        d1, d2 = d2, d1
    try:
        hol = holidays_pkg.country_holidays(country, subdiv=subdivision, years=range(d1.year, d2.year + 2))
    except NotImplementedError:
        hol = holidays_pkg.country_holidays(country, years=range(d1.year, d2.year + 2))
    count = 0
    holiday_hits = []
    cur = d1
    while cur < d2:
        if cur.weekday() < 5 and cur not in hol:
            count += 1
        elif cur.weekday() < 5 and cur in hol:
            holiday_hits.append({"date": cur.isoformat(), "name": hol.get(cur)})
        cur += timedelta(days=1)
    return {
        "start": d1.isoformat(),
        "end": d2.isoformat(),
        "country": country,
        "subdivision": subdivision,
        "business_days": count,
        "holidays_excluded": holiday_hits,
    }


def age(birth_date: str, *, on: Optional[str] = None) -> dict[str, Any]:
    d = _to_date(birth_date)
    ref = _to_date(on) if on else date.today()
    rd = relativedelta(ref, d)
    return {
        "birth_date": d.isoformat(),
        "on": ref.isoformat(),
        "years": rd.years,
        "months": rd.months,
        "days": rd.days,
        "total_days": (ref - d).days,
    }


def convert_tz(value: str, *, from_tz: str, to_tz: str) -> dict[str, Any]:
    try:
        dt = dateutil_parser.parse(value)
    except (ValueError, OverflowError) as exc:
        raise DateError(f"could not parse datetime: {value!r} ({exc})") from exc
    try:
        src = ZoneInfo(from_tz)
        dst = ZoneInfo(to_tz)
    except Exception as exc:  # noqa: BLE001
        raise DateError(f"unknown time zone ({exc})") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=src)
    converted = dt.astimezone(dst)
    return {
        "input": value,
        "from_tz": from_tz,
        "to_tz": to_tz,
        "result": converted.isoformat(),
        "utc_offset_hours": converted.utcoffset().total_seconds() / 3600 if converted.utcoffset() else 0,
    }
