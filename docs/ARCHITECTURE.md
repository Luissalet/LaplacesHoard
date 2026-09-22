# Architecture

## Layers

```
frontend/ (React 19 + Vite, TypeScript)
        │  fetch, same-origin, POST /api/ui/<tool> and UI endpoints
        ▼
laplaces_hoard/api.py   FastAPI app: browser-attack guard middleware,
        │                /api/agent/<tool> (MCP adapter) and /api/ui/<tool> (web UI),
        │                work log, notebook cells, CSV export, static SPA
        ▼
laplaces_hoard/engines/*   pure Python, no FastAPI imports
  safe_ast.py    the AST whitelist → SymPy converter (shared by calc and math)
  calc.py        exact numeric evaluation
  symbolic.py    solve/diff/integrate/matrices/...; notebook shorthand parser
  units.py       Pint-backed conversion and dimensional checks
  sandbox.py     runs calc, units and math in the timeout worker
  worker.py      generic timeout-guarded subprocess (spawn context)
  dates.py       dateutil + holidays + zoneinfo
  data.py        DuckDB catalogue, profiles and the SQL gate
  charts.py      Vega-Lite spec + vl-convert PNG render
  stats.py       NumPy/SciPy tests, reads dataset columns through data.py

laplaces_hoard/db.py          SQLite (stdlib, WAL): work log, notebook cells, settings
laplaces_hoard/mcp_server.py  standalone MCP stdio adapter (imports httpx + mcp only)
```

Every engine function takes plain Python values and returns a JSON-safe
`dict`. `api.py`'s `_record()` wraps every call: it times it, invokes the
engine, writes one row to the `computations` table (id `L-000042`,
`source` = `agent` or `ui`) whether it succeeds or fails, and returns the
engine's dict with `id`/`cite` added. Engine errors become
`{"error": "<code>", "message": "<text>"}` with status 400; an unexpected
exception becomes the same envelope with status 500 and is logged to
`data/logs/app.log`.

The tool handlers are mounted twice with identical code: under
`/api/agent/<tool>` for the MCP adapter (logged as `agent`) and under
`/api/ui/<tool>` for the web interface (logged as `ui`). That is what keeps
"Assistant activity" limited to what the model actually did. The adapter
never touches an engine directly — every tool is an HTTP POST — so
`tests/test_api*.py` (FastAPI `TestClient`) and `tests/test_mcp_protocol.py`
(real stdio) exercise the same path.

## Data model (SQLite, `data/app.sqlite`)

- `computations`: the work log and the assistant audit trail. `id`
  (`L-` + 6-digit sequence), `engine`, `operation`, `input_json` (only the
  arguments that differ from their defaults), `output_json` (capped at
  20,000 characters; an oversized output is stored as a valid
  `{"truncated": true, "preview": ...}` document), `ok`, `error`,
  `elapsed_ms`, `source` (`ui`/`agent`), `chart_path`, `created_at`.
  Chart PNGs and full chart specs are never stored in the row.
- `cells`: notebook cells (`engine`, `input`, `result_json`, `position`).
- `settings`: free-form key/value (reserved).

## Data model (DuckDB, `data/catalog.duckdb`)

- `_lh_datasets`: metadata (name, source path, kind, `linked`, row count,
  columns, profile, mtime/size for staleness, registration options).
- One `TABLE` (materialized) or `VIEW` (`linked`, for sources over 1 GB)
  per registered dataset, sheet or table. Excel sheets and SQLite tables
  are converted once to Parquet in `data/cache/` first.
- Dataset names are SQL-safe slugs of the file/sheet/table name
  ("Ventas año 2024.csv" → `Ventas_ano_2024`); lookups are
  case-insensitive.

### Connection model

DuckDB will not hold two differently configured connections to one file
in the same process, and `enable_external_access` cannot be switched back
on once it is off. So `Catalog` keeps exactly one connection open at a
time, under one lock:

| connection | when | configuration |
| --- | --- | --- |
| query connection | normal state, every `query()`/`describe()` | `read_only=True`; `allowed_paths`/`allowed_directories` = the sources of linked datasets and `data/cache/`; then `enable_external_access=false` |
| read-write | only while a dataset is registered, then closed | file access on |

Both disable automatic extension install/load, so nothing in a query can
make DuckDB download code, and DuckDB refuses to widen the allowed paths
once file access is off. The practical effects: a query cannot write to the
catalogue, cannot read any other file (`read_csv('/any/file')`, `glob()`,
`read_text()`, even in the same query as a linked dataset), and
registration keeps working after any number of queries.

