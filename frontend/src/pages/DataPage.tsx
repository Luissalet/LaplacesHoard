import { useEffect, useRef, useState } from "react";
import { Database, Download, Plus, Table2 } from "lucide-react";
import { api, ApiError, type DatasetDetail, type DatasetSummary, type QueryResult } from "../api";
import type { DictKey } from "../i18n";
import { CiteBadge, copyCite } from "../components/ResultView";

export function DataPage({ t }: { t: (k: DictKey) => string }) {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => api.datasets().then((r) => setDatasets(r.datasets));

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (selected) api.datasetDetail(selected).then(setDetail);
    else setDetail(null);
  }, [selected]);

  async function register() {
    if (!path.trim()) return;
    setBusy(true);
    setRegisterError(null);
    try {
      const res = await api.registerDataset(path.trim(), name.trim() || undefined);
      await refresh();
      const registeredName = (res.name as string) || (res.datasets as { name: string }[] | undefined)?.[0]?.name;
      setShowAdd(false);
      setPath("");
      setName("");
      if (registeredName) setSelected(registeredName);
    } catch (e) {
      setRegisterError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="two-col">
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
          <h3 className="card-title" style={{ margin: 0 }}>{t("data_title")}</h3>
          <button className="icon-btn" onClick={() => setShowAdd((s) => !s)} title={t("data_add")}>
            <Plus size={16} />
          </button>
        </div>

        {showAdd && (
          <div className="stack" style={{ marginBottom: 14 }}>
            <div className="col">
              <label className="field-label">{t("data_path")}</label>
              <input type="text" value={path} onChange={(e) => setPath(e.target.value)} placeholder="/path/to/file.csv" />
            </div>
            <div className="col">
              <label className="field-label">{t("data_name")}</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            {registerError && <div className="faint" style={{ color: "var(--danger)" }}>{registerError}</div>}
            <button className="btn" disabled={busy || !path.trim()} onClick={register}>
              {t("data_register")}
            </button>
          </div>
        )}

        {datasets.length === 0 && !showAdd && <div className="empty-state">{t("data_empty")}</div>}
        <div className="stack">
          {datasets.map((d) => (
            <button
              key={d.name}
              onClick={() => setSelected(d.name)}
              className="btn-ghost"
              style={{
                textAlign: "left",
                display: "flex",
                flexDirection: "column",
                gap: 2,
                borderColor: selected === d.name ? "var(--accent)" : "var(--border)",
              }}
            >
              <span className="row" style={{ gap: 6 }}>
                <Database size={13} /> <strong>{d.name}</strong>
              </span>
              <span className="faint">
                {d.row_count.toLocaleString()} {t("data_rows")} · {d.columns.length} {t("data_columns")}
                {d.linked ? " · linked" : ""}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="stack">
        {detail ? <DatasetPanel detail={detail} t={t} /> : (
          <div className="card">
            <div className="empty-state">
              <Table2 size={28} style={{ marginBottom: 8, opacity: 0.5 }} />
              <div>{t("data_empty")}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function DatasetPanel({ detail, t }: { detail: DatasetDetail; t: (k: DictKey) => string }) {
  const [sql, setSql] = useState(`SELECT * FROM ${detail.name} LIMIT 20`);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setSql(`SELECT * FROM ${detail.name} LIMIT 20`);
    setResult(null);
    setError(null);
  }, [detail.name]);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.query(sql, 200);
      setResult(r);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function exportCsv() {
    if (!result) return;
    const cols = result.columns.map((c) => c.name);
    const lines = [cols.join(",")];
    for (const row of result.rows) {
      lines.push(cols.map((c) => csvCell(row[c])).join(","));
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${detail.name}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <div className="card">
        <h3 className="card-title">{detail.name}</h3>
        <div className="faint" style={{ marginBottom: 10 }}>{detail.source_path}</div>
        <div className="table-scroll" style={{ maxHeight: 220 }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Column</th><th>Type</th><th>Nulls %</th><th>Distinct</th><th>Min</th><th>Max</th><th>Mean</th>
              </tr>
            </thead>
            <tbody>
              {detail.columns.map((c) => {
                const p = detail.profile[c.name];
                return (
                  <tr key={c.name}>
                    <td>{c.name}</td>
                    <td className="mono faint">{c.type}</td>
                    <td>{p?.nulls_pct ?? 0}%</td>
                    <td>{p?.distinct_approx ?? "-"}</td>
                    <td>{fmt(p?.min)}</td>
                    <td>{fmt(p?.max)}</td>
                    <td>{p?.mean !== undefined ? p.mean.toFixed(2) : "-"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">{t("data_sql")}</h3>
        <textarea
          className="mono"
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) run();
          }}
          rows={3}
        />
        <div className="faint" style={{ margin: "6px 0" }}>{t("data_sql_hint")}</div>
        <div className="row">
          <button className="btn" onClick={run} disabled={busy}>
            {t("common_run")}
          </button>
          {result && (
            <button className="btn-ghost" onClick={exportCsv}>
              <Download size={13} style={{ verticalAlign: -2, marginRight: 4 }} />
              {t("common_export_csv")}
            </button>
          )}
          {result && <CiteBadge id={result.id} onClick={copyCite} />}
        </div>
        {error && <div className="result-block" style={{ color: "var(--danger)" }}>{error}</div>}
        {result && (
          <div style={{ marginTop: 12 }}>
            {result.truncated && (
              <div className="faint" style={{ marginBottom: 6 }}>
                {t("data_truncated").replace("{n}", String(result.rows.length))}
              </div>
            )}
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    {result.columns.map((c) => (
                      <th key={c.name}>{c.name}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, i) => (
                    <tr key={i}>
                      {result.columns.map((c) => (
                        <td key={c.name}>{fmt(row[c.name])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <ChartBuilder datasetName={detail.name} columns={detail.columns.map((c) => c.name)} t={t} />
    </>
  );
}

function ChartBuilder({ datasetName, columns, t }: { datasetName: string; columns: string[]; t: (k: DictKey) => string }) {
  const [kind, setKind] = useState("bar");
  const [x, setX] = useState(columns[0] ?? "");
  const [y, setY] = useState(columns[1] ?? "");
  const [color, setColor] = useState("");
  const [title, setTitle] = useState("");
  const [spec, setSpec] = useState<object | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setX(columns[0] ?? "");
    setY(columns[1] ?? "");
  }, [columns]);

  useEffect(() => {
    if (spec && chartRef.current) {
      import("vega-embed").then(({ default: embed }) => {
        if (chartRef.current) embed(chartRef.current, spec as never, { actions: false }).catch(() => {});
      });
    }
  }, [spec]);

  async function build() {
    setBusy(true);
    setError(null);
    try {
      const sql = `SELECT * FROM ${datasetName} LIMIT 2000`;
      const r = await api.chart({ sql, kind, x, y: y || undefined, color: color || undefined, title: title || undefined });
      setSpec(r.spec);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h3 className="card-title">{t("data_chart_builder")}</h3>
      <div className="row" style={{ marginBottom: 10 }}>
        <div className="col">
          <label className="field-label">{t("data_chart_kind")}</label>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {["bar", "line", "area", "scatter", "histogram", "pie", "heatmap"].map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
        </div>
        <div className="col">
          <label className="field-label">{t("data_chart_x")}</label>
          <select value={x} onChange={(e) => setX(e.target.value)}>
            {columns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="col">
          <label className="field-label">{t("data_chart_y")}</label>
          <select value={y} onChange={(e) => setY(e.target.value)}>
            <option value="">—</option>
            {columns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="col">
          <label className="field-label">{t("data_chart_color")}</label>
          <select value={color} onChange={(e) => setColor(e.target.value)}>
            <option value="">—</option>
            {columns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="col grow">
          <label className="field-label">{t("data_chart_title")}</label>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
      </div>
      <button className="btn" onClick={build} disabled={busy || !x}>
        {t("data_chart_build")}
      </button>
      {error && <div className="result-block" style={{ color: "var(--danger)" }}>{error}</div>}
      {spec && (
        <div className="chart-frame" style={{ marginTop: 12 }}>
          <div ref={chartRef} />
        </div>
      )}
    </div>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "-";
  if (typeof v === "number") return v.toLocaleString();
  return String(v);
}

function csvCell(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
