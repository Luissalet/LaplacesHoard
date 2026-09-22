---
name: exact-numbers
description: Use Laplace's Hoard for any arithmetic, symbolic math, unit conversion, statistics, date math or question about a data file, instead of computing it yourself.
---

# Exact numbers with Laplace's Hoard

You are bad at arithmetic in your head and you know it. This app is not.
Every tool call is logged with an id like `L-000042` — cite it in your
answer as `[L-000042]` so the human can verify exactly how the number was
produced.

## When to reach for which tool

- Any arithmetic, percentage, or "how much is X% of Y" → `calc`. Never
  compute this yourself, even something that looks trivial like `15% of 2347`
  — you will get it wrong more often than you think.
- Solving an equation, a derivative, an integral, a limit, a matrix
  operation → `math`. Pass the operation name exactly (`solve`, `diff`,
  `integrate`, `matrix`, ...). For `solve`, check the `verified` field in the
  result before trusting a root.
- A quantity in one unit that needs to be in another (length, speed, mass,
  temperature, ...) → `units_convert`. Never eyeball a Fahrenheit-to-Celsius
  conversion; the offset makes naive scaling wrong.
- "Is this difference significant", "what's the correlation", "average and
  spread of this" → `stats`. Read the `interpretation` field but do not
  invent effect-size or causal language that is not in it.
- "How many days between", "how many business days", "what day of the week",
  "how old is", timezone conversion → `date_calc`.
- Any question about a CSV/Excel/Parquet/SQLite file the user gave you →
  **first** `data_list` (if you don't know its name) then **always**
  `data_describe` before `data_query`. Never guess a column name or a row
  count from memory of having "seen" the file — you have not seen it, only
  its name. `data_query` only accepts read-only SQL (SELECT/DESCRIBE/
  SUMMARIZE/EXPLAIN/PIVOT); anything else is rejected before it runs.
- A chart the user can see → `data_chart`. It runs the same read-only query
  as `data_query` and returns a PNG.

## Traps

- `calc` is numeric only — it has no variables. Use `math` (with
  `variable`/`variables`) for anything symbolic.
- `data_query` truncates at `limit` (default 50, max 1000) and sets
  `truncated: true` when there is more; do not report a `row_count` from a
  truncated query as if it were the dataset's total size — call
  `data_describe` for that instead.
- `math` operations run with a server-side timeout (default 10s). If you get
  a timeout error, simplify the input (fewer unknowns, narrower bounds)
  rather than retrying the identical call.
- `stats` needs equal-length samples for paired tests (`ttest_rel`,
  `wilcoxon`, `pearson`, `spearman`, `linregress`) — check `n` in the result.
- If any tool call fails with `laplaces-hoard_unavailable`, tell the human to
  start the app (Faustus → Apps, or "Iniciar Laplace's Hoard.cmd") — do not
  try to compute the answer yourself as a fallback; that defeats the point.
