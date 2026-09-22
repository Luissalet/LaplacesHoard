# Architecture

## Layers

```
frontend/ (React 19 + Vite, TypeScript)
        │  fetch, same-origin
        ▼
laplaces_hoard/api.py   FastAPI app: browser-attack guard middleware,
        │                /api/agent/<tool> (agent-facing), /api/... (UI)
        ▼
laplaces_hoard/engines/*   pure Python, no FastAPI imports
  calc.py        AST-whitelist → SymPy, exact rationals
  safe_ast.py    the whitelist itself (shared by calc and symbolic)
  symbolic.py    solve/diff/integrate/matrices/... via a worker process
  worker.py      generic timeout-guarded subprocess (spawn context)
  units.py       Pint-backed conversion
  dates.py       dateutil + holidays
  data.py        DuckDB catalogue + SQL gate
  charts.py      Vega-Lite spec + vl-convert PNG render
  stats.py       NumPy/SciPy tests, resolves data from `data.py` too

laplaces_hoard/db.py       SQLite (stdlib, WAL): work log, notebook cells, settings
laplaces_hoard/mcp_server.py   standalone MCP stdio adapter (imports httpx+mcp only)
```

Every engine function takes plain Python values and returns a JSON-safe
`dict`. `api.py`'s `_record()` helper wraps every call: it times it, invokes
the engine, and writes one row to the `computations` table (id `L-000042`,
`source` = `ui` or `agent`) whether it succeeds or fails, then returns the
engine's dict with `id`/`cite` added. The MCP adapter never touches an
engine directly — every tool is an HTTP POST to `/api/agent/<tool>`, so the
exact same code path is what `tests/test_api.py` exercises with FastAPI's
`TestClient` and what `tests/test_mcp_protocol.py` exercises over real
stdio.

## Data model (SQLite, `data/app.sqlite`)

- `computations`: the work log. `id` (`L-` + 6-digit sequence), `engine`,
  `operation`, `input_json`, `output_json`, `ok`, `error`, `elapsed_ms`,
  `source` (`ui`/`agent`), `chart_path`, `created_at`.
- `cells`: notebook cells (`engine`, `input`, `result_json`, `position`).
- `settings`: free-form key/value (reserved for future use).

## Data model (DuckDB, `data/catalog.duckdb`)

- `_lh_datasets`: metadata table (name, source path, kind, `linked`,
  row count, columns, profile, mtime/size for staleness checks).
- One `TABLE` (materialized) or `VIEW` (`linked`, for files over the 1 GB
  threshold) per registered dataset/sheet/table.

### The SQL gate

`data.gate_sql()` runs before any query touches the catalogue. DuckDB's own
`extract_statements()` classifies the statement; a bare "one statement,
type SELECT/EXPLAIN" check is not enough because this DuckDB version
classifies `DESCRIBE`, `SUMMARIZE` and `PRAGMA` all as type `SELECT`
internally — so the gate also rejects a fixed list of leading keywords
(`PRAGMA`, `ATTACH`, `COPY`, `INSTALL`, `LOAD`, `SET`, `CREATE`, `INSERT`,
`UPDATE`, `DELETE`, `EXPORT`, `CALL`, `DROP`, `ALTER`, ...) regardless of
how DuckDB classified it. `PIVOT`/`UNPIVOT` get one documented exception:
DuckDB's parser expands a single `PIVOT` into an internal `CREATE`+`SELECT`
pair, so exactly that two-statement shape is allowed when the query starts
with `PIVOT`/`UNPIVOT`; anything else with more than one statement is
rejected. See `tests/test_data.py::test_sql_gate_refuses_dangerous_statements`
for the exhaustive list this is tested against.

**Deviation from a literal second read-only connection.** The pinned
DuckDB version refuses to open a second, `read_only=True` connection to a
database file that already has a read-write connection open in the same
process (needed here for dataset registration) — it raises
`Connection Error: Can't open a connection to same database file with a
different configuration`. So `query()` runs on the same connection inside a
transaction that is **always rolled back** (success or failure), after the
statement-type/keyword gate already rejected anything but a read statement.
Read-only-ness is therefore enforced at the application level (gate +
always-rollback) rather than by a second OS-level file handle. Practical
effect: identical to a read-only connection for every query that passes the
gate; the only theoretical gap would be a bug in the gate itself, which the
rollback still catches before anything reaches disk.

## The symbolic-math worker

SymPy can hang on some inputs (`solve`, `integrate`, `nsolve` in particular).
`worker.TimeoutWorker` starts one `multiprocessing` process (the `spawn`
context — Windows has no `fork`, so the same code path runs on both
platforms) and talks to it over a `Pipe`. Each call sends `(op, payload)`
and waits up to `timeout` seconds (default 10s) with `Connection.poll()`. If
it times out, the process is `terminate()`d (then `kill()`ed if it does not
die within 2s) and the next call starts a fresh process — the worker
self-heals rather than wedging the app. `tests/test_symbolic.py` proves both
halves: a synthetic always-slow target times out predictably, and a normal
call right after still succeeds.

## Browser-attack guard

`security.BrowserGuardMiddleware` runs on every request:

- **Host header check** (all methods): rejects anything but
  `127.0.0.1:<port>` / `localhost:<port>`, which blocks DNS rebinding from a
  malicious page that resolves an attacker domain to `127.0.0.1`.
- **Origin / `Sec-Fetch-Site` check** (non-GET/HEAD/OPTIONS only): rejects a
  request whose `Origin` header names a different origin, or whose
  `Sec-Fetch-Site` is `cross-site`. Plain `GET` navigation from any tab
  keeps working — this is intentionally not CORS (no
  `Access-Control-Allow-Origin` header exists anywhere in the app); it is a
  same-origin-only write guard.

## Threads and processes

- The FastAPI/uvicorn process is single-process, async; the DuckDB
  connection and the SQLite connection are each guarded by a lock (SQLite:
  a module-level lock in `db.py`; DuckDB: an `RLock` on the `Catalog`) since
  multiple requests can arrive concurrently.
- Every `math` operation spawns/reuses exactly one worker subprocess (see
  above); nothing else in the app uses multiprocessing.
- Chart rendering (`vl_convert.vegalite_to_png`) runs synchronously in the
  request thread — it is a native (Rust) call, not a subprocess, and is fast
  enough (≤5,000 rows) not to need offloading.

## Why DuckDB over pandas

The spec's data engine (profiles, SQL, chart data) is naturally expressed as
SQL over columnar files; DuckDB reads CSV/Parquet/JSON directly, needs no
pandas/pyarrow dependency, and ships wheels for both target platforms
(Linux dev, Windows production).
