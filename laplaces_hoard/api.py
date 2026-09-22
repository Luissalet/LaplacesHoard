"""FastAPI application: HTTP surface for the UI and the MCP adapter.

`create_app(data_dir, static_dir, port)` builds the app. All the actual
computation lives in `engines/*` (no FastAPI imports there); this module
wires HTTP requests to those functions, logs every call to the work log,
and serves the built frontend.
"""
from __future__ import annotations

import base64
import re
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .engines import calc, charts, dates, stats, symbolic, units
from .engines.data import Catalog, DataError, SQLGateError
from .engines.safe_ast import UnsafeExpressionError
from .engines.stats import StatsError
from .engines.symbolic import SymbolicError
from .engines.units import UnitsError
from .engines.dates import DateError
from .engines.charts import ChartError
from .security import BrowserGuardMiddleware

__version__ = "0.1.0"
SERVICE_SLUG = "laplaces-hoard"
DISPLAY_NAME = "Laplace's Hoard"

_ENGINE_ERRORS = (
    UnsafeExpressionError, SymbolicError, UnitsError, DateError,
    StatsError, DataError, SQLGateError, ChartError,
)


def _error_code(exc: Exception) -> str:
    name = type(exc).__name__
    name = name.removesuffix("Error") or name
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return s2.lower() or "error"


class AppState:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.conn = db.connect(data_dir)
        self.catalog = Catalog(data_dir)


# ---------------------------------------------------------------------- #
# request bodies
#
# Defined at module level (not inside create_app) so FastAPI can resolve
# their string annotations under `from __future__ import annotations` —
# a class local to a function is invisible to `typing.get_type_hints`,
# which silently makes FastAPI treat the parameter as a query field
# instead of the JSON body.
# ---------------------------------------------------------------------- #


class CalcBody(BaseModel):
    expression: str
    precision: int = 15


class MathBody(BaseModel):
    operation: str
    expression: Optional[str] = None
    expressions: Optional[list[str]] = None
    variable: Optional[str] = None
    variables: Optional[list[str]] = None
    domain: str = "real"
    order: Optional[int] = None
    lower: Optional[Any] = None
    upper: Optional[Any] = None
    point: Optional[Any] = None
    direction: Optional[str] = None
    x0: Optional[float] = None
    matrix_op: Optional[str] = None
    matrix: Optional[list[list[str]]] = None
    matrix2: Optional[list[list[str]]] = None
    function: Optional[str] = None
    timeout: float = 10.0


class UnitsConvertBody(BaseModel):
    quantity: str
    to: str


class UnitsCheckBody(BaseModel):
    expression: str


class StatsBody(BaseModel):
    test: str
    data: Optional[list[Any]] = None
    data2: Optional[list[Any]] = None
    dataset: Optional[str] = None
    column: Optional[str] = None
    column2: Optional[str] = None
    group_by: Optional[str] = None
    where: Optional[str] = None
    mu: float = 0.0
    confidence: float = 0.95
    successes: Optional[int] = None
    trials: Optional[int] = None
    p0: float = 0.5


class DateCalcBody(BaseModel):
    operation: str
    start: Optional[str] = None
    end: Optional[str] = None
    value: Optional[str] = None
    unit: str = "days"
    days: int = 0
    weeks: int = 0
    months: int = 0
    years: int = 0
    country: str = "ES"
    subdivision: Optional[str] = "MD"
    birth_date: Optional[str] = None
    on: Optional[str] = None
    from_tz: Optional[str] = None
    to_tz: Optional[str] = None
    text: Optional[str] = None


class DataRegisterBody(BaseModel):
    path: str
    name: Optional[str] = None
    options: Optional[dict] = None


class DataDescribeBody(BaseModel):
    name: str


class DataQueryBody(BaseModel):
    sql: str
    limit: int = 50


class DataChartBody(BaseModel):
    sql: str
    kind: str
    x: str
    y: Optional[str] = None
    color: Optional[str] = None
    title: Optional[str] = None


class WorkLogQuery(BaseModel):
    limit: int = 10
    engine: Optional[str] = None
    query: Optional[str] = None


class CellBody(BaseModel):
    engine: str
    input: str


