import { useEffect, useRef, useState, type ReactNode } from "react";
import { BarChart3, Database, Download, Play, Plus, Table2 } from "lucide-react";
import { api, ApiError, type ColumnProfile, type DatasetDetail, type DatasetSummary, type QueryResult } from "../api";
import type { DictKey } from "../i18n";
import { CiteBadge, ErrorBlock, copyCite, fmtNum } from "../components/ResultView";

type T = (k: DictKey) => string;

const NUMERIC = /^(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|UTINYINT|USMALLINT|UINTEGER|UBIGINT|FLOAT|DOUBLE|REAL|DECIMAL|NUMERIC)/i;

export function DataPage({ t }: { t: T }) {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const refresh = () =>
    api.datasets().then((r) => {
      setDatasets(r.datasets);
      setLoaded(true);
      return r.datasets;
    });

  useEffect(() => {
    refresh().then((list) => {
      if (list.length > 0) setSelected((cur) => cur ?? list[0].name);
    });
  }, []);

  useEffect(() => {
    if (selected) api.datasetDetail(selected).then(setDetail).catch(() => setDetail(null));
    else setDetail(null);
  }, [selected]);

  return (
    <div className="two-col">
      <div className="card">
        <div className="card-head">
          <h3 className="card-title">{t("data_title")}</h3>
          <button className="icon-btn" onClick={() => setShowAdd((s) => !s)} title={t("data_add")}>
            <Plus size={16} />
          </button>
        </div>

        {showAdd && (
          <AddDataset
            t={t}
            onDone={async (name) => {
              setShowAdd(false);
              await refresh();
              if (name) setSelected(name);
            }}
          />
        )}

        {loaded && datasets.length === 0 && !showAdd && <div className="empty-state">{t("data_empty")}</div>}
        <div className="stack" style={{ gap: 6 }}>
          {datasets.map((d) => (
            <button
              key={d.name}
              onClick={() => setSelected(d.name)}
              className={`dataset-item ${selected === d.name ? "active" : ""}`}
            >
              <span className="row" style={{ gap: 6 }}>
                <Database size={13} /> <strong>{d.name}</strong>
              </span>
              <span className="faint">
                {d.row_count.toLocaleString()} {t("data_rows")} · {d.columns.length} {t("data_columns")}
                {d.linked ? ` · ${t("data_linked")}` : ""}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="stack" style={{ gap: 16 }}>
        {detail ? <DatasetPanel key={detail.name} detail={detail} t={t} /> : (
          <div className="card">
            <div className="empty-state">
              <Table2 size={28} style={{ marginBottom: 8, opacity: 0.5 }} />
              <div>{t("data_select")}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function AddDataset({ t, onDone }: { t: T; onDone: (name?: string) => void }) {
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [delimiter, setDelimiter] = useState("");
  const [sheet, setSheet] = useState("");
  const [header, setHeader] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function register() {
    if (!path.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const options: Record<string, unknown> = {};
      if (delimiter) options.delimiter = delimiter;
      if (sheet) options.sheet = sheet;
      if (!header) options.header = false;
      const res = await api.registerDataset(path.trim(), name.trim() || undefined, options);
      onDone((res.name as string) || undefined);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ marginBottom: 14 }}>
      <div className="col">
        <label className="field-label">{t("data_path")}</label>
        <input type="text" className="mono" value={path} onChange={(e) => setPath(e.target.value)} placeholder="C:\Users\...\ventas.xlsx" />
      </div>
      <div className="col">
        <label className="field-label">{t("data_name")}</label>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <div className="col grow">
          <label className="field-label">{t("data_delimiter")}</label>
          <input type="text" value={delimiter} onChange={(e) => setDelimiter(e.target.value)} placeholder=", ; |" style={{ width: "100%" }} />
        </div>
        <div className="col grow">
          <label className="field-label">{t("data_sheet")}</label>
          <input type="text" value={sheet} onChange={(e) => setSheet(e.target.value)} style={{ width: "100%" }} />
        </div>
      </div>
      <label className="row faint" style={{ gap: 6 }}>
        <input type="checkbox" checked={header} onChange={(e) => setHeader(e.target.checked)} /> {t("data_header")}
      </label>
      {error && <ErrorBlock message={error} />}
      <button className="btn" disabled={busy || !path.trim()} onClick={register}>
        {t("data_register")}
      </button>
    </div>
  );
}

function DatasetPanel({ detail, t }: { detail: DatasetDetail; t: T }) {
  const numericCol = detail.columns.find((c) => NUMERIC.test(c.type));
  const textCol = detail.columns.find((c) => !NUMERIC.test(c.type) && !/DATE|TIME/i.test(c.type));
  const initialSql =
    textCol && numericCol
      ? `SELECT ${textCol.name}, COUNT(*) AS n, ROUND(SUM(${numericCol.name}), 2) AS total_${numericCol.name}\nFROM ${detail.name}\nGROUP BY ${textCol.name}\nORDER BY total_${numericCol.name} DESC`
      : `SELECT * FROM ${detail.name} LIMIT 20`;
  const [sql, setSql] = useState(initialSql);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ranSql, setRanSql] = useState<string | null>(null);

  async function run(query = sql) {
    setBusy(true);
    setError(null);
    try {
      const r = await api.query(query, 1000);
      setResult(r);
      setRanSql(query);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function exportCsv() {
    if (!ranSql) return;
    try {
      // the whole result, not just the rows on screen
      const blob = await api.exportCsv(ranSql);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${detail.name}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  const total = result?.total_rows ?? result?.row_count ?? 0;

  return (
    <>
      <div className="card">
        <div className="card-head">
          <h3 className="card-title">{detail.name}</h3>
          <div className="chips">
            <span className="chip"><strong>{detail.row_count.toLocaleString()}</strong> {t("data_rows")}</span>
            <span className="chip"><strong>{detail.columns.length}</strong> {t("data_columns")}</span>
            <span className="chip">{detail.kind}</span>
          </div>
        </div>
        <div className="faint mono" style={{ marginBottom: 12, overflowWrap: "anywhere" }} title={detail.source_path}>
          {detail.source_path}
        </div>
        <div className="table-scroll" style={{ maxHeight: 330 }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("data_col_column")}</th>
                <th>{t("data_col_type")}</th>
                <th className="num">{t("data_col_nulls")}</th>
                <th className="num">{t("data_col_distinct")}</th>
                <th>{t("data_col_range")}</th>
                <th className="num">{t("data_col_mean")}</th>
                <th>{t("data_col_shape")}</th>
              </tr>
            </thead>
            <tbody>
              {detail.columns.map((c) => {
                const p = detail.profile[c.name];
                return (
                  <tr key={c.name}>
                    <td><strong>{c.name}</strong></td>
                    <td className="mono faint">{c.type}</td>
                    <td className="num">{p ? `${fmtNum(p.nulls_pct)}%` : "–"}</td>
                    <td className="num">{p ? p.distinct_approx.toLocaleString() : "–"}</td>
                    <td className="mono" style={{ fontSize: 12 }}>
                      {p && p.min !== undefined ? `${fmt(p.min)} – ${fmt(p.max)}` : "–"}
                    </td>
                    <td className="num">{p?.mean !== undefined && p.mean !== null ? fmtNum(p.mean, 5) : "–"}</td>
                    <td><ProfileShape p={p} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h3 className="card-title">{t("data_sql")}</h3>
          <span className="faint">{t("data_sql_hint")}</span>
        </div>
        <textarea
          className="mono sql-editor"
          value={sql}
          spellCheck={false}
          onChange={(e) => setSql(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) run();
          }}
          rows={4}
        />
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn" onClick={() => run()} disabled={busy}>
            <Play size={13} style={{ verticalAlign: -2, marginRight: 4 }} />
            {t("common_run")}
          </button>
          {result && (
            <button className="btn-ghost" onClick={exportCsv}>
              <Download size={13} style={{ verticalAlign: -2, marginRight: 4 }} />
              {t("common_export_csv")}
            </button>
          )}
          <span className="grow" />
          {result && (
            <span className="faint">
              {t("data_rows_of").replace("{n}", result.row_count.toLocaleString()).replace("{total}", total.toLocaleString())}
              {" · "}{fmtNum(result.elapsed_ms, 3)} ms
            </span>
          )}
          {result && <CiteBadge id={result.id} onClick={copyCite} title={t("common_copy_cite")} />}
        </div>
        {error && <ErrorBlock message={error} />}
        {!result && detail.sample_rows.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div className="faint" style={{ marginBottom: 6 }}>{t("data_sample")}</div>
            <div className="table-scroll" style={{ maxHeight: 240 }}>
              <table className="data-table">
                <thead>
                  <tr>{detail.columns.map((c) => <th key={c.name} className={NUMERIC.test(c.type) ? "num" : ""}>{c.name}</th>)}</tr>
                </thead>
                <tbody>
                  {detail.sample_rows.map((row, i) => (
                    <tr key={i}>
                      {detail.columns.map((c) => (
                        <td key={c.name} className={NUMERIC.test(c.type) ? "num" : ""}>{fmt(row[c.name])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {result && (
          <div style={{ marginTop: 12 }}>
            <div className="table-scroll" style={{ maxHeight: 360 }}>
              <table className="data-table">
                <thead>
                  <tr>
                    {result.columns.map((c) => (
                      <th key={c.name} className={NUMERIC.test(c.type) ? "num" : ""}>{c.name}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, i) => (
                    <tr key={i}>
                      {result.columns.map((c) => (
                        <td key={c.name} className={NUMERIC.test(c.type) ? "num" : ""}>{fmt(row[c.name])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {result.truncated && (
              <div className="faint" style={{ marginTop: 6 }}>
                {t("data_truncated").replace("{n}", String(result.rows.length))}
              </div>
            )}
          </div>
        )}
      </div>

      <ChartBuilder sql={ranSql} result={result} t={t} />
    </>
  );
}

function ProfileShape({ p }: { p: ColumnProfile | undefined }) {
  if (!p) return null;
  if (p.histogram && p.histogram.length) {
    const max = Math.max(...p.histogram, 1);
    return (
      <div className="spark" title={p.histogram.join(" · ")}>
        {p.histogram.map((n, i) => (
          <span key={i} style={{ height: `${Math.max(4, (n / max) * 100)}%` }} />
        ))}
      </div>
    );
  }
  if (p.top_values && p.top_values.length) {
    const max = Math.max(...p.top_values.map((v) => v.count), 1);
    return (
      <div className="topbars">
        {p.top_values.slice(0, 3).map((v) => (
          <div key={String(v.value)} className="topbar-row" title={`${String(v.value)}: ${v.count}`}>
            <span className="lbl">{String(v.value)}</span>
            <span className="bar" style={{ width: `${Math.max(6, (v.count / max) * 70)}px` }} />
          </div>
        ))}
      </div>
    );
  }
  return <span className="faint">–</span>;
}

const KINDS = ["bar", "line", "area", "scatter", "histogram", "pie", "heatmap"];

function ChartBuilder({ sql, result, t }: { sql: string | null; result: QueryResult | null; t: T }) {
  const columns = result?.columns ?? [];
  const names = columns.map((c) => c.name);
  const firstNumeric = columns.find((c) => NUMERIC.test(c.type))?.name ?? "";
  const [kind, setKind] = useState("bar");
  const [x, setX] = useState("");
  const [y, setY] = useState("");
  const [color, setColor] = useState("");
  const [title, setTitle] = useState("");
  const [spec, setSpec] = useState<object | null>(null);
  const [chartId, setChartId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);

  const colsKey = names.join("|");
  useEffect(() => {
    setX(names[0] ?? "");
    setY(firstNumeric && firstNumeric !== names[0] ? firstNumeric : names[1] ?? "");
    setColor("");
    setSpec(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [colsKey]);

  useEffect(() => {
    if (spec && chartRef.current) {
      const dark = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim().startsWith("#1");
      import("vega-embed").then(({ default: embed }) => {
        if (chartRef.current)
          embed(chartRef.current, { ...(spec as object), width: "container", height: 300, autosize: { type: "fit", contains: "padding" } } as never, {
            actions: false,
            theme: dark ? "dark" : undefined,
            config: { background: "transparent", mark: { color: "#7cb342" }, range: { category: { scheme: "tableau10" } } },
          } as never).catch(() => {});
      });
    }
  }, [spec]);

  async function build() {
    if (!sql) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.chart({ sql, kind, x, y: y || undefined, color: color || undefined, title: title || undefined });
      setSpec(r.spec);
      setChartId(r.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3 className="card-title"><BarChart3 size={15} style={{ verticalAlign: -2, marginRight: 6 }} />{t("data_chart_builder")}</h3>
        <span className="faint">{sql ? t("data_chart_hint") : t("data_chart_run_first")}</span>
      </div>
      <div className="row" style={{ marginBottom: 10, alignItems: "flex-end" }}>
        <Field label={t("data_chart_kind")}>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </Field>
        <Field label={t("data_chart_x")}>
          <select value={x} onChange={(e) => setX(e.target.value)} disabled={!names.length}>
            {names.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </Field>
        <Field label={t("data_chart_y")}>
          <select value={y} onChange={(e) => setY(e.target.value)} disabled={!names.length}>
            <option value="">—</option>
            {names.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </Field>
        <Field label={t("data_chart_color")}>
          <select value={color} onChange={(e) => setColor(e.target.value)} disabled={!names.length}>
            <option value="">—</option>
            {names.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </Field>
        <div className="col grow">
          <label className="field-label">{t("data_chart_title")}</label>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <button className="btn" onClick={build} disabled={busy || !x || !sql}>
          {t("data_chart_build")}
        </button>
      </div>
      {error && <ErrorBlock message={error} />}
      {spec && (
        <div className="chart-frame" style={{ marginTop: 12, flexDirection: "column", alignItems: "stretch" }}>
          <div ref={chartRef} style={{ width: "100%" }} />
          {chartId && <div style={{ textAlign: "right" }}><CiteBadge id={chartId} onClick={copyCite} title={t("common_copy_cite")} /></div>}
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="col">
      <label className="field-label">{label}</label>
      {children}
    </div>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "–";
  if (typeof v === "number") return fmtNum(v, 8);
  return String(v);
}

