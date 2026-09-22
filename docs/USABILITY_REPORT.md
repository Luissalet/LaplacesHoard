# Usability report

The app's first real use, walked twice: as a person in the browser
(`scripts/ui_walkthrough.py`, Playwright, Chromium at 1280×800, 1920×1080
and 390 px, with the screenshots read one by one) and as an agent over
real MCP stdio (`scripts/agent_walkthrough.py`, 46 tool calls chained the
way a local 27B would chain them). The scenarios are in
[USE_CASES.md](USE_CASES.md). The inputs are the synthetic but messy files
from `scripts/uxtest_data.py`: a Spanish bank export, a Windows-1252
statement with a preamble, a job-hunt workbook, a writing log, a
llama.cpp benchmark log, a Funes export and an Daguerre library.

Date of the walk: 2026-09-22, on commit `7236fa5`. **Status: findings
only.** No blocker stopped the walk (each had a workaround or the walk
moved on), so no code was changed in this pass. The "Fix" column is the
plan for the fix pass.

Severity: **blocker** = a wrong number shown as right, or a scenario that
cannot be finished without knowing the internals; **annoying** = it can be
done but it costs time or trust; **cosmetic** = looks or wording.

Two of the blockers were already reported from a real development machine and are
marked **(live)**: they must be fixed in the fix pass.

## Blockers