def create_app(data_dir: Path, static_dir: Optional[Path] = None, port: int = 8812) -> FastAPI:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    state = AppState(data_dir)

    app = FastAPI(title=DISPLAY_NAME, version=__version__)
    app.add_middleware(BrowserGuardMiddleware, port=port)
    app.state.lh = state

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _record(engine: str, operation: str, input_data: Any, source: str, fn):
        start = time.monotonic()
        try:
            output = fn()
        except _ENGINE_ERRORS as exc:
            elapsed = (time.monotonic() - start) * 1000
            db.log_computation(
                state.conn, engine=engine, operation=operation, input_data=input_data,
                output_data=None, ok=False, error=str(exc), elapsed_ms=elapsed, source=source,
            )
            raise HTTPException(status_code=400, detail={"error": _error_code(exc), "message": str(exc)}) from exc
        elapsed = (time.monotonic() - start) * 1000
        chart_path = output.get("_chart_path") if isinstance(output, dict) else None
        loggable = {k: v for k, v in output.items() if k != "_chart_path"} if isinstance(output, dict) else output
        cid = db.log_computation(
            state.conn, engine=engine, operation=operation, input_data=input_data,
            output_data=loggable, ok=True, error=None, elapsed_ms=elapsed, source=source,
            chart_path=chart_path,
        )
        if isinstance(output, dict):
            return {**loggable, "id": cid, "cite": f"[{cid}]"}
        return {"result": output, "id": cid, "cite": f"[{cid}]"}

    def agent(engine: str, operation: str, input_data: Any, fn):
        return _record(engine, operation, input_data, "agent", fn)

    def ui(engine: str, operation: str, input_data: Any, fn):
        return _record(engine, operation, input_data, "ui", fn)

    # ------------------------------------------------------------------ #
    # health
    # ------------------------------------------------------------------ #

    @app.get("/api/health")
    def health():
        n_computations = state.conn.execute("SELECT COUNT(*) AS n FROM computations").fetchone()["n"]
        n_datasets = len(state.catalog.list_datasets())
        return {
            "service": SERVICE_SLUG,
            "name": DISPLAY_NAME,
            "version": __version__,
            "status": "ok",
            "computations_logged": n_computations,
            "datasets_registered": n_datasets,
        }

    # ------------------------------------------------------------------ #
    # agent-facing operations  (POST /api/agent/<tool>)
    # ------------------------------------------------------------------ #

    @app.post("/api/agent/calc")
    def agent_calc(body: CalcBody):
        return agent("calc", "compute", body.model_dump(), lambda: calc.compute(body.expression, body.precision))

    @app.post("/api/agent/math")
    def agent_math(body: MathBody):
        payload = body.model_dump(exclude_none=True)
        op = payload.pop("operation")
        timeout = payload.pop("timeout", 10.0)
        if "expressions" not in payload and "expression" in payload and op == "solve":
            payload["expressions"] = [payload.pop("expression")]
        return agent("math", op, body.model_dump(), lambda: symbolic.run(op, timeout=timeout, **payload))

    @app.post("/api/agent/units_convert")
    def agent_units_convert(body: UnitsConvertBody):
        return agent("units", "convert", body.model_dump(), lambda: units.convert(body.quantity, body.to))

    @app.post("/api/agent/stats")
    def agent_stats(body: StatsBody):
        payload = body.model_dump(exclude={"test"})
        return agent(
            "stats", body.test, body.model_dump(),
            lambda: stats.run(body.test, catalog=state.catalog, **payload),
        )

    @app.post("/api/agent/date_calc")
    def agent_date_calc(body: DateCalcBody):
        return agent("dates", body.operation, body.model_dump(), lambda: _dispatch_date(body))

    @app.post("/api/agent/data_list")
    def agent_data_list():
        return agent("data", "list", {}, lambda: {"datasets": state.catalog.list_datasets()})

    @app.post("/api/agent/data_register")
    def agent_data_register(body: DataRegisterBody):
        return agent(
            "data", "register", body.model_dump(),
            lambda: state.catalog.register(body.path, body.name, body.options),
        )

    @app.post("/api/agent/data_describe")
    def agent_data_describe(body: DataDescribeBody):
        return agent("data", "describe", body.model_dump(), lambda: state.catalog.describe(body.name))

    @app.post("/api/agent/data_query")
    def agent_data_query(body: DataQueryBody):
        return agent("data", "query", body.model_dump(), lambda: state.catalog.query(body.sql, body.limit))

    @app.post("/api/agent/data_chart")
    def agent_data_chart(body: DataChartBody):
        def _run():
            chart_dir = state.data_dir / "charts"
            out_path = chart_dir / f"chart_{int(time.time() * 1000)}.png"
            result = charts.build_chart(
                state.catalog, body.sql, body.kind, body.x, body.y, body.color, body.title, out_path=out_path
            )
            return {
                "spec": result["spec"],
                "spec_summary": {
                    "mark": result["spec"]["mark"],
                    "encoding": list(result["spec"]["encoding"].keys()),
                },
                "row_count": result["row_count"],
                "truncated": result["truncated"],
                "png_base64": base64.b64encode(result["png_bytes"]).decode("ascii"),
                "_chart_path": str(out_path),
            }
        return agent("data", "chart", body.model_dump(), _run)

    @app.post("/api/agent/work_log")
    def agent_work_log(body: WorkLogQuery):
        items = db.list_computations(state.conn, limit=body.limit, engine=body.engine, query=body.query)
        return {"items": items, "count": len(items)}

    # ------------------------------------------------------------------ #
    # UI-facing richer endpoints
    # ------------------------------------------------------------------ #

    @app.get("/api/log")
    def get_log(limit: int = 20, engine: Optional[str] = None, source: Optional[str] = None, query: Optional[str] = None):
        return {"items": db.list_computations(state.conn, limit=limit, engine=engine, query=query, source=source)}

    @app.get("/api/log/{cid}")
    def get_log_item(cid: str):
        item = db.get_computation(state.conn, cid)
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"no computation {cid}"})
        return item

    @app.post("/api/log/{cid}/rerun")
    def rerun_log_item(cid: str):
        item = db.get_computation(state.conn, cid)
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"no computation {cid}"})
        engine_name = item["engine"]
        input_data = item["input"] or {}
        dispatch = {
            "calc": lambda: calc.compute(input_data.get("expression", ""), input_data.get("precision", 15)),
            "units": lambda: units.convert(input_data.get("quantity", ""), input_data.get("to", "")),
            "dates": lambda: _dispatch_date_dict(item["operation"], input_data),
            "data": lambda: _rerun_data(item["operation"], input_data),
        }
        if engine_name == "math":
            payload = dict(input_data)
            op = payload.pop("operation", item["operation"])
            timeout = payload.pop("timeout", 10.0)
            payload = {k: v for k, v in payload.items() if v is not None}
            if op == "solve" and "expressions" not in payload and "expression" in payload:
                payload["expressions"] = [payload.pop("expression")]
            fn = lambda: symbolic.run(op, timeout=timeout, **payload)  # noqa: E731
        elif engine_name == "stats":
            payload = {k: v for k, v in input_data.items() if k != "test" and v is not None}
            fn = lambda: stats.run(input_data.get("test", item["operation"]), catalog=state.catalog, **payload)  # noqa: E731
        elif engine_name in dispatch:
            fn = dispatch[engine_name]
        else:
            raise HTTPException(status_code=400, detail={"error": "not_rerunnable", "message": f"engine {engine_name} cannot be re-run"})
        return ui(engine_name, item["operation"], input_data, fn)

    @app.get("/api/datasets")
    def list_datasets():
        return {"datasets": state.catalog.list_datasets()}

    @app.get("/api/datasets/{name}")
    def describe_dataset(name: str):
        return ui("data", "describe", {"name": name}, lambda: state.catalog.describe(name))

    @app.post("/api/units/check")
    def units_check(body: UnitsCheckBody):
        return ui("units", "check", body.model_dump(), lambda: units.check(body.expression))

    @app.get("/api/units/compatible")
    def units_compatible(unit: str):
        return ui("units", "compatible", {"unit": unit}, lambda: units.compatible(unit))

    @app.get("/api/agent-calls")
    def agent_calls(limit: int = 20):
        return {"items": db.list_computations(state.conn, limit=limit, source="agent")}

    @app.get("/api/cells")
    def list_cells():
        return {"cells": db.list_cells(state.conn)}

    @app.post("/api/cells")
    def create_cell(body: CellBody):
        cell = db.add_cell(state.conn, engine=body.engine, input_text=body.input)
        try:
            result = _run_cell(body.engine, body.input)
            db.update_cell(state.conn, cell["id"], result=result)
            cell["result"] = result
        except _ENGINE_ERRORS as exc:
            error_result = {"error": _error_code(exc), "message": str(exc)}
            db.update_cell(state.conn, cell["id"], result=error_result)
            cell["result"] = error_result
        return cell

    @app.delete("/api/cells/{cell_id}")
    def remove_cell(cell_id: int):
        ok = db.delete_cell(state.conn, cell_id)
        if not ok:
            raise HTTPException(status_code=404, detail={"error": "not_found", "message": "no such cell"})
        return {"deleted": True}

    def _run_cell(engine_name: str, text: str) -> dict:
        if engine_name == "calc":
            return ui("calc", "compute", {"expression": text}, lambda: calc.compute(text))
        if engine_name == "math":
            return ui("math", "simplify", {"expression": text}, lambda: symbolic.run("simplify", expression=text))
        if engine_name == "units":
            if "->" in text:
                q, to = text.split("->", 1)
                return ui("units", "convert", {"quantity": q.strip(), "to": to.strip()},
                           lambda: units.convert(q.strip(), to.strip()))
            return ui("units", "check", {"expression": text}, lambda: units.check(text))
        if engine_name == "dates":
            return ui("dates", "parse", {"text": text}, lambda: dates.parse(text))
        raise HTTPException(status_code=400, detail={"error": "unknown_engine", "message": f"unknown cell engine {engine_name}"})

    def _dispatch_date(body: "DateCalcBody") -> dict:
        return _dispatch_date_dict(body.operation, body.model_dump())

    def _dispatch_date_dict(operation: str, d: dict) -> dict:
        if operation == "diff":
            return dates.diff(d["start"], d["end"], d.get("unit", "days"))
        if operation == "add":
            return dates.add(d["start"], days=d.get("days", 0), weeks=d.get("weeks", 0), months=d.get("months", 0), years=d.get("years", 0))
        if operation == "business_days":
            return dates.business_days(d["start"], d["end"], country=d.get("country", "ES"), subdivision=d.get("subdivision", "MD"))
        if operation == "weekday":
            return dates.weekday(d["value"])
        if operation == "iso_week":
            return dates.iso_week(d["value"])
        if operation == "age":
            return dates.age(d["birth_date"], on=d.get("on"))
        if operation == "convert_tz":
            return dates.convert_tz(d["value"], from_tz=d["from_tz"], to_tz=d["to_tz"])
        if operation == "parse":
            return dates.parse(d.get("text") or d.get("value", ""))
        raise DateError(f"unknown date operation: {operation}")

    def _rerun_data(operation: str, input_data: dict) -> dict:
        if operation == "query":
            return state.catalog.query(input_data.get("sql", ""), input_data.get("limit", 50))
        if operation == "describe":
            return state.catalog.describe(input_data.get("name", ""))
        if operation == "list":
            return {"datasets": state.catalog.list_datasets()}
        raise DataError(f"cannot re-run data operation: {operation}")

    # ------------------------------------------------------------------ #
    # static frontend
    # ------------------------------------------------------------------ #

    if static_dir is not None and Path(static_dir).is_dir():
        index_path = Path(static_dir) / "index.html"

        app.mount("/assets", StaticFiles(directory=Path(static_dir) / "assets"), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            candidate = Path(static_dir) / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_path)
    else:
        @app.get("/")
        def no_frontend():
            return HTMLResponse(
                "<html><body style='font-family:sans-serif;padding:2rem'>"
                "<h1>Laplace's Hoard</h1>"
                "<p>The frontend has not been built yet. Run:</p>"
                "<pre>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</pre>"
                "<p>API is live at <a href='/api/health'>/api/health</a>.</p>"
                "</body></html>"
            )

    return app
