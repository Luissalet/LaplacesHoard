"""FastAPI application: HTTP surface for the UI and the MCP adapter.

`create_app(data_dir, static_dir, port)` builds the app. All the actual
computation lives in `engines/*` (no FastAPI imports there); this module
wires HTTP requests to those functions, logs every call to the work log,
and serves the built frontend.
"""
from __future__ import annotations

import base64
import csv
import io
import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Union

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import backend as backend_mod
from . import db
from .engines import ask as ask_engine
from .engines import calc, charts, dates, sandbox, stats, symbolic, units
from .engines.calc import CalcError
from .engines.data import Catalog, DataError, SQLGateError
from .engines.safe_ast import UnsafeExpressionError
from .engines.stats import StatsError
from .engines.symbolic import SymbolicError
from .engines.units import UnitsError
from .engines.dates import DateError
from .engines.charts import ChartError
from .hoard_link import Link
from .security import BrowserGuardMiddleware

__version__ = "0.1.0"
SERVICE_SLUG = "laplaces-hoard"
DISPLAY_NAME = "Laplace's Hoard"

_ENGINE_ERRORS = (
    UnsafeExpressionError, CalcError, SymbolicError, UnitsError, DateError,
    StatsError, DataError, SQLGateError, ChartError,
)


def _error_code(exc: Exception) -> str:
    name = type(exc).__name__
    name = name.removesuffix("Error") or name
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return s2.lower() or "error"


log = logging.getLogger("laplaces_hoard")


def _setup_logging(data_dir: Path) -> None:
    """Rotating log at <data>/logs/app.log: call summaries and errors, never file contents."""
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    target = str((log_dir / "app.log").resolve())
    for h in log.handlers:
        if isinstance(h, RotatingFileHandler) and h.baseFilename == target:
            return
    handler = RotatingFileHandler(target, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(x) for x in err.get("loc", ()) if x != "body")
        parts.append(f"{loc or 'body'}: {err.get('msg', 'invalid')}")
    return "invalid arguments: " + "; ".join(parts)


def _calc(expression: str, precision: int = 15) -> dict:
    """calc runs in the timeout worker: `9**9**9**9` must not pin a server thread."""
    return sandbox.run("calc", {"expression": expression, "precision": precision}, error_cls=CalcError)


def _units(op: str, **payload: Any) -> dict:
    """Pint evaluates `**` too ("10**10**10 m"), so units share the same worker."""
    return sandbox.run(f"units.{op}", payload, error_cls=UnitsError)


def _dataset_brief(d: dict) -> dict:
    """data_list entry: enough to pick a dataset, small enough for a 27B context."""
    cols = [c["name"] for c in d.get("columns", [])]
    out = {"name": d["name"], "kind": d["kind"], "row_count": d["row_count"],
           "column_count": len(cols), "columns": cols[:30], "source_path": d["source_path"]}
    if len(cols) > 30:
        out["columns_truncated"] = True
    return out


class AppState:
    def __init__(self, data_dir: Path, link_factory: Optional[Callable[[], Link]] = None):
        self.data_dir = data_dir
        self.conn = db.connect(data_dir)
        self.catalog = Catalog(data_dir)
        # One Link per app, closed on shutdown. The factory is also what
        # "save config" and "re-check" use to rebuild it, so a test's
        # factory (a Link backed by httpx.MockTransport) keeps every
        # rebuilt Link offline too.
        self.link_factory = link_factory or (lambda: backend_mod.load_link(data_dir))
        self.link = self.link_factory()

    async def rebuild_link(self) -> None:
        """A fresh Link: picks up a saved config and starts with an empty probe cache."""
        old, self.link = self.link, self.link_factory()
        await old.aclose()


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
    matrix: Optional[list[list[Union[str, int, float]]]] = None
    matrix2: Optional[list[list[Union[str, int, float]]]] = None
    function: Optional[str] = None
    timeout: float = Field(default=10.0, ge=0.1, le=60.0)


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
    subdivision: Optional[str] = None  # ES without a subdivision means Madrid (MD)
    include_end: bool = True
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


class CapabilityOverride(BaseModel):
    # Only what the Settings form edits; "" clears a field. Anything else
    # (e.g. a `command` to run) is rejected rather than written to disk.
    model_config = ConfigDict(extra="forbid")
    url: Optional[str] = None
    model: Optional[str] = None


class BackendConfigBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    faustus_url: Optional[str] = None
    faustus_token: Optional[str] = None
    only_resident: Optional[bool] = None
    capabilities: Optional[dict[Literal["llm"], CapabilityOverride]] = None


class AskBody(BaseModel):
    question: str
    datasets: list[str] = Field(default_factory=list)


def create_app(
    data_dir: Path,
    static_dir: Optional[Path] = None,
    port: int = 8812,
    link_factory: Optional[Callable[[], Link]] = None,
) -> FastAPI:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    state = AppState(data_dir, link_factory=link_factory)

    _setup_logging(data_dir)
    # start the computation worker now (SymPy/Pint imports take seconds on
    # Windows) so the model's first calc call does not pay for it
    threading.Thread(target=sandbox.warm_up, name="laplace-warmup", daemon=True).start()

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        yield
        await state.link.aclose()

    app = FastAPI(title=DISPLAY_NAME, version=__version__, lifespan=_lifespan)
    app.add_middleware(BrowserGuardMiddleware, port=port)
    app.state.lh = state

    # Errors always come back as {"error": "<code>", "message": "<actionable text>"}.
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            body = detail
        else:
            body = {"error": "http_error" if exc.status_code != 404 else "not_found", "message": str(detail)}
        return JSONResponse(body, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse({"error": "invalid_arguments", "message": _validation_message(exc)}, status_code=422)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _log_failure(engine: str, operation: str, input_data: Any, source: str, start: float, exc: Exception):
        """Log a failed operation in the work log and raise the JSON error the API answers with."""
        elapsed = (time.monotonic() - start) * 1000
        if isinstance(exc, _ENGINE_ERRORS):
            db.log_computation(
                state.conn, engine=engine, operation=operation, input_data=input_data,
                output_data=None, ok=False, error=str(exc), elapsed_ms=elapsed, source=source,
            )
            log.info("%s %s.%s error %s", source, engine, operation, _error_code(exc))
            raise HTTPException(status_code=400, detail={"error": _error_code(exc), "message": str(exc)}) from exc
        # an engine bug must still answer in JSON and be logged
        message = f"{type(exc).__name__}: {exc}"[:500]
        db.log_computation(
            state.conn, engine=engine, operation=operation, input_data=input_data,
            output_data=None, ok=False, error=message, elapsed_ms=elapsed, source=source,
        )
        log.exception("%s %s.%s failed unexpectedly", source, engine, operation)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"unexpected failure in {engine}.{operation}: {message}"},
        ) from exc

    def _log_success(engine: str, operation: str, input_data: Any, source: str, start: float, output: Any):
        elapsed = (time.monotonic() - start) * 1000
        # "_chart_path" goes to its own column; "_response_extra" (PNG bytes,
        # full chart spec) is returned but never written to the work log.
        chart_path = output.get("_chart_path") if isinstance(output, dict) else None
        extra = output.get("_response_extra", {}) if isinstance(output, dict) else {}
        loggable = {k: v for k, v in output.items() if not k.startswith("_")} if isinstance(output, dict) else output
        cid = db.log_computation(
            state.conn, engine=engine, operation=operation, input_data=input_data,
            output_data=loggable, ok=True, error=None, elapsed_ms=elapsed, source=source,
            chart_path=chart_path,
        )
        if isinstance(output, dict):
            return {"id": cid, "cite": f"[{cid}]", **loggable, **extra}
        return {"id": cid, "cite": f"[{cid}]", "result": output}

    def _record(engine: str, operation: str, input_data: Any, source: str, fn):
        start = time.monotonic()
        try:
            output = fn()
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - _log_failure answers every failure in JSON
            _log_failure(engine, operation, input_data, source, start, exc)
        return _log_success(engine, operation, input_data, source, start, output)

    def ui(engine: str, operation: str, input_data: Any, fn):
        return _record(engine, operation, input_data, "ui", fn)

    async def _arecord(engine: str, operation: str, input_data: Any, source: str, fn):
        """Async twin of `_record`, for the one feature (`ask`) whose engine call must be awaited."""
        start = time.monotonic()
        try:
            output = await fn()
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - _log_failure answers every failure in JSON
            _log_failure(engine, operation, input_data, source, start, exc)
        return _log_success(engine, operation, input_data, source, start, output)

    # ------------------------------------------------------------------ #
    # health
    # ------------------------------------------------------------------ #

    @app.get("/api/health")
    def health():
        n_computations = state.conn.execute("SELECT COUNT(*) AS n FROM computations").fetchone()["n"]
        n_datasets = state.catalog.dataset_count()
        return {
            "service": SERVICE_SLUG,
            "name": DISPLAY_NAME,
            "version": __version__,
            "status": "ok",
            "computations_logged": n_computations,
            "datasets_registered": n_datasets,
        }

    # ------------------------------------------------------------------ #
    # shared model backend (Hoard Link): Settings -> Models panel
    # ------------------------------------------------------------------ #

    @app.get("/api/backend")
    async def get_backend():
        status = await state.link.status()
        return {
            "capabilities": {cap: status[cap] for cap in backend_mod.USED_CAPABILITIES},
            "config": {
                "only_resident": state.link.config.only_resident,
                "faustus_urls": list(state.link.config.faustus_urls),
                "token_set": backend_mod.token_set(state.data_dir),
                # what data/backend.json holds (never the token), so the form can show and clear it
                "saved": backend_mod.saved_overrides(state.data_dir),
                "error": backend_mod.config_error(state.data_dir),
            },
            "app": backend_mod.app_backends(),
        }

    @app.put("/api/backend/config")
    async def put_backend_config(body: BackendConfigBody):
        backend_mod.save_config(
            state.data_dir, faustus_url=body.faustus_url, faustus_token=body.faustus_token,
            only_resident=body.only_resident,
            capabilities={cap: o.model_dump(exclude_unset=True) for cap, o in (body.capabilities or {}).items()},
        )
        # rebuild the Link so the new config applies immediately, without restarting the app
        await state.rebuild_link()
        return {"ok": True, "token_set": backend_mod.token_set(state.data_dir)}

    @app.post("/api/backend/recheck")
    async def recheck_backend():
        # a fresh Link has an empty probe cache, which is what "re-check now" means
        await state.rebuild_link()
        status = await state.link.status()
        return {cap: status[cap] for cap in backend_mod.USED_CAPABILITIES}

    # ------------------------------------------------------------------ #
    # tool operations: POST /api/agent/<tool> (the MCP adapter, logged as
    # source "agent") and the identical POST /api/ui/<tool> (the web UI,
    # logged as "ui") — so "Assistant activity" only ever shows the model.
    # ------------------------------------------------------------------ #

    def _mount_tools(prefix: str, source: str) -> None:
        def rec(engine: str, operation: str, input_data: Any, fn):
            return _record(engine, operation, input_data, source, fn)

        @app.post(f"{prefix}/calc", name=f"{source}_calc")
        def tool_calc(body: CalcBody):
            return rec("calc", "compute", body.model_dump(exclude_defaults=True), lambda: _calc(body.expression, body.precision))

        @app.post(f"{prefix}/math", name=f"{source}_math")
        def tool_math(body: MathBody):
            payload = body.model_dump(exclude_none=True)
            op = payload.pop("operation")
            timeout = payload.pop("timeout", 10.0)
            if "expressions" not in payload and "expression" in payload and op == "solve":
                payload["expressions"] = [payload.pop("expression")]
            return rec("math", op, body.model_dump(exclude_defaults=True), lambda: symbolic.run(op, timeout=timeout, **payload))

        @app.post(f"{prefix}/units_convert", name=f"{source}_units_convert")
        def tool_units_convert(body: UnitsConvertBody):
            return rec("units", "convert", body.model_dump(),
                       lambda: _units("convert", quantity=body.quantity, to=body.to))

        @app.post(f"{prefix}/stats", name=f"{source}_stats")
        def tool_stats(body: StatsBody):
            payload = body.model_dump(exclude={"test"})
            return rec("stats", body.test, body.model_dump(exclude_defaults=True),
                       lambda: stats.run(body.test, catalog=state.catalog, **payload))

        @app.post(f"{prefix}/date_calc", name=f"{source}_date_calc")
        def tool_date_calc(body: DateCalcBody):
            return rec("dates", body.operation, body.model_dump(exclude_defaults=True), lambda: _dispatch_date(body))

        @app.post(f"{prefix}/data_list", name=f"{source}_data_list")
        def tool_data_list():
            return rec("data", "list", {}, lambda: {"datasets": [_dataset_brief(d) for d in state.catalog.list_datasets()]})

        @app.post(f"{prefix}/data_register", name=f"{source}_data_register")
        def tool_data_register(body: DataRegisterBody):
            return rec("data", "register", body.model_dump(),
                       lambda: state.catalog.register(body.path, body.name, body.options))

        @app.post(f"{prefix}/data_describe", name=f"{source}_data_describe")
        def tool_data_describe(body: DataDescribeBody):
            return rec("data", "describe", body.model_dump(), lambda: state.catalog.describe(body.name))

        @app.post(f"{prefix}/data_query", name=f"{source}_data_query")
        def tool_data_query(body: DataQueryBody):
            return rec("data", "query", body.model_dump(exclude_defaults=True), lambda: state.catalog.query(body.sql, body.limit))

        @app.post(f"{prefix}/data_chart", name=f"{source}_data_chart")
        def tool_data_chart(body: DataChartBody):
            return rec("data", "chart", body.model_dump(exclude_defaults=True), lambda: _chart(body, include_spec=(source == "ui")))

    def _chart(body: "DataChartBody", include_spec: bool) -> dict:
        out_path = state.data_dir / "charts" / f"chart_{time.time_ns()}.png"
        result = charts.build_chart(
            state.catalog, body.sql, body.kind, body.x, body.y, body.color, body.title, out_path=out_path
        )
        spec = result["spec"]
        extra: dict[str, Any] = {"png_base64": base64.b64encode(result["png_bytes"]).decode("ascii")}
        if include_spec:
            extra["spec"] = spec  # the UI re-renders it interactively; the model gets the image
        return {
            "kind": body.kind,
            "spec_summary": {
                "mark": spec["mark"]["type"],
                "encoding": {k: v.get("field") or v.get("aggregate") for k, v in spec["encoding"].items()},
                "title": body.title,
            },
            "row_count": result["row_count"],
            "total_rows": result.get("total_rows"),
            "truncated": result["truncated"],
            "png_bytes": len(result["png_bytes"]),
            "_chart_path": str(out_path),
            "_response_extra": extra,
        }

    _mount_tools("/api/agent", "agent")
    _mount_tools("/api/ui", "ui")

    @app.post("/api/agent/work_log")
    def agent_work_log(body: WorkLogQuery):
        def _run():
            limit = max(1, min(body.limit, 50))
            query = (body.query or "").strip() or None
            if query and re.fullmatch(r"\[?L-\d{6}\]?", query):
                item = db.get_computation(state.conn, query.strip("[]"))
                if item is None:
                    raise DataError(f"no computation with id {query}")
                return {"items": [db.brief(item, full=True)], "count": 1, "has_more": False}
            rows = db.list_computations(state.conn, limit=limit + 1, engine=body.engine, query=query,
                                        exclude_engine=None if body.engine else "log")
            return {"items": [db.brief(r) for r in rows[:limit]], "count": min(len(rows), limit),
                    "has_more": len(rows) > limit}
        return _record("log", "search", body.model_dump(exclude_none=True), "agent", _run)

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
            "calc": lambda: _calc(input_data.get("expression", ""), input_data.get("precision", 15)),
            "units": lambda: _rerun_units(item["operation"], input_data),
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

    @app.post("/api/export/csv")
    def export_csv(body: DataQueryBody):
        """The complete result of a gated read-only query as CSV (the UI grid shows at most 1000 rows)."""
        holder: dict[str, Any] = {}

        def _run():
            r = state.catalog.query_all(body.sql, max_rows=1_000_000)
            holder.update(r)
            return {"row_count": r["row_count"], "truncated": r["truncated"]}

        _record("data", "export_csv", {"sql": body.sql}, "ui", _run)
        buf = io.StringIO()
        names = [c["name"] for c in holder["columns"]]
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(names)
        for row in holder["rows"]:
            writer.writerow(["" if row[n] is None else row[n] for n in names])
        # BOM so Excel on Windows opens UTF-8 (accents) correctly
        return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="query.csv"'})

    @app.post("/api/ui/data_ask", name="ui_data_ask")
    async def ui_data_ask(body: AskBody):
        """"Ask your data" (Data screen, UI only - the agent already writes SQL itself via data_query)."""
        async def _run():
            return await ask_engine.ask(state.catalog, state.link, body.question, body.datasets)
        return await _arecord("data", "ask", body.model_dump(exclude_defaults=True), "ui", _run)

    @app.get("/api/datasets")
    def list_datasets():
        return {"datasets": state.catalog.list_datasets()}

    @app.get("/api/datasets/{name}")
    def describe_dataset(name: str):
        return ui("data", "describe", {"name": name}, lambda: state.catalog.describe(name))

    @app.post("/api/units/check")
    def units_check(body: UnitsCheckBody):
        return ui("units", "check", body.model_dump(), lambda: _units("check", expression=body.expression))

    @app.get("/api/units/compatible")
    def units_compatible(unit: str):
        return ui("units", "compatible", {"unit": unit}, lambda: _units("compatible", unit=unit))

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
            return ui("calc", "compute", {"expression": text}, lambda: _calc(text))
        if engine_name == "math":
            op, payload = symbolic.parse_cell(text)
            return ui("math", op, {"operation": op, **payload}, lambda: symbolic.run(op, **payload))
        if engine_name == "units":
            for sep in ("->", "→", " to ", " en "):
                if sep in text:
                    q, to = text.split(sep, 1)
                    return ui("units", "convert", {"quantity": q.strip(), "to": to.strip()},
                              lambda: _units("convert", quantity=q.strip(), to=to.strip()))
            return ui("units", "check", {"expression": text}, lambda: _units("check", expression=text))
        if engine_name == "dates":
            return ui("dates", "parse", {"text": text}, lambda: dates.parse(text))
        raise HTTPException(status_code=400, detail={"error": "unknown_engine", "message": f"unknown cell engine {engine_name}"})

    def _dispatch_date(body: "DateCalcBody") -> dict:
        return _dispatch_date_dict(body.operation, body.model_dump())

    def _dispatch_date_dict(operation: str, d: dict) -> dict:
        if operation == "diff":
            return dates.diff(d.get("start"), d.get("end"), d.get("unit") or "days")
        if operation == "add":
            return dates.add(d.get("start"), days=d.get("days") or 0, weeks=d.get("weeks") or 0,
                             months=d.get("months") or 0, years=d.get("years") or 0)
        if operation == "business_days":
            return dates.business_days(
                d.get("start"), d.get("end"), country=d.get("country") or "ES",
                subdivision=d.get("subdivision"), include_end=d.get("include_end", True),
            )
        if operation == "weekday":
            return dates.weekday(d.get("value") or d.get("start"))
        if operation == "iso_week":
            return dates.iso_week(d.get("value") or d.get("start"))
        if operation == "age":
            return dates.age(d.get("birth_date") or d.get("start"), on=d.get("on") or d.get("end"))
        if operation == "convert_tz":
            return dates.convert_tz(d.get("value") or d.get("start"), from_tz=d.get("from_tz"), to_tz=d.get("to_tz"))
        if operation == "parse":
            return dates.parse(d.get("text") or d.get("value") or "")
        raise DateError(
            f"unknown date operation: {operation}; choose diff, add, business_days, weekday, iso_week, age, convert_tz or parse"
        )

    def _rerun_units(operation: str, input_data: dict) -> dict:
        if operation == "check":
            return _units("check", expression=input_data.get("expression", ""))
        if operation == "compatible":
            return _units("compatible", unit=input_data.get("unit", ""))
        return _units("convert", quantity=input_data.get("quantity", ""), to=input_data.get("to", ""))

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
        static_root = Path(static_dir).resolve()
        index_path = static_root / "index.html"

        if (static_root / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=static_root / "assets"), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"no API route /{full_path}"})
            if full_path:
                # Only ever serve files that resolve *inside* the built frontend:
                # "..%2f", "//etc/passwd" and Windows "..\\" must not escape it.
                candidate = (static_root / full_path).resolve()
                if candidate.is_relative_to(static_root) and candidate.is_file():
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