| # | Area | Scenario | What happened | Fix |
| --- | --- | --- | --- | --- |
| B1 | `data_chart`, `mcp_server.py` **(live)** | UC5 | Every `data_chart` call returns the PNG as MCP `ImageContent` (129,448 base64 characters for a 7-bar chart), although the model never asked for an image. On a real machine, a text-only local model receiving an image made llama.cpp fail the whole turn (HTTP 500). There is also nothing a text model can hand the person instead: the UI has no URL per chart or per log entry (tab state only, `App.tsx`), and the work-log detail of a chart entry shows its JSON, not the chart. | `include_image: bool = False`; by default return text only: `id`, `cite`, `chart_url` (a hash route such as `/#/log/L-000023` that opens the entry and redraws the chart from the stored SQL/spec), and a compact summary of what is plotted (series, x/y ranges, top values). Work-log detail draws the chart. Description says images come only with `include_image=true`. Regression tests: default call has no image part; `include_image=true` has one. |
| B2 | CSV registration, `engines/data.py::_register_csv` **(live)** | UC1, UC2 | Spanish amounts (`-1.150,00`, `10.045,11`) stay `VARCHAR`. `SUM("Importe (€)")` fails (`sum(VARCHAR)`), `CAST(... AS DOUBLE)` fails (`Could not convert string '-1.150,00'`); the model only got an answer on its third query by writing `CAST(replace(replace(x, '.', ''), ',', '.') AS DECIMAL(12,2))` by hand. The UI's add form has no option for it either. DuckDB supports `decimal_separator=','` and `thousands='.'`. | Sniff: when a `;`-separated file has text columns whose values all match `^-?\d{1,3}(\.\d{3})*(,\d+)?$` / `^-?\d+,\d+$`, re-read with `decimal_separator=','` (+ `thousands='.'` when present) and report it in the result (`read_as: {...}`). Accept explicit `options.decimal`, `options.thousands`, `options.encoding`, `options.dateformat`; add them to the add form ("Formato español" preset). Tests with the three real-world shapes. |
| B3 | CSV registration, dates **(live)** | UC1 | `dd/mm/yy` is read as `yy/mm/dd` without a warning: `13/02/25` became 2013-02-25, `01/02/25` became 2001-02-25 (DuckDB's sniffer). `dd/mm/yyyy` (including ambiguous `03/04/2025`) is read correctly day-first. | Detect two-digit-year columns and read them with `dateformat='%d/%m/%y'` (or `%d-%m-%y`); allow `options.dateformat`; say in the result which format was used. Test. |
| B4 | CSV registration, encoding **(live)** | UC1 | A Windows-1252 file (the usual "export to Excel" of Spanish banks) with an accent fails: `Invalid unicode (byte sequence mismatch) ... Possible Solution: ... encoding='UTF-16'`, and there is no way to pass an encoding. | On a UTF-8 error, retry once with `encoding='latin-1'` (cp1252 superset for these bytes) and report it; accept `options.encoding`. Test. |
| B5 | `units_convert`, `engines/units.py` **(live)** | UC6 | `3,5 km` → `mi` answers **21.7479917283 mi**: the comma is dropped and 35 km is converted. The UI shows it formatted the Spanish way as "21,74799173 mi", so it looks right. | Treat `d,d` as a decimal comma when it is the only separator (`3,5` → `3.5`), refuse ambiguous forms (`1.234,5`… normalise; `1,234` → error "write 1234 or 1.234") with the exact spelling to use; report `input_normalized`. Test. |
| B6 | `calc`, `engines/calc.py` / `safe_ast.py` **(live)** | UC2, UC4 | `1.000 * 3` = **3** with no warning (a Spanish speaker means 3000). `3,5 + 2` → "calc evaluates one expression, not a list"; `pct(21, 1.234,56)` → "wrong arguments for pct(): _pct() takes 2 positional arguments but 3 were given" (internal name, no hint). The decimal-comma hint exists in `_parse_hint` but only runs on syntax errors. | Before parsing, detect Spanish-style literals: `1.234,56` → `1234.56` (unambiguous), `3,5` alone or next to operators → `3.5`; `1.000`/`1.234` (dot + exactly three digits, no comma) stays English but the result gets `warning: "'1.000' was read as 1 (one); if you meant one thousand write 1000"`. Where a comma is ambiguous inside a call (`pct(21, 1234,56)`), the error says "the ',' separates arguments; write decimals with '.': pct(21, 1234.56)". Tests with each input above. |
| B7 | Statistics screen, `StatisticsPage.tsx::parseNums` | UC3 | Pasting `3,5; 4,2; 5,1; 6,0` (Spanish decimals separated by `;`) gives **n = 8, mean 3.25** instead of n = 4, mean 4.7: the parser splits on commas too. | When the text contains `;` or newlines, split only on those and read `,` as the decimal separator; label says "separados por ; o saltos de línea si usas coma decimal". Test the parser. |
| B8 | Notebook, `NotebookPage.tsx::addCell` | UC4 | A cell that fails shows **nothing**: `addCell` has `try/finally` without `catch`, so the error is an unhandled rejection (4 `pageerror`s in the console) and the input just stays there. After a reload the failed cells appear as empty cards without an id or message. Affected: `3,5 + 2`, `pct(21, 1234,56)`, `x^2 - 5x + 6 = 0`. | Catch, show the error in the cell (red, with the hint), and render stored errors after a reload. |
| B9 | Re-registration, `engines/data.py::_materialize` | UC1 | Registering the same file again (the documented way to refresh it) always fails: `Catalog Error: Existing object movimientos_2023_2025 is of type Table, trying to drop type View`. `DROP VIEW IF EXISTS` on a table is an error in DuckDB 1.5. No test covered it. | Drop by the kind stored in `_lh_datasets` (or check `duckdb_tables()`/`duckdb_views()`), regression test "register twice, with and without new options". |
| B10 | `stats` over MCP, `mcp_server.py::stats` | UC3 | `fisher_exact` and `chi2_contingency` cannot be called over MCP: the description says `data = table, e.g. [[8, 2], [1, 9]]` but the schema is `data: list[float]`, so the client-side validation answers with two pydantic errors and a pydantic.dev URL. (The same test works on the Statistics screen: p = 0.126.) | `data: list[float] \| list[list[float]]` (and `table` alias); a protocol test calling `fisher_exact` with a 2×2 table. |
| B11 | JSON registration, `engines/data.py` | UC5 | Registering the Funes export returns **377,104 characters** to the model (the one sample row holds the whole `spans` list: `_json_safe` caps strings, not lists). The dataset is one row of nested lists, so every question needs `unnest(spans, recursive := true)`. | Cap nested values in profiles and sample rows (e.g. first 3 items + `"… 443 more"`), cap the whole result; for a top-level object whose keys are lists of records, register one dataset per key (`funes_export__spans`), like Excel sheets. Test with a Funes-shaped file. |

## Annoying

| # | Area | Scenario | What happened | Fix |
| --- | --- | --- | --- | --- |
| A1 | `stats` pairwise NULLs, `engines/stats.py` (`_column` loads each column with its own `IS NOT NULL`) | UC8 | `linregress` on `ctx` vs `tokens_per_s` with crashed runs: "needs two equal-length samples ... got 411 and 406". A model has to guess `AND tokens_per_s IS NOT NULL`. | Load both columns in one query and drop rows where either is NULL; report `dropped_null_rows`. Same for `pearson`, `spearman`, `ttest_rel`, `wilcoxon`. |
| A2 | `math` implicit multiplication | UC4 | `x^2 - 5x + 6 = 0` → "could not parse expression: invalid decimal literal", no hint. Small models write `5x` all the time. | Hint "write 5*x (implicit multiplication is not supported)" whenever `\d[a-zA-Z(]` appears. |
| A3 | SQLite BLOB columns, `_register_sqlite` | UC7 | The Daguerre `thumb` BLOB becomes Python repr text (`b"!\x18u\xf6..."`): the profile lists five of them as "top values", `data_describe` is 10,970 characters and `SELECT * LIMIT 3` 3,383. | Write BLOBs as `NULL` + a `<col>_bytes` length, or hex-capped; profile shows "binary, N bytes". |
| A4 | Excel title rows, `_register_excel` | UC3 | The *Entrevistas* sheet (title row + blank row above the header) registers with columns `Seguimiento de entrevistas 2026, col1, col2, col3, col4`. | Detect the header as the first row whose cells are mostly non-empty text, or accept `options.header_row`; say which row was used. |
| A5 | Mixed number formats in result tables, `DataPage.tsx::fmt` | UC1, UC4 | In a Spanish browser integers are localised (`28.530` words) but DECIMAL values arrive as strings and are shown raw (`17445.41` €). On one screen `.` is both a thousands and a decimal separator. | Format numeric-typed cells, including DECIMAL strings, with the UI language's locale. |
| A6 | Chart order, `engines/charts.py` | UC1 | The SQL sorts spending by amount (`ORDER BY 2 DESC`) but the bar chart re-sorts the categories alphabetically. | `sort: null` on nominal x so the query order is kept (or sort by y when the query has no ORDER BY). |
| A7 | English inside the Spanish UI | UC1, UC3, UC6 | Engine texts are English only: DuckDB errors, test interpretations ("no statistically significant association was found…"), "floating-point conversion, rounded to 12 significant digits", `counted: start and end included`, weekday names, the notebook pills (`calc math units dates`), chart kinds (`bar line`). | Translate the fixed strings in the UI; keep engine messages English for the model but give the UI a `message_es`/key where they are fixed sentences. |
| A8 | Work log, `WorkLogPage.tsx` | UC5 | Searching `L-000003` does nothing until Enter is pressed (no button, no live filter; the API itself finds it). There is no link that opens an entry, which is what an agent's `[L-000042]` should be. | Debounced live search; exact id opens the entry; `/#/log/<id>` route (shared with B1). |
| A9 | No dataset removal | UC1 | A dataset registered by mistake (or the duplicate `extracto_cuenta_2025`) cannot be removed from the UI or the API. | A delete action in the dataset card (UI only, with confirmation; the source file is never touched). |
| A10 | Spanish unit names | UC6 | `180 libras`, `72 pulgadas` → "'pulgadas' is not defined in the unit registry". | Map common Spanish names (libra, pulgada, pie, milla, onza, galón, grado…) or at least say "use the English symbol: in". |
| A11 | Export CSV for Spanish Excel | UC1 | The export is UTF-8 with BOM (good), `,`-separated with `.` decimals. Spanish-locale Excel expects `;` and `,`, so it would open in one column. *Not verified on a real Excel.* | Offer "CSV (Excel España)" with `;` and decimal commas when the UI is in Spanish. |
| A12 | No file picker | UC1 | The only way to add a file is to type or paste its full path. | A "Browse…" that uploads a copy into `data/uploads/` (the original is never touched), plus drag and drop. |
| A13 | Tool list size | all agent UCs | `list_tools` is 19,296 characters (about 4.8k tokens) before the first call; `date_calc` has 17 parameters and `math` 16. Fine at 32k context, heavy at 8k. | Shorten descriptions where they repeat the schema; keep the keyword lines. |

## Cosmetic

| # | Area | What happened |
| --- | --- | --- |
| C1 | Dataset list | Long names (`busqueda_empleo_2026__Aplicaciones`) overflow the card at 1280 and 1920 px. |
| C2 | 390 px | The dataset and profile cards overflow horizontally. |
| C3 | Data page | "1 rows"; the suggested SQL for the Funes dataset is `SUM(exported_at) ... GROUP BY spans`. |
| C4 | Data page | "Ask your data" stays at the top, disabled, when no model is available, pushing the datasets below the fold. |
| C5 | Assistant activity | The empty state does not say how to connect an assistant (Faustus → Connectors, or docs/MCP.md). |
| C6 | `calc` for money | `11745.55 / 12` answers `978.795833333333`; the description could suggest `round(x, 2)` for currency. |
| C7 | Excel dates | Excel date cells arrive as `TIMESTAMP` (`2026-09-04T00:00:00`) instead of `DATE`. |
| C8 | Console | "The input spec uses Vega-Lite v5, but the current version of Vega-Lite is v6.4.3" on every chart. |
| C9 | Notebook | The first-run screen does not point to Data for tables. |

## What worked

- `dd/mm/yyyy` dates, including all-ambiguous ones (`03/04/2025` → 3 April), were read day-first; the three preamble lines of a bank statement were skipped automatically; the UTF-8 BOM did not leak into the first column name.
- Speed on 2 CPUs: registering 1,930 rows took 130–230 ms, queries 5–20 ms, a chart about 0.6 s, a business-day count about 130 ms.
- Errors a model can act on: unknown dataset lists the registered names; unknown columns list `Candidate bindings`; the SQL gate names the statement and what is allowed; `group_by` with three groups names them; "app not running" says how to start it.
- Business days in Madrid excluded 12 October and listed it; `hoy` and `30/10/2026` were accepted.
- `work_log` by id returns the full entry; the audit split UI/assistant is right.
- Keyboard focus is visible; Ctrl+Enter runs SQL; Enter adds a notebook cell.

## Agent-side summary (last run)

46 calls, 16 errors (8 of them deliberate probes), 1 image sent without
being asked (B1), 2 results over 6,000 characters (B11, A3). Result size
by tool, largest seen: `data_register` 377,104 (Funes JSON; 4,241 for the
bank CSV), `data_describe` 10,970 (BLOBs), `data_query` 3,383,
`work_log` 1,772, all other tools under 600.

## Not tested

- Windows itself (the walk ran on Linux; paths were Linux paths), and the
  export opened in a real Spanish Excel (A11).
- "Ask your data" and the Models panel with a real model: no language model
  is running in this environment, so only the "unavailable" state was seen.
- Faustus itself: MCP was driven by a scripted client, not by Faustus and a
  real 27B model, so tool *selection* was simulated by keyword retrieval
  over the descriptions.
- The real Funes and Daguerre apps: their exports were imitated from their
  schemas (`funes_hoard/api.py` export, `daguerre_hoard/db.py` `photos`).
- The dark theme.
