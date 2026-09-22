import { useEffect, useState } from "react";
import { RotateCw, Search, X } from "lucide-react";
import { api, type LogItem } from "../api";
import type { DictKey } from "../i18n";
import { CiteBadge, copyCite } from "../components/ResultView";

const ENGINES = ["calc", "math", "units", "stats", "dates", "data"];

export function WorkLogPage({ t }: { t: (k: DictKey) => string }) {
  const [items, setItems] = useState<LogItem[]>([]);
  const [engine, setEngine] = useState("");
  const [source, setSource] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<LogItem | null>(null);

  const load = () =>
    api.log({ limit: 50, engine: engine || undefined, source: source || undefined, query: query || undefined }).then((r) => setItems(r.items));

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engine, source]);

  async function rerun(id: string) {
    await api.rerun(id);
    load();
  }

  return (
    <div>
      <div className="card">
        <div className="row">
          <div className="row grow" style={{ background: "var(--bg-sunken)", borderRadius: 6, padding: "6px 10px", border: "1px solid var(--border)" }}>
            <Search size={14} className="faint" />
            <input
              type="search"
              className="grow"
              style={{ background: "none", border: "none", padding: 0 }}
              placeholder={t("common_search")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && load()}
            />
          </div>
          <select value={engine} onChange={(e) => setEngine(e.target.value)}>
            <option value="">{t("log_all_engines")}</option>
            {ENGINES.map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">{t("log_source_all")}</option>
            <option value="ui">{t("log_source_ui")}</option>
            <option value="agent">{t("log_source_agent")}</option>
          </select>
        </div>
      </div>

      <div className="card">
        {items.length === 0 ? (
          <div className="empty-state">{t("log_empty")}</div>
        ) : (
          <div className="table-scroll" style={{ maxHeight: 560 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>id</th><th>{t("log_engine")}</th><th>operation</th><th>source</th><th>ok</th><th>ms</th><th>when</th><th></th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.id} style={{ cursor: "pointer" }} onClick={() => setSelected(it)}>
                    <td className="mono">{it.id}</td>
                    <td>{it.engine}</td>
                    <td className="mono">{it.operation}</td>
                    <td><span className="badge badge-muted">{it.source}</span></td>
                    <td>{it.ok ? <span className="badge badge-ok">ok</span> : <span className="badge badge-error">error</span>}</td>
                    <td>{it.elapsed_ms.toFixed(1)}</td>
                    <td className="faint">{new Date(it.created_at).toLocaleString()}</td>
                    <td>
                      <button
                        className="icon-btn"
                        title={t("common_rerun")}
                        onClick={(e) => {
                          e.stopPropagation();
                          rerun(it.id);
                        }}
                      >
                        <RotateCw size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selected && <DetailModal item={selected} onClose={() => setSelected(null)} t={t} onRerun={rerun} />}
    </div>
  );
}

function DetailModal({ item, onClose, t, onRerun }: { item: LogItem; onClose: () => void; t: (k: DictKey) => string; onRerun: (id: string) => void }) {
  return (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 30,
      }}
      onClick={onClose}
    >
      <div className="card" style={{ width: 560, maxHeight: "80vh", overflow: "auto" }} onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
          <div className="row">
            <CiteBadge id={item.id} onClick={copyCite} />
            <span className="badge badge-muted">{item.engine}</span>
          </div>
          <button className="icon-btn" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="faint" style={{ marginBottom: 4 }}>Input</div>
        <pre className="mono result-block" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(item.input, null, 2)}</pre>
        <div className="faint" style={{ margin: "10px 0 4px" }}>Output</div>
        <pre className="mono result-block" style={{ whiteSpace: "pre-wrap" }}>
          {item.ok ? JSON.stringify(item.output, null, 2) : item.error}
        </pre>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" onClick={() => onRerun(item.id)}>{t("common_rerun")}</button>
        </div>
      </div>
    </div>
  );
}