### The SQL gate

`data.gate_sql()` runs before any query reaches DuckDB. DuckDB's
`extract_statements()` classifies the statement, and because this DuckDB
version classifies `DESCRIBE`, `SUMMARIZE` and `PRAGMA` all as `SELECT`
internally, the gate also rejects a fixed list of leading keywords
(`PRAGMA`, `ATTACH`, `COPY`, `INSTALL`, `LOAD`, `SET`, `CREATE`, `INSERT`,
`UPDATE`, `DELETE`, `EXPORT`, `CALL`, `DROP`, `ALTER`, `DETACH`, ...)
after skipping leading comments. `PIVOT`/`UNPIVOT` have one documented
exception: DuckDB expands a single `PIVOT` into an internal
`CREATE`+`SELECT` pair, so exactly that shape is allowed when the query
starts with `PIVOT`/`UNPIVOT`. The gate is the first line; the read-only,
no-file-access connection is the second.

Results: `rows` capped at `limit` (max 1000), text cells cut at 500
characters, `row_count` = rows returned, `total_rows` = size of the whole
result (counted up to 1,000,000). `stats` and `data_chart` use an internal
`query_all()` through the same gate, so a statistic over a 5,000-row
column uses all 5,000 rows. `/api/export/csv` streams the complete result
(up to 1,000,000 rows) for the UI's "Export CSV".

## The computation worker

`calc`, `units` and `math` turn untrusted text into big-number arithmetic,
and some inputs never finish (`nextprime(10**3000)`, a pathological
`solve`). `worker.TimeoutWorker` keeps one `multiprocessing` process (the
`spawn` context — Windows has no `fork`, so the same code path runs on both
platforms) and talks to it over a `Pipe`:

- a lock serialises callers (concurrent HTTP requests share one pipe);
- the child sends a "ready" message after its imports, so start-up time
  never eats into the first call's timeout; the app warms it up at start;
- each call waits up to its timeout (default 10 s, capped at 60 s); on
  timeout the process is terminated (then killed) and the next call starts
  a fresh one — the worker self-heals instead of wedging the app;
- engine exceptions travel back by class name, so a syntax error is still
  reported as `unsafe_expression`, a division by zero as `calc`.

A timeout does not protect against allocation, so two guards run before
any work: exact integer/rational powers whose result would exceed about
six million digits are refused (`2**(10**10)` would allocate 1.25 GB in a
second), and unit expressions only accept plain numeric exponents up to
100.

On Windows, when the app has no console window (started detached by a
launcher), the worker is started with the base `pythonw.exe` so no console
window appears; with a console (the normal `start.ps1` path) the default
`python.exe` is used.

## Browser-attack guard

`security.BrowserGuardMiddleware` runs on every request:

- **Host header** (all methods): only `127.0.0.1:<port>` or
  `localhost:<port>`, which blocks DNS rebinding.
- **Origin / `Sec-Fetch-Site`** (non-GET/HEAD/OPTIONS): a request whose
  `Origin` names another origin, or whose `Sec-Fetch-Site` is
  `cross-site`, is rejected. Plain GET navigation keeps working; there is
  no CORS header anywhere.

The SPA fallback only serves files that resolve inside `frontend/dist`
(`/..%2f`, `//etc/passwd` and Windows `..\` all fall back to
`index.html`), and unknown `/api/` paths return a JSON 404.

## Threads and processes

- One uvicorn process. Sync handlers run in its thread pool; the SQLite
  connection is guarded by a module-level lock in `db.py`, the DuckDB
  catalogue by an `RLock`, the worker by its own lock.
- One computation worker process (see above).
- Chart rendering (`vl_convert.vegalite_to_png`) runs in the request
  thread; it is native code and fast for ≤5,000 rows. A PNG over 200 KB is
  re-rendered at scale 1 so the image a model receives stays small.

## Logging

`data/logs/app.log`, rotating (1 MB × 3): one line per failed call and
every unexpected exception with its traceback. File contents and query
results are never written there. `start.ps1` sends the process's own
stdout/stderr to `data/logs/server.log` / `server.err.log`.

## Why DuckDB over pandas

Profiles, SQL and chart data are naturally SQL over columnar files; DuckDB
reads CSV/Parquet/JSON directly, needs no pandas/pyarrow dependency, and
ships wheels for both target platforms (Linux dev, Windows production).
