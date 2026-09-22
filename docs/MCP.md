# MCP tools

Transport: stdio. The adapter (`laplaces_hoard/mcp_server.py`) is a
standalone script — launch it by absolute path, not with `-m`. It reads the
running app's URL from the `LAPLACE_URL` environment variable (default
`http://127.0.0.1:8812`) and refuses anything that is not loopback. Every
tool is a thin wrapper over `POST /api/agent/<tool>` on the running app, so
starting the app is required first.

## Any MCP client (not just Faustus)

```json
{
  "mcpServers": {
    "laplaces-hoard": {
      "command": "/absolute/path/to/laplaces-hoard/.venv/bin/python",
      "args": ["/absolute/path/to/laplaces-hoard/laplaces_hoard/mcp_server.py"],
      "env": { "LAPLACE_URL": "http://127.0.0.1:8812" }
    }
  }
}
```

On Windows, `command` is `...\.venv\Scripts\python.exe`.

## Tools

| tool | read-only | purpose |
| --- | --- | --- |
| `calc(expression, precision=15)` | yes | Exact arithmetic, percentages, number theory. Never returns a lossy float for a decimal literal — `0.1 + 0.2` is exactly `3/10`. |
| `math(operation, expression?, expressions?, variable?, variables?, domain?, ...)` | yes | Symbolic: `simplify expand factor apart together solve nsolve diff integrate limit series summation product matrix dsolve inequality`. `solve` reports `verified` (residual check). Runs with a server-side timeout. |
| `units_convert(quantity, to)` | yes | Unit conversion, including compound quantities ("5 ft 11 in") and correct temperature offsets. No currency. |
| `stats(test, data?, data2?, dataset?, column?, column2?, group_by?, where?, successes?, trials?)` | yes | Descriptive stats and hypothesis tests, with a neutral one-line interpretation. |
| `date_calc(operation, ...)` | yes | `diff add business_days weekday iso_week age convert_tz parse`. Business days default to Spain/Madrid holidays, overridable. |
| `data_list()` | yes | Registered datasets, with row counts and columns. |
| `data_register(path, name?, options?)` | no (materializes data) | Register a CSV/TSV/Parquet/JSON/Excel/SQLite file or a folder as one or more datasets. |
| `data_describe(name)` | yes | Schema + per-column profile + 5 sample rows. |
| `data_query(sql, limit=50)` | yes | Read-only SQL (see the gate below). |
| `data_chart(sql, kind, x, y?, color?, title?)` | yes | Renders bar/line/area/scatter/histogram/pie/heatmap as a PNG (returned as MCP `ImageContent`) plus a text summary. |
| `work_log(limit=10, engine?, query?)` | yes | Recent computations, to recall an id instead of recomputing. |

Every tool result includes an `id` like `L-000042` and is meant to be cited
as `[L-000042]`. `ToolAnnotations` are set honestly on every tool
(`readOnlyHint`, `destructiveHint=False` everywhere — nothing this app does
is destructive to data outside its own `data/` directory, `idempotentHint`,
`openWorldHint=False`).

## The SQL gate (`data_query`, `data_chart`)

Exactly one statement, and only `SELECT` / a `SELECT`-`WITH` / `DESCRIBE` /
`SUMMARIZE` / `EXPLAIN` / a single `PIVOT`/`UNPIVOT`. `ATTACH`, `COPY`,
`INSTALL`, `LOAD`, `SET`, `PRAGMA`, `CREATE`, `INSERT`, `UPDATE`, `DELETE`,
`EXPORT`, `CALL`, `DROP`, `ALTER` and multi-statement input are all rejected
with a clear `sql_gate` error before they run. See
`docs/ARCHITECTURE.md#the-sql-gate` for why the check is keyword-based as
well as type-based.

## Errors

- App not running: `ToolError("laplaces-hoard_unavailable: Laplace's Hoard "
  "is not running. Start it from Faustus (Apps) or with "
  "'Iniciar Laplace's Hoard.cmd', then retry.")`
- Any 4xx from the app: the adapter raises `ToolError` with the app's own
  `message` field, unchanged.

## Keywords for tool selection

Every tool's docstring ends with a `Keywords:` line in English and Spanish
(e.g. `calcular, cuánto es, porcentaje` for `calc`) so a retrieval-based
tool selector (like Faustus's) can find the right tool from a Spanish
prompt.
