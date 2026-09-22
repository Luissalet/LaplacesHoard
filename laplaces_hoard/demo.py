"""Synthetic demo data for `--demo`: no personal data, plausible numbers.

Generates a sales CSV (~5k rows), a two-sheet Excel workbook and a Parquet
file of sensor readings, registers them in the catalogue, and seeds a
handful of notebook cells and work-log entries so the app is not empty on
first look (screenshots, quick trial).
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

import duckdb
import openpyxl

from . import db
from .engines import calc, dates, symbolic, units
from .engines.data import Catalog

_MARKER = "SEEDED_V1"


def _generate_sales_csv(path: Path, n: int = 5000) -> None:
    rng = random.Random(20260101)
    regions = ["North", "South", "East", "West", "Central"]
    products = ["Widget", "Gadget", "Gizmo", "Doohickey", "Thingamajig"]
    start = date(2024, 1, 1)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "region", "product", "units", "unit_price", "amount"])
        for i in range(n):
            d = start + timedelta(days=rng.randint(0, 640))
            region = rng.choice(regions)
            product = rng.choice(products)
            qty = rng.randint(1, 40)
            price = round(rng.uniform(5, 120), 2)
            writer.writerow([d.isoformat(), region, product, qty, price, round(qty * price, 2)])


def _generate_sensor_parquet(path: Path, n: int = 2000) -> None:
    rng = random.Random(20260202)
    csv_path = path.with_suffix(".tmp.csv")
    start = date(2026, 1, 1)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["reading_at", "sensor_id", "temperature_c", "humidity_pct"])
        for i in range(n):
            ts = start + timedelta(hours=i)
            sensor = f"sensor-{rng.randint(1, 6):02d}"
            temp = round(18 + 6 * rng.random() + (2 if 6 <= (i % 24) <= 18 else -2), 2)
            humidity = round(30 + 50 * rng.random(), 1)
            writer.writerow([ts.isoformat(), sensor, temp, humidity])
    scratch = duckdb.connect()  # in-memory: never touches the catalogue file
    try:
        src = str(csv_path).replace("'", "''")
        dst = str(path).replace("'", "''")
        scratch.execute(f"COPY (SELECT * FROM read_csv_auto('{src}')) TO '{dst}' (FORMAT PARQUET)")
    finally:
        scratch.close()
    csv_path.unlink(missing_ok=True)


def _generate_workbook(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Employees"
    ws.append(["employee_id", "department", "tenure_years", "annual_bonus_eur"])
    rng = random.Random(20260303)
    departments = ["Engineering", "Sales", "Support", "Operations"]
    for i in range(1, 41):
        ws.append([i, rng.choice(departments), round(rng.uniform(0.2, 12), 1), round(rng.uniform(500, 6000), 2)])
    ws2 = wb.create_sheet("Departments")
    ws2.append(["department", "headcount", "budget_eur"])
    for dept in departments:
        ws2.append([dept, rng.randint(5, 40), rng.randint(50_000, 400_000)])
    wb.save(path)


def seed_demo_data(app_data_dir: Path, files_dir: Path) -> None:
    app_data_dir = Path(app_data_dir)
    files_dir = Path(files_dir)
    marker = app_data_dir / ".demo_seeded"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == _MARKER:
        return

    files_dir.mkdir(parents=True, exist_ok=True)
    sales_csv = files_dir / "sales.csv"
    sensors_parquet = files_dir / "sensor_readings.parquet"
    workbook_xlsx = files_dir / "hr_snapshot.xlsx"

    catalog = Catalog(app_data_dir)
    if not sales_csv.exists():
        _generate_sales_csv(sales_csv)
    if not sensors_parquet.exists():
        _generate_sensor_parquet(sensors_parquet)
    if not workbook_xlsx.exists():
        _generate_workbook(workbook_xlsx)

    catalog.register(str(sales_csv), name="sales")
    catalog.register(str(sensors_parquet), name="sensor_readings")
    catalog.register(str(workbook_xlsx), name="hr")

    conn = db.connect(app_data_dir)

    def log(engine, operation, input_data, fn, source="ui"):
        result = fn()
        db.log_computation(
            conn, engine=engine, operation=operation, input_data=input_data,
            output_data=result, ok=True, error=None, elapsed_ms=3.0, source=source,
        )
        return result

    log("calc", "compute", {"expression": "pct(15, 2347)"}, lambda: calc.compute("pct(15, 2347)"), source="agent")
    log("calc", "compute", {"expression": "sqrt(2) + pi"}, lambda: calc.compute("sqrt(2) + pi"))
    log(
        "math", "solve",
        {"expressions": ["x**2 - 5*x + 6 == 0"], "variables": ["x"]},
        lambda: symbolic.run("solve", expressions=["x**2 - 5*x + 6 == 0"], variables=["x"]),
        source="agent",
    )
    log("units", "convert", {"quantity": "3.5 km/h", "to": "m/s"}, lambda: units.convert("3.5 km/h", "m/s"))
    log(
        "dates", "business_days",
        {"start": "2026-05-01", "end": "2026-05-15", "country": "ES", "subdivision": "MD"},
        lambda: dates.business_days("2026-05-01", "2026-05-15"),
    )
    q = "SELECT region, ROUND(SUM(amount), 2) AS total FROM sales GROUP BY region ORDER BY total DESC"
    log("data", "query", {"sql": q, "limit": 50}, lambda: catalog.query(q, 50), source="agent")

    c2 = db.add_cell(conn, engine="calc", input_text="pct_change(2500, 3120)")
    db.update_cell(conn, c2["id"], result=calc.compute("pct_change(2500, 3120)"))
    c3 = db.add_cell(conn, engine="math", input_text="factor(x**3 - x)")
    db.update_cell(conn, c3["id"], result=symbolic.run("factor", expression="x**3 - x"))
    c4 = db.add_cell(conn, engine="units", input_text="5 ft 11 in -> cm")
    db.update_cell(conn, c4["id"], result=units.convert("5 ft 11 in", "cm"))

    conn.close()
    catalog.close()  # the app opens its own Catalog on the same file next
    marker.write_text(_MARKER, encoding="utf-8")
