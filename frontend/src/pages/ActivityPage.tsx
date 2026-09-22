import { useEffect, useState } from "react";
import { Bot } from "lucide-react";
import { api, type LogItem } from "../api";
import type { DictKey } from "../i18n";
import { CiteBadge, copyCite } from "../components/ResultView";

export function ActivityPage({ t }: { t: (k: DictKey) => string }) {
  const [items, setItems] = useState<LogItem[]>([]);

  useEffect(() => {
    api.agentCalls(50).then((r) => setItems(r.items));
  }, []);

  return (
    <div className="card">
      <div className="row" style={{ gap: 8, marginBottom: 4 }}>
        <Bot size={18} />
        <h3 className="card-title" style={{ margin: 0 }}>{t("activity_title")}</h3>
      </div>
      <div className="faint" style={{ marginBottom: 14 }}>{t("activity_subtitle")}</div>
      {items.length === 0 ? (
        <div className="empty-state">{t("activity_empty")}</div>
      ) : (
        <div className="stack">
          {items.map((it) => (
            <div key={it.id} className="cell" style={{ marginBottom: 0 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div className="row">
                  <span className="badge badge-muted">{it.engine}</span>
                  <code>{it.operation}</code>
                  {it.ok ? <span className="badge badge-ok">ok</span> : <span className="badge badge-error">error</span>}
                </div>
                <div className="row">
                  <span className="faint">{new Date(it.created_at).toLocaleString()}</span>
                  <CiteBadge id={it.id} onClick={copyCite} />
                </div>
              </div>
              <pre className="mono faint" style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>
                {JSON.stringify(it.input)}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
