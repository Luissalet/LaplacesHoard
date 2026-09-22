from laplaces_hoard.engines import dates


def test_business_days_excludes_madrid_holiday():
    """2026-05-01 is a public holiday in Madrid (Labour Day) and must not be counted."""
    r = dates.business_days("2026-05-01", "2026-05-15", country="ES", subdivision="MD")
    assert any(h["date"] == "2026-05-01" for h in r["holidays_excluded"])
    # Fri 1 (holiday, excluded) .. through Thu 14: weekdays are 1,4,5,6,7,8,11,12,13,14
    # minus the holiday on the 1st -> 9 counted business days.
    assert r["business_days"] == 9


def test_diff_calendar_aware():
    r = dates.diff("2026-01-31", "2026-03-01")
    assert r["calendar"]["months"] == 1
    assert r["calendar"]["days"] == 1


def test_add_days():
    r = dates.add("2026-09-22", days=10)
    assert r["result"] == "2026-10-02"


def test_weekday_and_iso_week():
    w = dates.weekday("2026-09-22")
    assert w["weekday"] == "Tuesday"
    iso = dates.iso_week("2026-09-22")
    assert iso["iso_week"] == 39


def test_age_calculation():
    r = dates.age("1990-05-15", on="2026-09-22")
    assert r["years"] == 36


def test_convert_tz_handles_offset():
    r = dates.convert_tz("2026-09-22 14:00", from_tz="Europe/Madrid", to_tz="America/New_York")
    assert r["result"].startswith("2026-09-22T08:00:00")


def test_parse_iso_date():
    r = dates.parse("2026-09-22")
    assert r["date"] == "2026-09-22"
